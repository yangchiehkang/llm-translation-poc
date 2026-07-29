#!/usr/bin/env python3
"""诊断：把参考译文本身当 mt 送去打分，应该接近 1.0；如果也很低，说明打分流程本身有问题。"""
from __future__ import annotations
import argparse, json, os, time
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")


def setup_npu(idx: int) -> None:
    import torch
    import torch_npu  # noqa: F401
    import torch_npu.contrib.transfer_to_npu  # noqa: F401
    torch.npu.set_device(idx)
    torch.cuda.get_device_capability = lambda device=None: (8, 0)
    torch.cuda.get_device_name = lambda device=None: "Ascend NPU"


ap = argparse.ArgumentParser()
ap.add_argument("--input", required=True)
ap.add_argument("--model-path", default="/data/MODEL_DIR/xcomet-xxl/checkpoints/model.ckpt")
ap.add_argument("--device-index", type=int, default=4)
a = ap.parse_args()

import torch
setup_npu(a.device_index)
from comet import load_from_checkpoint

rows = [json.loads(x) for x in Path(a.input).read_text(encoding="utf-8").splitlines() if x.strip()]
model = load_from_checkpoint(a.model_path)
model = model.to(torch.bfloat16)
model.eval()

# ref-as-mt 自比对：理论上应接近 1.0
items_selfcheck = [{"src": r["source_text"], "mt": r["ref_text"], "ref": r["ref_text"]} for r in rows]
pred = model.predict(items_selfcheck, batch_size=4, gpus=1, devices=[a.device_index],
                     accelerator="cuda", num_workers=0, progress_bar=False, length_batching=True)
scores = [float(s) for s in pred.scores]
for r, s in zip(rows, scores):
    print(f"{r['sample_id']}  len(src)={len(r['source_text'])}  ref-as-mt DA={s:.4f}")
print(f"\n均值: {sum(scores)/len(scores):.4f}")
