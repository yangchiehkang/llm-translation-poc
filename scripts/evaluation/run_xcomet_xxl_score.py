#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Run XCOMET-XXL QE scoring for qwen-max translations.

This script is a thin launcher around:
    scripts/evaluation/score_qwen_max_qe.py

It sets cache paths to /data, uses the local XCOMET-XXL checkpoint,
and writes the scoring report to:
    data/report/xcomet-xxl-qe/qwen_max_xcomet_xxl_qe.xlsx
"""

from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path


def project_root() -> Path:
    """
    Resolve project root from this file location.

    Current file:
        scripts/evaluation/run_xcomet_xxl_score.py

    Project root:
        ../../
    """
    return Path(__file__).resolve().parents[2]


def set_env() -> None:
    """
    Set Hugging Face / COMET cache paths to /data.

    This avoids downloading or caching large files under /home.
    """
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    os.environ.setdefault("HF_HOME", "/data/SERVICE_USER/models/huggingface")
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", "/data/SERVICE_USER/models/huggingface/hub")
    os.environ.setdefault("TRANSFORMERS_CACHE", "/data/SERVICE_USER/models/huggingface/transformers")
    os.environ.setdefault("TORCH_HOME", "/data/SERVICE_USER/models/torch")
    os.environ.setdefault("COMET_CACHE", "/data/SERVICE_USER/models/comet")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


def main() -> int:
    set_env()

    root = project_root()

    score_script = root / "scripts" / "evaluation" / "score_qwen_max_qe.py"

    mt_dir = root / "data" / "mt" / "qwen-max"
    out_dir = root / "data" / "report" / "xcomet-xxl-qe"
    out_xlsx = out_dir / "qwen_max_xcomet_xxl_qe.xlsx"

    xcomet_ckpt = Path("/data/SERVICE_USER/models/xcomet-xxl/checkpoints/model.ckpt")

    device = "npu"
    batch = "1"
    glob_pattern = "*.jsonl"

    print("=" * 80)
    print("XCOMET-XXL QE Scoring")
    print("=" * 80)
    print(f"Project root : {root}")
    print(f"Score script : {score_script}")
    print(f"MT dir       : {mt_dir}")
    print(f"Output xlsx  : {out_xlsx}")
    print(f"XCOMET ckpt  : {xcomet_ckpt}")
    print(f"Device       : {device}")
    print(f"Batch        : {batch}")
    print(f"Glob         : {glob_pattern}")
    print("=" * 80)

    if not score_script.is_file():
        print(f"[ERROR] score script not found: {score_script}", file=sys.stderr)
        return 1

    if not mt_dir.is_dir():
        print(f"[ERROR] mt_dir not found: {mt_dir}", file=sys.stderr)
        return 1

    if not xcomet_ckpt.is_file():
        print(f"[ERROR] XCOMET-XXL checkpoint not found: {xcomet_ckpt}", file=sys.stderr)
        print("Please check whether the model has been downloaded successfully.", file=sys.stderr)
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        str(score_script),
        "--mt_dir",
        str(mt_dir),
        "--out_xlsx",
        str(out_xlsx),
        "--xcomet_ckpt",
        str(xcomet_ckpt),
        "--device",
        device,
        "--batch",
        batch,
        "--glob",
        glob_pattern,
    ]

    print("Running command:")
    print(" ".join(cmd))
    print("=" * 80)

    result = subprocess.run(
        cmd,
        cwd=str(root),
        env=os.environ.copy(),
    )

    if result.returncode != 0:
        print("=" * 80)
        print(f"[ERROR] scoring failed with return code: {result.returncode}", file=sys.stderr)
        print("=" * 80)
        return result.returncode

    print("=" * 80)
    print("Scoring finished successfully.")
    print(f"Report saved to: {out_xlsx}")
    print("=" * 80)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
