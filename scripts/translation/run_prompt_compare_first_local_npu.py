#!/usr/bin/env python3
"""Run first translations with a local Qwen-style model on Ascend NPU."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.io_utils import append_jsonl, read_jsonl, resolve_path
from scripts.common.text_utils import utc_now

GROUPS = ("no_term_baseline", "term_baseline", "graded_prompt")
DA_FIELDS = (
    "ref_text",
    "page_ref",
    "order_ref",
    "alignment_method",
    "alignment_confidence",
    "use_for_da",
    "da_sample_role",
)


def sha256_text(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def clean_model_text(text: str) -> str:
    return str(text or "").strip()


def parse_dtype(torch: Any, dtype_name: str) -> Any:
    if dtype_name == "auto":
        return "auto"
    mapping = {
        "float16": torch.float16,
        "fp16": torch.float16,
        "bfloat16": torch.bfloat16,
        "bf16": torch.bfloat16,
        "float32": torch.float32,
        "fp32": torch.float32,
    }
    if dtype_name not in mapping:
        raise ValueError(f"Unsupported dtype: {dtype_name}")
    return mapping[dtype_name]


def candidate_model_roots(extra_roots: list[str]) -> list[Path]:
    roots: list[Path] = []
    for value in extra_roots:
        if value:
            roots.append(Path(value).expanduser())
    for env_name in ("LLM_MODELS_HOME", "MODELSCOPE_CACHE", "HF_HOME", "TRANSFORMERS_CACHE"):
        value = os.getenv(env_name)
        if value:
            roots.append(Path(value).expanduser())
    roots.extend(
        [
            Path("/data/MODEL_DIR"),
            Path("/data/models"),
            Path("/home/SERVICE_USER/models"),
            Path.home() / "models",
        ]
    )
    out: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if key not in seen:
            seen.add(key)
            out.append(root)
    return out


def find_local_model_path(model_path: str, search_roots: list[str], max_depth: int) -> Path:
    if model_path:
        path = Path(model_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"--model-path does not exist: {path}")
        return path.resolve()

    candidates: list[Path] = []
    for root in candidate_model_roots(search_roots):
        if not root.exists() or not root.is_dir():
            continue
        root_depth = len(root.resolve().parts)
        for dirpath, dirnames, filenames in os.walk(root):
            path = Path(dirpath)
            depth = len(path.resolve().parts) - root_depth
            if depth > max_depth:
                dirnames[:] = []
                continue
            if "config.json" not in filenames:
                continue
            lowered = str(path).lower()
            if "qwen" in lowered or "qwq" in lowered:
                candidates.append(path)

    if not candidates:
        searched = ", ".join(str(root) for root in candidate_model_roots(search_roots))
        raise FileNotFoundError(f"Could not auto-find a local Qwen model. Searched: {searched}")

    # Prefer instruct/chat models, then the shortest path for deterministic selection.
    candidates = sorted(
        candidates,
        key=lambda p: (
            0 if any(token in str(p).lower() for token in ("instruct", "chat")) else 1,
            len(str(p)),
            str(p),
        ),
    )
    return candidates[0].resolve()


def load_model(args: argparse.Namespace) -> tuple[Any, Any, Any, Path, str]:
    try:
        import torch
        import torch_npu  # noqa: F401
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except Exception as exc:
        raise RuntimeError("transformers, torch, and torch_npu are required on the server") from exc

    if not args.device.startswith("npu"):
        raise ValueError(f"This script is scoped to NPU execution; got --device {args.device!r}")

    try:
        torch.npu.set_device(args.device)
    except Exception as exc:
        raise RuntimeError(f"torch_npu could not set device {args.device}: {exc}") from exc

    if not torch.npu.is_available():
        raise RuntimeError("torch.npu.is_available() is False")

    model_path = find_local_model_path(args.model_path, args.model_search_root, args.model_search_max_depth)
    tokenizer = AutoTokenizer.from_pretrained(str(model_path), trust_remote_code=True, local_files_only=True)
    if getattr(tokenizer, "pad_token_id", None) is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "left"

    kwargs: dict[str, Any] = {
        "trust_remote_code": True,
        "local_files_only": True,
        "low_cpu_mem_usage": True,
    }
    dtype = parse_dtype(torch, args.dtype)
    if dtype is not None:
        kwargs["torch_dtype"] = dtype

    try:
        model = AutoModelForCausalLM.from_pretrained(str(model_path), **kwargs)
    except TypeError:
        kwargs.pop("torch_dtype", None)
        model = AutoModelForCausalLM.from_pretrained(str(model_path), **kwargs)

    model.to(args.device)
    model.eval()
    model_name = args.model_name or getattr(getattr(model, "config", None), "name_or_path", "") or model_path.name
    return tokenizer, model, torch, model_path, str(model_name)


def format_prompt(tokenizer: Any, prompt_text: str, use_chat_template: bool) -> str:
    if use_chat_template and hasattr(tokenizer, "apply_chat_template"):
        try:
            return tokenizer.apply_chat_template(
                [{"role": "user", "content": prompt_text}],
                tokenize=False,
                add_generation_prompt=True,
            )
        except Exception:
            pass
    return prompt_text


def generate_batch(
    rows: list[dict[str, Any]],
    tokenizer: Any,
    model: Any,
    torch: Any,
    args: argparse.Namespace,
) -> list[str]:
    prompts = [format_prompt(tokenizer, str(row.get("prompt_text") or ""), not args.no_chat_template) for row in rows]
    encode_kwargs: dict[str, Any] = {
        "return_tensors": "pt",
        "padding": True,
    }
    if args.max_input_tokens > 0:
        encode_kwargs.update({"truncation": True, "max_length": args.max_input_tokens})
    encoded = tokenizer(prompts, **encode_kwargs)
    encoded = {key: value.to(args.device) for key, value in encoded.items()}
    input_width = encoded["input_ids"].shape[1]

    generate_kwargs: dict[str, Any] = {
        "max_new_tokens": args.max_new_tokens,
        "do_sample": args.temperature > 0,
        "pad_token_id": tokenizer.pad_token_id,
    }
    if tokenizer.eos_token_id is not None:
        generate_kwargs["eos_token_id"] = tokenizer.eos_token_id
    if args.temperature > 0:
        generate_kwargs["temperature"] = args.temperature
        generate_kwargs["top_p"] = args.top_p

    with torch.inference_mode():
        output_ids = model.generate(**encoded, **generate_kwargs)
    new_token_ids = output_ids[:, input_width:]
    return [clean_model_text(text) for text in tokenizer.batch_decode(new_token_ids, skip_special_tokens=True)]


def load_resume_state(path: Path) -> set[str]:
    if not path.exists():
        return set()
    success_ids: set[str] = set()
    for row in read_jsonl(path):
        sample_id = str(row.get("sample_id") or "")
        if row.get("status") == "success" and row.get("hypothesis") and sample_id:
            success_ids.add(sample_id)
    return success_ids


def output_row(
    row: dict[str, Any],
    *,
    group: str,
    args: argparse.Namespace,
    model_name: str,
    model_path: Path,
    hypothesis: str,
    status: str,
    error_message: str,
    latency_ms: int,
) -> dict[str, Any]:
    prompt_text = str(row.get("prompt_text") or "")
    source_text = str(row.get("source_text") or "")
    out: dict[str, Any] = {
        "sample_id": row.get("sample_id"),
        "document_id": row.get("document_id"),
        "language_pair": row.get("language_pair"),
        "source_lang": row.get("source_lang"),
        "target_lang": row.get("target_lang"),
        "source_text": source_text,
        "hypothesis": hypothesis,
        "experiment_group": group,
        "prompt_strategy": row.get("prompt_strategy"),
        "prompt_mode": row.get("prompt_mode"),
        "prompt_hash": row.get("prompt_hash") or sha256_text(prompt_text),
        "model_name": model_name,
        "model_path": str(model_path),
        "model_backend": "local_npu",
        "device": args.device,
        "temperature": args.temperature,
        "max_new_tokens": args.max_new_tokens,
        "termbase_version": row.get("termbase_version"),
        "required_target_terms": row.get("required_target_terms") or [],
        "matched_terms": row.get("matched_terms") or [],
        "translation_stage": args.translation_stage,
        "status": status,
        "error_message": error_message,
        "latency_ms": latency_ms,
        "input_char_count": len(prompt_text),
        "output_char_count": len(hypothesis),
        "created_at": utc_now(),
    }
    for field in DA_FIELDS:
        if field in row:
            out[field] = row[field]
    return out


def summarize_existing_output(path: Path) -> dict[str, Any]:
    latest: dict[str, dict[str, Any]] = {}
    if path.exists():
        for row in read_jsonl(path):
            sample_id = str(row.get("sample_id") or "")
            if sample_id:
                latest[sample_id] = row
    rows = list(latest.values())
    latencies = [int(row.get("latency_ms") or 0) for row in rows if row.get("status") == "success"]
    return {
        "row_count": len(rows),
        "success_count": sum(1 for row in rows if row.get("status") == "success" and row.get("hypothesis")),
        "failed_count": sum(1 for row in rows if row.get("status") != "success"),
        "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0,
        "sample_ids": {str(row.get("sample_id")) for row in rows if row.get("sample_id")},
        "da_fields_preserved": {
            field: all(field in row for row in rows) if rows else False
            for field in DA_FIELDS
        },
    }


def translate_group(
    group: str,
    tokenizer: Any,
    model: Any,
    torch: Any,
    model_path: Path,
    model_name: str,
    args: argparse.Namespace,
) -> dict[str, Any]:
    input_dir = resolve_path(args.input_dir)
    output_dir = resolve_path(args.output_dir)
    input_path = input_dir / f"{group}.jsonl"
    output_path = output_dir / f"{group}_{args.output_suffix}.jsonl"
    rows = read_jsonl(input_path)
    expected_count = len(rows)
    if args.limit > 0:
        rows = rows[: args.limit]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and not args.resume:
        output_path.unlink()

    success_ids = load_resume_state(output_path) if args.resume else set()
    pending = [row for row in rows if str(row.get("sample_id") or "") not in success_ids]
    skipped_count = len(rows) - len(pending)
    processed_count = 0
    new_failed_count = 0

    for start in range(0, len(pending), args.batch_size):
        batch = pending[start : start + args.batch_size]
        t0 = time.monotonic()
        try:
            hypotheses = generate_batch(batch, tokenizer, model, torch, args)
            latency_ms = int((time.monotonic() - t0) * 1000)
            per_row_latency = max(0, round(latency_ms / max(1, len(batch))))
            for row, hypothesis in zip(batch, hypotheses):
                status = "success" if hypothesis else "failed"
                error_message = "" if hypothesis else "empty hypothesis"
                if status != "success":
                    new_failed_count += 1
                append_jsonl(
                    output_path,
                    output_row(
                        row,
                        group=group,
                        args=args,
                        model_name=model_name,
                        model_path=model_path,
                        hypothesis=hypothesis,
                        status=status,
                        error_message=error_message,
                        latency_ms=per_row_latency,
                    ),
                )
                processed_count += 1
                print(
                    json.dumps(
                        {
                            "split_name": args.split_name,
                            "group": group,
                            "sample_id": row.get("sample_id"),
                            "status": status,
                            "latency_ms": per_row_latency,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
        except Exception as exc:
            try:
                torch.npu.empty_cache()
            except Exception:
                pass
            if len(batch) > 1:
                # Fall back to single rows so one bad sample does not fail the whole batch.
                for row in batch:
                    one_args = argparse.Namespace(**vars(args))
                    one_args.batch_size = 1
                    one_start = time.monotonic()
                    try:
                        hypothesis = generate_batch([row], tokenizer, model, torch, one_args)[0]
                        status = "success" if hypothesis else "failed"
                        error_message = "" if hypothesis else "empty hypothesis"
                    except Exception as one_exc:
                        hypothesis = ""
                        status = "failed"
                        error_message = str(one_exc)
                    latency_ms = int((time.monotonic() - one_start) * 1000)
                    if status != "success":
                        new_failed_count += 1
                    append_jsonl(
                        output_path,
                        output_row(
                            row,
                            group=group,
                            args=args,
                            model_name=model_name,
                            model_path=model_path,
                            hypothesis=hypothesis,
                            status=status,
                            error_message=error_message,
                            latency_ms=latency_ms,
                        ),
                    )
                    processed_count += 1
                    print(
                        json.dumps(
                            {
                                "split_name": args.split_name,
                                "group": group,
                                "sample_id": row.get("sample_id"),
                                "status": status,
                                "latency_ms": latency_ms,
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
            else:
                row = batch[0]
                new_failed_count += 1
                append_jsonl(
                    output_path,
                    output_row(
                        row,
                        group=group,
                        args=args,
                        model_name=model_name,
                        model_path=model_path,
                        hypothesis="",
                        status="failed",
                        error_message=str(exc),
                        latency_ms=int((time.monotonic() - t0) * 1000),
                    ),
                )
                processed_count += 1

        if args.sleep > 0:
            time.sleep(args.sleep)

    final = summarize_existing_output(output_path)
    return {
        "group": group,
        "input_file": str(input_path),
        "output_file": str(output_path),
        "expected_count": expected_count,
        "limit_count": len(rows),
        "processed_count": processed_count,
        "skipped_count": skipped_count,
        "new_failed_count": new_failed_count,
        "success_count": final["success_count"],
        "failed_count": final["failed_count"],
        "avg_latency_ms": final["avg_latency_ms"],
        "sample_ids": final["sample_ids"],
        "da_fields_preserved": final["da_fields_preserved"],
    }


def write_summary(
    args: argparse.Namespace,
    group_results: list[dict[str, Any]],
    model_path: Path,
    model_name: str,
    started_at: str,
    finished_at: str,
) -> None:
    output_dir = resolve_path(args.output_dir)
    summary_json_path = output_dir / "translation_run_summary.json"
    summary_md_path = output_dir / "translation_run_summary.md"
    sample_sets = [result["sample_ids"] for result in group_results]
    sample_sets_equal = all(sample_set == sample_sets[0] for sample_set in sample_sets[1:]) if sample_sets else True
    da_fields_preserved = {
        result["group"]: result["da_fields_preserved"]
        for result in group_results
    }
    summary = {
        "split_name": args.split_name,
        "translation_stage": args.translation_stage,
        "model_name": model_name,
        "model_path": str(model_path),
        "model_backend": "local_npu",
        "device": args.device,
        "temperature": args.temperature,
        "max_new_tokens": args.max_new_tokens,
        "batch_size": args.batch_size,
        "input_files": {result["group"]: result["input_file"] for result in group_results},
        "output_files": {result["group"]: result["output_file"] for result in group_results},
        "expected_count_by_group": {result["group"]: result["expected_count"] for result in group_results},
        "success_count_by_group": {result["group"]: result["success_count"] for result in group_results},
        "failed_count_by_group": {result["group"]: result["failed_count"] for result in group_results},
        "skipped_count_by_group": {result["group"]: result["skipped_count"] for result in group_results},
        "avg_latency_ms_by_group": {result["group"]: result["avg_latency_ms"] for result in group_results},
        "started_at": started_at,
        "finished_at": finished_at,
        "notes": [
            "Used local transformers + torch_npu + NPU execution.",
            "Did not call DashScope or any external API.",
            "Did not use DASHSCOPE_API_KEY.",
            "Did not execute retry_repair.",
            "Did not execute TCR.",
            "Did not execute XCOMET.",
            "Did not run prompt_compare_300.",
        ],
        "validation": {
            "success_sample_sets_equal": sample_sets_equal,
            "da_fields_preserved_by_group": da_fields_preserved,
        },
    }
    summary_json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Translation Run Summary",
        "",
        f"- split_name: {args.split_name}",
        f"- translation_stage: {args.translation_stage}",
        f"- model_backend: local_npu",
        f"- model_name: {model_name}",
        f"- model_path: {model_path}",
        f"- device: {args.device}",
        f"- temperature: {args.temperature}",
        f"- max_new_tokens: {args.max_new_tokens}",
        f"- batch_size: {args.batch_size}",
        f"- started_at: {started_at}",
        f"- finished_at: {finished_at}",
        "",
        "## Counts",
        "",
        "| group | expected | success | failed | skipped | avg_latency_ms |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for result in group_results:
        lines.append(
            f"| {result['group']} | {result['expected_count']} | {result['success_count']} | "
            f"{result['failed_count']} | {result['skipped_count']} | {result['avg_latency_ms']} |"
        )
    lines.extend(
        [
            "",
            "## Validation",
            "",
            f"- success_sample_sets_equal: {sample_sets_equal}",
            f"- da_fields_preserved_by_group: {json.dumps(da_fields_preserved, ensure_ascii=False)}",
            "",
            "## Scope",
            "",
            "- 未调用 API。",
            "- 未使用 DASHSCOPE_API_KEY。",
            "- 未执行 retry_repair。",
            "- 未执行 TCR。",
            "- 未执行 XCOMET。",
            "- 未运行 prompt_compare_300。",
        ]
    )
    summary_md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Run prompt experiment first translations with a local NPU model.")
    ap.add_argument("--input-dir", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--groups", nargs="+", default=list(GROUPS), choices=GROUPS)
    ap.add_argument("--model-path", default="")
    ap.add_argument("--model-search-root", action="append", default=[])
    ap.add_argument("--model-search-max-depth", type=int, default=5)
    ap.add_argument("--model-name", default="")
    ap.add_argument("--device", default="npu:0")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--max-new-tokens", type=int, default=2048)
    ap.add_argument("--max-input-tokens", type=int, default=0)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--top-p", type=float, default=0.9)
    ap.add_argument("--split-name", required=True)
    ap.add_argument("--translation-stage", default="first")
    ap.add_argument("--output-suffix", default="first_translations")
    ap.add_argument("--batch-size", type=int, default=1)
    ap.add_argument("--dtype", default="auto", choices=["auto", "float16", "fp16", "bfloat16", "bf16", "float32", "fp32"])
    ap.add_argument("--sleep", type=float, default=0.0)
    ap.add_argument("--no-chat-template", action="store_true")
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    if args.batch_size < 1:
        raise ValueError("--batch-size must be >= 1")
    if args.max_new_tokens < 1:
        raise ValueError("--max-new-tokens must be >= 1")

    started_at = utc_now()
    tokenizer, model, torch, model_path, model_name = load_model(args)
    results = [
        translate_group(group, tokenizer, model, torch, model_path, model_name, args)
        for group in args.groups
    ]
    finished_at = utc_now()
    write_summary(args, results, model_path, model_name, started_at, finished_at)

    printable = []
    for result in results:
        item = dict(result)
        item.pop("sample_ids", None)
        printable.append(item)
    print(json.dumps({"files": printable}, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
