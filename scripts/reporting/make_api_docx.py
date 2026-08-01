#!/usr/bin/env python3
"""生成《港中深 API 接口文档 v2.0 — 标准法规翻译子系统》.docx

版式沿用甲方 v1.0 的"每接口一张属性表 + 请求参数表 / 请求示例 / 响应参数表 /
响应示例"结构。所有数字来自 2026-07-30 在 40004 上的实测，不沿用 dashscope 时代
的旧值。
"""
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
import sys

DOC = Document()

# ---- 全局字体：中文宋体 / 西文 Times，正文小四 ----
st = DOC.styles["Normal"]
st.font.name = "Times New Roman"
st.font.size = Pt(10.5)
st.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
for s in DOC.sections:
    s.left_margin = s.right_margin = Cm(2.4)


def _set_cn(run, name="宋体"):
    run.font.name = "Times New Roman"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)


def h(text, level=1):
    p = DOC.add_heading(level=level)
    r = p.add_run(text)
    _set_cn(r, "黑体")
    r.font.color.rgb = RGBColor(0, 0, 0)
    r.font.size = Pt({1: 15, 2: 13, 3: 11.5}[level])
    return p


def para(text, bold=False, size=10.5, italic=False):
    p = DOC.add_paragraph()
    r = p.add_run(text)
    _set_cn(r)
    r.bold = bold
    r.italic = italic
    r.font.size = Pt(size)
    return p


def code(text):
    p = DOC.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.5)
    p.paragraph_format.space_after = Pt(6)
    r = p.add_run(text)
    r.font.name = "Consolas"
    r.font.size = Pt(9)
    return p


def table(headers, rows, widths=None):
    t = DOC.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, hd in enumerate(headers):
        c = t.rows[0].cells[i]
        c.text = ""
        r = c.paragraphs[0].add_run(hd)
        _set_cn(r, "黑体"); r.bold = True; r.font.size = Pt(10)
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""
            r = cells[i].paragraphs[0].add_run(str(v))
            _set_cn(r); r.font.size = Pt(9.5)
    if widths:
        for i, w in enumerate(widths):
            for row in t.rows:
                row.cells[i].width = Cm(w)
    DOC.add_paragraph()
    return t


def iface_attr(no, name, method, path, requester="国创（甲方业务系统）",
               responder="广汽研究院法规翻译服务（本地部署）", trigger="甲方业务系统主动调用"):
    table(["属性", "内容"],
          [["接口编号", no], ["接口名称", name], ["请求方式", method], ["接口路径", path],
           ["请求方", requester], ["响应方", responder], ["触发方式", trigger],
           ["鉴权", "Bearer Token（`/health` 除外）"]],
          widths=[3.5, 12.5])


# ============================== 封面 ==============================
t = DOC.add_paragraph(); t.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = t.add_run("港中深 API 接口文档 v2.0"); _set_cn(r, "黑体"); r.bold = True; r.font.size = Pt(22)
t = DOC.add_paragraph(); t.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = t.add_run("标准法规翻译子系统"); _set_cn(r, "黑体"); r.font.size = Pt(15)
DOC.add_paragraph()
table(["项", "内容"],
      [["文档版本", "v2.0"], ["编制日期", "2026-07-30"],
       ["适用系统", "标准法规翻译 API（广汽汽车标准法规多语种翻译）"],
       ["取代版本", "v1.0（dashscope 云端模型时期编制，其中 5 项已与实际不符，见第 1.2 节）"],
       ["性能数据来源", "2026-07-30 在生产后端实测，40 次请求 + 325 次定时探针，见第 6 节"]],
      widths=[3.5, 12.5])

# ============================== 1 概述 ==============================
h("1. 概述", 1)
h("1.1 系统形态（与 v1.0 的根本差异）", 2)
para("标准法规翻译由**部署在本地服务器上的开源大模型**完成，不调用任何外部云端 API。"
     "原文、译文与术语数据全程不出服务器。", bold=False)
