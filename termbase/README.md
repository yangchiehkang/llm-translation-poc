# Termbase

本目录只保留当前实验闭环需要的术语库文件和 Markdown 说明文件。

## 当前版本

- `termbase_version = termbase_v1`
- 当前统一术语库：`auto_regulation_terms_v1.csv`
- 旧术语库文件和旧术语库说明不再随当前仓库保留；如需追溯，使用 Git 历史版本。
- 不在 `termbase/` 下新增复杂目录结构；说明文件只维护 Markdown 格式的本 `README.md`。

## 文件清单

| 文件 | 状态 | 说明 |
|---|---:|---|
| `auto_regulation_terms_v1.csv` | active | 本轮 baseline vs 分级 Prompt 实验统一使用的正式术语库。 |
| `README.md` | active | 术语库字段、使用规则、版本和统计说明。 |

## 字段规范

`auto_regulation_terms_v1.csv` 严格使用以下字段和顺序：

```text
term_id,source_lang,target_lang,source_term,target_term,domain,priority,alias,note,status
```

| 字段 | 要求 |
|---|---|
| `term_id` | 非空、唯一，格式为 `TERM_<SRC>_ZH_000001`，例如 `TERM_EN_ZH_000001`。 |
| `source_lang` | 源语言代码；当前为 `en`、`es`、`ru`、`de`、`fr`、`th`、`ar`。 |
| `target_lang` | 目标语言代码；本轮统一为 `zh`。 |
| `source_term` | 源语言术语、短语、标准名称、部件名称或法规关键表达；不放整句。 |
| `target_term` | 指定中文译法；非空。 |
| `domain` | 规范化领域标签，例如 `electric_vehicle`、`battery`、`safety`、`seat_belt`、`braking`、`lighting`、`emissions`、`waste_management`、`general_regulation`。 |
| `priority` | 只能为 `high`、`medium`、`low`。 |
| `alias` | 源术语别名、缩写、拼写变体或同义表达；多个 alias 用英文分号 `;` 分隔；不放中文目标译法同义词。 |
| `note` | 备注，可记录来源、适用范围或歧义说明。 |
| `status` | 只能为 `active`、`review`、`inactive`。 |

## 术语使用规则

| 条件 | 后续用途 | 是否计入硬 TCR |
|---|---|---:|
| `priority = high` 且 `status = active` | 作为 hard required terms，后续进入 `required_target_terms`。 | 是 |
| `priority = medium` 且 `status = active` | 作为 review / soft terms，可提示模型。 | 否 |
| `priority = low` 且 `status = active` | 作为 soft terms，仅辅助提示。 | 否 |
| `status = review` | 可保留在术语库中，后续可召回。 | 否 |
| `status = inactive` | 不参与后续术语召回。 | 否 |

说明：alias 只用于源术语匹配或人工诊断，不作为硬 TCR 的目标译法通过口径。

## v1 构建口径

- 以历史旧版术语库为迁移来源，清洗为 v1 字段、ID、领域标签、优先级和 alias 分隔格式。
- 补充了任务指定的关键英文术语，例如 `conductive connection`、`venting`、`approval marking`、`seat belt anchorage`、`3-D H machine`、`electromagnetic compatibility`、`waste hierarchy`、`end-of-waste status`、`test report`。
- 修复了历史旧版中泰语 `ไม่เกิน ๓,๕๐๐ กิโลกรัม` 因逗号导致的 CSV 字段错位。
- 泛化且容易过匹配的通用词被降为 `medium`，不默认进入 hard required terms。
- 本轮没有执行术语召回、翻译、TCR 校验、Qwen-Max 调用或 XCOMET 评分。

## 语言统计

| source_lang | 术语数 |
|---|---:|
| `en` | 285 |
| `es` | 289 |
| `ru` | 236 |
| `de` | 336 |
| `fr` | 321 |
| `th` | 290 |
| `ar` | 304 |
| **合计** | **2061** |

## 优先级与状态统计

| 字段 | 值 | 数量 |
|---|---|---:|
| `priority` | `high` | 930 |
| `priority` | `medium` | 1097 |
| `priority` | `low` | 34 |
| `status` | `active` | 2061 |
| `status` | `review` | 0 |
| `status` | `inactive` | 0 |

## 默认引用

默认配置应指向：

```text
termbase/auto_regulation_terms_v1.csv
```

