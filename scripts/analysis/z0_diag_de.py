import sys, json
sys.path.insert(0, "PROJECT_ROOT")
from pathlib import Path
from scripts.evaluation.prepare_da_pairs import parse_pdf_segments, align_segments, scoped_key, MAX_SEGMENT_CHARS
from collections import Counter

RAW = Path("PROJECT_ROOT/data/raw/de-zh")
docs = [
    ("StVZO_road_traffic_licensing_regulations", "StVZO_road_traffic_licensing_regulations_de.pdf", "StVZO_road_traffic_licensing_regulations_zh.pdf"),
    ("Circular_Economy_Waste_Management_Act", "Circular_Economy_Waste_Management_Act_de.pdf", "Circular_Economy_Waste_Management_Act_zh.pdf"),
]
for doc_id, src_name, ref_name in docs:
    src_segs, src_filt, src_notes = parse_pdf_segments(RAW/src_name, doc_id, "de-zh", "de", min_chars=30, max_chars=MAX_SEGMENT_CHARS)
    ref_segs, ref_filt, ref_notes = parse_pdf_segments(RAW/ref_name, doc_id, "de-zh", "zh", min_chars=2, max_chars=MAX_SEGMENT_CHARS)
    print(f"=== {doc_id} ===")
    print(f"  source segs={len(src_segs)} filtered={src_filt}   ref segs={len(ref_segs)} filtered={ref_filt}")
    ratio = len(src_segs)/len(ref_segs) if ref_segs else float('nan')
    print(f"  count_ratio(src/ref) = {ratio:.4f}   (需 0.75~1.35 才做 exact_section_scoped)")
    src_key_counts = Counter(k for k in (scoped_key(s) for s in src_segs) if k)
    ref_key_counts = Counter(k for k in (scoped_key(r) for r in ref_segs) if k)
    src_has_key = sum(1 for s in src_segs if scoped_key(s))
    ref_has_key = sum(1 for r in ref_segs if scoped_key(r))
    print(f"  source 有 scoped_key: {src_has_key}/{len(src_segs)}   唯一key次数=1占比: {sum(1 for v in src_key_counts.values() if v==1)}/{len(src_key_counts)}")
    print(f"  ref    有 scoped_key: {ref_has_key}/{len(ref_segs)}   唯一key次数=1占比: {sum(1 for v in ref_key_counts.values() if v==1)}/{len(ref_key_counts)}")
    aligned = align_segments(src_segs, ref_segs, {"document_id": doc_id, "language_pair":"de-zh","source_lang":"de","target_lang":"zh"}, 30)
    print(f"  aligned = {len(aligned)}")
    from collections import Counter as C2
    print(f"  alignment_method 分布:", C2(a['alignment_method'] for a in aligned))
    print()

print("=== zh 参考侧内容抽样（StVZO）===")
ref_segs, _, _ = parse_pdf_segments(RAW/"StVZO_road_traffic_licensing_regulations_zh.pdf", "x", "de-zh", "zh", min_chars=2, max_chars=MAX_SEGMENT_CHARS)
for r in ref_segs[10:20]:
    print(repr(r['source_text'][:70]), '-> section_no=', r.get('section_no'))
