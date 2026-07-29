#!/usr/bin/env python3
"""诊断二：同一批 fr 自比对样本，分别用 length_batching=True/False、batch_size=1 跑，
比较是否是批处理内部重排序把分数错配到别的样本上。"""
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

items = [{"src": r["source_text"], "mt": r["ref_text"], "ref": r["ref_text"]} for r in rows]

print("=== A) length_batching=True, batch_size=4（原设置）===", flush=True)
predA = model.predict(items, batch_size=4, gpus=1, devices=[a.device_index],
                      accelerator="cuda", num_workers=0, progress_bar=False, length_batching=True)
scoresA = [float(s) for s in predA.scores]

print("=== B) length_batching=False, batch_size=4 ===", flush=True)
predB = model.predict(items, batch_size=4, gpus=1, devices=[a.device_index],
                      accelerator="cuda", num_workers=0, progress_bar=False, length_batching=False)
scoresB = [float(s) for s in predB.scores]

print("=== C) batch_size=1（逐条单独跑，无批处理交互可能）===", flush=True)
scoresC = []
for it in items:
    p = model.predict([it], batch_size=1, gpus=1, devices=[a.device_index],
                      accelerator="cuda", num_workers=0, progress_bar=False, length_batching=False)
    scoresC.append(float(p.scores[0]))

print("\nsample_id | len(src) | A(lb=T,bs=4) | B(lb=F,bs=4) | C(bs=1单条)")
for r, sa, sb, sc in zip(rows, scoresA, scoresB, scoresC):
    print(f"{r['sample_id']:45s} {len(r['source_text']):5d}  {sa:.4f}  {sb:.4f}  {sc:.4f}")
print(f"\n均值: A={sum(scoresA)/len(scoresA):.4f}  B={sum(scoresB)/len(scoresB):.4f}  C={sum(scoresC)/len(scoresC):.4f}")
