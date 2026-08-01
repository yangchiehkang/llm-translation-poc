#!/usr/bin/env python3
"""生成《标准法规翻译接口 · 调用说明 v3.0》.docx —— 与 v2.2 同一格式。

这是**发给国创的那一份**：七节短文档、以"照着敲就能调通"为目标，
不是 make_api_docx.py 那份完整规格书（那份是 v2.0/v3.0 规格书，受众不同）。

v3.0 相对 v2.2 的变更（2026-08-01）：
  1. 生产机迁至 <API_HOST>。第一节的服务地址表由三行（在服务器上直接
     调用 / SSH 隧道 / 对方外网）**收敛为一行外网地址**；第二节的
     `systemctl --user status` 一并删除——那是内部运维动作，不该出现在对外文档。
  2. 第五节「耗时」与「并发」两行标 [待实测]：v2.2 的数出自旧生产机 220，
     迁机后不得沿用。其余（长度上限、超时约定）不变。
  3. 第五节新增「输出一致性」一行：相同配置下输出高度一致，但**不承诺同一输入
     逐字节相同**；质量以 TCR / XCOMET-DA 验收口径为准，术语约束仍是逐字保证。
  4. 修正 v2.2 的一处不实陈述：translateType="2" 实测返回 **code:422**
     （提示需上传文件），不是 v2.2 写的 code:404。已在 125 上实测确认。
  5. 第七节补一句占位接口**同样需要鉴权**（不带 token 返回 401 而非 404），
     v2.2 未说明，实测确认。

token 处理
----------
本脚本**不硬编码 token**（项目纪律：token 不进代码/文档/日志/commit）。
生成时从环境变量 GUOCHUANG_TOKEN 注入；产物落在 outputs/（已 gitignore），
因此产物里可以像 v2.2 一样内联真实 token，而版本库里没有。

    GUOCHUANG_TOKEN=$(ssh <NPU_HOST>-2 'grep ^API_TOKENS= .../.env | sed ... | cut -d, -f1') \
        python3 scripts/reporting/make_call_guide_docx.py outputs/deliverables/xxx.docx

不设该变量时，文档里显示占位符 <贵方 token（另行发送）>。
"""
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
import os
import sys

TOKEN = os.environ.get("GUOCHUANG_TOKEN", "") or "<贵方 token（另行发送）>"

# ---------------------------------------------------------------------------
# 服务地址与性能口径做成 profile：兜底切回 220 时同一生成器出另一版，文档零重写。
#
#   python3 make_call_guide_docx.py out.docx                 # 默认 125，性能 [待实测]
#   python3 make_call_guide_docx.py out.docx --profile 220   # 220 地址 + 220 实测数字
#   python3 make_call_guide_docx.py out.docx --addr http://x:4188   # 显式覆盖地址
#
# ⚠️ 220 profile 的地址端口写的是 4188，但 **220 当前实际监听 8188**，
#    且实测 8188 从外网不可达（该机只有 4000–5000 段做了 NAT 转发）。
#    因此启用 220 profile 前必须先把 220 切到 4000–5000 段的端口，
#    否则这份文档给出的地址是通不了的。切完若不是 4188，用 --addr 覆盖。
# ---------------------------------------------------------------------------
_TBD = "**[待实测]**"

PROFILES = {
    # 当前生产机
    "125": {
        "addr": "http://<API_HOST>",
        "elapsed": _TBD + " —— v2.2 的耗时数出自旧生产机，本次迁机后不予沿用；"
                          "我方在新机重测后补发本节数字",
        "jitter": "服务器为多服务共享资源，负载波动呈阵发性，安静时段的耗时不代表最坏情况。"
                  "**迁机后的抖动幅度同样 [待实测]**",
        "concurrency": _TBD + " —— 新机并发能力需重测后方可给出承诺。"
                              "贵方预期并发量与调用频率上限请告知，我方据此确定限流策略",
        "footnote": "**说明**：第五节中标 [待实测] 的两项，是我方主动不沿用旧机数字所致，"
                    "并非能力缺失。新机实测完成后我方会立即补发，届时仅更新本节，其余内容不变。",
    },
    # 兜底：切回原生产机。数字为 2026-07-30 在该机上的实测存档
    # （docs/deliverables/latency_40004_20260730.jsonl，n=8/档，全部成功）。
    "220": {
        "addr": "http://220.154.1.75:4188",
        "elapsed": "1000 字符约 4 秒，2000 字符约 8 秒，4000 字符约 17 秒，6000 字符约 21 秒"
                   "（2026-07-30 实测，每档 n=8，全部成功）",
        "jitter": "服务器为多服务共享资源，约 1%–3% 的时段会出现阵发性拥塞，"
                  "此时短请求也可能耗时 40–90 秒；6000 字符长请求曾实际发生过 1 次 120 秒超时",
        "concurrency": "已验证 5 路并发正常，5 路并发下单请求耗时与单发基本一致",
        "footnote": "**说明**：第五节耗时为 2026-07-30 在本机的实测值，非估算；"
                    "原始测量日志可按需提供。",
    },
}

