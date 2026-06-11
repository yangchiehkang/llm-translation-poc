# scripts/mt_local_madlad400.py
# -*- coding: utf-8 -*-

import os
import re
import json
import time
import glob
import argparse
from typing import Dict, Any, List, Optional

import torch
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM


def read_jsonl(path: str) -> List[Dict[str, Any]]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def write_jsonl(path: str, rows: List[Dict[str, Any]]):
    out_dir = os.path.dirname(path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


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
}

# 常见 MADLAD 目标语言 tag：<2en> <2zh> ...
_TGT_TAG = {k: f"<2{k}>" for k in _LANG_MAP.keys()}


def infer_src_lang_from_filename(path: str) -> Optional[str]:
    base = os.path.basename(path).lower()
    m = re.search(r"_src_([a-z]{2})", base)
    if not m:
        return None
    return _LANG_MAP.get(m.group(1))


def pick_src_text(r: Dict[str, Any]) -> str:
    return (r.get("src_text") or r.get("src") or r.get("source") or r.get("text") or "").strip()


def make_out_path(out_dir: str, in_file: str, model_id: str) -> str:
    base = os.path.basename(in_file)
    if base.lower().endswith(".jsonl"):
        base = base[:-5]
    safe_model = model_id.replace("/", "_").replace("\\", "_").replace(":", "_")
    return os.path.join(out_dir, f"mt_{base}_{safe_model}.jsonl")


def should_skip_file(path: str) -> bool:
    b = os.path.basename(path)
    if b.startswith("mt_"):
        return True
    if b.endswith(".da.jsonl"):
        return True
    return False


