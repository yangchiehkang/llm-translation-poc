# 法规翻译实验闭环流程

## 1. 闭环目标

本项目的核心不是单次翻译，而是建立一个可以持续改进的法规翻译质量闭环：先用术语库和 Prompt 控制译前风险，再用 TCR 和 XCOMET 发现译后问题，最后把失败样本回流到术语库、Prompt 策略和 retry 规则中。

## 2. 闭环主线

当前实验闭环可以概括为：

| 环节 | 作用 | 主要关注点 |
|---|---|---|
| 样本构建 | 从法规 PDF 形成 source_text，并筛出可用于 DA 的 ref_text | 样本完整性、对齐可信度、语种覆盖 |
| 术语召回 | 找出源文中需要约束的高优先级术语 | hard required terms、required target terms |
| 三组翻译 | 对同一批样本生成 no-term、term baseline、graded prompt 三组译文 | 控制变量一致，避免样本或模型差异影响结论 |
| 首译 TCR | 检查指定术语译法是否出现在译文中 | pass、fail、no_terms、failed_terms |
| retry 修复 | 只对 TCR fail 样本做局部修复 | 修复率、残余失败术语、是否引入副作用 |
| XCOMET 评分 | 分别评估 QE 和 DA / COMET 质量分 | QE 覆盖 all_eval，DA 只覆盖可信参考译文样本 |
| 报告汇总 | 合并 TCR、retry、QE、DA 和错误类型 | 判断分层 Prompt 的收益与代价 |
| 错误回流 | 将高频失败项反馈给术语库和 Prompt 策略 | 高频术语、错误类型、人工复核优先级 |

## 3. 术语控制逻辑

术语控制分为三个层次：

| 层次 | 说明 |
|---|---|
| 硬术语 | `priority=high` 且 `status=active` 的术语，进入 strict TCR。 |
| 辅助术语 | 中低优先级或 review 术语，可用于 Prompt 辅助，但不作为硬通过条件。 |
| 诊断信息 | alias、宽泛术语和疑似误召回项用于错误分析，不直接包装成验收达标。 |

本轮实验的 TCR 只围绕硬术语计算，避免通过放宽 alias 或 relaxed 口径虚高指标。

## 4. Prompt 策略逻辑

本轮实验不是比较“有没有术语”，而是同时保留三个参照层次：

- `no_term_baseline`：观察没有术语约束时的自然质量和术语风险。
- `term_baseline`：观察统一术语 Prompt 对 TCR 的基础提升。
- `graded_prompt`：观察分层 Prompt 是否在统一术语 Prompt 基础上继续改善 TCR、减少 retry 或保护质量分。

分层 Prompt 的核心思想是让不同风险类型的样本使用不同约束强度：结构样本优先保格式，硬术语样本优先保 TCR，普通法规句兼顾准确性和自然度。

## 5. TCR 与 retry 的关系

TCR 是硬门禁，retry 是补救机制。

- 首译 TCR 用于判断 Prompt 策略本身的术语控制能力。
- retry_needed_count 用于判断某个策略给后续修复带来的负担。
- retry_recovery_rate 用于判断局部修复是否有效。
- final pass rate 用于判断完整闭环能达到什么术语一致性水平。

如果一个策略首译 TCR 更高、retry 需求更少、final pass rate 不低于 baseline，则说明它对术语一致性有工程价值。

## 6. XCOMET 与 TCR 的关系

XCOMET-QE 和 XCOMET-DA / COMET 用来观察整体译文质量，但不能替代 TCR。

常见判断方式：

| 现象 | 解释 |
|---|---|
| TCR 上升，XCOMET 稳定 | 理想情况，说明术语控制没有明显伤害整体质量。 |
| TCR 上升，XCOMET 下降 | 可能说明 Prompt 或 retry 约束过强，需要人工抽检。 |
| TCR 下降，XCOMET 上升 | 译文可能更自然，但不满足法规术语要求。 |
| TCR 与 XCOMET 都下降 | 策略失败，应回到 Prompt、术语库或样本问题排查。 |

本轮现有结果显示：分层 Prompt 的 TCR 有小幅收益，但 XCOMET 未稳定提升，因此结论应明确写成“术语硬一致性收益”，而不是“整体自动质量显著提升”。

## 7. 报告使用方式

当前对外或组内汇报时，优先使用：

- `outputs/reports/tcr_final_report.md`
- `outputs/reports/xcomet_qe_da_final_report.md`

`docs/` 负责解释实验逻辑和指标口径，`outputs/reports/` 负责承载本轮具体数值结论。
