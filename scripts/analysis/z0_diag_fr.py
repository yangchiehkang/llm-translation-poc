import sys, json
sys.path.insert(0, "PROJECT_ROOT")
from pathlib import Path
from scripts.evaluation.prepare_da_pairs import parse_pdf_segments, align_segments, scoped_key, MAX_SEGMENT_CHARS
from collections import Counter

RAW = Path("PROJECT_ROOT/data/raw/fr-zh")
docs = [
    ("FR_1981_tachograph_order", "FR_1981_tachograph_order_fr.pdf", "FR_1981_tachograph_order_zh.pdf"),
    ("FR_environment_code_L541", "FR_environment_code_L541_fr.pdf", "FR_environment_code_L541_zh.pdf"),
]
for doc_id, src_name, ref_name in docs:
    src_segs, src_filt, src_notes = parse_pdf_segments(RAW/src_name, doc_id, "fr-zh", "fr", min_chars=30, max_chars=MAX_SEGMENT_CHARS)
    ref_segs, ref_filt, ref_notes = parse_pdf_segments(RAW/ref_name, doc_id, "fr-zh", "zh", min_chars=2, max_chars=MAX_SEGMENT_CHARS)
    print(f"=== {doc_id} ===")
    print(f"  source segs={len(src_segs)} filtered={src_filt}   ref segs={len(ref_segs)} filtered={ref_filt}")
    ratio = len(src_segs)/len(ref_segs) if ref_segs else float('nan')
    print(f"  count_ratio(src/ref) = {ratio:.4f}")
    src_key_counts = Counter(k for k in (scoped_key(s) for s in src_segs) if k)
    ref_key_counts = Counter(k for k in (scoped_key(r) for r in ref_segs) if k)
    src_has_key = sum(1 for s in src_segs if scoped_key(s))
    ref_has_key = sum(1 for r in ref_segs if scoped_key(r))
    print(f"  source 有 scoped_key: {src_has_key}/{len(src_segs)}")
    print(f"  ref    有 scoped_key: {ref_has_key}/{len(ref_segs)}")
    aligned = align_segments(src_segs, ref_segs, {"document_id": doc_id, "language_pair":"fr-zh","source_lang":"fr","target_lang":"zh"}, 30)
    print(f"  aligned = {len(aligned)}")
    print(f"  alignment_method 分布:", Counter(a['alignment_method'] for a in aligned))
    print()
    print("  source 段样例（前10条）:")
    for s in src_segs[:10]:
        print("   ", repr(s['text'][:70]), '-> section_no=', s.get('section_no'))
