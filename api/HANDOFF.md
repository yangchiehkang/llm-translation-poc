# 法规翻译 API — 对接说明（致国创）

## 1. 接入信息

| 项 | 值 |
|---|---|
| 协议 | HTTP/1.1 |
| 服务监听 | `0.0.0.0:8188`（服务器本地）|
| 外网访问地址 | `http://<对外IP或域名>:8188` —— 由贵方 NAT/端口转发提供，我方只保证服务在主机上监听 `0.0.0.0:8188` |
| 联调自测方式 | SSH 隧道：`ssh -L 8188:127.0.0.1:8188 <server>` 后访问 `http://127.0.0.1:8188` |
| 请求头 | `Content-Type: application/json`、`Authorization: Bearer <token>` |
| Token | 我方签发，**单独通过安全渠道发送**，不在本文档明文；支持多 token（贵方一枚、我方自测一枚），可轮换 |

## 2. 通用响应约定（重要）

所有接口**统一返回** `{code, msg, data}`，**HTTP 状态码一律 200**，业务结果看 `code`：

```json
{ "code": 0, "msg": "ok", "data": { ... } }
```

`data` 无数据时为 `null`。业务码：`0` 成功 / `401` 未授权 / `403` 无权限 / `404` 资源不存在或未开放 / `422` 参数校验失败 / `500` 服务端错误。
**不会出现** FastAPI 原生的 `{"detail":[...]}`——已被全局兜底。

## 3. 接口清单与当前状态

| 接口 | 方法 | 路径 | 鉴权 | 当前状态 |
|---|---|---|---|---|
| 健康检查 | GET | `/health` | 否 | ✅ 可用 |
| 标准法规翻译 | POST | `/openApi/translate/law` | 是 | ✅ 文本翻译可用；文档翻译暂未开放 |
| 术语库列表 | GET | `/openApi/terminology/list` | 是 | ✅ 可用 |
| 企标编写 | GET/POST | `/openApi/standard/write` | — | ⏳ 占位，返回 `code:404 接口尚未实现` |
| 培训PPT生成 | GET/POST | `/openApi/ppt/generate` | — | ⏳ 占位，返回 `code:404 接口尚未实现` |
| 术语提取 | GET/POST | `/openApi/terminology/extract` | — | ⏳ 占位，返回 `code:404 接口尚未实现` |

> 占位接口已上线，可提前做连通性/联调测试。

## 4. 标准法规翻译 `/openApi/translate/law`

### 请求字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `translateType` | string | 是 | **字符串** `"1"` 文本翻译 / `"2"` 文档翻译 |
| `languageType` | string | 是 | 语向，见枚举 |
| `originalText` | string | `"1"` 时必填 | 原文文本 |
| `terminologyList` | array | 是（可空数组）| 术语列表，字段必须存在 |
| `originalFile` / `originalFileBase64` | file/string | `"2"` 时 | 文档（multipart 或 base64，二选一）|

`terminologyList` 元素：`{ "originalTerminology": "外文术语", "translateTerminology": "指定中文译法" }`

**languageType 枚举**（未知取值 → `code:422` 并在 msg 列出全部枚举）：
`EN-CN`、`DE-CN`、`FR-CN`、`ES-CN`、`RU-CN`、`AR-CN`、`TH-CN`（均为「外文 → 中文」）。

### 术语行为
- 贵方传入的每条术语一律按**硬约束**处理，要求在译文中使用指定中文译法。
- 与我方本地术语库冲突时，**以贵方传入为准**。
- 译后做命中校验；未命中会记录告警，但**不做强制替换**（避免破坏中文语序）。

### 请求示例（translateType="1"）
```bash
curl -X POST http://<host>:8188/openApi/translate/law \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "translateType": "1",
    "languageType": "EN-CN",
    "originalText": "The approval authority shall notify the technical service before granting type approval.",
    "terminologyList": [
      {"originalTerminology": "type approval", "translateTerminology": "整车型式批准"},
      {"originalTerminology": "approval authority", "translateTerminology": "型式批准主管部门"}
    ]
  }'
```
成功响应：
```json
{ "code": 0, "msg": "ok", "data": { "translateText": "……中文译文……" } }
```

### 校验与限制
- `translateType="1"` 且 `originalText` 为空 → `code:422`。
- 单次 `originalText` 上限 **8000 字符**，超长 → `code:422`（本期不做自动切分）。
- 单条超时上限 **120 秒**。

### 响应时间（实测承诺值）
| 输入长度 | 典型耗时 |
|---|---|
| ~500 字符 | ~2.5s |
| ~4000 字符 | ~33s |
| ~8000 字符（上限）| ~44s |

即便满上限输入也约 45s 完成，留有充足余量。建议贵方客户端超时设 **≥120s**。
（并发已验证 5 路无损、无限流失败。）
- `translateType="2"`（文档翻译）：multipart 与 base64 两种上传通道均可连通与参数校验，但**本期返回** `code:404`，msg「文档翻译暂未开放，当前仅支持文本翻译」。可用于提前验证上传链路。

## 5. 术语库列表 `/openApi/terminology/list`

- 可选查询参数：`languageType`（按语向过滤）、`limit`（限制条数）。
- 默认返回**数组**，元素字段：`terminology`（中文）、`terminologyType`（语种类型，如 `EN-CN`）、`terminologyEn`（外文）、`terminologyRemark`（说明）。

```json
{ "code":0,"msg":"ok","data":[
  {"terminology":"车辆","terminologyType":"EN-CN","terminologyEn":"vehicle","terminologyRemark":"汽车法规通用术语"}
]}
```

## 6. 健康检查 `/health`（不鉴权）
```json
{ "code":0,"msg":"ok","data":{"status":"ok","backend":"dashscope","max_text_chars":8000,
  "supported_language_types":["EN-CN","DE-CN","FR-CN","ES-CN","RU-CN","AR-CN","TH-CN"]}}
```

## 7. 需贵方确认的开放问题

1. **各接口最终 URL 路径**：现用 `/openApi/translate/law` 等（我方可配置），是否按此定？
2. **文档上传通道**：`originalFile` 走 multipart 还是 base64？（两者均已支持，需统一约定）
3. **文档结果回传**：文档翻译开放后 `translateTextFileUrl` 的可访问域名、是否需公网、链接有效期？
4. **Token**：由我方签发；轮换周期与方式？
5. **术语库列表返回形态**：数组（当前默认）还是单对象？
6. **承诺值确认**：单次最大文本 8000 字符、单请求超时 120s，是否满足贵方场景？
7. **并发与频率**：贵方预期并发量与调用频率上限？（我方据此定限流）
8. **languageType 完整枚举**：当前 7 个语向是否覆盖贵方需求？是否需要 `中文→外文` 方向？
9. **外网可达**：`0.0.0.0:8188` 的对外 IP/域名、端口转发由贵方提供，请确认联调地址。
