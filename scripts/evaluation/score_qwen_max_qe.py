import os
import re
import json
import argparse
from typing import List, Dict, Any, Tuple, Optional

# -----------------------------
# Hugging Face cache / mirror
# -----------------------------
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HOME", "/home/SERVICE_USER/models/huggingface")
os.environ.setdefault("HUGGINGFACE_HUB_CACHE", "/home/SERVICE_USER/models/huggingface/hub")
os.environ.setdefault("TRANSFORMERS_CACHE", "/home/SERVICE_USER/models/huggingface/transformers")
os.environ.setdefault("TORCH_HOME", "/home/SERVICE_USER/models/torch")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import numpy as np
import pandas as pd
import torch

try:
    import torch_npu

    # Important for Ascend:
    # Redirect CUDA APIs used by COMET / PyTorch Lightning to NPU where possible.
    import torch_npu.contrib.transfer_to_npu

    HAS_NPU = True
except Exception:
    torch_npu = None
    HAS_NPU = False

from comet import load_from_checkpoint, download_model


# -----------------------------
# Excel sanitize, fix IllegalCharacterError
# -----------------------------
_ILLEGAL_XLSX_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")


def sanitize_for_excel(df: pd.DataFrame) -> pd.DataFrame:
    """Remove illegal control characters from all string/object columns so openpyxl will not crash."""
    obj_cols = df.select_dtypes(include=["object", "string"]).columns
    for c in obj_cols:
        s = df[c]
        mask = s.notna()
        if mask.any():
            df.loc[mask, c] = s.loc[mask].astype(str).map(lambda x: _ILLEGAL_XLSX_RE.sub("", x))
    return df


# -----------------------------
# IO helpers
# -----------------------------
def read_jsonl(path: str) -> List[Dict[str, Any]]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def norm(x: Any) -> str:
    return (x or "").strip() if isinstance(x, str) else (str(x).strip() if x is not None else "")


def safe_sheet_name(name: str) -> str:
    name = re.sub(r"[:\\/?*\[\]]+", "_", name)
    return (name[:31] if name else "sheet")


# -----------------------------
# Device helpers
# -----------------------------
def npu_is_available() -> bool:
    if not HAS_NPU:
        return False
    try:
        return bool(torch.npu.is_available())
    except Exception:
        return False


def patch_cuda_for_transfer_to_npu():
    """
    Patch CUDA capability checks for PyTorch Lightning when using
    torch_npu.contrib.transfer_to_npu on Ascend.

    Why:
      Lightning's CUDA accelerator calls:
        torch.cuda.get_device_capability(device)

      On Ascend, torch_npu may route this to torch.npu.get_device_capability,
      which is not implemented and returns None.

      Returning (8, 0) satisfies Lightning's expected tuple format.
    """
    if not HAS_NPU:
        return

    def fake_get_device_capability(device=None):
        return (8, 0)

    def fake_get_device_name(device=None):
        try:
            return torch.npu.get_device_name(0)
        except Exception:
            return "Ascend NPU"

    torch.cuda.get_device_capability = fake_get_device_capability
    torch.cuda.get_device_name = fake_get_device_name

    try:
        torch.set_float32_matmul_precision("high")
    except Exception:
        pass


def setup_device(device: str):
    """
    Setup runtime device.

    Supported:
      - cpu
      - cuda
      - npu

    For npu:
      We use torch_npu.contrib.transfer_to_npu, so COMET / Lightning will see
      a CUDA-compatible path, while actual execution is redirected to Ascend NPU.
    """
    print("torch cuda available:", torch.cuda.is_available())
    print("torch npu available:", npu_is_available())

    if device == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("You selected --device cuda, but torch.cuda.is_available() is False.")
        print("GPU:", torch.cuda.get_device_name(0))
        return

    if device == "npu":
        if not HAS_NPU:
            raise RuntimeError("You selected --device npu, but torch_npu import failed.")
        if not npu_is_available():
            raise RuntimeError("You selected --device npu, but torch.npu.is_available() is False.")

        torch.npu.set_device(0)
        patch_cuda_for_transfer_to_npu()

        print("torch.cuda.is_available after transfer_to_npu:", torch.cuda.is_available())
        print("torch.cuda.get_device_capability(0):", torch.cuda.get_device_capability(0))

        try:
            print("NPU:", torch.npu.get_device_name(0))
            print("CUDA-compatible device name:", torch.cuda.get_device_name(0))
        except Exception:
            print("NPU device 0 is available.")

        print("Using Ascend NPU via transfer_to_npu CUDA-compatible path.")
        return

    print("Using CPU.")