def build_prompt(src_text: str, tgt_iso: str, tgt_lang_name: str, mode: str) -> str:
    """
    mode:
      - tag: <2zh> {src}
      - instruct: Translate to Chinese: {src}
    """
    if mode == "tag":
        tag = _TGT_TAG.get(tgt_iso)
        return f"{tag} {src_text}" if tag else src_text
    elif mode == "instruct":
        # 指令式作为兜底（当 tag 不被 tokenizer 识别时更稳）
        return f"Translate to {tgt_lang_name}: {src_text}"
    else:
        raise ValueError(f"Unknown prompt_mode: {mode}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in_file", default=None, help="Single input jsonl file")
    ap.add_argument("--in_dir", default=None, help="Input directory, will glob *.jsonl")
    ap.add_argument("--in_glob", default=None, help="Glob pattern, e.g. data/eval/*.jsonl")

    ap.add_argument("--out_dir", required=True, help="Output dir, e.g. data/mt")
    ap.add_argument("--model_path", required=True, help="Local model dir path on server")

    ap.add_argument("--tgt_lang", required=True, help="Target ISO code: zh/en/de/fr/es/ru/ar/th/ms")
    ap.add_argument("--src_lang", default=None, help="Optional source language name override (for metadata)")

    ap.add_argument("--max_new_tokens", type=int, default=256)
    ap.add_argument("--num_beams", type=int, default=1)

    # 采样默认关闭（更稳）；需要采样再开
    ap.add_argument("--do_sample", action="store_true")
    ap.add_argument("--temperature", type=float, default=0.7)

    ap.add_argument("--sleep", type=float, default=0.0)
    ap.add_argument("--dtype", default="float16", choices=["float16", "bfloat16", "float32"])
    ap.add_argument("--batch_size", type=int, default=8)

    ap.add_argument("--device", default="cuda:0", help="e.g. cuda:0 / cpu")
    ap.add_argument("--prompt_mode", default="tag", choices=["tag", "instruct"])
    ap.add_argument("--overwrite", action="store_true", help="Overwrite existing output file")
    ap.add_argument("--debug_tag", action="store_true", help="Print how <2xx> tag is tokenized")

    args = ap.parse_args()

    if not os.path.exists(args.model_path):
        raise FileNotFoundError(f"model_path not found: {args.model_path}")

    # Collect input files
    in_files: List[str] = []
    if args.in_file:
        in_files = [args.in_file]
    elif args.in_glob:
        in_files = sorted(glob.glob(args.in_glob))
    elif args.in_dir:
        in_files = sorted(glob.glob(os.path.join(args.in_dir, "*.jsonl")))
    else:
        raise RuntimeError("Please provide one of: --in_file / --in_dir / --in_glob")

    in_files = [p for p in in_files if os.path.isfile(p) and not should_skip_file(p)]
    if not in_files:
        raise RuntimeError("No input jsonl files found after filtering.")

    # dtype
    if args.dtype == "float16":
        torch_dtype = torch.float16
    elif args.dtype == "bfloat16":
        torch_dtype = torch.bfloat16
    else:
        torch_dtype = torch.float32

    # tgt lang
    tgt_iso = args.tgt_lang.strip().lower()
    if not re.fullmatch(r"[a-z]{2}", tgt_iso):
        raise ValueError(f"tgt_lang should be 2-letter ISO code, got: {args.tgt_lang}")
    tgt_lang_name = _LANG_MAP.get(tgt_iso, tgt_iso)

    # Load tokenizer/model (更稳：use_fast=False；显式 device；不使用 device_map)
    tok = AutoTokenizer.from_pretrained(args.model_path, local_files_only=True, use_fast=False)
    model = AutoModelForSeq2SeqLM.from_pretrained(
        args.model_path,
        local_files_only=True,
        torch_dtype=torch_dtype,
    ).to(args.device)
    model.eval()

    # Debug: check tag tokenization
    if args.debug_tag and tgt_iso in _TGT_TAG:
        tag = _TGT_TAG[tgt_iso]
        print("[DEBUG] tag:", tag)
        print("[DEBUG] tag tokenize:", tok.tokenize(tag))
        print("[DEBUG] tag ids:", tok.encode(tag, add_special_tokens=False))

        # 如果 tag 被拆得很碎，提示用户切换 instruct
        toks = tok.tokenize(tag)
        if len(toks) >= 4 and args.prompt_mode == "tag":
            print("[WARN] <2xx> tag seems NOT recognized as a stable token by tokenizer.")
            print("[WARN] Recommend rerun with: --prompt_mode instruct")

    os.makedirs(args.out_dir, exist_ok=True)

    for in_file in in_files:
        rows = read_jsonl(in_file)
        if not rows:
            raise RuntimeError(f"Empty input: {in_file}")

        src_lang_name = args.src_lang or infer_src_lang_from_filename(in_file) or "source language"
        out_path = make_out_path(args.out_dir, in_file, os.path.basename(os.path.normpath(args.model_path)))

        if os.path.exists(out_path) and (not args.overwrite):
            print(f"[SKIP] exists: {out_path} (use --overwrite to regenerate)")
            continue

        out_rows = []
        buf_texts: List[str] = []
        buf_idx: List[int] = []

        def flush_batch():
            nonlocal buf_texts, buf_idx, out_rows
            if not buf_texts:
                return

            enc = tok(
                buf_texts,
                return_tensors="pt",
                padding=True,
                truncation=True,
            )
            enc = {k: v.to(args.device) for k, v in enc.items()}

            gen = model.generate(
                **enc,
                max_new_tokens=args.max_new_tokens,
                num_beams=args.num_beams,
                do_sample=args.do_sample,
                temperature=args.temperature if args.do_sample else None,
                repetition_penalty=1.1,
                no_repeat_ngram_size=3,
            )

            outs = tok.batch_decode(gen, skip_special_tokens=True)
            for k, mt in zip(buf_idx, outs):
                rr = dict(rows[k])
                rr["src_lang"] = src_lang_name
                rr["tgt_lang"] = tgt_lang_name
                rr["mt_text"] = (mt or "").strip()
                rr["mt_model"] = os.path.basename(os.path.normpath(args.model_path))
                rr["mt_engine"] = "local_transformers"
                out_rows.append(rr)

            buf_texts = []
            buf_idx = []

        for i, r in enumerate(rows):
            src_text = pick_src_text(r)
            if not src_text:
                raise RuntimeError(f"Row missing text/src_text/src/source (line {i+1}) in {in_file}")

            prompt = build_prompt(src_text, tgt_iso, tgt_lang_name, args.prompt_mode)
            buf_texts.append(prompt)
            buf_idx.append(i)

            if len(buf_texts) >= max(1, args.batch_size):
                flush_batch()
                if args.sleep and args.sleep > 0:
                    time.sleep(args.sleep)

            if (i + 1) % 10 == 0:
                print(f"[{os.path.basename(in_file)}] [{i+1}/{len(rows)}] translated")

        flush_batch()
        write_jsonl(out_path, out_rows)
        print(f"[OK] Wrote: {out_path}  (rows={len(out_rows)})")


if __name__ == "__main__":
    main()
