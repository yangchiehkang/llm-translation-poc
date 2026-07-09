# 项目文档索引

`docs/` 只保留当前实验和对外汇报需要持续维护的高层说明，不再维护按阶段编号拆开的执行手册、服务器同步命令、脚本参数说明或临时运行记录。具体实现细节以 `scripts/`、配置文件和实际输出产物为准。

## 当前文档

| 文档 | 用途 |
|---|---|
| `requirements.md` | 说明标准法规翻译子模块的业务定位、语种范围、核心能力和验收目标。 |
| `current_experiment_plan.md` | 说明新 300-by-language split 上的 Prompt 分级策略对比实验目标、样本范围、整体流程和当前状态。 |
| `closed_loop_pipeline.md` | 说明术语召回、三组翻译、TCR、retry、XCOMET-DA/COMET 和报告汇总之间的闭环关系。 |
| `evaluation_and_acceptance.md` | 说明 TCR、XCOMET-DA/COMET、retry 效果和质量风险的统一解释口径。 |

## 文档边界

- 不在 `docs/` 下维护按阶段编号拆开的逐步执行文档。
- 不在高层文档中保存服务器同步、测试运行、脚本参数等实现命令。
- 不把日志、缓存、临时检查结果写成长期文档。
- 最终实验结果优先放在 `outputs/reports/`，文档只说明如何理解这些结果。
- 阶段结论必须区分“已经在本仓库产出”和“后续待补充”。

## 下一轮结果产物

新 split 重新跑通后，主要产物应位于：

| 产物 | 用途 |
|---|---|
| `outputs/translations/source_only_300_by_lang/first/` | 第一次翻译结果。 |
| `outputs/translations_retry/source_only_300_by_lang/` | retry 重新翻译结果。 |
| `outputs/evaluation/tcr/source_only_300_by_lang/` | 首译 TCR 和 retry 输入统计。 |
| `outputs/evaluation/tcr_retry/source_only_300_by_lang/` | retry 后 TCR recheck。 |
| `outputs/reports/tcr_final_report.md` | TCR 首译、retry 后恢复率、最终 pass rate 和失败术语分析。 |
| `outputs/reports/xcomet_da_final_report.md` | 三组译文的 XCOMET-DA/COMET 评分对比。 |
| `outputs/reports/tcr_group_metrics.csv` | TCR 组间指标表，便于后续合并或制图。 |
| `outputs/reports/tcr_language_metrics.csv` | TCR 分语种指标表，便于后续按语种分析。 |
| `outputs/reports/xcomet_group_metrics.csv` | XCOMET 组间指标表，便于后续合并或制图。 |
| `outputs/reports/xcomet_language_metrics.csv` | XCOMET 分语种指标表，便于后续按语种分析。 |

## 维护原则

- 一个主题优先合并进现有文档，避免继续新增碎片化说明。
- 实验流程写成可读的整体链路，不写成命令清单。
- 对外汇报优先引用 `outputs/reports/` 的最终报告，而不是中间 JSONL 或日志。
- 如需复现实验，先看 `scripts/README.md` 和配置文件，再查具体脚本。
