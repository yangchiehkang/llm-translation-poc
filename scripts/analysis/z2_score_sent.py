#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, os, time
from pathlib import Path
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

def setup_npu(idx):
    import torch, torch_npu
    import torch_npu.contrib.transfer_to_npu
    torch.npu.set_device(idx)
    torch.cuda.get_device_capability = lambda device=None: (8, 0)
    torch.cuda.get_device_name = lambda device=None: "Ascend NPU"

ap = argparse.ArgumentParser()
ap.add_argument("--input", required=True)
ap.add_argument("--output", required=True)
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
items = [{"src": r["source_text"], "mt": r["hypothesis"], "ref": r["ref_text"]} for r in rows]
pred = model.predict(items, batch_size=8, gpus=1, devices=[a.device_index],
                     accelerator="cuda", num_workers=0, progress_bar=False, length_batching=True)
scores = [float(s) for s in pred.scores]
with open(a.output, "w", encoding="utf-8") as f:
    for r, s in zip(rows, scores):
        rec = dict(r); rec["score"] = s
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
print(f"均值: {sum(scores)/len(scores):.4f}  n={len(scores)}")