# -----------------------------
# Model loading
# -----------------------------
def load_metric_model(model_or_ckpt: str):
    """
    model_or_ckpt can be:
      - local .ckpt file path
      - local checkpoint directory
      - Hugging Face / COMET model name, e.g. Unbabel/XCOMET-XL
    """
    print(f"Resolving COMET model/checkpoint: {model_or_ckpt}")

    # Case 1: local file path, e.g. /path/to/model.ckpt
    if os.path.isfile(model_or_ckpt):
        if not model_or_ckpt.endswith(".ckpt"):
            raise ValueError(f"Local model file exists but is not a .ckpt file: {model_or_ckpt}")

        ckpt_path = model_or_ckpt
        print(f"Using local checkpoint file: {ckpt_path}")
        model = load_from_checkpoint(ckpt_path)
        return model, ckpt_path

    # Case 2: local directory path.
    # It may be:
    #   /path/to/snapshot/
    #   /path/to/snapshot/checkpoints/
    #   /path/to/unbabel_comet/model_name/
    if os.path.isdir(model_or_ckpt):
        candidates = []

        # Direct .ckpt files under this directory
        for name in os.listdir(model_or_ckpt):
            p = os.path.join(model_or_ckpt, name)
            if os.path.isfile(p) and p.endswith(".ckpt"):
                candidates.append(p)

        # Common COMET/HF layout: checkpoints/*.ckpt
        checkpoints_dir = os.path.join(model_or_ckpt, "checkpoints")
        if os.path.isdir(checkpoints_dir):
            for name in os.listdir(checkpoints_dir):
                p = os.path.join(checkpoints_dir, name)
                if os.path.isfile(p) and p.endswith(".ckpt"):
                    candidates.append(p)

        # Recursive fallback
        if not candidates:
            for root, _, files in os.walk(model_or_ckpt):
                for name in files:
                    if name.endswith(".ckpt"):
                        candidates.append(os.path.join(root, name))

        candidates = sorted(set(candidates))

        if not candidates:
            raise FileNotFoundError(f"No .ckpt file found under local directory: {model_or_ckpt}")

        ckpt_path = candidates[0]
        print(f"Using local checkpoint from directory: {ckpt_path}")
        model = load_from_checkpoint(ckpt_path)
        return model, ckpt_path

    # Case 3: model name, e.g. Unbabel/XCOMET-XL
    print(f"Treating as downloadable COMET/HF model name: {model_or_ckpt}")
    ckpt_path = download_model(model_or_ckpt)
    print(f"Downloaded/resolved checkpoint: {ckpt_path}")

    if not os.path.isfile(ckpt_path):
        raise FileNotFoundError(
            f"COMET returned checkpoint path, but file does not exist: {ckpt_path}"
        )

    model = load_from_checkpoint(ckpt_path)
    return model, ckpt_path


# -----------------------------
# Language helpers
# -----------------------------
LANG_ZH = {
    "zh": "中文",
    "en": "英语",
    "de": "德语",
    "fr": "法语",
    "es": "西班牙语",
    "ru": "俄语",
    "th": "泰语",
    "ms": "马来语",
    "it": "意大利语",
    "ja": "日语",
    "ko": "韩语",
    "pt": "葡萄牙语",
    "nl": "荷兰语",
    "pl": "波兰语",
    "cs": "捷克语",
    "tr": "土耳其语",
    "vi": "越南语",
    "id": "印尼语",
    "ar": "阿拉伯语",
}

LANG_ALIAS_TO_CODE = {
    "arabic": "ar",
    "english": "en",
    "german": "de",
    "french": "fr",
    "russian": "ru",
    "spanish": "es",
    "malay": "ms",
    "thai": "th",

    "ch": "zh",
    "cn": "zh",
    "chn": "zh",
    "chinese": "zh",
    "zhongwen": "zh",
    "zh-cn": "zh",
    "zh_cn": "zh",
    "chinesesimplified": "zh",
    "chinesetraditional": "zh",
}