table(["项", "内容"],
      [["推理服务", "vLLM（OpenAI 兼容接口），部署在本机，监听内网地址"],
       ["模型", "Qwen3.6-35B-A3B（开源权重，MoE 架构）"],
       ["权重位置", "服务器本地磁盘 /data/MODEL_DIR/（约 67 GB），离线加载"],
       ["并行方式", "张量并行 TP=2 + 专家并行，最大上下文 32768 token"],
       ["外部依赖", "无。不经过 dashscope 或任何公有云推理服务"],
       ["回退通道", "代码中保留云端后端实现，仅作故障回退预案；生产配置未启用，"
                    "日志可核验：截至 2026-07-30 全部翻译请求均落在本地推理服务"]],
      widths=[3.5, 12.5])

h("1.2 v1.0 过期项对照", 2)
para("以下 5 项 v1.0 与当前实现不符，本版全部更正：")
table(["项", "v1.0 文档", "v2.0 实际", "影响"],
      [["后端 / 模型", "qwen-max（云端 API）", "本地开源模型 Qwen3.6-35B-A3B", "数据不出服务器；延迟曲线整体改变"],
       ["单次字符上限", "8000", "6000", "超过 6000 返回 code:422"],
       ["延迟表", "500 字=2.5s … 8000 字=44.3s（云端实测）", "见第 6 节（本地后端重测）", "同长度延迟显著下降"],
       ["languageType", "必填", "选填；缺省时自动识别，识别不出返回 code:422", "可不传；不静默猜测"],
       ["terminologyList", "必填", "选填，缺省为空数组", "可不传"]],
      widths=[3.0, 4.2, 4.8, 4.0])
para("另：`/health` 新增 backend_reachable / backend_check_detail / backend_checked_at 三个字段，"
     "用于判断后端推理服务此刻是否真的可用（v1.0 只反映配置是否填写）。")

# ============================== 2 接入信息 ==============================
h("2. 接入信息", 1)
table(["项", "内容"],
      [["协议", "HTTP/1.1"], ["服务监听", "0.0.0.0:8188（服务器本地）"],
       ["外网地址", "由贵方 NAT / 端口转发提供；我方保证服务在主机 0.0.0.0:8188 上监听"],
       ["请求头", "Content-Type: application/json；Authorization: Bearer <token>"],
       ["Token", "我方签发，通过安全渠道单独发送，不在本文档明文；支持多 token 与轮换"],
       ["字符集", "UTF-8"],
       ["联调自测", "SSH 隧道：ssh -L 8188:127.0.0.1:8188 <server> 后访问 http://127.0.0.1:8188"]],
      widths=[3.5, 12.5])

# ============================== 3 通用约定 ==============================
h("3. 通用响应约定", 1)
para("所有接口统一返回 {code, msg, data} 三段式，**HTTP 状态码一律 200**，业务结果看 code。"
     "data 无数据时为 null。不会出现框架原生的 {\"detail\":[...]} 结构。")
code('{ "code": 0, "msg": "ok", "data": { ... } }')
table(["code", "含义", "典型场景"],
      [["0", "成功", "正常返回"],
       ["401", "未授权", "缺少或错误的 Authorization 头"],
       ["403", "无权限", "token 无该接口权限"],
       ["404", "资源不存在或未开放", "文档翻译、企标编写等未开放能力"],
       ["422", "参数校验失败", "缺 translateType；originalText 为空；超字符上限；"
                              "languageType 取值不在枚举；无法识别源语种"],
       ["500", "服务端错误", "后端推理服务不可达、译文被截断、超时"]],
      widths=[2.0, 3.5, 10.5])

DOC.add_page_break()

# ============================== 4 接口 1：法规翻译 ==============================
h("4. 接口 1：标准法规翻译", 1)
iface_attr("GZS-TRANS-001", "标准法规翻译", "POST", "/openApi/translate/law")

