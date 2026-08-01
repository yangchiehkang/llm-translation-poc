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
# `-`（2026-07-30，fr 拆句）：法语法条常见"- item1 ; - item2 ; - item3"列表项，
# `semicolon_is_boundary=True` 把 ";" 换成 "." 后，下一项以 "- " 开头（列表
# 项符号），原判据要求句末标点后接大写字母/引号，"-" 不在其中，导致这些
# 列表项永远切不开——14/44 fr 段落三侧句数不一致、拆不开退回段级，根因就是
# 这个。中文译文侧每个列表项独立成句（句末句号），法语/英语侧因为这个缺口
# 被并成一句，三侧句数天然不对称。
_EN_END = re.compile(r"[.!?](?=\s+[\"“'(\[A-ZА-ЯЁ-]|\s*$)")
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


# ---------------------------------------------------------------------------
# 泰文两层嵌套编号项（2026-07-30，M6：th 唯一的阻塞项）
# ---------------------------------------------------------------------------
# 这份语料的真实结构是**两层嵌套编号**，不是句子：
#     ข้อ 4 …ดังนี้ (๑) …  (๒) … (๔) (ก) … (ข) … (ค) …
# 第一层是数字项，泰文数字 "(๑)" 与阿拉伯数字 "(1)" **两种写法都出现**（同一份
# 文件里混用）；第二层是泰文字母子项 "(ก)(ข)(ค)"，中文译文侧对应写 "(a)(b)(c)"
# 或 "（1）"（全角）。
#
# 关键决定：**按编号标签配对，不按切分后的计数配对**。
# 之前 th 只有 4/21 条能进句级，就是因为要求三侧独立切分后句数恰好相等——
# 泰文侧一个编号项里可能写成一句，中文译文侧拆成两三句，计数天然不等。
# 标签是跨语言不变量（数字就是数字，ก→a 是固定对照表），按标签对齐既天然
# 允许 m:n，也不会像纯位置对齐那样一处错位就整条报废。
_TH_DIGITS = "๐๑๒๓๔๕๖๗๘๙"
_TH_DIGIT_TRANS = {ord(c): str(i) for i, c in enumerate(_TH_DIGITS)}
# 泰文字母子项序号 ก ข ค ง จ ฉ ช ซ → a b c d e f g h（泰语字母表顺序，
# 与中文译文侧的 (a)(b)(c) 一一对应；译文也可能用 (1)(2)(3)，那属于第一层写法，
# 由调用方按标签集合决定用哪一层，见 align_labeled_units）。
_TH_LETTER_SEQ = "กขคงจฉชซ"
_TH_LETTER_MAP = {c: chr(ord("a") + i) for i, c in enumerate(_TH_LETTER_SEQ)}

# 编号标记：(๑) / (1) / （1） / (ก) / (a) / 1.1) / 1° （法语序数列表）
# `N°`（2026-07-30）：法语法条用 "1° … 2° … 3°" 做列表项，中文译文侧写成
# "（1）…（2）" 或各自独立成句——源文侧不认这个标记，整串就是一句，与译文
# 句数天然不等，5 段 fr 样本因此拆不开（用户点名的那一项）。度数符号只在
# 紧跟数字、且后面不是温度/角度单位（C/F/°/字母）时才算列表标记。
_MARKER_RE = re.compile(
    r"[(（]\s*([0-9๐-๙]{1,3}(?:\.[0-9๐-๙]{1,3})*|[ก-ฮ]|[a-zA-Z])\s*[)）]"
    r"|(?:^|\s)([0-9๐-๙]{1,3}(?:\.[0-9๐-๙]{1,3})+)\)"
    r"|(?:^|(?<=[:;.،；：])\s{0,3})([0-9]{1,3})°(?=\s)")


def normalize_label(raw: str) -> str:
    """编号标签归一化成跨语言可比的形式：泰文数字→阿拉伯数字，泰文字母→拉丁字母。"""
    s = raw.strip().translate(_TH_DIGIT_TRANS)
    if len(s) == 1 and s in _TH_LETTER_MAP:
        return _TH_LETTER_MAP[s]
    return s.lower()


def split_labeled_units(text: str) -> list[tuple[str, str]]:
    """按编号标记切成 [(归一化标签, 文本)]；标记之前的引导句标签为 "_head"。

    不判断层级归属（第一层/第二层由标签本身区分：数字 vs 字母），也不递归——
    两层嵌套在同一个平铺序列里各自带自己的标签，配对时按标签查即可。
    """
    t = (text or "").strip()
    if not t:
        return []
    marks: list[tuple[int, int, str]] = []
    for m in _MARKER_RE.finditer(t):
        raw = m.group(1) or m.group(2) or m.group(3)
        if raw is None:
            continue
        marks.append((m.start(), m.end(), normalize_label(raw)))
    if not marks:
        return [("_head", t)]
    out: list[tuple[str, str]] = []
    head = t[: marks[0][0]].strip()
    if head:
        out.append(("_head", head))
    for i, (s, e, lab) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(t)
        body = t[s:end].strip()
        if body:
            out.append((lab, body))
    return out