_argv = [a for a in sys.argv[1:]]


def _opt(name, default=None):
    if name in _argv:
        i = _argv.index(name)
        v = _argv[i + 1]
        del _argv[i:i + 2]
        return v
    return default


PROFILE = _opt("--profile", "125")
if PROFILE not in PROFILES:
    raise SystemExit(f"未知 profile：{PROFILE}（可选 {'/'.join(PROFILES)}）")
P = PROFILES[PROFILE]
ADDR = _opt("--addr", P["addr"])

DOC = Document()
st = DOC.styles["Normal"]
st.font.name = "Times New Roman"
st.font.size = Pt(10.5)
st.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
for s in DOC.sections:
    s.left_margin = s.right_margin = Cm(2.2)


def _cn(run, name="宋体"):
    run.font.name = "Times New Roman"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)


def _emit(p, text, size=10.5, bold=False, cn="宋体"):
    """渲染 **粗体** 标记；避免星号裸露进交付文档。"""
    for i, seg in enumerate(str(text).split("**")):
        if not seg:
            continue
        r = p.add_run(seg)
        _cn(r, cn)
        r.bold = bold or (i % 2 == 1)
        r.font.size = Pt(size)
    return p


def h(text, level=1):
    p = DOC.add_heading(level=level)
    r = p.add_run(text)
    _cn(r, "黑体")
    r.font.color.rgb = RGBColor(0, 0, 0)
    r.font.size = Pt({1: 15, 2: 12.5}[level])
    return p


def para(text, bold=False, size=10.5):
    return _emit(DOC.add_paragraph(), text, size=size, bold=bold)


def code(text):
    p = DOC.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.4)
    p.paragraph_format.space_after = Pt(6)
    r = p.add_run(text)
    r.font.name = "Consolas"
    r.font.size = Pt(8.5)
    return p


def table(headers, rows, widths=None):
    t = DOC.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, hd in enumerate(headers):
        c = t.rows[0].cells[i]
        c.text = ""
        r = c.paragraphs[0].add_run(hd)
        _cn(r, "黑体"); r.bold = True; r.font.size = Pt(10)
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


# ============================== 标题 ==============================
t = DOC.add_paragraph(); t.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = t.add_run("标准法规翻译接口 · 调用说明"); _cn(r, "黑体"); r.bold = True; r.font.size = Pt(19)
t = DOC.add_paragraph(); t.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = t.add_run("v3.0 · 2026-08-01（取代 v2.2）"); _cn(r, "黑体"); r.font.size = Pt(11)
DOC.add_paragraph()
para("**本版相对 v2.2 的变化**：服务地址已更新（见第一节，**只有一个地址**，"
     "v2.2 中的三种访问方式全部作废）；第五节的耗时与并发数字" +
     ("待在新机重测，暂标 [待实测]" if PROFILE == "125" else "为本机实测值") +
     "。token、字段、错误码、术语库接口均与 v2.2 一致，**贵方已实现的对接代码无需改动，"
     "只需替换服务地址**。")

# ============================== 一 ==============================
h("一、服务地址", 1)
table(["场景", "地址"],
      [["调用（唯一地址）", ADDR]],
      widths=[4.0, 12.0])
