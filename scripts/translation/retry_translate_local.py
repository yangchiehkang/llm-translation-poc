#!/usr/bin/env python3
"""Run Step 7 TCR retry translations with a local Transformers model."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.io_utils import read_jsonl, resolve_path
from scripts.common.text_utils import utc_now

SPLITS = ("prompt_compare_200", "da_eval_strict")
GROUPS = ("no_term_baseline", "term_baseline", "graded_prompt")
OUTPUT_FIELDS = [
    "sample_id",
    "split",
    "group",
    "source_text",
    "original_translation",
    "retry_translation",
    "required_target_terms",
    "missing_hard_terms",
    "tcr_status_before_retry",
    "tcr_sample_before_retry",
    "prompt_mode",
    "model_path",
    "generation_config",
    "latency_ms",
    "status",
    "error",
    "retry_attempt",
    "created_at",
]
PASSTHROUGH_FIELDS = [
    "document_id",
    "language_pair",
    "source_lang",
    "target_lang",
    "ref_text",
    "page_ref",
    "order_ref",
    "alignment_method",
    "alignment_confidence",
    "use_for_da",
]


def pick_first(row: dict[str, Any], names: list[str], default: Any = "") -> Any:
    for name in names:
        value = row.get(name)
        if value is None or value == "":
            continue
        return value
    return default


def as_list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return [text]
        return parsed if isinstance(parsed, list) else [parsed]
    return [value]


def default_input_path(split: str, group: str) -> Path:
    return resolve_path(f"outputs/retry_inputs/{split}/{group}_retry_inputs.jsonl")


def default_output_path(split: str, group: str) -> Path:
    return resolve_path(f"outputs/translations_retry/{split}/{group}_retry_translations.jsonl")


def path_is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def validate_output_path(output_path: Path) -> None:
    first_pass_root = resolve_path("outputs/translations")
    retry_root = resolve_path("outputs/translations_retry")
    if path_is_relative_to(output_path, first_pass_root) and not path_is_relative_to(output_path, retry_root):
        raise ValueError(
            "Refusing to write retry output under outputs/translations; "
            "use outputs/translations_retry so first-pass translations are not overwritten."
        )


def missing_hard_terms(sample: dict[str, Any]) -> list[Any]:
    return as_list(
        pick_first(
            sample,
            ["missing_hard_terms", "failed_terms", "failed_hard_terms", "failed_required_terms"],
            [],
        )
    )


def required_target_terms(sample: dict[str, Any]) -> list[Any]:
    raw_terms = as_list(sample.get("required_target_terms"))
    if raw_terms:
        return raw_terms

    derived: list[str] = []
    seen: set[str] = set()
    for term in missing_hard_terms(sample):
        if isinstance(term, dict):
            target = str(
                term.get("required_target_term")
                or term.get("target_term")
                or term.get("target")
                or ""
            ).strip()
        else:
            target = str(term).strip()
        if target and target not in seen:
            seen.add(target)
            derived.append(target)
    return derived


def original_translation(sample: dict[str, Any]) -> str:
    return str(
        pick_first(
            sample,
            ["original_translation", "translation", "previous_hypothesis", "hypothesis", "translated_text"],
            "",
        )
    )


def term_to_prompt_line(term: Any) -> str:
    if isinstance(term, dict):
        source = str(term.get("source_term") or term.get("source") or "").strip()
        target = str(term.get("required_target_term") or term.get("target_term") or term.get("target") or "").strip()
        error_type = str(term.get("error_type") or "").strip()
        observed = str(term.get("observed") or "").strip()
        details = []
        if source or target:
            main = f"{source} -> {target}" if source else target
        else:
            main = json.dumps(term, ensure_ascii=False)
        if error_type:
            details.append(f"error_type={error_type}")
        if observed:
            details.append(f"observed={observed}")
        return f"{main} ({', '.join(details)})" if details else main
    return str(term).strip()


def list_for_prompt(values: list[Any]) -> str:
    lines = [term_to_prompt_line(value) for value in values]
    lines = [line for line in lines if line]
    return "\n".join(f"- {line}" for line in lines) if lines else "- 无"


def build_retry_prompt(sample: dict[str, Any]) -> str:
    """Build the retry prompt from one retry-input row."""

    source_text = str(sample.get("source_text") or "")
    prev_translation = original_translation(sample)
    required_terms = required_target_terms(sample)
    missing_terms = missing_hard_terms(sample)

    return (
        "你正在进行法律/法规/合规语境的翻译修正。\n"
        "目标语言：中文。\n\n"
        "任务：基于源文和上一轮译文，只修正上一轮未命中的硬术语，输出最终中文译文。\n\n"
        "硬性要求：\n"
        "1. 必须保留并准确使用 required_target_terms 中的硬术语。\n"
        "2. missing_hard_terms 是上一轮未命中的硬术语，本次必须修复。\n"
        "3. 在自然流畅与术语一致之间，优先保证硬术语一致。\n"
        "4. 不要解释，不要输出分析，只输出最终中文译文。\n"
        "5. 不要输出 Markdown。\n\n"
        f"required_target_terms:\n{list_for_prompt(required_terms)}\n\n"
        f"missing_hard_terms:\n{list_for_prompt(missing_terms)}\n\n"
        f"源文:\n{source_text}\n\n"
        f"上一轮译文:\n{prev_translation}\n\n"
        "最终中文译文:"
    )


def parse_torch_dtype(torch: Any, dtype_name: str) -> Any:
    if dtype_name == "auto":
        return "auto"
    mapping = {
        "bfloat16": torch.bfloat16,
        "bf16": torch.bfloat16,
        "float16": torch.float16,
        "fp16": torch.float16,
        "float32": torch.float32,
        "fp32": torch.float32,
    }
    if dtype_name not in mapping:
        raise ValueError(f"Unsupported --torch-dtype: {dtype_name}")
    return mapping[dtype_name]


def load_model(args: argparse.Namespace) -> tuple[Any, Any, Any]:
    model_path = Path(args.model_path).expanduser()
    if not model_path.exists():
        raise FileNotFoundError(f"--model-path does not exist: {model_path}")

    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except Exception as exc:  # pragma: no cover - depends on server runtime
        raise RuntimeError("transformers and torch are required on the server for retry translation") from exc

    if args.device.startswith("npu"):
        try:
            import torch_npu  # noqa: F401
        except Exception as exc:  # pragma: no cover - depends on server runtime
            raise RuntimeError("torch_npu is required when --device starts with npu") from exc
        try:
            torch.npu.set_device(args.device)
        except Exception as exc:  # pragma: no cover - depends on server runtime
            raise RuntimeError(f"torch_npu could not set device {args.device}: {exc}") from exc
        if not torch.npu.is_available():
            raise RuntimeError("torch.npu.is_available() is False")

    tokenizer_kwargs = {
        "trust_remote_code": True,
        "local_files_only": True,
    }
    try:
        tokenizer = AutoTokenizer.from_pretrained(str(model_path), **tokenizer_kwargs)
    except Exception:
        tokenizer = AutoTokenizer.from_pretrained(str(model_path), use_fast=False, **tokenizer_kwargs)
    if getattr(tokenizer, "pad_token_id", None) is None and getattr(tokenizer, "eos_token", None) is not None:
        tokenizer.pad_token = tokenizer.eos_token
    if hasattr(tokenizer, "padding_side"):
        tokenizer.padding_side = "left"

    model_kwargs: dict[str, Any] = {
        "trust_remote_code": True,
        "local_files_only": True,
        "torch_dtype": parse_torch_dtype(torch, args.torch_dtype),
    }
    if args.device_map and args.device_map.lower() not in {"none", "off", "false", "no"}:
        model_kwargs["device_map"] = args.device_map
    try:
        model = AutoModelForCausalLM.from_pretrained(str(model_path), **model_kwargs)
    except (TypeError, ValueError):
        # Older Transformers/Accelerate builds may not support dtype or device_map.
        model_kwargs.pop("device_map", None)
        model_kwargs.pop("torch_dtype", None)
        model = AutoModelForCausalLM.from_pretrained(str(model_path), **model_kwargs)
    if not getattr(model, "hf_device_map", None) and args.device != "auto":
        model.to(args.device)
    model.eval()
    return tokenizer, model, torch


def model_input_device(model: Any) -> Any:
    device = getattr(model, "device", None)
    if device is not None:
        return device
    try:
        return next(model.parameters()).device
    except StopIteration:
        return "cpu"


def format_prompt(tokenizer: Any, prompt: str) -> str:
    if hasattr(tokenizer, "apply_chat_template"):
        messages = [{"role": "user", "content": prompt}]
        try:
            return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        except Exception:
            return prompt
    return prompt


def clean_generation(text: str) -> str:
    lines = [line.strip() for line in str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    compact: list[str] = []
    blank_seen = False
    for line in lines:
        if not line:
            if not blank_seen:
                compact.append("")
            blank_seen = True
            continue
        compact.append(line)
        blank_seen = False
    return "\n".join(compact).strip()


def generate_batch(
    samples: list[dict[str, Any]],
    tokenizer: Any,
    model: Any,
    torch: Any,
    args: argparse.Namespace,
) -> list[str]:
    prompts = [format_prompt(tokenizer, build_retry_prompt(sample)) for sample in samples]
    encode_kwargs: dict[str, Any] = {
        "return_tensors": "pt",
        "padding": True,
    }
    if args.max_input_tokens > 0:
        encode_kwargs.update({"truncation": True, "max_length": args.max_input_tokens})
    encoded = tokenizer(prompts, **encode_kwargs)
    device = model_input_device(model)
    encoded = {key: value.to(device) for key, value in encoded.items()}
    input_width = encoded["input_ids"].shape[1]

    generation_kwargs: dict[str, Any] = {
        "max_new_tokens": args.max_new_tokens,
        "do_sample": args.temperature > 0,
        "pad_token_id": getattr(tokenizer, "pad_token_id", None),
    }
    eos_token_id = getattr(tokenizer, "eos_token_id", None)
    if eos_token_id is not None:
        generation_kwargs["eos_token_id"] = eos_token_id
    if args.temperature > 0:
        generation_kwargs["temperature"] = args.temperature
        generation_kwargs["top_p"] = args.top_p

    with torch.inference_mode():
        output_ids = model.generate(**encoded, **generation_kwargs)
    new_token_ids = output_ids[:, input_width:]
    return [clean_generation(text) for text in tokenizer.batch_decode(new_token_ids, skip_special_tokens=True)]


def generation_config(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "temperature": args.temperature,
        "top_p": args.top_p,
        "max_new_tokens": args.max_new_tokens,
        "batch_size": args.batch_size,
        "do_sample": args.temperature > 0,
        "torch_dtype": args.torch_dtype,
        "device": args.device,
        "device_map": args.device_map,
        "max_input_tokens": args.max_input_tokens,
    }


def output_row(
    sample: dict[str, Any],
    args: argparse.Namespace,
    *,
    retry_translation: str,
    status: str,
    error: str,
    latency_ms: int,
    retry_attempt: int,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "sample_id": sample.get("sample_id"),
        "split": pick_first(sample, ["split", "split_name"], args.split),
        "group": pick_first(sample, ["group", "experiment_group"], args.group),
        "source_text": sample.get("source_text", ""),
        "original_translation": original_translation(sample),
        "retry_translation": retry_translation,
        "required_target_terms": required_target_terms(sample),
        "missing_hard_terms": missing_hard_terms(sample),
        "tcr_status_before_retry": pick_first(
            sample,
            ["tcr_status_before_retry", "tcr_status"],
            "fail" if pick_first(sample, ["retry_reason"], "") == "tcr_fail" else "",
        ),
        "tcr_sample_before_retry": pick_first(sample, ["tcr_sample_before_retry", "tcr_sample"], None),
        "prompt_mode": sample.get("prompt_mode", ""),
        "model_path": args.model_path,
        "generation_config": generation_config(args),
        "latency_ms": latency_ms,
        "status": status,
        "error": error,
        "retry_attempt": retry_attempt,
        "created_at": utc_now(),
        "retry_prompt_text": build_retry_prompt(sample),
        "translation_stage": "retry_tcr",
        "model_backend": "local_npu" if str(args.device).startswith("npu") else "local_transformers",
        "device": args.device,
    }
    for field in PASSTHROUGH_FIELDS:
        if field in sample:
            row[field] = sample[field]

    ordered = {field: row.get(field) for field in OUTPUT_FIELDS}
    for key, value in row.items():
        if key not in ordered:
            ordered[key] = value
    return ordered


def load_existing_state(path: Path) -> tuple[set[str], dict[str, int]]:
    success_ids: set[str] = set()
    attempts: dict[str, int] = {}
    if not path.exists():
        return success_ids, attempts

    for row in read_jsonl(path):
        sample_id = str(row.get("sample_id") or "")
        if not sample_id:
            continue
        try:
            attempt = int(row.get("retry_attempt") or 0)
        except (TypeError, ValueError):
            attempt = 0
        attempts[sample_id] = max(attempts.get(sample_id, 0), attempt)
        if row.get("status") == "success":
            success_ids.add(sample_id)
    return success_ids, attempts


def write_line(handle: Any, row: dict[str, Any]) -> None:
    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    handle.flush()


def run_translation(args: argparse.Namespace) -> dict[str, Any]:
    input_path = resolve_path(args.input) if args.input else default_input_path(args.split, args.group)
    output_path = resolve_path(args.output) if args.output else default_output_path(args.split, args.group)
    validate_output_path(output_path)

    if not input_path.exists():
        raise FileNotFoundError(f"Retry input JSONL does not exist: {input_path}")

    rows = read_jsonl(input_path)
    total_input_rows = len(rows)
    if args.limit > 0:
        rows = rows[: args.limit]

    success_ids, attempts = load_existing_state(output_path) if args.resume else (set(), {})
    pending = [row for row in rows if str(row.get("sample_id") or "") not in success_ids]

    summary = {
        "split": args.split,
        "group": args.group,
        "input": str(input_path),
        "output": str(output_path),
        "model_path": args.model_path,
        "total_input_rows": total_input_rows,
        "selected_rows": len(rows),
        "resume": args.resume,
        "already_success_count": len(rows) - len(pending),
        "pending_count": len(pending),
        "dry_run": args.dry_run,
    }
    if args.dry_run:
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
        return summary

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not args.resume:
        output_path.write_text("", encoding="utf-8")
    elif not output_path.exists():
        output_path.touch()

    if not pending:
        print(json.dumps({**summary, "processed_count": 0, "failed_count": 0}, ensure_ascii=False, indent=2), flush=True)
        return {**summary, "processed_count": 0, "failed_count": 0}

    tokenizer, model, torch = load_model(args)
    processed_count = 0
    failed_count = 0

    with output_path.open("a", encoding="utf-8") as handle:
        for start in range(0, len(pending), args.batch_size):
            batch = pending[start : start + args.batch_size]
            batch_start = time.monotonic()
            try:
                translations = generate_batch(batch, tokenizer, model, torch, args)
                elapsed_ms = int((time.monotonic() - batch_start) * 1000)
                per_row_latency = round(elapsed_ms / max(1, len(batch)))
                for sample, retry_translation in zip(batch, translations):
                    sample_id = str(sample.get("sample_id") or "")
                    status = "success" if retry_translation else "failed"
                    error = "" if retry_translation else "empty model output"
                    if status == "failed":
                        failed_count += 1
                    retry_attempt = attempts.get(sample_id, 0) + 1
                    attempts[sample_id] = retry_attempt
                    write_line(
                        handle,
                        output_row(
                            sample,
                            args,
                            retry_translation=retry_translation,
                            status=status,
                            error=error,
                            latency_ms=per_row_latency,
                            retry_attempt=retry_attempt,
                        ),
                    )
                    processed_count += 1
                    print(
                        json.dumps(
                            {
                                "sample_id": sample.get("sample_id"),
                                "status": status,
                                "latency_ms": per_row_latency,
                                "retry_attempt": retry_attempt,
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
            except Exception as exc:
                try:
                    if str(args.device).startswith("npu"):
                        torch.npu.empty_cache()
                except Exception:
                    pass
                if len(batch) > 1:
                    for sample in batch:
                        one_start = time.monotonic()
                        try:
                            retry_translation = generate_batch([sample], tokenizer, model, torch, args)[0]
                            status = "success" if retry_translation else "failed"
                            error = "" if retry_translation else "empty model output"
                        except Exception as one_exc:
                            try:
                                if str(args.device).startswith("npu"):
                                    torch.npu.empty_cache()
                            except Exception:
                                pass
                            retry_translation = ""
                            status = "failed"
                            error = str(one_exc)
                        latency_ms = int((time.monotonic() - one_start) * 1000)
                        if status == "failed":
                            failed_count += 1
                        sample_id = str(sample.get("sample_id") or "")
                        retry_attempt = attempts.get(sample_id, 0) + 1
                        attempts[sample_id] = retry_attempt
                        write_line(
                            handle,
                            output_row(
                                sample,
                                args,
                                retry_translation=retry_translation,
                                status=status,
                                error=error,
                                latency_ms=latency_ms,
                                retry_attempt=retry_attempt,
                            ),
                        )
                        processed_count += 1
                        print(
                            json.dumps(
                                {
                                    "sample_id": sample.get("sample_id"),
                                    "status": status,
                                    "latency_ms": latency_ms,
                                    "retry_attempt": retry_attempt,
                                },
                                ensure_ascii=False,
                            ),
                            flush=True,
                        )
                else:
                    sample = batch[0]
                    sample_id = str(sample.get("sample_id") or "")
                    retry_attempt = attempts.get(sample_id, 0) + 1
                    attempts[sample_id] = retry_attempt
                    failed_count += 1
                    processed_count += 1
                    write_line(
                        handle,
                        output_row(
                            sample,
                            args,
                            retry_translation="",
                            status="failed",
                            error=str(exc),
                            latency_ms=int((time.monotonic() - batch_start) * 1000),
                            retry_attempt=retry_attempt,
                        ),
                    )

    final_summary = {**summary, "processed_count": processed_count, "failed_count": failed_count}
    print(json.dumps(final_summary, ensure_ascii=False, indent=2), flush=True)
    return final_summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local-model retry translations for TCR-failed samples.")
    parser.add_argument("--split", required=True, choices=SPLITS)
    parser.add_argument("--group", required=True, choices=GROUPS)
    parser.add_argument("--input", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--top-p", type=float, default=0.9)
    parser.add_argument("--max-new-tokens", type=int, default=2048)
    parser.add_argument("--max-input-tokens", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--device", default="npu:0")
    parser.add_argument("--device-map", default="auto")
    parser.add_argument(
        "--torch-dtype",
        default="auto",
        choices=["auto", "bfloat16", "bf16", "float16", "fp16", "float32", "fp32"],
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.batch_size < 1:
        raise ValueError("--batch-size must be >= 1")
    if args.max_new_tokens < 1:
        raise ValueError("--max-new-tokens must be >= 1")
    if args.temperature < 0:
        raise ValueError("--temperature must be >= 0")
    if not (0 < args.top_p <= 1):
        raise ValueError("--top-p must be in (0, 1]")
    run_translation(args)


if __name__ == "__main__":
    main()
