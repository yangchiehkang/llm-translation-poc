import sys, json
sys.path.insert(0, "PROJECT_ROOT")
from pathlib import Path
from scripts.evaluation.prepare_da_pairs import parse_pdf_segments, align_segments, scoped_key, MAX_SEGMENT_CHARS
from collections import Counter

RAW = Path("PROJECT_ROOT/data/raw/es-zh")
docs = [
    ("Decreto_119_2012_antitheft", "Decreto_119_2012_antitheft_es.pdf", "Decreto_119_2012_antitheft_zh.pdf"),
    ("Resolucion_816_Exenta_2023", "Resolucion_816_Exenta_2023_es.pdf", "Resolucion_816_Exenta_2023_zh.pdf"),
]
for doc_id, src_name, ref_name in docs:
    src_segs, src_filt, _ = parse_pdf_segments(RAW/src_name, doc_id, "es-zh", "es", min_chars=30, max_chars=MAX_SEGMENT_CHARS)
    ref_segs, ref_filt, _ = parse_pdf_segments(RAW/ref_name, doc_id, "es-zh", "zh", min_chars=2, max_chars=MAX_SEGMENT_CHARS)
    print(f"=== {doc_id} ===")
    print(f"  source segs={len(src_segs)} filtered={src_filt}   ref segs={len(ref_segs)} filtered={ref_filt}")
    ratio = len(src_segs)/len(ref_segs) if ref_segs else float('nan')
    print(f"  count_ratio(src/ref) = {ratio:.4f}")
    src_has_key = sum(1 for s in src_segs if scoped_key(s))
    ref_has_key = sum(1 for r in ref_segs if scoped_key(r))
    print(f"  source 有 scoped_key: {src_has_key}/{len(src_segs)}   ref 有 scoped_key: {ref_has_key}/{len(ref_segs)}")
    aligned = align_segments(src_segs, ref_segs, {"document_id": doc_id, "language_pair":"es-zh","source_lang":"es","target_lang":"zh"}, 30)
    print(f"  aligned = {len(aligned)}   方法分布:", Counter(a['alignment_method'] for a in aligned))
    print("  source 段样例（前8条）:")
    for s in src_segs[:8]:
        print("   ", repr(s['text'][:65]), '-> section_no=', s.get('section_no'))
    print("  ref 段样例（前8条）:")
    for r in ref_segs[:8]:
        print("   ", repr(r['text'][:65]), '-> section_no=', r.get('section_no'))
    print()
