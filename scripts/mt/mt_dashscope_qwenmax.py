# scripts/mt/mt_dashscope_qwenmax.py
# -*- coding: utf-8 -*-

import os
import re
import sys
import csv
import json
import time
import glob
import argparse
from typing import Dict, Any, List, Optional, Tuple

from dashscope import Generation


def _looks_like_path(s: str) -> bool:
    s2 = s.strip('"')
    return (
        (":\\" in s2)
        or ("\\" in s2)
        or ("/" in s2)
        or s2.lower().endswith(".jsonl")
        or any(ch in s2 for ch in ["*", "?", "["])
    )


def _exists_file_or_dir(p: str) -> bool:
    p2 = p.strip('"')
    return os.path.exists(p2)


def _repair_argv_for_paths(argv: List[str]) -> List[str]:
    repaired: List[str] = []
    i = 0

    while i < len(argv):
        tok = argv[i]
        repaired.append(tok)

        if tok in ("--in_file", "--out_dir", "--termbase", "--prompt_doc"):
            if i + 1 >= len(argv):
                i += 1
                continue

            first = argv[i + 1]

            if not _looks_like_path(first):
                repaired.append(first)
                i += 2
                continue

            if _exists_file_or_dir(first):
                repaired.append(first)
                i += 2
                continue

            parts = [first]
            j = i + 2
            found = None

            while j < len(argv) and not argv[j].startswith("--"):
                parts.append(argv[j])
                candidate = " ".join(parts)

                if _exists_file_or_dir(candidate):
                    found = candidate
                    j += 1
                    break

                j += 1

            repaired.append(found if found is not None else " ".join(parts))
            i = j
            continue

        i += 1

    return repaired


def read_jsonl(path: str) -> List[Dict[str, Any]]:
    rows = []

    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()

            if not line:
                continue

            try:
                rows.append(json.loads(line))
            except Exception as e:
                raise RuntimeError(f"Invalid JSON on line {line_no} in {path}: {e}") from e

    return rows


def write_jsonl(path: str, rows: List[Dict[str, Any]]):
    out_dir = os.path.dirname(path)

    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def append_jsonl(path: str, row: Dict[str, Any]):
    out_dir = os.path.dirname(path)

    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def count_jsonl(path: str) -> int:
    if not os.path.exists(path):
        return 0

    n = 0

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                n += 1

    return n


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

_LANG_NAME_BY_CODE = dict(_LANG_MAP)

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


def normalize_lang_code(lang: str) -> str:
    value = (lang or "").strip().lower()

    if not value:
        return ""

    if value in _LANG_MAP:
        return value

    return _LANG_CODE_BY_NAME.get(value, value)


def infer_src_lang_from_filename(path: str) -> Optional[str]:
    base = os.path.basename(path).lower()
    m = re.search(r"_src_([a-z]{2})", base)

    if not m:
        return None

    return _LANG_NAME_BY_CODE.get(m.group(1))


def infer_src_lang_from_jsonl_basename(path: str) -> Optional[str]:
    base = os.path.basename(path).lower()
    m = re.match(r"^([a-z]{2})\.jsonl$", base)

    if not m:
        return None

    return _LANG_NAME_BY_CODE.get(m.group(1))


def infer_src_lang_code_from_jsonl_basename(path: str) -> Optional[str]:
    base = os.path.basename(path).lower()
    m = re.match(r"^([a-z]{2})\.jsonl$", base)

    if not m:
        return None

    code = m.group(1)

    if code in _LANG_MAP:
        return code

    return None


def infer_src_lang_from_row(r: Dict[str, Any]) -> Optional[str]:
    code = (r.get("lang") or r.get("src_lang") or "").strip().lower()

    if not code:
        return None

    if code in _LANG_MAP:
        return _LANG_NAME_BY_CODE.get(code)

    return code


def infer_src_lang_code_from_row(r: Dict[str, Any]) -> Optional[str]:
    value = (r.get("lang") or r.get("src_lang") or "").strip()

    if not value:
        return None

    code = normalize_lang_code(value)

    if code in _LANG_MAP:
        return code

    return None


def pick_src_text(r: Dict[str, Any]) -> str:
    return (
        r.get("src_text")
        or r.get("src")
        or r.get("source")
        or r.get("text")
        or ""
    ).strip()


def make_out_path(out_dir: str, in_file: str, model: str) -> str:
    base = os.path.basename(in_file)

    if base.lower().endswith(".jsonl"):
        base = base[:-5]

    safe_model = model.replace("/", "_")

    return os.path.join(out_dir, f"mt_{base}_{safe_model}.jsonl")


