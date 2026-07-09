# 新 300-by-language 参考样本实验说明

## 1. 实验目标

下一轮实验要在新整理的数据上重新验证同一套闭环：

1. 三组首译：`no_term_baseline`、`term_baseline`、`graded_prompt`。
2. 首译 TCR：比较硬术语一致性和 retry 需求。
3. TCR fail 样本 retry：只修复失败术语，不重写整个实验。
4. retry 后 TCR recheck：验证 recovered / still_fail。
5. XCOMET-DA / COMET：用配对参考译文评价 first_pass 和 final 译文。

本轮比较仍然回答同一个核心问题：分层 Prompt 是否在不明显损害有参考质量分的前提下，提升法规硬术语一致性并减少 retry 成本。

## 2. 实验组设计

| 组名 | 设计含义 | 作用 |
|---|---|---|
| `no_term_baseline` | 无术语约束 baseline | 观察没有术语注入时的自然译文质量和术语缺失风险。 |
| `term_baseline` | 不分层术语 Prompt baseline | 所有样本使用统一法规翻译 Prompt，并注入同一批 required target terms。 |
| `graded_prompt` | 分层 Prompt 策略 | 根据样本特征路由到不同 Prompt 模式，例如结构保持、严格术语、普通法规语体等。 |

正式比较时，`term_baseline` 是主要 baseline，`graded_prompt` 是策略组；`no_term_baseline` 只作为无术语约束参照。

## 3. 当前样本范围

本轮只保留原始法规文件和两套新 split：

| split | 用途 | 主文件 | ref_text |
|---|---|---|---|
| `source_only_300_by_lang` | 三组翻译、首译 TCR、retry 输入来源 | `all_samples_source_only.jsonl` | 不包含 |
| `reference_with_ref_300_by_lang` | DA/COMET 参考译文来源 | `all_samples_with_reference.jsonl` | 包含 |

两套 split 的行顺序和样本键保持一一对应，匹配键为 `sample_id`、`da_reference_id`、`source_text`。后续翻译只能使用 `source_only_300_by_lang`，跑分时再用 `reference_with_ref_300_by_lang` 补入 `ref_text`。

当前可用样本数：

| language_pair | rows |
|---|---:|
| `ar-zh` | 89 |
| `de-zh` | 300 |
| `en-zh` | 300 |
| `es-zh` | 67 |
| `fr-zh` | 300 |
| `ru-zh` | 292 |
| `th-zh` | 300 |
| total | 1648 |

说明：目标是每语种最多 300 条；如果某语种可信参考译文不足 300 条，则保留当前可用的全部配对样本，不补无参考样本。

## 4. 下一轮流程

按闭环顺序执行，但本次适配只准备脚本和文档，不启动真实翻译或评分：

1. 用 `source_only_300_by_lang/all_samples_source_only.jsonl` 生成三组 Prompt 实验输入，默认放到 `outputs/experiment_inputs/source_only_300_by_lang/`。
2. 对三组输入分别跑首译，输出到 `outputs/translations/source_only_300_by_lang/first/`。
3. 对首译输出执行 TCR，输出到 `outputs/evaluation/tcr/source_only_300_by_lang/`，并生成 `outputs/retry_inputs/source_only_300_by_lang/`。
4. 对 retry 输入执行重新翻译，输出到 `outputs/translations_retry/source_only_300_by_lang/`。
5. 用首译 TCR 和 retry 译文做 retry recheck，输出到 `outputs/evaluation/tcr_retry/source_only_300_by_lang/`。
6. 用 `reference_with_ref_300_by_lang/all_samples_with_reference.jsonl` 为同一批样本补入 `ref_text`，构建 XCOMET-DA / COMET 输入。
7. 对 first_pass 和 final 两个阶段跑 XCOMET-DA / COMET，并汇总三组结果。

## 5. 关键约束

- 三组翻译必须使用同一批 `sample_id` 和同一顺序，避免样本差异影响结论。
- TCR 只统计 `priority=high` 且 `status=active` 的硬术语。
- retry 只处理首译 `tcr_status=fail` 的样本。
- DA/COMET 只能使用有 `ref_text` 且 `use_for_da=true` 的配对样本。
- 源文 split 不应混入 `ref_text`，避免参考译文泄漏到翻译阶段。

## 6. 当前阶段状态

当前阶段是“小适配”：

- 已将脚本默认 split 指向 `source_only_300_by_lang`。
- 已将 DA/COMET 参考 split 指向 `reference_with_ref_300_by_lang`。
- 已更新文档说明新 split、样本数和下一轮流程。
- 尚未生成新的 Prompt 输入、首译、TCR、retry、XCOMET 或报告。
