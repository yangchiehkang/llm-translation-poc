#!/usr/bin/env python3
# 翻译脚本：调用 Qwen-Max 进行法规文本翻译。
# 运行位置：服务器；需要服务器环境和 DASHSCOPE_API_KEY，本地只建议 dry-run 检查。

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.dashscope_client import call_dashscope_generation
from scripts.common.io_utils import read_jsonl, append_jsonl, pick_first, row_key, resolve_path
from scripts.common.lang import infer_lang_from_path, normalize_lang
from scripts.common.termbase import load_termbase, match_terms, required_target_terms, count_core_high
from scripts.common.prompting import classify_sample, build_messages


def expand_inputs(specs: list[str]) -> list[Path]:
    files: list[Path] = []
    for spec in specs:
        p = resolve_path(spec)
        if p.is_dir():
            files.extend(sorted(p.glob("*.jsonl")))
        elif any(ch in str(spec) for ch in ["*", "?", "["]):
            files.extend(resolve_path(x) for x in glob.glob(str(resolve_path(spec))))
        else:
            files.append(p)
    out = []
    seen = set()
    for p in files:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def call_qwenmax(messages: list[dict[str, str]], model: str, temperature: float, max_tokens: int, timeout: int, retries: int) -> str:
    text, _ = call_dashscope_generation(
        messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        max_attempts=retries,
        sleep_seconds=lambda attempt: min(10, 1.5 * attempt),
        retry_log_prefix="[RETRY]",
        failure_message="Qwen-Max call failed after retries",
    )
    return text


def output_path_for(input_path: Path, output_dir: Path, model: str) -> Path:
    if input_path.name.startswith("mt_"):
        return output_dir / input_path.name
    return output_dir / f"mt_{input_path.stem}._{model}.jsonl"


def load_done_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    done = set()
    for idx, row in enumerate(read_jsonl(path), 1):
        if not row.get("mt_error"):
            done.add(row_key(row, idx))
    return done


def translate_file(input_path: Path, output_path: Path, args: argparse.Namespace) -> dict[str, Any]:
    rows = read_jsonl(input_path)
    if args.limit > 0:
        rows = rows[: args.limit]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and not args.resume:
        output_path.unlink()
    done_ids = load_done_ids(output_path) if args.resume else set()

    fallback_lang = normalize_lang(args.source_lang) or infer_lang_from_path(input_path)
    term_cache: dict[str, list[dict]] = {}
    completed = 0
    skipped = 0
    failed = 0

    for idx, row in enumerate(rows, 1):
        sample_id = row.get("sample_id") or row_key(row, idx)
        if sample_id in done_ids:
            skipped += 1
            continue
        src_lang = normalize_lang(
            args.source_lang
            or row.get("source_lang")
            or row.get("src_lang_code")
            or row.get("lang")
            or fallback_lang
        )
        if not src_lang:
            raise ValueError(f"Cannot determine source language for {input_path}:{idx}")
        if src_lang not in term_cache:
            term_cache[src_lang] = load_termbase(args.termbase, source_lang=src_lang, target_lang=args.target_lang)
        source_text = pick_first(row, ["source_text", "text", "src", "source"])
        matched = match_terms(source_text, term_cache[src_lang])
        prompt_mode = args.prompt_mode if args.prompt_mode != "auto" else classify_sample(source_text, matched)
        messages = build_messages(source_text, src_lang, args.target_lang, matched, prompt_mode)

        out = dict(row)
        out.update({
            "sample_id": sample_id,
            "source_lang": src_lang,
            "target_lang": normalize_lang(args.target_lang),
            "source_text": source_text,
            "matched_terms": matched,
            "matched_term_count": len(matched),
            "matched_core_high_count": count_core_high(matched),
            "required_target_terms": required_target_terms(matched),
            "prompt_mode": prompt_mode,
            "prompt_version": args.prompt_version,
            "mt_model": args.model,
            "mt_engine": "qwenmax_server",
            "term_injection": bool(matched),
        })
        try:
            if args.dry_run:
                mt_text = f"[DRY_RUN] {source_text}"
            else:
                mt_text = call_qwenmax(messages, args.model, args.temperature, args.max_tokens, args.timeout, args.retries)
            out["mt_text"] = mt_text
            out["new_translation"] = mt_text
            out["mt_error"] = ""
            completed += 1
        except Exception as exc:
            out["mt_text"] = ""
            out["new_translation"] = ""
            out["mt_error"] = str(exc)
            failed += 1
        append_jsonl(output_path, out)
        if args.sleep > 0:
            time.sleep(args.sleep)

    return {"input": str(input_path), "output": str(output_path), "completed": completed, "skipped": skipped, "failed": failed}


def main() -> None:
    ap = argparse.ArgumentParser(description="Qwen-Max 翻译入口。")
    ap.add_argument("--input", required=True, nargs="+", help="Input JSONL file(s), directory, or glob.")
    ap.add_argument("--output-dir", default="data/mt/qwen-max-term")
    ap.add_argument("--termbase", default="termbase/auto_regulation_terms_v1.csv")
    ap.add_argument("--source-lang", default="")
    ap.add_argument("--target-lang", default="zh")
    ap.add_argument("--model", default="qwen-max")
    ap.add_argument("--temperature", type=float, default=0.2)
    ap.add_argument("--max-tokens", type=int, default=2048)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--sleep", type=float, default=0.0)
    ap.add_argument("--prompt-mode", default="auto", choices=["auto", "lightweight", "structure", "strict_term", "natural_legal", "retry_repair"])
    ap.add_argument("--prompt-version", default="prompt_route_v1")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="Do not call DashScope; useful for server smoke tests.")
    args = ap.parse_args()

    if not args.dry_run and not os.getenv("DASHSCOPE_API_KEY"):
        raise RuntimeError("Missing environment variable DASHSCOPE_API_KEY on server.")

    output_dir = resolve_path(args.output_dir)
    results = []
    for input_path in expand_inputs(args.input):
        out_path = output_path_for(input_path, output_dir, args.model)
        print(f"[TRANSLATE] {input_path} -> {out_path}", flush=True)
        results.append(translate_file(input_path, out_path, args))
    print(json.dumps({"files": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
