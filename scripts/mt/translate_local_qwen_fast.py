# -*- coding: utf-8 -*-
"""
Fast local Qwen translation script for Ascend NPU.

Features:
- Local Qwen model inference on NPU.
- JSONL input / JSONL output.
- Batch generation for higher throughput.
- Termbase matching and prompt injection.
- Compatible output fields for later TCR / XCOMET-QE evaluation.
"""

import argparse
import csv
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import torch
import torch_npu
from transformers import AutoTokenizer, AutoModelForCausalLM


_LANG_MAP = {
    "en": "English",
    "zh": "Chinese",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "ru": "Russian",
    "ar": "Arabic",
    "th": "Thai",
    "ms": "Malay",
    "nl": "Dutch",
    "pt": "Portuguese",
    "it": "Italian",
    "id": "Indonesian",
    "no": "Norwegian",
    "sv": "Swedish",
    "vi": "Vietnamese",
}

_LANG_CODE_BY_NAME = {
    "english": "en",
    "german": "de",
    "french": "fr",
    "spanish": "es",
    "russian": "ru",
    "arabic": "ar",
    "thai": "th",
    "malay": "ms",
    "dutch": "nl",
    "portuguese": "pt",
    "italian": "it",
    "indonesian": "id",
    "norwegian": "no",
    "swedish": "sv",
    "vietnamese": "vi",
    "chinese": "zh",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_lang_code(lang: str) -> str:
    value = str(lang or "").strip().lower()

    if not value:
        return ""

    if value in _LANG_MAP:
        return value

    return _LANG_CODE_BY_NAME.get(value, value)


def lang_name(code_or_name: str) -> str:
    code = normalize_lang_code(code_or_name)

    return _LANG_MAP.get(code, code_or_name or "source language")


def read_jsonl(path: str) -> List[Dict[str, Any]]:
    rows = []

    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()

            if not line:
                continue

            try:
                rows.append(json.loads(line))
            except Exception as exc:
                raise RuntimeError(f"Invalid JSON on line {line_no} in {path}: {exc}") from exc

    return rows


def append_jsonl(path: str, row: Dict[str, Any]):
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_json(path: str, payload: Dict[str, Any]):
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def count_jsonl(path: str) -> int:
    if not os.path.exists(path):
        return 0

    n = 0
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                n += 1

    return n


def normalize_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value

    text = str(value or "").strip().lower()

    return text in ("true", "1", "yes", "y")


def pick_src_text(row: Dict[str, Any]) -> str:
    return (
        row.get("source_text")
        or row.get("src_text")
        or row.get("src")
        or row.get("source")
        or row.get("text")
        or ""
    ).strip()


def pick_sample_id(row: Dict[str, Any], fallback_idx: int) -> str:
    return str(
        row.get("sample_id")
        or row.get("id")
        or row.get("sid")
        or f"sample_{fallback_idx:06d}"
    )


def load_termbase(
    termbase_path: str,
    source_lang: str,
    target_lang: str = "zh",
) -> List[Dict[str, Any]]:
    if not termbase_path:
        return []

    if not os.path.exists(termbase_path):
        raise FileNotFoundError(f"Termbase not found: {termbase_path}")

    terms: List[Dict[str, Any]] = []

    source_lang = normalize_lang_code(source_lang)
    target_lang = normalize_lang_code(target_lang)

    with open(termbase_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:
            row_source_lang = normalize_lang_code(
                row.get("source_lang") or row.get("src_lang") or row.get("lang") or ""
            )
            row_target_lang = normalize_lang_code(
                row.get("target_lang") or row.get("tgt_lang") or "zh"
            )

            if row_source_lang != source_lang:
                continue

            if row_target_lang != target_lang:
                continue

            source_term = (
                row.get("source_term")
                or row.get("src_term")
                or row.get("term")
                or ""
            ).strip()

            target_term = (
                row.get("target_term")
                or row.get("tgt_term")
                or row.get("translation")
                or row.get("zh")
                or ""
            ).strip()

            if not source_term or not target_term:
                continue

            terms.append({
                "term_id": row.get("term_id") or row.get("id") or "",
                "source_lang": row_source_lang,
                "source_term": source_term,
                "target_lang": row_target_lang,
                "target_term": target_term,
                "domain": row.get("domain", ""),
                "priority": row.get("priority", ""),
                "case_sensitive": normalize_bool(row.get("case_sensitive", False)),
                "match_type": row.get("match_type", "exact"),
                "note": row.get("note", ""),
            })

    terms.sort(key=lambda x: len(x["source_term"]), reverse=True)

    return terms


def normalize_for_match(text: str, case_sensitive: bool) -> str:
    text = str(text or "")

    if case_sensitive:
        return text

    return text.lower()


def term_exists_in_text(text: str, term: Dict[str, Any]) -> bool:
    term_text = str(term.get("source_term", "") or "")
    lang = str(term.get("source_lang", "") or "")
    case_sensitive = bool(term.get("case_sensitive", False))

    if not text or not term_text:
        return False

    text_for_match = normalize_for_match(text, case_sensitive)
    term_for_match = normalize_for_match(term_text, case_sensitive)

    alphabetic_langs = {
        "en", "es", "de", "fr", "pt", "it", "nl", "no", "sv", "vi", "id", "ms"
    }

    if lang in alphabetic_langs:
        escaped = re.escape(term_for_match)
        pattern = rf"(?<![A-Za-z0-9_]){escaped}(?![A-Za-z0-9_])"
        return re.search(pattern, text_for_match) is not None

    return term_for_match in text_for_match


def match_terms_in_source(
    source_text: str,
    terms: List[Dict[str, Any]],
    max_terms: int = 30,
) -> List[Dict[str, Any]]:
    matched: List[Dict[str, Any]] = []
    seen = set()

    for term in terms:
        source_term = term.get("source_term", "")
        target_term = term.get("target_term", "")
        key = (source_term, target_term)

        if key in seen:
            continue

        if term_exists_in_text(source_text, term):
            matched.append(term)
            seen.add(key)

        if len(matched) >= max_terms:
            break

    return matched


def format_term_table(matched_terms: List[Dict[str, Any]]) -> str:
    if not matched_terms:
        return "无"

    lines = []

    for term in matched_terms:
        source_term = term.get("source_term", "")
        target_term = term.get("target_term", "")
        priority = term.get("priority", "")

        if source_term and target_term:
            if priority:
                lines.append(f"- {source_term} => {target_term} ｜ priority={priority}")
            else:
                lines.append(f"- {source_term} => {target_term}")

    return "\n".join(lines) if lines else "无"


def build_messages(
    src_text: str,
    src_lang: str,
    tgt_lang: str,
    matched_terms: List[Dict[str, Any]],
    use_terms: bool = True,
) -> List[Dict[str, str]]:
    src_lang_name = lang_name(src_lang)
    tgt_lang_name = "Chinese" if normalize_lang_code(tgt_lang) == "zh" else lang_name(tgt_lang)

    if use_terms:
        term_table = format_term_table(matched_terms)

        system = (
            "你是一名汽车标准法规翻译专家。"
            "请严格遵守用户提供的翻译要求和术语表。"
            "只输出中文译文，不输出解释、注释、总结或额外说明。"
        )

        user = (
            f"请将以下{src_lang_name}汽车标准法规文本翻译为中文。\n\n"
            "翻译要求：\n"
            "1. 忠实表达原文含义，不得增删事实。\n"
            "2. 保留条款编号、数字、单位、日期、标准号和引用关系。\n"
            "3. 使用正式、严谨、符合中文法规文本习惯的表达。\n"
            "4. 严格使用术语表中的指定译法。\n"
            "5. 不输出解释、注释、总结或额外说明。\n"
            "6. 只输出中文译文。\n\n"
            "术语表：\n"
            f"{term_table}\n\n"
            "原文：\n"
            f"{src_text}"
        )
    else:
        system = (
            "You are a professional translator for automotive regulatory documents. "
            "Translate into Chinese only. Do not explain."
        )

        user = (
            f"Translate from {src_lang_name} to {tgt_lang_name}.\n\n"
            "Rules:\n"
            "- Preserve numbers, units, references, parentheses and section numbers.\n"
            "- Output only the translated text.\n\n"
            f"Text:\n{src_text}"
        )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def clean_translation(text: str) -> str:
    text = str(text or "").strip()

    # 去掉少量模型可能生成的包裹符号
    text = re.sub(r"^\s*```(?:text|markdown|json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```\s*$", "", text)

    # 去掉常见前缀
    prefixes = [
        "中文译文：",
        "译文：",
        "翻译：",
        "Translation:",
        "Chinese translation:",
    ]

    for p in prefixes:
        if text.startswith(p):
            text = text[len(p):].strip()

    return text.strip()


def chunked(items: List[Any], batch_size: int):
    for i in range(0, len(items), batch_size):
        yield i, items[i:i + batch_size]


def generate_batch(
    tokenizer,
    model,
    device: str,
    prompts: List[str],
    max_new_tokens: int,
) -> List[str]:
    inputs = tokenizer(
        prompts,
        return_tensors="pt",
        padding=True,
        truncation=True,
    )

    inputs = {k: v.to(device) for k, v in inputs.items()}

    input_len = inputs["input_ids"].shape[1]

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            temperature=None,
            top_p=None,
            top_k=None,
            pad_token_id=tokenizer.eos_token_id,
        )

    results = []

    for output_ids in outputs:
        new_tokens = output_ids[input_len:]
        text = tokenizer.decode(new_tokens.cpu(), skip_special_tokens=True)
        results.append(clean_translation(text))

    return results


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--input", required=True, help="Input JSONL file.")
    parser.add_argument("--output", required=True, help="Output JSONL file.")
    parser.add_argument("--summary", default="", help="Summary JSON path.")

    parser.add_argument("--model-path", default="/data/MODEL_DIR/Qwen2.5-14B-Instruct")
    parser.add_argument("--model-name", default="Qwen2.5-14B-Instruct")
    parser.add_argument("--device", default="npu:0")

    parser.add_argument("--src-lang", default="", help="Override source language code, e.g. en/de/fr.")
    parser.add_argument("--tgt-lang", default="zh")

    parser.add_argument("--termbase", default="termbase/auto_regulation_terms_v0.2.csv")
    parser.add_argument("--disable-terms", action="store_true")
    parser.add_argument("--max-terms", type=int, default=30)

    parser.add_argument("--prompt-version", default="prompt_v3_local")
    parser.add_argument("--termbase-version", default="termbase_v0.3_candidate")

    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--max-new-tokens", type=int, default=512)

    args = parser.parse_args()

    if not args.summary:
        args.summary = str(Path(args.output).with_suffix(".summary.json"))

    print("=" * 80, flush=True)
    print("[LOCAL-QWEN-FAST]", flush=True)
    print(f"[MODEL] {args.model_path}", flush=True)
    print(f"[DEVICE] {args.device}", flush=True)
    print(f"[INPUT] {args.input}", flush=True)
    print(f"[OUTPUT] {args.output}", flush=True)
    print(f"[BATCH] batch_size={args.batch_size}, max_new_tokens={args.max_new_tokens}", flush=True)
    print("=" * 80, flush=True)

    torch.npu.set_device(args.device)

    rows = read_jsonl(args.input)

    if args.limit and args.limit > 0:
        rows = rows[: args.limit]

    start_index = max(args.start, 1)

    already_done = 0
    if args.skip_existing and os.path.exists(args.output):
        already_done = count_jsonl(args.output)
        start_index = max(start_index, already_done + 1)

    if not args.skip_existing and os.path.exists(args.output):
        os.remove(args.output)

    rows_with_idx = [
        (idx, row)
        for idx, row in enumerate(rows, start=1)
        if idx >= start_index
    ]

    if not rows_with_idx:
        print("[DONE] Nothing to translate.", flush=True)
        return

    # 按语种加载术语。为了兼容多语种输入，这里做 per-language cache。
    term_cache: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}

    def get_terms(src_lang_code: str, tgt_lang_code: str):
        if args.disable_terms:
            return []

        key = (src_lang_code, tgt_lang_code)

        if key not in term_cache:
            term_cache[key] = load_termbase(
                termbase_path=args.termbase,
                source_lang=src_lang_code,
                target_lang=tgt_lang_code,
            )
            print(f"[TERM] loaded {len(term_cache[key])} terms for {src_lang_code}->{tgt_lang_code}", flush=True)

        return term_cache[key]

    print("[LOAD] tokenizer...", flush=True)
    tokenizer = AutoTokenizer.from_pretrained(
        args.model_path,
        trust_remote_code=True,
        local_files_only=True,
        padding_side="left",
    )

    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token

    print("[LOAD] model...", flush=True)
    t_load = time.time()

    model = AutoModelForCausalLM.from_pretrained(
        args.model_path,
        trust_remote_code=True,
        local_files_only=True,
        torch_dtype=torch.float16,
        low_cpu_mem_usage=True,
    )

    print("[LOAD] moving model to NPU...", flush=True)
    model = model.to(args.device)
    model.eval()

    load_sec = round(time.time() - t_load, 3)
    print(f"[LOAD] done, load_sec={load_sec}", flush=True)

    total_start = time.time()
    success_count = 0
    failed_count = 0
    total_term_hits = 0
    records_with_terms = 0
    latencies = []

    prepared = []

    for idx, row in rows_with_idx:
        src_text = pick_src_text(row)

        src_lang_code = normalize_lang_code(
            args.src_lang
            or row.get("source_lang")
            or row.get("src_lang")
            or row.get("lang")
            or ""
        )

        tgt_lang_code = normalize_lang_code(
            row.get("target_lang")
            or row.get("tgt_lang")
            or args.tgt_lang
            or "zh"
        )

        if not src_lang_code:
            src_lang_code = "en"

        if not tgt_lang_code:
            tgt_lang_code = "zh"

        terms = get_terms(src_lang_code, tgt_lang_code)
        matched_terms = []

        if not args.disable_terms and terms:
            matched_terms = match_terms_in_source(
                source_text=src_text,
                terms=terms,
                max_terms=args.max_terms,
            )

        if matched_terms:
            records_with_terms += 1
            total_term_hits += len(matched_terms)

        messages = build_messages(
            src_text=src_text,
            src_lang=src_lang_code,
            tgt_lang=tgt_lang_code,
            matched_terms=matched_terms,
            use_terms=not args.disable_terms,
        )

        prompt = tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )

        prepared.append({
            "idx": idx,
            "row": row,
            "sample_id": pick_sample_id(row, idx),
            "source_text": src_text,
            "source_lang": src_lang_code,
            "target_lang": tgt_lang_code,
            "matched_terms": matched_terms,
            "prompt": prompt,
        })

    print(f"[RUN] prepared={len(prepared)}", flush=True)

    for batch_start, batch_items in chunked(prepared, args.batch_size):
        batch_t0 = time.time()

        prompts = [item["prompt"] for item in batch_items]

        try:
            translations = generate_batch(
                tokenizer=tokenizer,
                model=model,
                device=args.device,
                prompts=prompts,
                max_new_tokens=args.max_new_tokens,
            )

            batch_latency_ms = int((time.time() - batch_t0) * 1000)
            per_item_latency_ms = int(batch_latency_ms / max(len(batch_items), 1))

            for item, translation in zip(batch_items, translations):
                out = dict(item["row"])
                out.update({
                    "sample_id": item["sample_id"],
                    "source_lang": item["source_lang"],
                    "target_lang": item["target_lang"],
                    "source_text": item["source_text"],
                    "translation": translation,
                    "mt_text": translation,
                    "model": args.model_name,
                    "model_path": args.model_path,
                    "mt_model": args.model_name,
                    "engine": "local",
                    "mt_engine": "local",
                    "device": "ascend_910b",
                    "active_device": args.device,
                    "num_cards": 1,
                    "prompt_version": args.prompt_version,
                    "termbase_version": args.termbase_version,
                    "term_injection": not args.disable_terms,
                    "matched_terms": [
                        {
                            "term_id": t.get("term_id", ""),
                            "source_term": t.get("source_term", ""),
                            "target_term": t.get("target_term", ""),
                            "domain": t.get("domain", ""),
                            "priority": t.get("priority", ""),
                        }
                        for t in item["matched_terms"]
                    ],
                    "matched_term_count": len(item["matched_terms"]),
                    "term_table": format_term_table(item["matched_terms"]),
                    "latency_ms": per_item_latency_ms,
                    "batch_latency_ms": batch_latency_ms,
                    "batch_size": len(batch_items),
                    "status": "success" if translation else "failed",
                    "error_type": "" if translation else "empty_output",
                    "error_message": "",
                    "created_at": now_iso(),
                })

                append_jsonl(args.output, out)

                if translation:
                    success_count += 1
                else:
                    failed_count += 1

                latencies.append(per_item_latency_ms)

        except Exception as exc:
            batch_latency_ms = int((time.time() - batch_t0) * 1000)
            per_item_latency_ms = int(batch_latency_ms / max(len(batch_items), 1))

            for item in batch_items:
                out = dict(item["row"])
                out.update({
                    "sample_id": item["sample_id"],
                    "source_lang": item["source_lang"],
                    "target_lang": item["target_lang"],
                    "source_text": item["source_text"],
                    "translation": "",
                    "mt_text": "",
                    "model": args.model_name,
                    "model_path": args.model_path,
                    "mt_model": args.model_name,
                    "engine": "local",
                    "mt_engine": "local",
                    "device": "ascend_910b",
                    "active_device": args.device,
                    "num_cards": 1,
                    "prompt_version": args.prompt_version,
                    "termbase_version": args.termbase_version,
                    "term_injection": not args.disable_terms,
                    "matched_terms": [
                        {
                            "term_id": t.get("term_id", ""),
                            "source_term": t.get("source_term", ""),
                            "target_term": t.get("target_term", ""),
                            "domain": t.get("domain", ""),
                            "priority": t.get("priority", ""),
                        }
                        for t in item["matched_terms"]
                    ],
                    "matched_term_count": len(item["matched_terms"]),
                    "term_table": format_term_table(item["matched_terms"]),
                    "latency_ms": per_item_latency_ms,
                    "batch_latency_ms": batch_latency_ms,
                    "batch_size": len(batch_items),
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "created_at": now_iso(),
                })

                append_jsonl(args.output, out)
                failed_count += 1
                latencies.append(per_item_latency_ms)

            print(f"[ERROR] batch_start={batch_start}, error={type(exc).__name__}: {exc}", flush=True)

        done = success_count + failed_count
        print(
            f"[PROGRESS] done={done}/{len(prepared)}, "
            f"success={success_count}, failed={failed_count}, "
            f"last_batch_latency_ms={batch_latency_ms}",
            flush=True,
        )

    total_time_sec = round(time.time() - total_start, 3)

    avg_latency_ms = round(sum(latencies) / len(latencies), 3) if latencies else 0
    throughput = round((success_count / total_time_sec) * 60, 3) if total_time_sec else 0

    sorted_latencies = sorted(latencies)

    def percentile(values, p):
        if not values:
            return 0
        k = int(round((len(values) - 1) * p))
        return values[k]

    summary = {
        "model": args.model_name,
        "model_path": args.model_path,
        "engine": "local",
        "device": "ascend_910b",
        "active_device": args.device,
        "num_cards": 1,
        "input": args.input,
        "output": args.output,
        "total_samples": len(prepared),
        "success_count": success_count,
        "failed_count": failed_count,
        "total_time_sec": total_time_sec,
        "load_sec": load_sec,
        "average_latency_ms": avg_latency_ms,
        "p50_latency_ms": percentile(sorted_latencies, 0.50),
        "p95_latency_ms": percentile(sorted_latencies, 0.95),
        "throughput_samples_per_min": throughput,
        "batch_size": args.batch_size,
        "max_new_tokens": args.max_new_tokens,
        "term_injection": not args.disable_terms,
        "records_with_terms": records_with_terms,
        "total_term_hits": total_term_hits,
        "prompt_version": args.prompt_version,
        "termbase_version": args.termbase_version,
        "created_at": now_iso(),
    }

    write_json(args.summary, summary)

    print("=" * 80, flush=True)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    print("=" * 80, flush=True)


if __name__ == "__main__":
    main()