def normalize_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value

    text = str(value or "").strip().lower()

    return text in ("true", "1", "yes", "y")


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

            terms.append(
                {
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
                }
            )

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

        if source_term and target_term:
            lines.append(f"- {source_term} => {target_term}")

    return "\n".join(lines) if lines else "无"


def build_translate_prompt(
    src_text: str,
    src_lang: str,
    tgt_lang: str,
    matched_terms: Optional[List[Dict[str, Any]]] = None,
    use_terms: bool = True,
) -> List[Dict[str, str]]:
    term_table = format_term_table(matched_terms or [])

    if use_terms:
        system = (
            "你是一名汽车标准法规翻译专家。"
            "请严格遵守用户提供的翻译要求和术语表。"
            "只输出中文译文，不输出解释、注释、总结或额外说明。"
        )

        user = (
            "你是一名汽车标准法规翻译专家。请将以下文本翻译为中文。\n\n"
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
            "You are a professional translator for regulatory and technical documents. "
            "Preserve numbers, units, symbols, references, parentheses, section numbers. "
            "Keep the original structure such as list markers. "
            "Do not add explanations or extra text. Output only the translated text."
        )

        user = f"Translate from {src_lang} to {tgt_lang}.\n\nText:\n{src_text}"

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def write_prompt_doc(path: str):
    if not path:
        return

    out_dir = os.path.dirname(path)

    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    content = """# Prompt Term Injection V1

你是一名汽车标准法规翻译专家。请将以下文本翻译为中文。

翻译要求：
1. 忠实表达原文含义，不得增删事实。
2. 保留条款编号、数字、单位、日期、标准号和引用关系。
3. 使用正式、严谨、符合中文法规文本习惯的表达。
4. 严格使用术语表中的指定译法。
5. 不输出解释、注释、总结或额外说明。
6. 只输出中文译文。

术语表：
{term_table}

原文：
{source}

## 术语表格式

- vehicle => 车辆
- type approval => 型式认证
- braking system => 制动系统
"""

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _to_dict_maybe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return obj

    if hasattr(obj, "__dict__"):
        return obj.__dict__

    return obj


def _extract_choice_text(resp: Any) -> Tuple[Optional[str], str]:
    dbg_parts = []

    if isinstance(resp, dict):
        code = resp.get("code")
        message = resp.get("message")
        request_id = resp.get("request_id") or resp.get("requestId")
        output = resp.get("output")

        if code is not None:
            dbg_parts.append(f"code={code}")

        if message is not None:
            dbg_parts.append(f"message={message}")

        if request_id is not None:
            dbg_parts.append(f"request_id={request_id}")

        if isinstance(output, dict):
            choices = output.get("choices")

            if isinstance(choices, list) and choices:
                c0 = choices[0] if isinstance(choices[0], dict) else None
                msg = c0.get("message") if isinstance(c0, dict) else None

                if isinstance(msg, dict):
                    content = msg.get("content")

                    if isinstance(content, str):
                        return content.strip(), "; ".join(dbg_parts)

        return None, "; ".join(dbg_parts) or "no_debug_info"

    code = getattr(resp, "code", None)
    message = getattr(resp, "message", None)
    request_id = getattr(resp, "request_id", None) or getattr(resp, "requestId", None)

    if code is not None:
        dbg_parts.append(f"code={code}")

    if message is not None:
        dbg_parts.append(f"message={message}")

    if request_id is not None:
        dbg_parts.append(f"request_id={request_id}")

    output = getattr(resp, "output", None)

    if isinstance(output, dict):
        choices = output.get("choices")

        if isinstance(choices, list) and choices:
            c0 = choices[0] if isinstance(choices[0], dict) else None
            msg = c0.get("message") if isinstance(c0, dict) else None

            if isinstance(msg, dict):
                content = msg.get("content")

                if isinstance(content, str):
                    return content.strip(), "; ".join(dbg_parts)

    as_dict = _to_dict_maybe(resp)

    if isinstance(as_dict, dict) and as_dict is not resp:
        return _extract_choice_text(as_dict)

    return None, "; ".join(dbg_parts) or "no_debug_info"


def dashscope_translate_one(
    model: str,
    messages: List[Dict[str, str]],
    temperature: float,
    max_tokens: int,
    retries: int = 3,
    retry_sleep: float = 1.5,
    request_timeout: int = 60,
) -> str:
    last_err = None
    last_dbg = None

    for i in range(retries):
        try:
            resp = Generation.call(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                result_format="message",
                timeout=request_timeout,
            )

            text, dbg = _extract_choice_text(resp)

            if text is not None and text != "":
                return text

            last_dbg = dbg
            raise RuntimeError(f"Empty/invalid response structure ({dbg})")

        except TypeError:
            resp = Generation.call(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                result_format="message",
            )

            text, dbg = _extract_choice_text(resp)

            if text is not None and text != "":
                return text

            last_dbg = dbg
            last_err = RuntimeError(f"Empty/invalid response structure ({dbg})")

        except Exception as e:
            last_err = e
            print(f"[RETRY] attempt={i + 1}/{retries}, error={e}", flush=True)
            time.sleep(retry_sleep * (i + 1))

    raise RuntimeError(
        f"DashScope call failed after retries. Last error: {last_err}. Last debug: {last_dbg}"
    )


