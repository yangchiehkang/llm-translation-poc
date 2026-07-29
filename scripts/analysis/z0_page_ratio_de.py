import sys
sys.path.insert(0, "PROJECT_ROOT")
import pdfplumber
from pathlib import Path
from scripts.evaluation.prepare_da_pairs import CJK_RE, LATIN_RE

RAW = Path("PROJECT_ROOT/data/raw/de-zh")

def page_count(p):
    with pdfplumber.open(p) as pdf:
        return len(pdf.pages)

def cjk_ratio_by_page(p):
    ratios = []
    with pdfplumber.open(p) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            cjk = len(CJK_RE.findall(text))
            latin = len(LATIN_RE.findall(text))
            total = cjk + latin
            ratios.append(round(9 * cjk / total) if total else -1)
    return ratios

for name, pdf_name in [("de(源文)", "StVZO_road_traffic_licensing_regulations_de.pdf"),
                        ("zh(参考)", "StVZO_road_traffic_licensing_regulations_zh.pdf")]:
    n = page_count(RAW / pdf_name)
    print(f"{name}: {pdf_name} 页数={n}")

print()
zh_ratios = cjk_ratio_by_page(RAW / "StVZO_road_traffic_licensing_regulations_zh.pdf")
print(f"zh PDF 总页数: {len(zh_ratios)}")
print("逐页中文字符占比（0=纯外文，9=纯中文，-1=无字符）：")
for i in range(0, len(zh_ratios), 62):
    chunk = zh_ratios[i:i+62]
    print(f"p{i+1:4d}: " + "".join(str(x) if x>=0 else "." for x in chunk))

zh_major = sum(1 for x in zh_ratios if x >= 5)
foreign_major = sum(1 for x in zh_ratios if 0 <= x < 1)
mixed = len(zh_ratios) - zh_major - foreign_major
print()
print(f"中文页(占比>=50%): {zh_major}   近乎纯外文页(<10%): {foreign_major}   混排: {mixed}")

# odd/even check
odd_pages = zh_ratios[0::2]  # 1-indexed page 1,3,5... => index 0,2,4
even_pages = zh_ratios[1::2]
odd_valid = [x for x in odd_pages if x>=0]
even_valid = [x for x in even_pages if x>=0]
print()
print(f"奇数页(1,3,5...) 均值占比: {sum(odd_valid)/len(odd_valid):.2f}  (n={len(odd_valid)})")
print(f"偶数页(2,4,6...) 均值占比: {sum(even_valid)/len(even_valid):.2f}  (n={len(even_valid)})")