h("4.1 请求参数", 2)
table(["参数名", "类型", "必填", "说明"],
      [["translateType", "string", "是", "\"1\"=文本翻译；\"2\"=文档翻译（本期未开放，返回 code:404）。注意是字符串不是数字"],
       ["originalText", "string", "translateType=\"1\" 时必填", "待翻译原文，长度上限 6000 字符（超出返回 code:422，本期不做自动切分）"],
       ["languageType", "string", "否", "语向枚举。**不传时由系统自动识别**；传了则按传入值处理。"
                                        "取值不在枚举返回 code:422 并列出全部枚举"],
       ["terminologyList", "array", "否", "术语列表，缺省为空数组。元素：{originalTerminology, translateTerminology}"],
       ["originalFile / originalFileBase64", "file / string", "translateType=\"2\" 时", "文档上传通道（multipart 或 base64），本期仅做参数校验"]],
      widths=[4.0, 2.2, 3.0, 6.8])
para("languageType 枚举（均为「外文 → 中文」）：EN-CN、DE-CN、FR-CN、ES-CN、RU-CN、AR-CN、TH-CN。")
para("语种自动识别（不传 languageType 时生效）分两级：① 按 Unicode 字符集直接判定 "
     "俄语 / 阿拉伯语 / 泰语，零推理开销；② 拉丁字母语种交由模型判定。"
     "**识别不出时返回 code:422「无法识别源语种」，不会静默按默认语种翻译**"
     "——静默猜错会导致术语库按错误语向匹配、术语静默丢失。实测自动识别带来的额外耗时约 +0.2 秒。")
para("术语行为：贵方传入的术语一律按硬约束处理；与我方本地术语库冲突时以贵方传入为准；"
     "译后做命中校验，未命中记录告警但不做强制字符串替换（避免破坏中文语序）。")

h("4.2 请求示例", 2)
code('''POST /openApi/translate/law HTTP/1.1
Host: <host>:8188
Content-Type: application/json
Authorization: Bearer <token>

{
  "translateType": "1",
  "languageType": "EN-CN",
  "originalText": "5.1. The approval authority shall verify that the technical service performs
                   the tests in accordance with this Regulation before granting type approval
                   for the rechargeable electrical energy storage system.",
  "terminologyList": [
    {"originalTerminology": "technical service", "translateTerminology": "技术服务机构"}
  ]
}''')

h("4.3 响应参数", 2)
table(["参数名", "类型", "说明"],
      [["code", "int", "业务码，0 为成功"],
       ["msg", "string", "结果说明，成功为 \"ok\""],
       ["data.translateText", "string", "中文译文"],
       ["data.detectedLanguageType", "string", "本次实际使用的语向。显式传入则原样回显；"
                                              "未传则回显自动识别结果，供贵方核对"]],
      widths=[5.0, 2.2, 8.8])

h("4.4 响应示例", 2)
code('''{
  "code": 0,
  "msg": "ok",
  "data": {
    "translateText": "5.1. 认证主管机构应在授予可充电储能系统的型式认证之前，核实技术服务机构是否按照本法规进行测试。",
    "detectedLanguageType": "EN-CN"
  }
}''')

h("4.5 真实调用记录（2026-07-30 实测，未经修饰）", 2)
para("以下为在生产环境上真实发出的一次请求与其原始返回，可作为联调期望值对照。", italic=True)
table(["项", "内容"],
      [["请求原文（EN）",
        "5.1. The approval authority shall verify that the technical service performs the tests "
        "in accordance with this Regulation before granting type approval for the rechargeable "
        "electrical energy storage system."],
       ["传入术语", "technical service → 技术服务机构"],
       ["返回译文（ZH）",
        "5.1. 认证主管机构应在授予可充电储能系统的型式认证之前，核实技术服务机构是否按照本法规进行测试。"],
       ["detectedLanguageType", "EN-CN"],
       ["实际耗时", "1.55 秒"],
       ["术语核验", "指定译法「技术服务机构」已出现在译文中"]],
      widths=[3.5, 12.5])
para("另一例（不传 languageType、不传 terminologyList，验证两个字段确为选填）：", italic=True)
table(["项", "内容"],
      [["请求原文（DE）", "§ 22 Betriebserlaubnis für Fahrzeugteile: Die Betriebserlaubnis für "
                        "Fahrzeugteile wird auf Antrag des Herstellers erteilt."],
       ["返回译文（ZH）", "第22条 车辆部件的运行许可：车辆部件的运行许可应制造商的申请予以颁发。"],
       ["detectedLanguageType", "DE-CN（自动识别得出）"],
       ["实际耗时", "1.66 秒"]],
      widths=[3.5, 12.5])

