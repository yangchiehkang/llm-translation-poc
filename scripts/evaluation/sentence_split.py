#!/usr/bin/env python3
"""句级切分 —— 评测单元由「段」改为「句」的基础件。

历史教训（每一次分段类改动都带出过 bug，这次没有第二轮兜底）
------------------------------------------------------------
地雷 1：**英文句末正则把条款号的点当句号**。
    `5.4.1. The vehicle shall…` 里 `5.4.1.` 是条款号，不是三个句子。
    这个 bug 在结构判据里出现过，造成"源文过覆盖 17.3%"的假数。
    但反向也会错：`…complies with paragraph 5.1. The manufacturer shall…`
    里那个点**确实是句末**。两者字面完全一样（数字+点+空格+大写），
    只能靠位置与上下文区分 —— 见 `_protect()`。

地雷 2：**中英句读不对称**。`；` 算句末而 `;` 不算，曾是 acceptance_subset.py 的 live bug。
    本模块**强制对称**：`SEMICOLON_IS_BOUNDARY` 一个开关同时作用于两侧，
    不允许一侧算一侧不算。默认 False（只用强终止符），
    因为法规正文里 `;` 多用于列表项，切开会把一个条款打成十几个碎片。

设计
----
先"保护"掉所有不该断句的点（替换成哨兵字符），切分，再还原。
保护清单是显式的、可单测的，不靠正则的巧合。
"""
from __future__ import annotations

import re

# 段首条款号：5.4.1. / 6.8.1.1.2. / A. / (a)
LEADING_SEC = re.compile(r"^\s*(?:\d{1,3}(?:\.\d{1,3})*\.?|[A-Z]\.|\([a-z0-9]{1,3}\))\s*")

_SENTINEL = ""          # 私用区，语料里不会出现

# ---- 保护规则：这些位置的点**不是**句末 ----
_ABBREV = (
    r"e\.g|i\.e|cf|etc|vs|approx|min|max|No|Nos|Fig|Figs|Art|para|paras|"
    r"Rev|Amend|Suppl|Ch|Sect|Vol|Ann|Tab|Eq|Ref|Dr|Mr|Mrs|Ms|St|Inc|Ltd|Co"
)
_PROTECT = [
    # 缩写词后的点
    re.compile(rf"\b(?:{_ABBREV})(\.)", re.I),
    # 数字之间的点：0.5 / 5.4.1 —— 后面不是空格的那种
    re.compile(r"(?<=\d)(\.)(?=\d)"),
    # 单字母缩写连写：I.R.I.S. / R.E.3.
    re.compile(r"(?<=\b[A-Z])(\.)(?=[A-Z]\b|[A-Z]\.)"),
    # 条款号形态 5.4.1. 里**非最后一个**点（最后一个可能是句末，留给下面判）
    re.compile(r"(?<=\d)(\.)(?=\d+\.)"),
]


def _protect(text: str) -> tuple[str, list[str]]:
    """把不该断句的点换成哨兵。返回 (处理后文本, 被保护的原字符列表)。"""
    saved: list[str] = []

    def sub(m: re.Match) -> str:
        # 只替换捕获组那个点，其余原样
        s, e = m.span(1)
        saved.append(m.group(1))
        return m.group(0)[: s - m.start()] + _SENTINEL + m.group(0)[e - m.start():]

    out = text
    for rx in _PROTECT:
        prev = None
        while prev != out:            # 反复扫，处理 5.4.1.1 这种连续重叠
            prev = out
            out = rx.sub(sub, out)
    return out, saved


def _restore(text: str) -> str:
    return text.replace(_SENTINEL, ".")


# 英文句末：强终止符 + 后面是空白+大写/引号/括号，或到文末
# [A-ZА-ЯЁ]（2026-07-29，ru 拆句）：西里尔大写字母，本项目第五次同型 Latin-only
# 字符集 bug（前四次：SECTION_PATTERNS 缺西里尔附录字母、good_char_ratio 缺阿拉伯
# 展示形字符、match_terms 词边界只认拉丁字符、acceptance_subset._SENT_EN 缺西里尔
# 大写判断）。只认 [A-Z] 会让俄语句号后接西里尔大写字母的正常句子边界一个都识别
# 不到——split_auto 对纯俄语文本会落到这个分支（既非 CJK 也非拉丁计数占多数），
# 不修就会让拆句对俄语整体失效（不切或切错，不是切不准）。
_EN_END = re.compile(r"[.!?](?=\s+[\"“'(\[A-ZА-ЯЁ]|\s*$)")
# 中文句末：只用强终止符；后随的引号/括号一并吃进上一句
_ZH_END = re.compile(r"[。！？](?:[”』」）)\]】]|\s)*")


