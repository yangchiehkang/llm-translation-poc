import sys, json
sys.path.insert(0, "PROJECT_ROOT")
from pathlib import Path
from scripts.evaluation.prepare_da_pairs import parse_pdf_segments, align_segments, scoped_key, MAX_SEGMENT_CHARS
from collections import Counter

RAW = Path("PROJECT_ROOT/data/raw/ar-zh")
doc_id, src_name, ref_name = "SASO_Electric_Vehicles_TR_V3", "SASO_Electric_Vehicles_TR_V3_ar.pdf", "SASO_Electric_Vehicles_TR_V3_zh.pdf"
src_segs, src_filt, _ = parse_pdf_segments(RAW/src_name, doc_id, "ar-zh", "ar", min_chars=30, max_chars=MAX_SEGMENT_CHARS)
ref_segs, ref_filt, _ = parse_pdf_segments(RAW/ref_name, doc_id, "ar-zh", "zh", min_chars=2, max_chars=MAX_SEGMENT_CHARS)
print(f"source segs={len(src_segs)} filtered={src_filt}   ref segs={len(ref_segs)} filtered={ref_filt}")
ratio = len(src_segs)/len(ref_segs) if ref_segs else float('nan')
print(f"count_ratio(src/ref) = {ratio:.4f}")
src_has_key = sum(1 for s in src_segs if scoped_key(s))
ref_has_key = sum(1 for r in ref_segs if scoped_key(r))
print(f"source 有 scoped_key: {src_has_key}/{len(src_segs)}   ref 有 scoped_key: {ref_has_key}/{len(ref_segs)}")
aligned = align_segments(src_segs, ref_segs, {"document_id": doc_id, "language_pair":"ar-zh","source_lang":"ar","target_lang":"zh"}, 30)
print(f"aligned = {len(aligned)}  方法分布:", Counter(a['alignment_method'] for a in aligned))
print()
print("ref 段样例（前10条，看zh侧条款号体系）:")
for r in ref_segs[:10]:
    print(" ", repr(r['text'][:70]), '-> section_no=', r.get('section_no'))
