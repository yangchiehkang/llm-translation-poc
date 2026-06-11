#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Parallel XCOMET-XXL QE scoring for qwen-max term-prompt translations.

Strategy:
1. Read JSONL files from:
      data/mt/qwen-max-term/
2. Split work by language/file.
3. For each file, create a temporary one-file mt_dir.
4. Launch scripts/evaluation/score_qwen_max_qe.py in parallel.
5. Bind each worker to a selected NPU using environment variables.
6. Merge all per-language Excel reports into one workbook:
      data/report/xcomet-xxl-qe/qwen_max_term_prompt_xcomet_xxl_qe.xlsx

This launcher does not modify score_qwen_max_qe.py.
"""

from __future__ import annotations

import os
import re
import sys
import time
import shutil
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def set_base_env(env: dict) -> dict:
    env.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    env.setdefault("HF_HOME", "/data/yinzs/models/huggingface")
    env.setdefault("HUGGINGFACE_HUB_CACHE", "/data/yinzs/models/huggingface/hub")
    env.setdefault("TRANSFORMERS_CACHE", "/data/yinzs/models/huggingface/transformers")
    env.setdefault("TORCH_HOME", "/data/yinzs/models/torch")
    env.setdefault("COMET_CACHE", "/data/yinzs/models/comet")
    env.setdefault("TOKENIZERS_PARALLELISM", "false")
    return env


def infer_lang(path: Path) -> str:
    name = path.name.lower()

    patterns = [
        r"mt_([a-z]{2})\._qwen-max\.jsonl",
        r"mt_([a-z]{2})_qwen-max\.jsonl",
        r"^([a-z]{2})\.jsonl",
    ]

    for p in patterns:
        m = re.search(p, name)
        if m:
            return m.group(1)

    return path.stem


def prepare_one_file_dir(src_file: Path, tmp_root: Path, lang: str) -> Path:
    one_dir = tmp_root / lang
    one_dir.mkdir(parents=True, exist_ok=True)

    dst = one_dir / src_file.name

    if dst.exists():
        dst.unlink()

    shutil.copy2(src_file, dst)

    return one_dir


def run_one_language(
    lang: str,
    src_file: Path,
    npu_id: int,
    root: Path,
    score_script: Path,
    xcomet_ckpt: Path,
    tmp_root: Path,
    per_lang_out_dir: Path,
    batch: str,
) -> tuple[str, int, Path]:
    one_mt_dir = prepare_one_file_dir(src_file, tmp_root, lang)
    out_xlsx = per_lang_out_dir / f"qwen_max_term_prompt_{lang}_xcomet_xxl_qe.xlsx"

    env = os.environ.copy()
    env = set_base_env(env)

    # Ascend / torch-npu 常用可见卡控制变量
    env["ASCEND_RT_VISIBLE_DEVICES"] = str(npu_id)
    env["ASCEND_VISIBLE_DEVICES"] = str(npu_id)
    env["CUDA_VISIBLE_DEVICES"] = str(npu_id)

    # 降低多进程 CPU 线程争抢
    env.setdefault("OMP_NUM_THREADS", "4")
    env.setdefault("MKL_NUM_THREADS", "4")
    env.setdefault("NUMEXPR_NUM_THREADS", "4")

    cmd = [
        sys.executable,
        str(score_script),
        "--mt_dir",
        str(one_mt_dir),
        "--out_xlsx",
        str(out_xlsx),
        "--xcomet_ckpt",
        str(xcomet_ckpt),
        "--device",
        "npu",
        "--batch",
        batch,
        "--glob",
        "*.jsonl",
    ]

    print("=" * 80, flush=True)
    print(f"[START] lang={lang}, npu={npu_id}", flush=True)
    print(f"[INPUT] {src_file}", flush=True)
    print(f"[OUT  ] {out_xlsx}", flush=True)
    print("[CMD  ] " + " ".join(cmd), flush=True)
    print("=" * 80, flush=True)

    t0 = time.time()

    result = subprocess.run(
        cmd,
        cwd=str(root),
        env=env,
    )

    elapsed = time.time() - t0

    if result.returncode == 0:
        print(f"[OK] lang={lang}, npu={npu_id}, elapsed={elapsed:.1f}s, out={out_xlsx}", flush=True)
    else:
        print(f"[ERROR] lang={lang}, npu={npu_id}, returncode={result.returncode}", flush=True)

    return lang, result.returncode, out_xlsx


def merge_excels(per_lang_files: list[Path], final_xlsx: Path) -> None:
    import pandas as pd

    final_xlsx.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(final_xlsx, engine="openpyxl") as writer:
        summary_rows = []

        for path in per_lang_files:
            if not path.exists():
                continue

            lang = infer_lang(path)

            try:
                xl = pd.ExcelFile(path)

                for sheet_name in xl.sheet_names:
                    df = pd.read_excel(path, sheet_name=sheet_name)

                    safe_sheet = f"{lang}_{sheet_name}"[:31]
                    df.to_excel(writer, index=False, sheet_name=safe_sheet)

                    score_col = None
                    for c in df.columns:
                        c_lower = str(c).lower()
                        if c_lower in ("score", "qe_score", "xcomet_score", "xcomet_xxl_score", "comet_score"):
                            score_col = c
                            break

                    if score_col is None:
                        for c in df.columns:
                            c_lower = str(c).lower()
                            if "score" in c_lower or "xcomet" in c_lower or "comet" in c_lower:
                                score_col = c
                                break

                    if score_col is not None:
                        values = pd.to_numeric(df[score_col], errors="coerce").dropna()
                        if len(values) > 0:
                            summary_rows.append(
                                {
                                    "lang": lang,
                                    "source_file": path.name,
                                    "sheet": sheet_name,
                                    "score_column": score_col,
                                    "count": int(len(values)),
                                    "mean": float(values.mean()),
                                    "min": float(values.min()),
                                    "max": float(values.max()),
                                }
                            )
                    else:
                        summary_rows.append(
                            {
                                "lang": lang,
                                "source_file": path.name,
                                "sheet": sheet_name,
                                "score_column": "",
                                "count": len(df),
                                "mean": "",
                                "min": "",
                                "max": "",
                            }
                        )

            except Exception as e:
                summary_rows.append(
                    {
                        "lang": lang,
                        "source_file": path.name,
                        "sheet": "READ_FAILED",
                        "score_column": "",
                        "count": 0,
                        "mean": "",
                        "min": "",
                        "max": "",
                        "error": str(e),
                    }
                )

        summary_df = pd.DataFrame(summary_rows)

        if summary_df.empty:
            summary_df = pd.DataFrame(
                [
                    {
                        "lang": "",
                        "source_file": "",
                        "sheet": "",
                        "score_column": "",
                        "count": 0,
                        "mean": "",
                        "min": "",
                        "max": "",
                    }
                ]
            )

        summary_df.to_excel(writer, index=False, sheet_name="summary")

    print("=" * 80, flush=True)
    print(f"[MERGED] {final_xlsx}", flush=True)
    print("=" * 80, flush=True)


def main() -> int:
    root = project_root()

    score_script = root / "scripts" / "evaluation" / "score_qwen_max_qe.py"
    mt_dir = root / "data" / "mt" / "qwen-max-term"

    out_dir = root / "data" / "report" / "xcomet-xxl-qe"
    per_lang_out_dir = out_dir / "term-prompt-per-lang"
    final_xlsx = out_dir / "qwen_max_term_prompt_xcomet_xxl_qe.xlsx"

    tmp_root = root / "data" / "tmp" / "xcomet-term-prompt-by-lang"

    xcomet_ckpt = Path("/data/yinzs/models/xcomet-xxl/checkpoints/model.ckpt")

    # 先避开已经被 vLLM 大量占用的 2、3。
    # 从你的 npu-smi 看，4 也有较大占用，稳妥起见先用 0、1、5、6、7。
    npu_ids = [0, 1, 5, 6, 7]

    # 如果想更激进，可以改成：
    # npu_ids = [0, 1, 4, 5, 6, 7]

    batch = "1"

    print("=" * 80)
    print("Parallel XCOMET-XXL QE Scoring - Qwen-Max Term Prompt")
    print("=" * 80)
    print(f"Project root     : {root}")
    print(f"Score script     : {score_script}")
    print(f"MT dir           : {mt_dir}")
    print(f"Per-lang out dir : {per_lang_out_dir}")
    print(f"Final xlsx       : {final_xlsx}")
    print(f"Tmp root         : {tmp_root}")
    print(f"XCOMET ckpt      : {xcomet_ckpt}")
    print(f"NPU ids          : {npu_ids}")
    print(f"Batch            : {batch}")
    print("=" * 80)

    if not score_script.is_file():
        print(f"[ERROR] score script not found: {score_script}", file=sys.stderr)
        return 1

    if not mt_dir.is_dir():
        print(f"[ERROR] mt_dir not found: {mt_dir}", file=sys.stderr)
        return 1

    if not xcomet_ckpt.is_file():
        print(f"[ERROR] XCOMET-XXL checkpoint not found: {xcomet_ckpt}", file=sys.stderr)
        return 1

    files = sorted(mt_dir.glob("*.jsonl"))

    if not files:
        print(f"[ERROR] no jsonl files found in: {mt_dir}", file=sys.stderr)
        return 1

    jobs = []
    for i, f in enumerate(files):
        lang = infer_lang(f)
        npu_id = npu_ids[i % len(npu_ids)]
        jobs.append((lang, f, npu_id))

    print("Jobs:")
    for lang, f, npu_id in jobs:
        print(f"  - lang={lang:>3} npu={npu_id} file={f.name}")
    print("=" * 80)

    per_lang_out_dir.mkdir(parents=True, exist_ok=True)
    tmp_root.mkdir(parents=True, exist_ok=True)

    finished_files: list[Path] = []
    failed = []

    max_workers = len(npu_ids)

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = []

        for lang, f, npu_id in jobs:
            fut = ex.submit(
                run_one_language,
                lang,
                f,
                npu_id,
                root,
                score_script,
                xcomet_ckpt,
                tmp_root,
                per_lang_out_dir,
                batch,
            )
            futs.append(fut)

        for fut in as_completed(futs):
            lang, code, out_xlsx = fut.result()

            if code == 0 and out_xlsx.exists():
                finished_files.append(out_xlsx)
            else:
                failed.append((lang, code, out_xlsx))

    print("=" * 80)
    print("[PARALLEL FINISHED]")
    print(f"Success: {len(finished_files)}")
    print(f"Failed : {len(failed)}")
    print("=" * 80)

    if failed:
        for lang, code, out_xlsx in failed:
            print(f"[FAILED] lang={lang}, code={code}, out={out_xlsx}")

    if finished_files:
        merge_excels(sorted(finished_files), final_xlsx)

    if failed:
        return 1

    print("[DONE] all languages scored and merged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
