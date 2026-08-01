#!/usr/bin/env python3
"""D — RU 术语候选的**逐条语料验证**。

上一步（a5）在中文端做差集，指出 ru 术语库缺口集中在 HVAC / 测量 / 试验装置这
几个域——这两份 GOST 恰好就是"风窗玻璃除霜除雾"和"微气候标准化系统"，术语库
里一条相关条目都没有。

本脚本对每个候选 (俄语词形, 中文译法) 做**双向验证**，判据只用语料，不用我的判断：

    support      源文含该俄语形态 且 参考含该中文译法 的对齐句对数
    src_only     源文含该俄语形态 但 参考不含该中文译法 的句对数（反例）
    precision    support / (support + src_only)

只有 support ≥ 2 且 precision ≥ 0.8 的候选才算"有语料依据"，其余一律列出但标注
不采纳。**不看它对样本量的影响**——先定判据再套用。

用法：
    python scripts/analysis/a6_ru_term_verify.py --pairs <ru_sent_pairs.jsonl> --out <dir>
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# 候选来自"当前 0 术语命中"的 59 个 ru 句级单元里肉眼可见的专业名词，
# 全部是 GOST 30593 / GOST 33992 的核心概念。每条给出俄语词干（匹配各种变格
# 形态）与拟定中文译法；是否采纳由下面的语料验证决定，不由这张表决定。
CANDIDATES: list[tuple[str, str, str]] = [
    # (俄语词干正则, 中文译法, 领域)
    (r"кондиционирован\w*", "空气调节", "hvac"),
    (r"вентиляц\w*", "通风", "hvac"),
    (r"отоплени\w*", "供暖", "hvac"),
    (r"микроклимат\w*", "微气候", "hvac"),
    (r"обогрев\w*", "加热", "hvac"),
    (r"охлаждающ\w*\s+жидкост\w*", "冷却液", "powertrain"),
    (r"ведущ\w*\s+колес\w*", "驱动轮", "chassis"),
    (r"измерительн\w*\s+прибор\w*", "测量仪器", "test_equipment"),
    (r"климатическ\w*\s+камер\w*", "气候室", "test_equipment"),
    (r"обдув\w*", "吹风", "hvac"),
    (r"размораживани\w*|размораживател\w*", "除霜", "hvac"),
    (r"запотевани\w*|противозапотева\w*", "除雾", "hvac"),
    (r"ветров\w*\s+стекл\w*|窗", "风窗玻璃", "body"),
    (r"салон\w*", "客厢", "body"),
    (r"обитаем\w*", "乘员舱", "body"),
    (r"温度|температур\w*", "温度", "general"),
    (r"испытани\w*", "测试", "testing"),
    (r"поверк\w*|повер\w*", "校准", "test_equipment"),
    (r"расход\w*\s+воздух\w*", "空气流量", "hvac"),
    (r"относительн\w*\s+влажност\w*", "相对湿度", "hvac"),
    (r"скорост\w*\s+движени\w*", "行驶速度", "general"),
    (r"стеклоочистител\w*", "刮水器", "body"),
    (r"теплов\w*\s+поток\w*", "热流", "hvac"),
    (r"воздушн\w*\s+поток\w*", "气流", "hvac"),
    (r"эксплуатационн\w*", "使用", "general"),
    (r"работоспособност\w*", "工作能力", "general"),
    (r"герметичност\w*", "密封性", "general"),
    (r"технологическ\w*", "工艺", "general"),
    (r"погрешност\w*", "误差", "test_equipment"),
    (r"датчик\w*", "传感器", "test_equipment"),
    (r"термопар\w*", "热电偶", "test_equipment"),
    (r"тахограф\w*", "行车记录仪", "test_equipment"),
    (r"органы\s+управлени\w*|орган\w*\s+управлени\w*", "操纵件", "controls"),
    (r"наружн\w*\s+воздух\w*", "外部空气", "hvac"),
    (r"частот\w*\s+вращени\w*", "转速", "powertrain"),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", required=True, help="句级 pairs jsonl（含 source_text/ref_text）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-support", type=int, default=2)
    ap.add_argument("--min-precision", type=float, default=0.8)
    a = ap.parse_args()

    rows = [json.loads(l) for l in Path(a.pairs).read_text(encoding="utf-8").splitlines() if l.strip()]
    out = []
    for pat, zh, domain in CANDIDATES:
        rx = re.compile(pat, re.IGNORECASE)
        support = src_only = 0
        ev = []
        for r in rows:
            if not rx.search(r["source_text"]):
                continue
            if zh in r["ref_text"]:
                support += 1
                if len(ev) < 3:
                    m = rx.search(r["source_text"])
                    ev.append({"sample_id": r["sample_id"], "src_form": m.group(0),
                               "src": r["source_text"][:120], "ref": r["ref_text"][:100]})
            else:
                src_only += 1
        total = support + src_only
        prec = support / total if total else 0.0
        ok = support >= a.min_support and prec >= a.min_precision
        out.append({"source_pattern": pat, "target_term": zh, "domain": domain,
                    "support": support, "src_only": src_only,
                    "precision": round(prec, 3), "accepted": ok, "evidence": ev})

    out.sort(key=lambda x: (-x["accepted"], -x["support"]))
    dest = Path(a.out)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "ru_term_verified.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    acc = [o for o in out if o["accepted"]]
    print(f"候选 {len(out)} 条；判据 support>={a.min_support} 且 precision>={a.min_precision}")
    print(f"**通过 {len(acc)} 条**，未通过 {len(out)-len(acc)} 条\n")
    print(f"{'中文译法':12s}{'support':>8s}{'反例':>6s}{'precision':>10s}  俄语实例")
    for o in out:
        mark = "✓" if o["accepted"] else " "
        form = o["evidence"][0]["src_form"] if o["evidence"] else "—"
        print(f"{mark} {o['target_term']:11s}{o['support']:8d}{o['src_only']:6d}{o['precision']:10.2f}  {form[:40]}")
    print(f"\nwrote {dest}/ru_term_verified.json")


if __name__ == "__main__":
    main()
