# Scripts

脚本目录按功能分类，不再按本地/服务器分类。运行位置写在本说明和各脚本开头注释里。

## 目录结构

| 目录 | 功能 | 运行位置 |
|---|---|---|
| `common/` | JSONL/CSV 读写、语言映射、术语匹配、Prompt 构造、DashScope 调用等共用逻辑。 | 本地和服务器共用 |
| `termbase/` | 术语召回、术语命中标注、Prompt 模式预路由。 | 本地 |
| `translation/` | 首译、retry 翻译、API/本地模型翻译入口。 | API/本地模型翻译在服务器；输入池整理在本地 |
| `evaluation/` | TCR、DA 输入准备、XCOMET 输入构建、XCOMET-QE/DA 评分和汇总。 | TCR/输入准备/汇总在本地；XCOMET 评分在服务器 |
| `reporting/` | 合并 TCR、QE、DA、重试状态等指标，生成统一分析表。 | 本地 |

## 规范入口

| 脚本 | 功能 | 运行位置 |
|---|---|---|
| `termbase/term_recall.py` | 对评测样本做术语召回，生成 `matched_terms`、`required_target_terms` 和 `prompt_mode`。 | 本地 |
| `translation/run_prompt_compare_first_local_npu.py` | 使用服务器本地 Qwen 类模型跑 prompt_compare/DA 首译。 | 服务器 |
| `translation/run_prompt_compare_first.py` | 使用 DashScope/Qwen-Max 跑 prompt_compare 首译；DashScope 重试逻辑复用 `common/dashscope_client.py`。 | 服务器 |
| `translation/retry_translate_local.py` | 使用服务器本地 Transformers 模型跑 TCR retry 翻译。 | 服务器 |
| `evaluation/tcr_check.py` | 规范 TCR 入口；支持首译 TCR、retry 输入生成和 retry 后 recheck。 | 本地 |
| `evaluation/build_xcomet_inputs.py` | 从首译/final/retry 结果生成标准 XCOMET-QE 和 XCOMET-DA 输入。 | 本地 |
| `evaluation/run_xcomet.py` | 规范 XCOMET-QE 和 XCOMET-DA/COMET 评分入口；支持本地 checkpoint、resume、dry-run。 | 服务器 |
| `evaluation/summarize_xcomet.py` | 汇总 XCOMET 评分 JSONL，生成 Markdown/JSON 汇总。 | 本地 |
| `reporting/merge_metrics.py` | 合并多份指标文件，输出统一 JSONL 或 CSV。 | 本地 |

## 兼容入口和已合并重复

| 旧/辅助入口 | 当前处理 | 说明 |
|---|---|---|
| `evaluation/xcomet_score.py` | 已收敛为兼容 wrapper，直接委托 `evaluation/run_xcomet.py`。 | 保留旧命令不报错，新流程统一用 `run_xcomet.py`。 |
| `evaluation/check_tcr.py` | 保留为单文件 TCR 诊断脚本。 | 批量流程、retry 输入和 retry recheck 统一用 `evaluation/tcr_check.py`。 |
| `translation/qwenmax_translate.py` | 保留为通用 Qwen-Max 翻译入口。 | 与 `run_prompt_compare_first.py` 共用 `common/dashscope_client.py`，避免重复维护 DashScope 解析/重试逻辑。 |
| `translation/build_retry_pool.py` | 保留为通用 retry 样本池构建器。 | `evaluation/tcr_check.py` 的首译模式已能直接生成当前实验的 retry 输入。 |

## 推荐流程

1. 本地运行 `termbase/term_recall.py`，准备术语召回和 Prompt 路由字段。
2. 服务器运行 `translation/run_prompt_compare_first_local_npu.py` 或 `translation/run_prompt_compare_first.py`，生成首译。
3. 本地运行 `evaluation/tcr_check.py --mode first_pass`，执行 TCR 并生成 retry 输入。
4. 服务器运行 `translation/retry_translate_local.py`，生成 retry 译文。
5. 本地运行 `evaluation/tcr_check.py --mode retry_recheck`，验证 retry 后 TCR 恢复情况。
6. 本地运行 `evaluation/build_xcomet_inputs.py`，生成 QE/DA 评分输入。
7. 服务器运行 `evaluation/run_xcomet.py`，生成 XCOMET-QE 或 XCOMET-DA/COMET 分数。
8. 本地运行 `evaluation/summarize_xcomet.py` 和 `reporting/merge_metrics.py`，汇总阶段分析表。

## 运行边界

- Qwen-Max/DashScope 翻译和本地模型翻译在服务器上运行。
- XCOMET-QE 和 XCOMET-DA/COMET 评分在服务器上运行。
- 术语召回、TCR、重试池、DA/XCOMET 输入准备和指标合并都在本地运行。
- 不要把 API Key、服务器模型路径或临时输出写死到脚本里；使用环境变量和命令行参数传入。
