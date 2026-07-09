# LLM Translation POC

本仓库是面向广汽汽车标准法规场景的多语种翻译实验仓库，用于验证法规文本翻译、术语约束、术语一致性检查、XCOMET-DA/COMET 有参考评分，以及后续速度并发实验所需的关键能力。

当前仓库定位是 POC / 实验验证，不是最终生产系统。旧周报、历史版本结论和归档材料不在仓库内继续维护；如需追溯历史内容，以 GitHub 历史提交为准。

## 当前目标

- 多语种汽车标准法规文本翻译。
- 基于术语库的术语召回、Prompt 注入和译后 TCR 校验。
- 三组 Prompt 策略对比：无术语 baseline、不分层术语 baseline、分层 Prompt。
- TCR 闭环：失败拦截、定向 retry、重试后复核和失败术语分析。
- XCOMET 评价：DA/COMET 覆盖可信配对参考译文样本。
- 报告汇总：以 TCR 与 XCOMET 两类最终报告解释当前实验结论。

## 目录结构

```text
.
├── configs/        # 模型、语言和评分配置
├── data/           # 原始文档、评测样本和实验输入
├── docs/           # 当前阶段高层说明文档
├── outputs/        # 翻译、评估和最终报告产物
├── scripts/        # 预处理、翻译、术语、评估和工具脚本
└── termbase/       # 当前汽车标准法规术语库和说明
```

## 核心文档

| 文档 | 用途 |
|---|---|
| `docs/README.md` | 文档索引、边界和维护原则。 |
| `docs/requirements.md` | 标准法规翻译子模块需求、语种范围和验收目标。 |
| `docs/current_experiment_plan.md` | 本轮 Prompt 分级策略对比实验的目标、三组设计、样本范围和整体流程。 |
| `docs/closed_loop_pipeline.md` | 术语召回、三组翻译、TCR、retry、XCOMET-DA/COMET 和报告汇总闭环。 |
| `docs/evaluation_and_acceptance.md` | TCR、retry、XCOMET-DA/COMET 和质量风险解释口径。 |

`docs/` 不再维护按阶段编号拆开的执行手册；具体命令、脚本参数和运行细节以 `scripts/`、配置文件和实际产物为准。

## 主要产物

| 产物 | 用途 |
|---|---|
| `outputs/README.md` | 输出目录说明：翻译、TCR、XCOMET 和报告产物的默认位置。 |
| `outputs/reports/tcr_final_report.md` | TCR 首译、retry 后恢复率、最终 pass rate 和失败术语分析。 |
| `outputs/reports/xcomet_da_final_report.md` | 三组译文的 XCOMET-DA/COMET 评分对比。 |
| `outputs/reports/tcr_group_metrics.csv` | TCR 组间指标表。 |
| `outputs/reports/tcr_language_metrics.csv` | TCR 分语种指标表。 |
| `outputs/reports/xcomet_group_metrics.csv` | XCOMET 组间指标表。 |
| `outputs/reports/xcomet_language_metrics.csv` | XCOMET 分语种指标表。 |

## 配置文件

| 文件 | 用途 |
|---|---|
| `configs/README.md` | 配置目录说明和维护规则。 |
| `configs/languages.yaml` | 当前必做/待确认语种、优先级和质量阈值。 |
| `configs/translation.yaml` | 翻译模型、术语库、Prompt 路由、重试和输出字段配置。 |
| `configs/evaluation.yaml` | TCR、DA/COMET、速度、并发和报告字段配置。 |

## 主要数据

| 目录 | 说明 |
|---|---|
| `data/raw/` | 标准化原始法规文档和中文参考译文，按语种方向组织。 |
| `data/eval/splits/source_only_300_by_lang/` | 下一轮三组翻译和 TCR 使用的源文 split，不包含 `ref_text`。 |
| `data/eval/splits/reference_with_ref_300_by_lang/` | 与源文 split 一一对应的 DA/COMET 参考译文 split，包含 `ref_text`。 |
| `data/eval/splits/*/by_lang/` | 按语种拆分的源文或参考译文文件，便于抽样和人工检查。 |
| `outputs/translations/source_only_300_by_lang/first/` | 下一轮第一次翻译结果，生成前为空或不存在。 |
| `outputs/translations_retry/source_only_300_by_lang/` | 下一轮 retry 重新翻译结果，生成前为空或不存在。 |
| `outputs/evaluation/tcr*/source_only_300_by_lang/` | 下一轮 TCR 和 retry recheck 结果。 |

## 主要脚本

脚本按功能分类，运行位置和参数以脚本自身说明、`scripts/README.md` 和配置文件为准。

| 目录 | 说明 |
|---|---|
| `scripts/termbase/` | 术语召回、术语命中标注和 Prompt 模式预路由。 |
| `scripts/translation/` | 首译、retry 和翻译输入构造相关脚本。 |
| `scripts/evaluation/` | TCR 硬校验、retry recheck、XCOMET-DA/COMET 输入构造和评分汇总。 |
| `scripts/reporting/` | 多指标合并和阶段分析表生成。 |
| `scripts/common/` | JSONL/CSV 读写、语言映射、术语匹配和 Prompt 构造等共用逻辑。 |

## 术语库

当前核心术语文件位于 `termbase/`：

| 文件 | 说明 |
|---|---|
| `termbase/README.md` | 术语库保留范围、字段和使用原则。 |
| `termbase/auto_regulation_terms_v1.csv` | 当前统一术语库，版本为 `termbase_v1`。 |

术语相关实验需要明确区分：

- `strict`：对外验收口径，只看 required target term。
- `relaxed`：内部诊断口径，可参考 alias 和合理变体。
- `hard required terms`：进入硬 TCR 控制的核心术语。
- `soft/review terms`：用于辅助 Prompt 或人工复核，不直接包装成硬达标。

## 当前实验工作流

1. 从 raw 法规 PDF 和中文参考 PDF 构建源文 split 与配对参考译文 split。
2. 使用统一术语库召回 hard required terms 和 required target terms。
3. 对 `source_only_300_by_lang` 的同一批 source_text 生成三组翻译：`no_term_baseline`、`term_baseline`、`graded_prompt`。
4. 对首译结果做 TCR，生成 retry 样本池。
5. 对 TCR fail 样本做 retry，并复核 retry 后 TCR。
6. 使用 `reference_with_ref_300_by_lang` 补入 `ref_text`，对 first_pass 和 final 译文做 XCOMET-DA/COMET。
7. 汇总 TCR、retry、DA 和失败术语，形成最终报告。

## 文档维护原则

- `docs/` 保留高层说明，不保留逐步执行命令。
- 阶段结果必须注明是否已经在本仓库产出。
- 对外指标优先引用 `outputs/reports/` 的最终报告。
- 旧版本术语库、历史实验说明和临时运行记录需要追溯时使用 Git 历史。