def normalize_lang(code_or_name: str) -> str:
    s = (code_or_name or "").strip()
    if not s:
        return "unk"
    k = s.lower().strip()
    k = re.sub(r"[\(\)\[\]\{\}]", "", k)
    k = re.sub(r"[^a-z\-_/]+", "", k)
    return LANG_ALIAS_TO_CODE.get(k, k)


def lang_code_to_zh(code: str) -> str:
    code = normalize_lang(code)
    return LANG_ZH.get(code, f"未知语言({code})")


def parse_lang_pair(lp: str) -> Tuple[str, str]:
    """
    Parse lang_pair formats like:
      Arabic2Ch, English2Cn, de2zh, de-zh, de_zh, de→zh ...
    Return normalized codes, e.g. ('ar','zh')
    """
    if not lp:
        return ("unk", "unk")

    s0 = lp.strip().lower()
    s0 = s0.replace("→", "2").replace("->", "2").replace("-", "2").replace("_", "2").replace("/", "2")

    if "2" in s0:
        left, right = s0.split("2", 1)
        left = left.strip()
        right = right.strip()

        left_tok = re.findall(r"[a-z]{2,}", left)
        right_tok = re.findall(r"[a-z]{2,}", right)

        src_raw = left_tok[0] if left_tok else left
        tgt_raw = right_tok[0] if right_tok else right
        return normalize_lang(src_raw), normalize_lang(tgt_raw)

    parts = re.findall(r"[a-z]{2,}", s0)
    if len(parts) >= 2:
        return normalize_lang(parts[0]), normalize_lang(parts[1])

    return ("unk", "unk")


def infer_src_lang_from_filename(filename: str) -> Optional[str]:
    m = re.search(r"_src_([a-z]{2,3})(?:[^a-z]|$)", filename.lower())
    return normalize_lang(m.group(1)) if m else None


# -----------------------------
# COMET predict
# -----------------------------
def predict_scores(model, data, batch_size: int, device: str) -> List[float]:
    """
    Predict COMET scores.

    device:
      - cpu:
          COMET predict with gpus=0

      - cuda:
          COMET predict with CUDA path

      - npu:
          Use Ascend NPU through torch_npu.contrib.transfer_to_npu.
          Important:
            Do NOT manually move model to npu:0 here.
            Do NOT use gpus=0.
            Use gpus=1, devices=[0], accelerator="cuda".
    """
    if device == "cuda":
        pred = model.predict(
            data,
            batch_size=batch_size,
            gpus=1,
            devices=[0],
            accelerator="cuda",
            num_workers=0,
            progress_bar=True,
            length_batching=True,
        )
        return [float(s) for s in pred.scores]

    if device == "npu":
        if not HAS_NPU:
            raise RuntimeError("torch_npu is not available in this Python environment.")
        if not npu_is_available():
            raise RuntimeError("torch.npu.is_available() is False.")

        torch.npu.set_device(0)
        patch_cuda_for_transfer_to_npu()

        print("[NPU] Running COMET predict through CUDA-compatible Ascend path...")

        model.eval()

        with torch.no_grad():
            pred = model.predict(
                data,
                batch_size=batch_size,
                gpus=1,
                devices=[0],
                accelerator="cuda",
                num_workers=0,
                progress_bar=True,
                length_batching=True,
            )

        return [float(s) for s in pred.scores]

    # CPU fallback
    pred = model.predict(
        data,
        batch_size=batch_size,
        gpus=0,
        num_workers=0,
        progress_bar=True,
        length_batching=True,
    )
    return [float(s) for s in pred.scores]


