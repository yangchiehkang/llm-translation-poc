# 标准法规翻译 Prompt 分级策略对比实验说明

## 1. 实验目标

本轮实验要回答的问题是：在相同样本、相同模型、相同术语库和相同评价口径下，分级 Prompt 是否比不分层 Prompt 更适合汽车标准法规翻译。

重点观察两个方面：

1. TCR：分级 Prompt 是否提升硬术语一致率，并减少需要 retry 的样本。
2. XCOMET：分级 Prompt 在提升 TCR 的同时，是否保持或损害 QE / DA 自动质量分。

本轮实验不是生产系统验收，也不是全量文档翻译交付；它是围绕 Prompt 策略、术语硬控制和自动评价链路的阶段性验证。

## 2. 实验组设计

| 组名 | 设计含义 | 作用 |
|---|---|---|
| `no_term_baseline` | 无术语约束 baseline | 观察没有术语注入时的自然译文质量和术语缺失风险。 |
| `term_baseline` | 不分层术语 Prompt baseline | 所有样本使用统一法规翻译 Prompt，并注入同一批 required target terms。 |
| `graded_prompt` | 分层 Prompt 策略 | 根据样本特征路由到不同 Prompt 模式，例如结构保持、严格术语、普通法规语体等。 |

正式比较时，`term_baseline` 是主要 baseline，`graded_prompt` 是策略组；`no_term_baseline` 作为“没有术语约束”的参照组。

## 3. 样本范围

本轮实验使用从 raw 法规 PDF 和中文参考 PDF 重新构建的评测样本，并区分 QE 和 DA 的样本范围。

| split | 用途 | 样本数 | DA 范围 |
|---|---|---:|---:|
| `prompt_compare_200` | 多语种 Prompt 对比主样本 | 1156 | 77 |
| `da_eval_strict` | 严格对齐 DA 样本 | 531 | 531 |

说明：

- QE 不需要参考译文，因此覆盖 all_eval 范围。
- DA / COMET 需要可信参考译文，因此只覆盖严格对齐样本。
- `da_eval_strict` 的 DA 样本主要来自高置信 source/ref 对齐结果，不强行覆盖没有可靠参考译文的语种。

## 4. 整体实验流程

实验流程按一个闭环理解，而不是按零散步骤维护：

1. 从 raw 法规 PDF 和中文参考 PDF 构建源文样本与可信参考译文样本。
2. 使用统一术语库进行术语召回，生成 hard required terms 和 required target terms。
3. 对同一批 source_text 生成三组翻译输入：无术语 baseline、不分层术语 baseline、分层 Prompt。
4. 使用同一模型和参数完成三组首译。
5. 对首译结果做 TCR 硬校验，识别 failed terms 和需要 retry 的样本。
6. 只对 TCR fail 样本执行 retry 修复，并再次做 TCR recheck。
7. 对首译和 retry 后 final 译文分别做 XCOMET-QE 与 XCOMET-DA / COMET 评分。
8. 汇总 TCR、retry、QE、DA 和失败术语，形成最终报告。

## 5. 当前已完成产物

当前重点产物已经按 TCR 和 XCOMET 两类整理：

| 类别 | 产物 |
|---|---|
| 第一次翻译结果 | `data/eval/splits/*/translations/first/` |
| retry 重新翻译结果 | `data/eval/splits/*/translations/retry/` |
| 最终译文 | `data/eval/splits/*/translations/final/` |
| retry 输入 | `data/eval/splits/*/retry_inputs/` |
| TCR 报告 | `outputs/reports/tcr_final_report.md` |
| XCOMET 报告 | `outputs/reports/xcomet_qe_da_final_report.md` |
| TCR 指标表 | `outputs/reports/tcr_group_metrics.csv` |
| XCOMET 指标表 | `outputs/reports/xcomet_group_metrics.csv` |
| TCR 分语种指标表 | `outputs/reports/tcr_language_metrics.csv` |
| XCOMET 分语种指标表 | `outputs/reports/xcomet_language_metrics.csv` |

这些报告覆盖三组译文、两个 split、首译和 retry 后 final 阶段。

## 6. 当前阶段结论口径

从现有结果看，可以形成以下阶段性判断：

- 术语约束本身显著提升 TCR：`term_baseline` 明显优于 `no_term_baseline`。
- 分层 Prompt 相比不分层术语 Prompt 继续带来小幅 TCR 增益，并减少 retry 需求。
- XCOMET 平均分没有稳定偏向分层 Prompt；无术语 baseline 往往更高，但术语一致性明显不足。
- retry 能显著提高最终 TCR，但可能带来少量 QE / DA 平均分下降。
- 因此当前最稳妥的结论是：分层 Prompt 的主要价值在硬术语一致性和 retry 需求控制，而不是自动质量分的显著提升。

## 7. 后续待补充

当前报告已经覆盖 TCR 与 XCOMET-QE/DA 两个核心方面。若继续扩展，建议补充：

- 数字、单位、编号和格式保持率的独立统计。
- 分 Prompt 模式的更细粒度图表。
- 对 high-risk failed terms 的人工复核和术语库修订建议。
- 对 retry 后自然度下降样本的人工抽检。
