#!/usr/bin/env python3
"""把段级三元组（源文/参考/译文）切成句级三元组，供 XCOMET 逐句打分。

对齐纪律
--------
**只在高置信时对齐，绝不硬凑。**
  高置信 = 源文句数 == 参考句数 == 译文句数（位置一一对应）
  其余一律标为 `unaligned`，**不进句级打分**，但**保留在分母里**：
  聚合时该条回落到段级分。绝不因为对不齐就把它从分母拿掉——
  那会变成一次按分数挑样本。

不重译、不重分段、不碰语料：输入就是臂 A 的打分结果文件，只在打分环节切句。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.evaluation.sentence_split import split_en, split_zh  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scores", required=True, help="段级打分结果（含 source/ref/hyp）")
    ap.add_argument("--out-pairs", required=True, help="句级打分输入 JSONL")
    ap.add_argument("--out-map", required=True, help="句 -> 段 的映射与对齐状态")
    ap.add_argument("--semicolon", action="store_true",
                    help="把分号也当句末（两侧对称生效）。默认关。")
    args = ap.parse_args()

    rows = [json.loads(x) for x in Path(args.scores).read_text(encoding="utf-8").splitlines() if x.strip()]
    kw = {"semicolon_is_boundary": args.semicolon}

    pairs, mapping, stat = [], [], Counter()
    for r in rows:
        sid = r["sample_id"]
        s = split_en(r["source_text"], **kw)
        f = split_zh(r["ref_text"], **kw)
        h = split_zh(r["hypothesis_translation"], **kw)
        aligned = len(s) == len(f) == len(h) and len(s) > 0
        stat["aligned" if aligned else "unaligned"] += 1
        mapping.append({
            "sample_id": sid, "aligned": aligned,
            "n_src": len(s), "n_ref": len(f), "n_hyp": len(h),
            "paragraph_score": float(r["score"]),
            "source_char_count": len(r["source_text"]),
        })
        if not aligned:
            continue
        for k, (ss, ff, hh) in enumerate(zip(s, f, h)):
            pairs.append({
                "sample_id": f"{sid}#s{k:02d}", "parent_id": sid, "sent_index": k,
                "split": "sent", "system_or_group": "armA_T4tb",
                "translation_stage": "first_pass",
                "source_text": ss, "hypothesis_translation": hh, "ref_text": ff,
            })

    Path(args.out_pairs).write_text(
        "\n".join(json.dumps(p, ensure_ascii=False) for p in pairs) + "\n", encoding="utf-8")
    Path(args.out_map).write_text(
        "\n".join(json.dumps(m, ensure_ascii=False) for m in mapping) + "\n", encoding="utf-8")

    n = len(rows)
    print(f"段 {n} 条 -> 句 {len(pairs)} 条")
    print(f"  高置信对齐 {stat['aligned']:3d} ({stat['aligned']/n:5.1%})")
    print(f"  未对齐     {stat['unaligned']:3d} ({stat['unaligned']/n:5.1%})  "
          f"-> 不进句级打分，聚合时回落段级分，**仍在分母里**")


if __name__ == "__main__":
    main()