# -----------------------------
# Scoring, QE: src + mt only
# -----------------------------
def score_one_file(fp: str, model, metric_model_label: str, batch: int, device: str) -> pd.DataFrame:
    rows = read_jsonl(fp)
    base = os.path.basename(fp)

    # Your jsonl keys
    SRC_KEY = "text"
    MT_KEY = "mt_text"

    missing_src = [i for i, r in enumerate(rows) if not norm(r.get(SRC_KEY))]
    missing_mt = [i for i, r in enumerate(rows) if not norm(r.get(MT_KEY))]

    if missing_src:
        raise ValueError(f"[{base}] missing `{SRC_KEY}` rows: {len(missing_src)} e.g. {missing_src[:5]}")
    if missing_mt:
        raise ValueError(f"[{base}] missing `{MT_KEY}` rows: {len(missing_mt)} e.g. {missing_mt[:5]}")

    data = [{"src": norm(r.get(SRC_KEY)), "mt": norm(r.get(MT_KEY))} for r in rows]
    scores = predict_scores(model, data, batch_size=batch, device=device)

    out = []
    src_lang_hint = infer_src_lang_from_filename(base)

    for r, sc in zip(rows, scores):
        raw_lp = norm(r.get("lang_pair"))
        raw_lang = norm(r.get("lang"))
        raw_src = norm(r.get("src_lang"))
        raw_tgt = norm(r.get("tgt_lang"))

        if raw_lp:
            src_lang, tgt_lang = parse_lang_pair(raw_lp)
        else:
            src_lang = normalize_lang(raw_src or src_lang_hint or raw_lang or "unk")
            tgt_lang = normalize_lang(raw_tgt or "zh")  # default zh

        lang_pair = f"{src_lang}2{tgt_lang}"

        doc_id = r.get("doc_id")
        if doc_id is None:
            doc_id = r.get("doc")

        # Try to get MT model label from data; fallback to something readable.
        mt_model = norm(r.get("mt_model")) or norm(r.get("system")) or "qwen-max"

        out.append(
            dict(
                file=base,
                mt_model=mt_model,
                metric="comet-qe",
                metric_model=metric_model_label,

                doc_id=doc_id,
                seg_id=r.get("seg_id"),
                page_no=r.get("page_no"),

                src_lang=src_lang,
                tgt_lang=tgt_lang,
                src_lang_zh=lang_code_to_zh(src_lang),
                tgt_lang_zh=lang_code_to_zh(tgt_lang),
                lang_pair=lang_pair,

                src_text=r.get(SRC_KEY),
                mt_text=r.get(MT_KEY),

                score=float(sc),
            )
        )

    return pd.DataFrame(out)


# -----------------------------
# Summary, wide table
# -----------------------------
def make_summary_wide(df: pd.DataFrame) -> pd.DataFrame:
    """
    Wide, human-friendly:
    one row per language pair, columns: n/mean/std/min/p05/p10/max
    """
    d = df.dropna(subset=["score"]).copy()

    def qv(x: np.ndarray, q: float) -> float:
        return float(np.quantile(x, q)) if len(x) else np.nan

    rows = []
    for (src_zh, lp), g in d.groupby(["src_lang_zh", "lang_pair"], dropna=False):
        s = g["score"].to_numpy()
        rows.append(
            dict(
                src_lang=src_zh,
                lang_pair=lp,
                n=int(np.isfinite(s).sum()),
                mean=float(np.mean(s)),
                std=float(np.std(s, ddof=1)) if len(s) > 1 else 0.0,
                min=float(np.min(s)),
                p05=qv(s, 0.05),
                p10=qv(s, 0.10),
                max=float(np.max(s)),
            )
        )

    out = pd.DataFrame(rows).sort_values(["src_lang", "lang_pair"], na_position="last").reset_index(drop=True)
    return out