h("4.6 校验与限制", 2)
table(["情形", "返回"],
      [["缺 translateType", "code:422「缺少 translateType（字符串 '1' 文本翻译 / '2' 文档翻译）」"],
       ["translateType=\"1\" 且 originalText 为空", "code:422"],
       ["originalText 超过 6000 字符", "code:422，msg 含实际长度与上限"],
       ["languageType 取值不在枚举", "code:422，msg 列出全部支持枚举"],
       ["无法识别源语种（未传 languageType）", "code:422「无法识别源语种」"],
       ["译文触顶被截断", "code:500「译文超长被截断」——**不会静默返回半截译文**"],
       ["单请求超过 120 秒未返回", "code:500「翻译超时」，连接立即释放，不影响后续请求"],
       ["translateType=\"2\"（文档翻译）", "code:404「文档翻译暂未开放，当前仅支持文本翻译」；"
                                        "上传通道可提前联调"]],
      widths=[6.0, 10.0])

DOC.add_page_break()

# ============================== 5 其余接口 ==============================
h("5. 接口 2：术语库列表", 1)
iface_attr("GZS-TERM-001", "术语库列表查询", "GET", "/openApi/terminology/list")
h("5.1 请求参数", 2)
table(["参数名", "类型", "必填", "说明"],
      [["languageType", "string", "否", "按语向过滤，取值同翻译接口枚举；不传返回全部"],
       ["limit", "int", "否", "限制返回条数；不传或 ≤0 返回全部"]],
      widths=[4.0, 2.2, 3.0, 6.8])
h("5.2 请求示例", 2)
code("GET /openApi/terminology/list?languageType=EN-CN&limit=2\nAuthorization: Bearer <token>")
h("5.3 响应参数", 2)
table(["参数名", "类型", "说明"],
      [["data", "array", "术语数组"],
       ["data[].terminology", "string", "中文译法"],
       ["data[].terminologyType", "string", "语种类型，如 EN-CN"],
       ["data[].terminologyEn", "string", "外文术语"],
       ["data[].terminologyRemark", "string", "说明/备注"]],
      widths=[5.0, 2.2, 8.8])
h("5.4 响应示例（真实返回）", 2)
code('''{
  "code": 0, "msg": "ok",
  "data": [
    {"terminology": "车辆",   "terminologyType": "EN-CN", "terminologyEn": "vehicle",
     "terminologyRemark": "汽车法规通用术语"},
    {"terminology": "机动车", "terminologyType": "EN-CN", "terminologyEn": "motor vehicle",
     "terminologyRemark": "道路车辆法规常见术语"}
  ]
}''')

h("6. 接口 3：健康检查", 1)
iface_attr("GZS-HEALTH-001", "健康检查", "GET", "/health",
           requester="国创（甲方业务系统）/ 监控系统", trigger="定时轮询或按需调用")
para("该接口**不鉴权**，且**永远返回 HTTP 200 / code:0**，后端探测失败也不例外"
     "——避免贵方集成用例因一次后端抖动而误判为接口故障。是否可用请读 backend_reachable 字段。")
h("6.1 响应参数", 2)
table(["参数名", "类型", "说明"],
      [["data.status", "string", "服务自身状态，固定 \"ok\""],
       ["data.backend", "string", "当前后端标识，生产为 local_npu（本地推理服务）"],
       ["data.backend_info.model", "string", "当前实际服务的模型名，生产为 Qwen3.6-35B-A3B"],
       ["data.backend_reachable", "bool", "**新增**。此刻后端推理服务是否真的可达且在服务该模型"],
       ["data.backend_check_detail", "string", "**新增**。探测详情；不可用时给出具体原因"],
       ["data.backend_checked_at", "string", "**新增**。本次探测时间（UTC）"],
       ["data.max_text_chars", "int", "单次文本上限，当前 6000"],
       ["data.supported_language_types", "array", "支持的语向枚举"]],
      widths=[5.5, 2.0, 8.5])