def split_en(text: str, semicolon_is_boundary: bool = False,
             strip_leading_section: bool = True) -> list[str]:
    """切英文句。默认剥掉段首条款号——它不是句子的一部分。"""
    t = text.strip()
    if strip_leading_section:
        t = LEADING_SEC.sub("", t, count=1).strip()
    if not t:
        return []
    prot, _ = _protect(t)
    if semicolon_is_boundary:
        prot = re.sub(r";(?=\s)", ".", prot)
    out, last = [], 0
    for m in _EN_END.finditer(prot):
        seg = prot[last:m.end()].strip()
        if seg:
            out.append(_restore(seg))
        last = m.end()
    tail = prot[last:].strip()
    if tail:
        out.append(_restore(tail))
    return [s for s in out if s]


def split_zh(text: str, semicolon_is_boundary: bool = False,
             strip_leading_section: bool = True) -> list[str]:
    """切中文句。**与 split_en 对称**：分号是否算句末由同一个开关控制。"""
    t = text.strip()
    if strip_leading_section:
        t = LEADING_SEC.sub("", t, count=1).strip()
    if not t:
        return []
    prot, _ = _protect(t)          # 中文里也可能夹 5.4.1. / No. 这类
    if semicolon_is_boundary:
        prot = re.sub(r"；", "。", prot)
    out, last = [], 0
    for m in _ZH_END.finditer(prot):
        seg = prot[last:m.end()].strip()
        if seg:
            out.append(_restore(seg))
        last = m.end()
    tail = prot[last:].strip()
    if tail:
        out.append(_restore(tail))
    return [s for s in out if s]


def split_auto(text: str, **kw) -> list[str]:
    """按文本主要语种选切分器。"""
    cjk = len(re.findall(r"[一-鿿]", text))
    lat = len(re.findall(r"[A-Za-z]", text))
    return split_zh(text, **kw) if cjk > lat else split_en(text, **kw)


# ---------------------------------------------------------------------------
# 自测：两个地雷各自的正反例。改这个文件前先跑 `python -m scripts.evaluation.sentence_split`
# ---------------------------------------------------------------------------
CASES_EN = [
    # (文本, 期望句数, 说明)
    ("5.4.1. The vehicle shall comply.", 1, "段首条款号不算句末"),
    ("6.8.1.1.2. In the case of bench seats, this area shall extend.", 1, "多级条款号"),
    ("The test complies with paragraph 5.1. The manufacturer shall notify.", 2,
     "句中交叉引用后确实是句末"),
    ("Values are 0.5 m and 1.25 m in total.", 1, "小数点不断句"),
    ("See Annex 5A. The result is valid.", 2, "附件号后是句末"),
    ("Download from the I.R.I.S. application powered by Applus IDIADA.", 1,
     "I.R.I.S. 单字母缩写不断句"),
    ("Refer to No. 94 for details.", 1, "No. 缩写不断句"),
    ("Requirements: (a) fire; (b) explosion; (c) venting.", 1,
     "默认分号不算句末（列表项不切碎）"),
    ("First sentence. Second sentence. Third one.", 3, "普通三句"),
    ("", 0, "空文本"),
]
CASES_ZH = [
    ("5.4.1. 车辆应符合要求。", 1, "段首条款号"),
    ("本试验符合第 5.1 款。制造商应通知。", 2, "两句"),
    ("要求包括：(a) 起火；(b) 爆炸；(c) 通风。", 1, "默认分号不算句末"),
    ("数值为 0.5 m 与 1.25 m。", 1, "小数点"),
    ("第一句。第二句。第三句。", 3, "三句"),
    ("他说“可以。”然后离开了。", 2, "引号内句末，闭引号归上一句"),
]


def _selftest() -> int:
    bad = 0
    print("=== split_en ===")
    for txt, want, why in CASES_EN:
        got = split_en(txt)
        ok = len(got) == want
        bad += not ok
        print(f"  {'OK ' if ok else 'FAIL'} 期望{want} 实得{len(got)}  {why}")
        if not ok:
            print(f"        输入: {txt!r}\n        切出: {got}")
    print("=== split_zh ===")
    for txt, want, why in CASES_ZH:
        got = split_zh(txt)
        ok = len(got) == want
        bad += not ok
        print(f"  {'OK ' if ok else 'FAIL'} 期望{want} 实得{len(got)}  {why}")
        if not ok:
            print(f"        输入: {txt!r}\n        切出: {got}")
    print("=== 对称性：分号开关必须同时作用两侧 ===")
    a = len(split_en("A; B; C.", semicolon_is_boundary=True))
    b = len(split_zh("甲；乙；丙。", semicolon_is_boundary=True))
    ok = a == b == 3
    bad += not ok
    print(f"  {'OK ' if ok else 'FAIL'} 开=True 时 en {a} 句 / zh {b} 句（应都是 3）")
    a = len(split_en("A; B; C."))
    b = len(split_zh("甲；乙；丙。"))
    ok = a == b == 1
    bad += not ok
    print(f"  {'OK ' if ok else 'FAIL'} 开=False 时 en {a} 句 / zh {b} 句（应都是 1）")
    print(f"\n{'全部通过' if not bad else f'{bad} 个用例不通过'}")
    return bad


if __name__ == "__main__":
    raise SystemExit(1 if _selftest() else 0)
