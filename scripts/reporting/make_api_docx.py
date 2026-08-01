#!/usr/bin/env python3
"""生成《港中深 API 接口文档 v3.0 — 标准法规翻译子系统》.docx

版式沿用甲方 v1.0 的"每接口一张属性表 + 请求参数表 / 请求示例 / 响应参数表 /
响应示例"结构。

v3.0 相对 v2.2 的变更（2026-08-01）：
  1. 生产机由 220 迁至 **<API_HOST>**，服务地址收敛为**唯一一行外网地址**；
     删除 SSH 隧道与"在服务器上直接调用"两种内部访问方式（对外不再提供）。
  2. "复现 / 确定性"表述改口径：质量以术语一致率(TCR)与 XCOMET-DA 验收口径为准，
     **不承诺同一输入逐字节相同**（125 实测同输入短句会出现两种合法译法）。
  3. 第 8 章性能数字全部标 **[待实测]** —— v2.2 的数出自 220，迁机后必须在 125 重测，
     不得沿用。125 主机当前存在 CPU 侧异常（见 docs/forensics_125_rcu-sched_20260801.md），
     待其恢复后按验收序列回填。

**token 不写进本文档**（沿用既有做法：通过安全渠道单独发送）。这与 v2.2 的处理
不同——v2.2 把 token 明文写进了正文。项目纪律是任何情况下不把 token 写进代码 /
文档 / 日志 / commit，故本生成器不内联 token；如需与 v2.2 保持一致，
可设环境变量 GUOCHUANG_TOKEN，生成时注入（值不进版本库）。
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


def _emit(paragraph, text, size=10.5, bold=False, italic=False, cn="宋体"):
    """把 **粗体** 标记渲染成真正的加粗 run。

    此前 para()/table() 直接把整串塞进一个 run，源码里的 `**xxx**` 会**原样**
    出现在交付给甲方的 docx 里（v2.0 的表格单元格里就有裸露的星号）。
    这是发出去会被看见的排版缺陷，故在此统一处理。
    """
    for i, seg in enumerate(str(text).split("**")):
        if not seg:
            continue
        r = paragraph.add_run(seg)
        _set_cn(r, cn)
        r.bold = bold or (i % 2 == 1)      # 奇数段落在 ** 之间 -> 加粗
        r.italic = italic
        r.font.size = Pt(size)
    return paragraph


def para(text, bold=False, size=10.5, italic=False):
    p = DOC.add_paragraph()
    _emit(p, text, size=size, bold=bold, italic=italic)
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
            _emit(cells[i].paragraphs[0], v, size=9.5)
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
r = t.add_run("港中深 API 接口文档 v3.0"); _set_cn(r, "黑体"); r.bold = True; r.font.size = Pt(22)
t = DOC.add_paragraph(); t.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = t.add_run("标准法规翻译子系统"); _set_cn(r, "黑体"); r.font.size = Pt(15)
DOC.add_paragraph()
table(["项", "内容"],
      [["文档版本", "v3.0"], ["编制日期", "2026-08-01"],
       ["适用系统", "标准法规翻译 API（广汽汽车标准法规多语种翻译）"],
       ["取代版本", "**v2.2**（2026-07-31 编制）。v2.2 的服务地址与性能数字均出自旧生产机，已全部作废"],
       ["本次主要变更", "① 服务地址迁至 http://<API_HOST>，且仅此一个；"
                        "② 性能数字待在新机重测（第 8 章标 [待实测]）；"
                        "③ 输出一致性表述改口径（见 8.6）"],
       ["性能数据来源", "**[待实测]** —— 迁机后需在新生产机重新测量，不沿用旧机数字"]],
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
       ["并行方式", "张量并行 TP=4，最大上下文 32768 token"],
       ["外部依赖", "无。不经过 dashscope 或任何公有云推理服务"],
       ["回退通道", "代码中保留云端后端实现，仅作故障回退预案；生产配置未启用，"
                    "日志可核验：截至 2026-07-30 全部翻译请求均落在本地推理服务"]],
      widths=[3.5, 12.5])

h("1.2 v1.0 过期项对照", 2)
para("以下 5 项 v1.0 与当前实现不符，本版全部更正：")
table(["项", "v1.0 文档", "v3.0 实际", "影响"],
      [["后端 / 模型", "qwen-max（云端 API）", "本地开源模型 Qwen3.6-35B-A3B", "数据不出服务器；延迟曲线整体改变"],
       ["单次字符上限", "8000", "6000", "超过 6000 返回 code:422"],
       ["延迟表", "500 字=2.5s … 8000 字=44.3s（云端实测）", "见第 8 章（新机重测中，当前 [待实测]）", "同长度延迟显著下降"],
       ["languageType", "必填", "选填；缺省时自动识别，识别不出返回 code:422", "可不传；不静默猜测"],
       ["terminologyList", "必填", "选填，缺省为空数组", "可不传"]],
      widths=[3.0, 4.2, 4.8, 4.0])
para("另：`/health` 新增 backend_reachable / backend_check_detail / backend_checked_at 三个字段，"
     "用于判断后端推理服务此刻是否真的可用（v1.0 只反映配置是否填写）。")

# ============================== 2 接入信息 ==============================
h("2. 接入信息", 1)
table(["项", "内容"],
      [["协议", "HTTP/1.1"],
       ["服务地址", "http://<API_HOST>"],
       ["请求头", "Content-Type: application/json；Authorization: Bearer <token>"],
       ["Token", "我方签发，通过安全渠道单独发送，不在本文档明文；支持多 token 与轮换。"
                 "v2.2 中已发放的 token 继续有效，无需更换"],
       ["字符集", "UTF-8"],
       ["健康检查", "GET http://<API_HOST>/health（免鉴权，可用于连通性自查）"]],
      widths=[3.5, 12.5])
para("**服务地址仅此一个。** v2.2 中的「在服务器上直接调用（127.0.0.1:8188）」与"
     "「SSH 隧道联调」两种方式属内部访问路径，v3.0 起不再对外提供，相应条目已删除。",
     bold=False)

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
Host: <API_HOST>
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
h("8. 性能与容量（[待实测] —— 迁机后需在新生产机重新测量）", 1)
para("**本章数字尚未回填。** v2.2 的性能数据出自旧生产机，迁至 <API_HOST> 后"
     "硬件与共享负载条件均已改变，旧数不具备参考性、也不会被沿用。"
     "我方将在新机按 8.1 的方法重测后回填，并同步更新本文档版本。**在回填前，"
     "请勿以本章任何数字作为容量规划或超时设置依据**，仅 8.5 的超时约定继续有效。",
     bold=False)
h("8.1 测量方法（方法本身不变，沿用旧机口径以便前后可比）", 2)
para("方法如下，以便贵方复核：")
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

h("8.2 延迟表 [待实测]", 2)
table(["输入字符", "p50", "p95", "最大", "最小", "译文 token 数（p50 / 最大）", "折合"],
      [["500", "[待实测]", "[待实测]", "[待实测]", "[待实测]", "[待实测]", "[待实测]"],
       ["1000", "[待实测]", "[待实测]", "[待实测]", "[待实测]", "[待实测]", "[待实测]"],
       ["2000", "[待实测]", "[待实测]", "[待实测]", "[待实测]", "[待实测]", "[待实测]"],
       ["4000", "[待实测]", "[待实测]", "[待实测]", "[待实测]", "[待实测]", "[待实测]"],
       ["6000（上限）", "[待实测]", "[待实测]", "[待实测]", "[待实测]", "[待实测]", "[待实测]"]],
      widths=[2.6, 2.0, 2.0, 2.0, 2.0, 4.0, 2.4])
para("自动识别开销：**[待实测]**（旧机上实测约 +0.15 秒，新机需复测后再给结论）。")

h("8.3 ⚠️ 尾部延迟：阵发性抖动（必须与上表一并阅读）", 2)
para("这一节的**结论在旧机上已被证实，且预期在新机同样成立**，因此先行保留；"
     "具体分位数 **[待实测]**。")
para("生产服务器是多服务共享的，负载波动呈**阵发性**——安静时段的分位数不能代表最坏情况。"
     "旧机上连续 2.4 天、每 10 分钟一次的定时探针曾观测到：约 1%–3% 的时段里，"
     "138 字符的短请求也可能耗时 40–90 秒，6000 字符长请求实际发生过 1 次 120 秒超时。")
table(["探针", "样本数", "p50", "p95", "p99", "最大"],
      [["短文本（138 字符）", "[待实测]", "[待实测]", "[待实测]", "[待实测]", "[待实测]"],
       ["长文本（6000 字符）", "[待实测]", "[待实测]", "[待实测]", "[待实测]", "[待实测]"]],
      widths=[3.4, 2.4, 2.4, 2.4, 2.4, 3.0])
para("无论新机实测结果如何，以下三条约定不变：", bold=True)
para("① **客户端超时必须设 ≥ 120 秒**（沿用 v1.0/v2.2 的这条约定）。")
para("② 建议对 code:500「翻译超时」实现一次重试——超时后我方连接立即释放，重试不会叠加负载。")
para("③ 抖动来源是服务器共享负载，不是本接口逻辑；我方已部署 10 分钟一次的生产自检探针，"
     "持续记录该时序，可按需提供。")

h("8.4 并发 [待实测]", 2)
para("并发放大系数 **[待实测]**。旧机上 5 路并发实测无损、墙钟约等于单次，"
     "新机需重测后方可给出承诺。贵方预期并发量与调用频率上限请告知，我方据此确定限流策略。")

h("8.6 关于输出一致性", 2)
para("相同配置下，本接口对同一输入的输出**高度一致**；"
     "但**不承诺同一输入逐字节相同**。", bold=True)
para("推理服务为多请求共享、按批次动态编排，同一输入在不同批次组成下可能产生"
     "用词不同但含义等价的合法译法（例如「验证生产一致性」与「核实生产的一致性」）。"
     "我方已固定 temperature=0 等全部可控采样参数以收窄输出方差，但这不构成逐字节可复现的承诺。")
para("**翻译质量以术语一致率（TCR）与 XCOMET-DA 验收口径为准**，"
     "不以「两次调用字符串是否完全相同」为准。术语约束是硬性的：贵方通过 "
     "terminologyList 传入的术语必定按指定译法输出（见 4.1），这一条是逐字保证的。")

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
para("⑥ 本文档响应样例均来自生产环境真实调用，未做修饰；性能数字见第 8 章，当前 **[待实测]**。"
     "我方可提供测量脚本与原始日志供贵方复核。需说明：**相同配置下输出高度一致；"
     "不承诺同一输入逐字节相同。翻译质量以术语一致率（TCR）与 XCOMET-DA 验收口径为准**（见 8.6）。")
para("⑦ 本版服务地址为 http://<API_HOST>，取代 v2.2 中的全部地址。"
     "v2.2 已发放的 token 继续有效。")

out = sys.argv[1] if len(sys.argv) > 1 else "港中深API接口文档_v3.0.docx"
DOC.save(out)
print("saved:", out)