h("6.2 响应示例（真实返回）", 2)
code('''{
  "code": 0, "msg": "ok",
  "data": {
    "status": "ok",
    "backend": "local_npu",
    "backend_info": {"backend": "local_npu", "model": "Qwen3.6-35B-A3B",
                     "base_url": "http://<内网地址>/v1", "configured": true},
    "backend_reachable": true,
    "backend_check_detail": "ok",
    "backend_checked_at": "2026-07-30T13:41:54Z",
    "law_path": "/openApi/translate/law",
    "supported_language_types": ["EN-CN","DE-CN","FR-CN","ES-CN","RU-CN","AR-CN","TH-CN"],
    "max_text_chars": 6000
  }
}''')

h("7. 占位接口（本期未开放）", 1)
table(["接口编号", "接口名称", "方法", "路径", "当前返回"],
      [["GZS-STD-001", "企标编写", "GET/POST", "/openApi/standard/write", "code:404「接口尚未实现」"],
       ["GZS-PPT-001", "培训 PPT 生成", "GET/POST", "/openApi/ppt/generate", "code:404「接口尚未实现」"],
       ["GZS-TERMEX-001", "术语提取", "GET/POST", "/openApi/terminology/extract", "code:404「接口尚未实现」"]],
      widths=[3.2, 3.0, 2.2, 4.6, 4.0])
para("占位接口已上线，可提前做连通性与联调测试。")

DOC.add_page_break()

# ============================== 8 性能 ==============================
h("8. 性能与容量（2026-07-30 在本地后端实测）", 1)
h("8.1 测量方法", 2)
para("v1.0 的延迟表出自云端 dashscope，与当前本地部署不可比，本节全部重测。方法如下，"
     "以便贵方复核或自行复现：")
table(["项", "做法", "为什么"],
      [["分档", "1000 / 2000 / 4000 / 6000 字符", "覆盖到合同上限 6000"],
       ["每档轮数", "8 轮，共 40 次请求（含 8 次自动识别对照）", "单次采样在这台机上没有意义，见 8.3"],
       ["轮次编排", "四档交错轮转，不把同一档连续打完，整体铺开 25 分钟",
        "该机负载波动是阵发性的；连续打同一档会把某一阵抖动全记在那一档上"],
       ["输入文本", "每档 8 段**互不相同**的真实法规条款",
        "① 推理服务开了前缀缓存，重复同一段文本会让后 7 次命中缓存、系统性低估延迟；"
        "② 用同一句话复制成长文本会触发模型病态生成，不代表真实业务"],
       ["计时口径", "客户端从发出到收到完整响应，含鉴权、术语匹配、推理全过程", "贵方实际感知的时间"],
       ["token 数", "由服务端日志记录的 completion_tokens", "字符数与 token 数非线性，容量规划要看 token"]],
      widths=[2.6, 6.4, 7.0])

h("8.2 延迟表（正常时段，n=8/档，全部成功）", 2)
table(["输入字符", "p50", "p95", "最大", "最小", "译文 token 数（p50 / 最大）", "折合"],
      [["1000", "4.29 s", "4.94 s", "5.07 s", "3.98 s", "182 / 225", "4.4 ms/字符"],
       ["2000", "7.84 s", "9.20 s", "9.46 s", "7.17 s", "349 / 442", "4.0 ms/字符"],
       ["4000", "16.71 s", "17.91 s", "18.23 s", "15.32 s", "800 / 850", "4.2 ms/字符"],
       ["6000（上限）", "20.98 s", "23.71 s", "24.12 s", "19.57 s", "1026 / 1204", "3.6 ms/字符"]],
      widths=[2.6, 2.0, 2.0, 2.0, 2.0, 4.0, 2.4])
para("对照 v1.0（云端）：8000 字符约 44 秒。当前本地后端在 6000 字符上限处 p50 约 21 秒、"
     "p95 约 24 秒，同等长度下明显更快。40 次请求全部 code:0，无失败、无截断。")