def _expand_in_files(in_specs: List[str]) -> List[str]:
    out: List[str] = []

    for spec in in_specs:
        s = spec.strip('"')

        if os.path.isdir(s):
            out.extend(sorted(glob.glob(os.path.join(s, "*.jsonl"))))
            continue

        if any(ch in s for ch in ["*", "?", "["]):
            out.extend(sorted(glob.glob(s)))
            continue

        out.append(s)

    seen = set()
    uniq = []

    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)

    return uniq


def _default_tgt_lang(s: str) -> str:
    t = (s or "").strip().lower()

    if t in (
        "zh",
        "zh-cn",
        "zh_hans",
        "chinese",
        "chinese (simplified)",
        "simplified chinese",
        "中文",
        "简体中文",
    ):
        return "Chinese"

    return s


def _default_tgt_lang_code(s: str) -> str:
    t = (s or "").strip().lower()

    if t in (
        "zh",
        "zh-cn",
        "zh_hans",
        "chinese",
        "chinese (simplified)",
        "simplified chinese",
        "中文",
        "简体中文",
    ):
        return "zh"

    return normalize_lang_code(s)


def main():
    argv = _repair_argv_for_paths(sys.argv[1:])

    ap = argparse.ArgumentParser()

    ap.add_argument(
        "--in_file",
        required=True,
        nargs="+",
        help="jsonl file(s) OR a directory OR glob pattern(s)",
    )

    ap.add_argument("--out_dir", required=True)
    ap.add_argument("--model", default="qwen-max")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--max_tokens", type=int, default=2048)
    ap.add_argument("--sleep", type=float, default=0.2)
    ap.add_argument("--src_lang", default=None)
    ap.add_argument("--tgt_lang", required=True)

    ap.add_argument(
        "--termbase",
        default="termbase/auto_regulation_terms.csv",
        help="Termbase CSV path",
    )

    ap.add_argument(
        "--max_terms",
        type=int,
        default=30,
        help="Maximum matched terms injected into one prompt",
    )

    ap.add_argument(
        "--disable_terms",
        action="store_true",
        help="Disable term injection",
    )

    ap.add_argument(
        "--prompt_doc",
        default="docs/prompt_term_v1.md",
        help="Prompt document output path",
    )

    ap.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Only translate first N rows after start. 0 means all.",
    )

    ap.add_argument(
        "--start",
        type=int,
        default=1,
        help="Start row index, 1-based.",
    )

    ap.add_argument(
        "--progress_every",
        type=int,
        default=1,
        help="Print progress every N rows.",
    )

    ap.add_argument(
        "--request_timeout",
        type=int,
        default=60,
        help="DashScope request timeout seconds.",
    )

    ap.add_argument(
        "--skip_existing",
        action="store_true",
        help="Skip rows already written in output jsonl.",
    )

    args = ap.parse_args(argv)

    api_key = os.getenv("DASHSCOPE_API_KEY")

    if not api_key:
        raise RuntimeError("Missing env DASHSCOPE_API_KEY. Please set it before running.")

    os.environ["DASHSCOPE_API_KEY"] = api_key

    in_files = _expand_in_files(args.in_file)

    if not in_files:
        raise FileNotFoundError(f"No input files matched: {args.in_file}")

    tgt_lang = _default_tgt_lang(args.tgt_lang)
    tgt_lang_code = _default_tgt_lang_code(args.tgt_lang)

    os.makedirs(args.out_dir, exist_ok=True)

    if not args.disable_terms:
        write_prompt_doc(args.prompt_doc)

    total_files = len(in_files)

    for fi, in_file in enumerate(in_files, start=1):
        if not os.path.exists(in_file):
            print(f"[SKIP] Input file not found: {in_file}", flush=True)
            continue

        try:
            rows = read_jsonl(in_file)
        except Exception as e:
            print(f"[SKIP] Failed to read jsonl: {in_file} ({e})", flush=True)
            continue

        if not rows:
            print(f"[SKIP] Empty input: {in_file}", flush=True)
            continue

        src_lang = (
            args.src_lang
            or infer_src_lang_from_row(rows[0])
            or infer_src_lang_from_jsonl_basename(in_file)
            or infer_src_lang_from_filename(in_file)
            or "source language"
        )

        src_lang_code = (
            normalize_lang_code(args.src_lang or "")
            or infer_src_lang_code_from_row(rows[0])
            or infer_src_lang_code_from_jsonl_basename(in_file)
            or normalize_lang_code(src_lang)
        )

        terms = []

        if not args.disable_terms:
            terms = load_termbase(
                termbase_path=args.termbase,
                source_lang=src_lang_code,
                target_lang=tgt_lang_code,
            )

        out_path = make_out_path(args.out_dir, in_file, args.model)

        already_done = 0

        if args.skip_existing and os.path.exists(out_path):
            already_done = count_jsonl(out_path)

        if not args.skip_existing and os.path.exists(out_path):
            os.remove(out_path)

        total_term_hits = 0
        records_with_terms = 0
        translated_count = 0

        start_index = max(args.start, 1)

        if args.skip_existing and already_done > 0:
            start_index = max(start_index, already_done + 1)

        end_index = len(rows)

        if args.limit and args.limit > 0:
            end_index = min(len(rows), start_index + args.limit - 1)

        print("=" * 80, flush=True)
        print(f"[FILE] {fi}/{total_files}: {in_file}", flush=True)
        print(f"[LANG] src_lang={src_lang}, src_lang_code={src_lang_code}, tgt_lang={tgt_lang}", flush=True)
        print(f"[TERM] loaded_terms={len(terms)}, term_injection={not args.disable_terms}", flush=True)
        print(f"[OUT ] {out_path}", flush=True)
        print(f"[RANGE] start={start_index}, end={end_index}, total={len(rows)}, skip_existing={args.skip_existing}, already_done={already_done}", flush=True)

        for idx, r in enumerate(rows, start=1):
            if idx < start_index:
                continue

            if idx > end_index:
                break

            src_text = pick_src_text(r)

            if not src_text:
                print(f"[WARN] Missing text fields on line {idx} in {in_file}, skip this row.", flush=True)
                continue

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

            print(
                f"[CALL] file={fi}/{total_files}, row={idx}/{len(rows)}, "
                f"matched_terms={len(matched_terms)}, chars={len(src_text)}",
                flush=True,
            )

            messages = build_translate_prompt(
                src_text=src_text,
                src_lang=src_lang,
                tgt_lang=tgt_lang,
                matched_terms=matched_terms,
                use_terms=not args.disable_terms,
            )

            try:
                mt_text = dashscope_translate_one(
                    model=args.model,
                    messages=messages,
                    temperature=args.temperature,
                    max_tokens=args.max_tokens,
                    request_timeout=args.request_timeout,
                )
            except KeyboardInterrupt:
                print("[STOP] KeyboardInterrupt received. Current progress saved.", flush=True)
                raise
            except Exception as e:
                mt_text = ""
                print(f"[ERROR] row={idx}, error={e}", flush=True)

            rr = dict(r)
            rr["src_lang"] = src_lang
            rr["src_lang_code"] = src_lang_code
            rr["tgt_lang"] = tgt_lang
            rr["tgt_lang_code"] = tgt_lang_code
            rr["mt_text"] = mt_text
            rr["mt_model"] = args.model
            rr["mt_engine"] = "dashscope"
            rr["term_injection"] = not args.disable_terms
            rr["matched_terms"] = [
                {
                    "term_id": t.get("term_id", ""),
                    "source_term": t.get("source_term", ""),
                    "target_term": t.get("target_term", ""),
                    "domain": t.get("domain", ""),
                    "priority": t.get("priority", ""),
                }
                for t in matched_terms
            ]
            rr["matched_term_count"] = len(matched_terms)
            rr["term_table"] = format_term_table(matched_terms)
            rr["mt_error"] = "" if mt_text else "translation_failed"

            append_jsonl(out_path, rr)

            translated_count += 1

            if args.sleep and args.sleep > 0:
                time.sleep(args.sleep)

            if args.progress_every > 0 and translated_count % args.progress_every == 0:
                print(
                    f"[PROGRESS] {os.path.basename(in_file)} "
                    f"translated={translated_count}, current_row={idx}, "
                    f"records_with_terms={records_with_terms}, total_term_hits={total_term_hits}",
                    flush=True,
                )

        print(
            f"[OK] {fi}/{total_files} Wrote: {out_path} "
            f"(new_rows={translated_count}, records_with_terms={records_with_terms}, total_term_hits={total_term_hits})",
            flush=True,
        )

    print("=" * 80, flush=True)
    print("[DONE] Prompt term injection translation finished.", flush=True)
    print(f"[PROMPT DOC] {args.prompt_doc if not args.disable_terms else 'disabled'}", flush=True)
    print("=" * 80, flush=True)


if __name__ == "__main__":
    main()
