#!/usr/bin/env python3
"""Run local XCOMET-QE or XCOMET-DA/COMET scoring on a prepared JSONL file."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.io_utils import ensure_parent, read_jsonl, resolve_path
from scripts.common.text_utils import clean_text, utc_now


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local XCOMET-QE or XCOMET-DA/COMET scoring.")
    parser.add_argument("--mode", choices=["qe", "da"], required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--device", default="cuda", help="cpu, cuda, cuda:0, npu, or npu:0 style device.")
    parser.add_argument("--limit", type=int, default=0, help="Optional smoke-test limit; 0 means all rows.")
    parser.add_argument("--resume", action="store_true", help="Skip existing successful sample/group/stage rows.")
    parser.add_argument("--dry-run", action="store_true", help="Validate inputs without loading the model or writing output.")
    return parser.parse_args()


def result_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        clean_text(row.get("sample_id")),
        clean_text(row.get("split")),
        clean_text(row.get("system_or_group")),
        clean_text(row.get("translation_stage")),
    )


def validate_row(row: dict[str, Any], mode: str) -> str | None:
    for field in ["sample_id", "split", "system_or_group", "translation_stage", "source_text", "hypothesis_translation"]:
        if not clean_text(row.get(field)):
            return f"missing required field: {field}"
    if mode == "qe":
        if row.get("ref_text") not in {None, ""}:
            return "QE input must have ref_text null or empty"
    if mode == "da" and not clean_text(row.get("ref_text")):
        return "DA input requires non-empty ref_text"
    return None


def load_existing_successes(output: Path) -> set[tuple[str, str, str, str]]:
    if not output.exists():
        return set()
    successes: set[tuple[str, str, str, str]] = set()
    for row in read_jsonl(output):
        if clean_text(row.get("status")).lower() == "success":
            successes.add(result_key(row))
    return successes


def parse_device(device: str) -> tuple[str, int | None]:
    text = device.strip().lower()
    if text == "cpu":
        return "cpu", None
    if text == "cuda":
        return "cuda", 0
    if text.startswith("cuda:"):
        return "cuda", int(text.split(":", 1)[1])
    if text == "npu":
        return "npu", 0
    if text.startswith("npu:"):
        return "npu", int(text.split(":", 1)[1])
    raise ValueError(f"Unsupported device: {device}")


def setup_npu(device_index: int) -> None:
    try:
        import torch
        import torch_npu  # noqa: F401
        import torch_npu.contrib.transfer_to_npu  # noqa: F401
    except Exception as exc:
        raise RuntimeError("torch_npu is required for --device npu:N on the scoring server") from exc

    if not torch.npu.is_available():
        raise RuntimeError("torch.npu.is_available() is False")
    torch.npu.set_device(device_index)

    def fake_get_device_capability(device: Any = None) -> tuple[int, int]:
        return (8, 0)

    def fake_get_device_name(device: Any = None) -> str:
        try:
            return str(torch.npu.get_device_name(device_index))
        except Exception:
            return "Ascend NPU"

    # Some COMET/Lightning CUDA checks run after transfer_to_npu; keep them harmless.
    torch.cuda.get_device_capability = fake_get_device_capability
    torch.cuda.get_device_name = fake_get_device_name


def resolve_local_checkpoint(model_path: str) -> Path:
    path = Path(model_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(
            f"Model path does not exist: {model_path}. Use a local XCOMET/COMET checkpoint path; "
            "this script does not download models or call external APIs."
        )
    if path.is_file():
        return path

    checkpoint_patterns = ["*.ckpt", "*.pt", "*.pth"]
    candidates: list[Path] = []
    for pattern in checkpoint_patterns:
        candidates.extend(sorted(path.glob(f"**/{pattern}")))
    ckpt_candidates = [candidate for candidate in candidates if candidate.suffix == ".ckpt"]
    if ckpt_candidates:
        return ckpt_candidates[0]
    if candidates:
        return candidates[0]
    raise FileNotFoundError(f"No local checkpoint file found under model path: {model_path}")


def load_model(model_path: str):
    try:
        from comet import load_from_checkpoint
    except Exception as exc:
        raise RuntimeError("unbabel-comet is required on the scoring server: pip install unbabel-comet") from exc

    checkpoint = resolve_local_checkpoint(model_path)
    return load_from_checkpoint(str(checkpoint)), str(checkpoint)


def to_model_item(row: dict[str, Any], mode: str) -> dict[str, str]:
    item = {
        "src": clean_text(row["source_text"]),
        "mt": clean_text(row["hypothesis_translation"]),
    }
    if mode == "da":
        item["ref"] = clean_text(row["ref_text"])
    return item


def predict_scores(model, items: list[dict[str, str]], batch_size: int, device_kind: str, device_index: int | None) -> list[float]:
    if device_kind == "cpu":
        pred = model.predict(
            items,
            batch_size=batch_size,
            gpus=0,
            num_workers=0,
            progress_bar=False,
            length_batching=True,
        )
    else:
        pred = model.predict(
            items,
            batch_size=batch_size,
            gpus=1,
            devices=[device_index or 0],
            accelerator="cuda",
            num_workers=0,
            progress_bar=False,
            length_batching=True,
        )
    scores = getattr(pred, "scores", None)
    if scores is None and isinstance(pred, dict):
        scores = pred.get("scores")
    if scores is None:
        raise RuntimeError("COMET prediction object did not expose a scores field")
    return [float(score) for score in scores]


def failure_result(
    row: dict[str, Any],
    *,
    mode: str,
    model_path: str,
    batch_size: int,
    device: str,
    error: str,
    latency_ms: int,
) -> dict[str, Any]:
    return {
        "sample_id": row.get("sample_id"),
        "split": row.get("split"),
        "system_or_group": row.get("system_or_group"),
        "translation_stage": row.get("translation_stage"),
        "source_text": row.get("source_text"),
        "hypothesis_translation": row.get("hypothesis_translation"),
        "ref_text": row.get("ref_text"),
        "score": None,
        "model_path": model_path,
        "mode": mode,
        "batch_size": batch_size,
        "device": device,
        "status": "failed",
        "error": error,
        "latency_ms": latency_ms,
        "created_at": utc_now(),
    }


def success_result(
    row: dict[str, Any],
    *,
    score: float,
    mode: str,
    model_path: str,
    batch_size: int,
    device: str,
    latency_ms: int,
) -> dict[str, Any]:
    return {
        "sample_id": row.get("sample_id"),
        "split": row.get("split"),
        "system_or_group": row.get("system_or_group"),
        "translation_stage": row.get("translation_stage"),
        "source_text": row.get("source_text"),
        "hypothesis_translation": row.get("hypothesis_translation"),
        "ref_text": row.get("ref_text"),
        "score": score,
        "model_path": model_path,
        "mode": mode,
        "batch_size": batch_size,
        "device": device,
        "status": "success",
        "error": "",
        "latency_ms": latency_ms,
        "created_at": utc_now(),
    }


def score_batch(
    model,
    rows: list[dict[str, Any]],
    *,
    mode: str,
    model_path: str,
    batch_size: int,
    device: str,
    device_kind: str,
    device_index: int | None,
) -> list[dict[str, Any]]:
    start = time.perf_counter()
    try:
        scores = predict_scores(
            model,
            [to_model_item(row, mode) for row in rows],
            batch_size,
            device_kind,
            device_index,
        )
        if len(scores) != len(rows):
            raise RuntimeError(f"Expected {len(rows)} scores, got {len(scores)}")
        latency_ms = int((time.perf_counter() - start) * 1000)
        per_row_latency = int(latency_ms / max(len(rows), 1))
        return [
            success_result(
                row,
                score=score,
                mode=mode,
                model_path=model_path,
                batch_size=batch_size,
                device=device,
                latency_ms=per_row_latency,
            )
            for row, score in zip(rows, scores)
        ]
    except Exception as exc:
        if len(rows) > 1:
            results: list[dict[str, Any]] = []
            for row in rows:
                results.extend(
                    score_batch(
                        model,
                        [row],
                        mode=mode,
                        model_path=model_path,
                        batch_size=1,
                        device=device,
                        device_kind=device_kind,
                        device_index=device_index,
                    )
                )
            return results
        latency_ms = int((time.perf_counter() - start) * 1000)
        return [
            failure_result(
                rows[0],
                mode=mode,
                model_path=model_path,
                batch_size=batch_size,
                device=device,
                error=str(exc),
                latency_ms=latency_ms,
            )
        ]


def batched(rows: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [rows[i : i + size] for i in range(0, len(rows), size)]


def main() -> None:
    args = parse_args()
    input_path = resolve_path(args.input)
    output_path = resolve_path(args.output)
    rows = read_jsonl(input_path)
    if args.limit and args.limit > 0:
        rows = rows[: args.limit]

    invalid = [(idx, validate_row(row, args.mode)) for idx, row in enumerate(rows, 1)]
    invalid = [(idx, error) for idx, error in invalid if error]
    if invalid:
        preview = "\n".join(f"- row {idx}: {error}" for idx, error in invalid[:20])
        raise SystemExit(f"Input validation failed for {input_path}:\n{preview}")

    skipped = 0
    if args.resume:
        successes = load_existing_successes(output_path)
        before = len(rows)
        rows = [row for row in rows if result_key(row) not in successes]
        skipped = before - len(rows)

    summary = {
        "mode": args.mode,
        "input": str(input_path),
        "output": str(output_path),
        "rows_to_score": len(rows),
        "skipped_success_on_resume": skipped,
        "model_path": args.model_path,
        "batch_size": args.batch_size,
        "device": args.device,
        "dry_run": args.dry_run,
    }
    if args.dry_run:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    device_kind, device_index = parse_device(args.device)
    if device_kind == "npu":
        setup_npu(device_index or 0)
    model, resolved_model = load_model(args.model_path)
    summary["resolved_model"] = resolved_model
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)

    output = ensure_parent(output_path)
    mode = "a" if args.resume else "w"
    success_count = 0
    failed_count = 0
    with output.open(mode, encoding="utf-8") as fh:
        for batch in batched(rows, max(args.batch_size, 1)):
            results = score_batch(
                model,
                batch,
                mode=args.mode,
                model_path=resolved_model,
                batch_size=args.batch_size,
                device=args.device,
                device_kind=device_kind,
                device_index=device_index,
            )
            for result in results:
                if result["status"] == "success":
                    success_count += 1
                else:
                    failed_count += 1
                fh.write(json.dumps(result, ensure_ascii=False) + "\n")
            fh.flush()

    print(
        json.dumps(
            {
                "output": str(output),
                "success_count": success_count,
                "failed_count": failed_count,
                "skipped_success_on_resume": skipped,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