def align_labeled_units(src: str, ref: str, hyp: str) -> list[tuple[str, str, str, str]]:
    """三侧按编号标签配对，返回 [(标签, src块, ref块, hyp块)]。

    只保留**三侧都有同一标签**的单元；标签重复出现的（两层嵌套里字母子项在不同
    数字项下会重名，如 (๔)(ก) 与 (๕)(ก)）按出现顺序逐个配对，个数不等时只取
    公共前缀个数，不硬凑。三侧都缺的标签自然不出现，缺一侧的标签被丢掉并可由
    调用方统计——这就是"允许 m:n、不要求句数严格相等"的落地方式。
    """
    def group(text: str) -> dict[str, list[str]]:
        g: dict[str, list[str]] = {}
        for lab, body in split_labeled_units(text):
            g.setdefault(lab, []).append(body)
        return g

    gs, gr, gh = group(src), group(ref), group(hyp)
    out: list[tuple[str, str, str, str]] = []
    for lab in gs:
        if lab not in gr or lab not in gh:
            continue
        n = min(len(gs[lab]), len(gr[lab]), len(gh[lab]))
        for i in range(n):
            out.append((lab, gs[lab][i], gr[lab][i], gh[lab][i]))
    return out


_THAI_RE = re.compile(r"[฀-๿]")
# 泰文行政条款的天然单位是"(N)"编号项，不是语言学意义上的句子（2026-07-30，M3）。
# 先试过 pythainlp 的 crfcut（CRF 断句模型）：21 条源文能切出 119 句，量级
# 证明"通用切分器锁死在 21 句"确实是工具选错了，不是样本不够；但逐条核对
# 发现 crfcut 会在名词短语中间断句（如"...ที่นั่ง "后断开，后半句"จุดยึด..."
# 仍是同一个名词短语的一部分——泰语政府公告的正式文体不在 crfcut 训练分布
# 内），三侧对齐后出现明显语义错位（如某条被强行配上完全不相关的另一条
# 内容），不能直接用。改用编号项切分："(1)"/"(๑)"这类圆括号编号，中文参考
# 译文用的是同一套编号约定（"(1)"/"（1）"），21 条源文里 16 条三侧编号项
# 数完全一致，其余小幅偏差（1~2项）留给 m:n 对齐处理——比 crfcut 更贴合
# 这份语料的真实结构，也印证了 z4 README 里"天然单位是编号项不是句子"的猜测。
_NUM_ITEM_RE = re.compile(r"(?=[(（][0-9๐-๙]+[)）])")


def split_th(text: str, use_pythainlp: bool = True, min_pythainlp_chars: int = 200,
             **_kw) -> list[str]:
    """切泰文：**先按编号项切，再对没有编号的长块用 pythainlp 断句**。

    两层的分工是有判据的（2026-07-30，M6）：
      - 编号项切分是主力。这份语料的天然单位就是编号项，标签跨语言可比，
        配对可靠（见 align_labeled_units）。
      - pythainlp（crfcut）只用在**没有任何编号标记的长块**上。单独用它切全文
        跑过：21 条源文能切出 119 句，量级上证明"锁死在 21 句"是工具选错而非
        样本不足；但逐条核对发现它会在名词短语中间断开（如 "…ที่นั่ง" 后断，
        后半 "จุดยึด…" 仍属同一名词短语——泰语政府公告的正式文体不在 crfcut
        的训练分布内），三侧对齐后出现语义错位。所以它的作用域被限制成
        "编号项已经切完之后，剩下的长块再细分"，错位风险由 min 长度门槛兜住。
    """
    t = (text or "").strip()
    if not t:
        return []
    units = [body for _lab, body in split_labeled_units(t)]
    if not use_pythainlp:
        return units
    out: list[str] = []
    for u in units:
        if len(u) < min_pythainlp_chars:
            out.append(u)
            continue
        try:
            from pythainlp.tokenize import sent_tokenize
            parts = [p.strip() for p in sent_tokenize(u, engine="crfcut") if p.strip()]
        except Exception:
            parts = [u]                      # 装不上/报错就退回不细分，不静默切错
        out.extend(parts if parts else [u])
    return out


def split_auto(text: str, **kw) -> list[str]:
    """按文本主要语种选切分器。"""
    thai = len(_THAI_RE.findall(text))
    cjk = len(re.findall(r"[一-鿿]", text))
    lat = len(re.findall(r"[A-Za-z]", text))
    if thai > cjk and thai > lat:
        return split_th(text, **kw)
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