para("所有请求需带请求头：Content-Type: application/json，以及 Authorization 鉴权头。")
para("本次为贵方分配的 token 如下（区分大小写，请原样复制；Bearer 与 token 之间需有一个空格）：")
code("Authorization: Bearer " + TOKEN)
para("该 token 为贵方专用、长期有效，无过期时间。**v2.2 已发放的 token 继续有效，无需更换。**"
     "健康检查接口 /health 免鉴权，其余业务接口均需携带。")
para("翻译由部署在本服务器的开源模型 Qwen3.6-35B-A3B 完成，权重存放于本地磁盘，不调用任何外部云端 API。")

# ============================== 二 ==============================
h("二、先确认服务在跑", 1)
para("健康检查不需要 token，可直接用于连通性自查：")
code("curl " + ADDR + "/health")
para("返回 code:0 即服务正常：")
code('{"code":0,"msg":"ok","data":{"status":"ok","backend":"local_npu",\n'
     ' "backend_info":{"backend":"local_npu","model":"Qwen3.6-35B-A3B",\n'
     '                 "base_url":"<内部地址>","configured":true},\n'
     ' "backend_reachable":true,"backend_check_detail":"ok",\n'
     ' "backend_checked_at":"2026-08-01T07:30:57Z",\n'
     ' "law_path":"/openApi/translate/law",\n'
     ' "supported_language_types":["EN-CN","DE-CN","FR-CN","ES-CN","RU-CN","AR-CN","TH-CN"],\n'
     ' "max_text_chars":6000}}')
para("backend_reachable 为 true 表示后端模型可达；若为 false，接口仍返回 200，但翻译会失败。")

# ============================== 三 ==============================
h("三、调用翻译接口", 1)
para("POST /openApi/translate/law")
para("输入示例（英译汉，带 3 条术语约束）：")
code('curl -X POST ' + ADDR + '/openApi/translate/law \\\n'
     '  -H "Authorization: Bearer ' + TOKEN + '" \\\n'
     '  -H "Content-Type: application/json" \\\n'
     "  -d '{\n"
     '    "translateType": "1",\n'
     '    "languageType": "EN-CN",\n'
     '    "originalText": "The approval authority shall notify the technical service '
     'before granting type approval for the vehicle.",\n'
     '    "terminologyList": [\n'
     '      {"originalTerminology": "type approval",\n'
     '       "translateTerminology": "整车型式批准"},\n'
     '      {"originalTerminology": "approval authority",\n'
     '       "translateTerminology": "型式批准主管部门"},\n'
     '      {"originalTerminology": "technical service",\n'
     '       "translateTerminology": "技术服务机构"}\n'
     '    ]\n'
     "  }'")
para("输出示例：")
code('{\n'
     '  "code": 0,\n'
     '  "msg": "ok",\n'
     '  "data": {\n'
     '    "translateText": "型式批准主管部门应在授予车辆整车型式批准之前通知技术服务机构。",\n'
     '    "detectedLanguageType": "EN-CN"\n'
     '  }\n'
     '}')
para("三条术语都按传入的指定译法输出。传入的术语优先级高于本地术语库。")

# ============================== 四 ==============================
h("四、字段说明", 1)
table(["字段", "必填", "说明"],
      [["translateType", "是",
        '"1" 文本翻译（当前可用）；"2" 文档翻译（暂未开放）。'
        '注意是字符串不是数字'],
       ["languageType", "否",
        "EN-CN / DE-CN / FR-CN / ES-CN / RU-CN / AR-CN / TH-CN；不传时自动识别源语种，"
        "并在 data.detectedLanguageType 回显；识别不出或传入不支持的枚举值返回 code:422"],
       ["originalText", "是", "原文，上限 6000 字符"],
       ["terminologyList", "否",
        "术语数组，不传或传空数组 [] 均可；传入的术语优先级高于本地术语库"]],
      widths=[3.6, 1.8, 10.6])
para("返回结构统一是 {code, msg, data}，HTTP 状态码一律 200，看 code 判断成败：")
table(["code", "说明"],
      [["0", "成功"],
       ["401", "鉴权失败（未带 token、格式错误或 token 无效）"],
       ["404", "接口未实现或功能未开放（如占位接口）"],
       ["422", "参数错误（超长、缺字段、语种不支持、语种无法识别、"
               "translateType=\"2\" 但未上传文件）"],
       ["500", "服务端错误（含请求超时）"]],
      widths=[2.0, 14.0])