para("自动识别开销：同为 2000 字符，传 languageType 时 p50 = 7.84 s，不传时 p50 = 7.99 s，"
     "差 +0.15 s（n=8）。**可以放心不传 languageType。**")

h("8.3 ⚠️ 尾部延迟：阵发性抖动（必须与上表一并阅读）", 2)
para("8.2 是一个 25 分钟窗口内的测量，那段时间机器状态平稳（p95/p50 ≈ 1.15）。"
     "但这台服务器是多服务共享的，负载波动呈**阵发性**——安静时段的分位数不能代表最坏情况。"
     "以下是同一套生产接口上、连续 2.4 天、每 10 分钟一次的定时探针结果，可作为尾部的独立证据：")
table(["探针", "样本数", "p50", "p95", "p99", "最大", "说明"],
      [["短文本（138 字符）", "325", "1.02 s", "5.86 s", "39.61 s", "89.58 s",
        "最慢的 8 次全部集中在 2026-07-28 17:14–19:00 (UTC) 这一个多小时内"],
       ["长文本（6000 字符）", "7", "29.2 s", "—", "—", "**120 s 超时 1 次**",
        "6 次成功（22.4–33.2 s），1 次撞上同一阵抖动，超过 120 s 超时上限"]],
      widths=[3.4, 1.8, 1.8, 1.8, 1.8, 2.6, 4.8])
para("结论（如实陈述，不用平均值掩盖）：", bold=True)
para("① 正常时段：6000 字符 20–24 秒完成，远低于 120 秒上限。")
para("② 抖动时段（观测到约占 1%–3% 的时间）：138 字符的短请求也可能耗时 40–90 秒；"
     "6000 字符的长请求已经实际发生过 1 次 120 秒超时。")
para("③ 因此**客户端超时必须设 ≥ 120 秒**（重申 v1.0 的这条约定），"
     "并且建议对 code:500「翻译超时」实现一次重试——超时后我方连接立即释放，重试不会叠加负载。")
para("④ 抖动来源是服务器共享负载，不是本接口逻辑；我方已部署 10 分钟一次的生产自检探针，"
     "持续记录该时序，可按需提供。")

h("8.4 并发", 2)
para("5 路并发实测无损、无限流失败，墙钟时间约等于单次。贵方预期并发量与调用频率上限请告知，"
     "我方据此确定限流策略。")

h("8.5 超时与错误处理约定（沿用 v1.0）", 2)
table(["项", "约定"],
      [["服务端单请求超时", "120 秒。超过即返回 code:500「翻译超时：超过 120s 未返回」，连接释放"],
       ["客户端超时建议", "≥ 120 秒（见 8.3，务必遵守）"],
       ["重试建议", "对 code:500 超时类错误重试 1 次；对 code:422 参数类错误不重试"],
       ["截断保护", "译文触顶被截断时返回 code:500 并说明，**绝不返回半截译文**"],
       ["后端不可用", "返回 code:500；可先用 /health 的 backend_reachable 字段确认"]],
      widths=[4.5, 11.5])

# ============================== 9 附注 ==============================
h("9. 联调注意事项", 1)
para("① translateType 是**字符串** \"1\" / \"2\"，不是数字 1 / 2，传数字会返回 code:422。")
para("② 所有业务错误的 HTTP 状态码都是 200，请勿以 HTTP 状态码判断成败，一律读 code 字段。")
para("③ /health 永远返回 200/code:0，判断后端是否可用请读 data.backend_reachable。")
para("④ 单次文本上限 6000 字符（v1.0 写的 8000 已作废），本期不做自动切分，超长请贵方分段调用。")
para("⑤ languageType 与 terminologyList 现均为选填；若贵方已按 v1.0 实现为必填，无需修改，"
     "传入的值仍按原语义处理，向后兼容。")
para("⑥ 本文档所有性能数字与响应样例均来自 2026-07-30 生产环境真实调用，未做修饰；"
     "如需复现，我方可提供测量脚本与原始日志。")

out = sys.argv[1] if len(sys.argv) > 1 else "港中深API接口文档_v2.0.docx"
DOC.save(out)
print("saved:", out)