def get_metric_model_label(ckpt_path: str, original_arg: str) -> str:
    """
    Build a readable metric model label for Excel meta/raw sheets.
    """
    # If original argument is a model name like Unbabel/XCOMET-XL
    if original_arg and (not os.path.exists(original_arg)) and "/" in original_arg:
        return original_arg.replace("/", "_")

    normalized = ckpt_path.replace("\\", "/")

    # Hugging Face cache layout:
    # .../models--Unbabel--XCOMET-XL/snapshots/<hash>/checkpoints/model.ckpt
    m = re.search(r"models--([^/]+)/snapshots/", normalized)
    if m:
        return m.group(1).replace("--", "_")

    # Legacy COMET layout:
    # .../unbabel_comet/wmt21-comet-qe-da/checkpoints/model.ckpt
    parts = normalized.split("/")
    if "unbabel_comet" in parts:
        idx = parts.index("unbabel_comet")
        if idx + 1 < len(parts):
            return parts[idx + 1]

    # General fallback
    parent = os.path.basename(os.path.dirname(os.path.dirname(normalized)))
    if parent and parent not in {"snapshots", "checkpoints"}:
        return parent

    return os.path.basename(ckpt_path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mt_dir", default="PROJECT_ROOT/data/mt")
    ap.add_argument("--out_xlsx", default="PROJECT_ROOT/data/report/score.xlsx")
    ap.add_argument(
        "--xcomet_ckpt",
        default="/root/.cache/torch/unbabel_comet/wmt21-comet-qe-da/checkpoints/model.ckpt",
        help="Local ckpt path, local checkpoint directory, or comet/HF model name.",
    )
    ap.add_argument("--device", choices=["cuda", "cpu", "npu"], default="npu")
    ap.add_argument("--batch", type=int, default=1)
    ap.add_argument("--glob", default="mt_*qwen-max*.jsonl")
    args = ap.parse_args()

    setup_device(args.device)

    print("Loading COMET QE from:", args.xcomet_ckpt)
    metric_model, ckpt_path = load_metric_model(args.xcomet_ckpt)

    # Important:
    # For NPU transfer_to_npu path, do not manually move model to npu:0.
    # Lightning will manage device placement via the CUDA-compatible path.
    if args.device == "npu":
        print("Using Ascend NPU via transfer_to_npu-managed CUDA-compatible path ...")
        metric_model.eval()
    elif args.device == "cuda":
        print("Moving metric model to cuda:0 ...")
        metric_model = metric_model.to("cuda:0")
        metric_model.eval()
    else:
        print("Moving metric model to cpu ...")
        metric_model = metric_model.to("cpu")
        metric_model.eval()

    metric_model_label = get_metric_model_label(ckpt_path, args.xcomet_ckpt)
    print("Resolved checkpoint:", ckpt_path)
    print("Metric model label:", metric_model_label)
    print("Runtime device:", args.device)

    mt_dir = args.mt_dir
    if not os.path.isdir(mt_dir):
        raise NotADirectoryError(mt_dir)

    import glob as _glob
    paths = sorted(_glob.glob(os.path.join(mt_dir, args.glob)))
    if not paths:
        raise FileNotFoundError(f"No files matched: {os.path.join(mt_dir, args.glob)}")

    print(f"Matched files: {len(paths)}")
    for p in paths[:10]:
        print(" -", os.path.basename(p))
    if len(paths) > 10:
        print(f" ... and {len(paths) - 10} more")

    dfs = []
    for p in paths:
        print("Scoring:", os.path.basename(p))
        dfs.append(score_one_file(p, metric_model, metric_model_label, args.batch, args.device))

    df_all = pd.concat(dfs, ignore_index=True)

    # Decide MT model label, for meta sheet.
    mt_models = sorted([x for x in df_all["mt_model"].dropna().unique().tolist() if str(x).strip()])
    mt_model_label = mt_models[0] if len(mt_models) == 1 else ",".join(mt_models[:5]) + ("..." if len(mt_models) > 5 else "")

    summary = make_summary_wide(df_all)

    # Sanitize before writing.
    df_all = sanitize_for_excel(df_all)
    summary = sanitize_for_excel(summary)

    out_dir = os.path.dirname(args.out_xlsx)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    # Write xlsx.
    with pd.ExcelWriter(args.out_xlsx, engine="openpyxl") as w:
        meta = pd.DataFrame(
            [
                {"key": "mt_model", "value": mt_model_label},
                {"key": "metric", "value": "comet-qe"},
                {"key": "metric_model", "value": metric_model_label},
                {"key": "checkpoint_path", "value": ckpt_path},
                {"key": "device", "value": args.device},
                {"key": "batch", "value": args.batch},
                {"key": "matched_files", "value": len(paths)},
            ]
        )
        meta = sanitize_for_excel(meta)
        meta.to_excel(w, index=False, sheet_name="meta")

        summary.to_excel(w, index=False, sheet_name="summary")

        df_raw = df_all.sort_values(["src_lang_zh", "lang_pair", "doc_id", "seg_id"], na_position="last")
        df_raw.to_excel(w, index=False, sheet_name="raw")

    print("Wrote:", args.out_xlsx)


if __name__ == "__main__":
    main()