para("鉴权失败有两种提示，可据此自查：未带 Authorization 头或漏了 Bearer 前缀，"
     "返回「缺少或格式错误的 Authorization Bearer token」；格式正确但 token 值不对"
     "（含大小写写错），返回「无效的 API token」。")

# ============================== 五 ==============================
h("五、限制", 1)
table(["项", "说明"],
      [["原文长度", "单次上限 6000 字符，超长返回 code:422（本期不做自动切分）"],
       ["耗时（典型值）", P["elapsed"]],
       ["延迟抖动", P["jitter"]],
       ["超时", "单请求上限 120 秒，超时返回 code:500。请将客户端超时设为 ≥120 秒，"
                "并对超时类错误重试一次"],
       ["并发", P["concurrency"]],
       ["输出一致性", "相同配置下对同一输入的输出**高度一致**，但**不承诺同一输入逐字节相同**："
                      "推理服务按批次动态编排，同一输入可能产生用词不同但含义等价的合法译法。"
                      "翻译质量以术语一致率（TCR）与 XCOMET-DA 验收口径为准。"
                      "**贵方通过 terminologyList 传入的术语必定按指定译法输出，这一条是逐字保证的**"]],
      widths=[3.2, 12.8])
para(P["footnote"])

# ============================== 六 ==============================
h("六、术语库列表接口", 1)
para("GET /openApi/terminology/list（需鉴权）")
para("两个参数都是可选的 query 参数：")
table(["参数", "必填", "说明"],
      [["languageType", "否",
        "按语向过滤，枚举同翻译接口。**注意：传入不支持的值不会报错，会静默返回全量数据"
        "（不过滤），请确认拼写**"],
       ["limit", "否",
        "只取前 N 条。不传即返回全量 2061 条（约 300KB），建议务必带 limit 或 languageType；"
        "传 0 或负数等同不限制；传非整数返回 code:422"]],
      widths=[3.2, 1.8, 11.0])
para("各语向条数（合计 2061）：DE-CN 336、FR-CN 321、AR-CN 304、TH-CN 290、"
     "ES-CN 289、EN-CN 285、RU-CN 236。")
para("请求示例与返回：")
code('curl -H "Authorization: Bearer ' + TOKEN + '" \\\n'
     '  "' + ADDR + '/openApi/terminology/list?languageType=EN-CN&limit=3"')
code('{"code":0,"msg":"ok","data":[\n'
     ' {"terminology":"车辆","terminologyType":"EN-CN",\n'
     '  "terminologyEn":"vehicle","terminologyRemark":"汽车法规通用术语"},\n'
     ' {"terminology":"机动车","terminologyType":"EN-CN",\n'
     '  "terminologyEn":"motor vehicle","terminologyRemark":"道路车辆法规常见术语"},\n'
     ' {"terminology":"型式认证","terminologyType":"EN-CN",\n'
     '  "terminologyEn":"type approval","terminologyRemark":"认证法规术语"}]}')
table(["字段", "说明"],
      [["terminology", "中文译法"],
       ["terminologyType", "语向"],
       ["terminologyEn", "外文原词。字段名虽为 En，阿拉伯语等语向存放的是该语种原文，并非英文"],
       ["terminologyRemark", "术语说明"]],
      widths=[4.0, 12.0])

# ============================== 七 ==============================
h("七、其他接口", 1)
table(["接口", "路径", "状态"],
      [["企标编写", "/openApi/standard/write", "占位，返回 code:404"],
       ["培训PPT生成", "/openApi/ppt/generate", "占位，返回 code:404"],
       ["术语提取", "/openApi/terminology/extract", "占位，返回 code:404"]],
      widths=[4.0, 6.0, 6.0])
para("占位接口**同样需要鉴权**：不带 token 调用返回 code:401 而非 code:404，"
     "贵方做连通性测试时请带上 Authorization 头。")

out = _argv[0] if _argv else f"标准法规翻译接口_调用说明_v3.0_{PROFILE}.docx"
DOC.save(out)
print("saved:", out)
print("profile:", PROFILE, " 地址:", ADDR)
print("token:", "已内联" if TOKEN.startswith("guochuang_") else "占位符（未设 GUOCHUANG_TOKEN）")
