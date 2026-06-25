# LLM Translation POC

本项目是面向汽车标准法规场景的多语种翻译实验仓库，主要用于验证法规文本的机器翻译、术语约束翻译、术语一致性检查和自动质量评估流程。

项目主要围绕以下能力展开：

- 多语种法规样本管理；
- 多语种到中文的机器翻译；
- 基于汽车法规术语库的术语约束翻译；
- 普通翻译与术语约束翻译结果对比；
- XCOMET-QE 自动质量评分；
- 术语一致率 TCR 统计；
- Prompt 实验与低分样本分析；
- 翻译速度、并发与本地模型相关实验准备。

本仓库为实验验证仓库，不是最终生产系统。

---

## 1. 根目录结构

```text
LLM-TRANSLATION-POC/
├── .gitignore
├── fusion_result.json
├── README.md
├── .vscode/
├── configs/
├── data/
├── docs/
├── notes/
├── outputs/
├── scripts/
└── termbase/

```

---

## 2. 根目录文件说明

| 文件 / 目录 | 说明 |
|---|---|
| `.gitignore` | Git 忽略文件配置，用于排除缓存、环境文件、临时输出等不需要提交的内容 |
| `fusion_result.json` | 实验过程中生成的融合结果文件，用于保存某次实验的合并输出或中间结果 |
| `README.md` | 项目说明文件 |
| `.vscode/` | VS Code 本地开发配置目录 |
| `configs/` | 项目配置文件目录 |
| `data/` | 实验数据目录，包含评测样本、翻译结果和分析报告 |
| `docs/` | 项目文档目录，存放 Prompt、方案说明和实验设计文档 |
| `notes/` | 实验记录、日报、周报和阶段性笔记目录 |
| `outputs/` | 脚本运行产生的临时输出目录 |
| `scripts/` | 项目脚本目录，包含预处理、翻译、评分、术语处理等脚本 |
| `termbase/` | 汽车标准法规术语库及术语候选文件目录 |

---

## 3. `.vscode/`

```text
.vscode/
└── sftp.json
```

| 文件 | 说明 |
|---|---|
| `sftp.json` | VS Code SFTP 插件配置文件，用于本地与远程服务器之间同步代码或文件 |

---

## 4. `configs/`

```text
configs/
├── languages.yaml
├── qwen_max.yaml
└── xcomet_xl_qe_npu.yaml
```

| 文件 | 说明 |
|---|---|
| `languages.yaml` | 语种配置文件，记录项目支持的源语言、目标语言及相关语言映射信息 |
| `qwen_max.yaml` | Qwen-Max 翻译模型调用配置文件 |
| `xcomet_xl_qe_npu.yaml` | XCOMET-XL / XCOMET-QE 在 NPU 环境下的评分配置文件 |

---

## 5. `data/`

`data/` 是项目的主要实验数据目录，包含评测样本、模型翻译结果和评分报告。

```text
data/
├── eval/
├── mt/
└── report/
```

---

### 5.1 `data/eval/`

```text
data/eval/
├── ar.jsonl
├── de.jsonl
├── en.jsonl
├── es.jsonl
├── fr.jsonl
├── id.jsonl
├── it.jsonl
├── ms.jsonl
├── nl.jsonl
├── no.jsonl
├── pt.jsonl
├── ru.jsonl
├── sv.jsonl
├── th.jsonl
└── vi.jsonl
```

该目录存放多语种法规评测样本，每个文件对应一个源语言。

| 文件 | 说明 |
|---|---|
| `ar.jsonl` | 阿拉伯语法规评测样本 |
| `de.jsonl` | 德语法规评测样本 |
| `en.jsonl` | 英语法规评测样本 |
| `es.jsonl` | 西班牙语法规评测样本 |
| `fr.jsonl` | 法语法规评测样本 |
| `id.jsonl` | 印尼语法规评测样本 |
| `it.jsonl` | 意大利语法规评测样本 |
| `ms.jsonl` | 马来语法规评测样本 |
| `nl.jsonl` | 荷兰语法规评测样本 |
| `no.jsonl` | 挪威语法规评测样本 |
| `pt.jsonl` | 葡萄牙语法规评测样本 |
| `ru.jsonl` | 俄语法规评测样本 |
| `sv.jsonl` | 瑞典语法规评测样本 |
| `th.jsonl` | 泰语法规评测样本 |
| `vi.jsonl` | 越南语法规评测样本 |

---

### 5.2 `data/mt/`

```text
data/mt/
├── qwen-max/
└── qwen-max-term/
```

该目录存放机器翻译结果。

| 子目录 | 说明 |
|---|---|
| `qwen-max/` | Qwen-Max 普通翻译结果 |
| `qwen-max-term/` | Qwen-Max 术语约束 Prompt 翻译结果 |

---

#### 5.2.1 `data/mt/qwen-max/`

```text
data/mt/qwen-max/
├── mt_ar._qwen-max.jsonl
├── mt_de._qwen-max.jsonl
├── mt_en._qwen-max.jsonl
├── mt_es._qwen-max.jsonl
├── mt_fr._qwen-max.jsonl
├── mt_id._qwen-max.jsonl
├── mt_it._qwen-max.jsonl
├── mt_ms._qwen-max.jsonl
├── mt_nl._qwen-max.jsonl
├── mt_no._qwen-max.jsonl
├── mt_pt._qwen-max.jsonl
├── mt_ru._qwen-max.jsonl
├── mt_sv._qwen-max.jsonl
├── mt_th._qwen-max.jsonl
└── mt_vi._qwen-max.jsonl
```

这些文件为各语种调用 Qwen-Max 后生成的普通翻译结果。

文件命名规则：

```text
mt_{source_lang}._qwen-max.jsonl
```

例如：

| 文件 | 说明 |
|---|---|
| `mt_en._qwen-max.jsonl` | 英语到中文的 Qwen-Max 普通翻译结果 |
| `mt_de._qwen-max.jsonl` | 德语到中文的 Qwen-Max 普通翻译结果 |
| `mt_fr._qwen-max.jsonl` | 法语到中文的 Qwen-Max 普通翻译结果 |
| `mt_ru._qwen-max.jsonl` | 俄语到中文的 Qwen-Max 普通翻译结果 |
| `mt_ar._qwen-max.jsonl` | 阿拉伯语到中文的 Qwen-Max 普通翻译结果 |

---

#### 5.2.2 `data/mt/qwen-max-term/`

```text
data/mt/qwen-max-term/
├── mt_ar._qwen-max.jsonl
├── mt_de._qwen-max.jsonl
├── mt_en._qwen-max.jsonl
├── mt_es._qwen-max.jsonl
├── mt_fr._qwen-max.jsonl
├── mt_id._qwen-max.jsonl
├── mt_it._qwen-max.jsonl
├── mt_ms._qwen-max.jsonl
├── mt_nl._qwen-max.jsonl
├── mt_no._qwen-max.jsonl
├── mt_pt._qwen-max.jsonl
├── mt_ru._qwen-max.jsonl
├── mt_sv._qwen-max.jsonl
├── mt_th._qwen-max.jsonl
└── mt_vi._qwen-max.jsonl
```

这些文件为各语种调用 Qwen-Max 后生成的术语约束翻译结果。

该目录中的译文通常会在 Prompt 中注入术语库命中的术语，用于测试术语约束对译文质量和术语一致率的影响。

---

### 5.3 `data/report/`

```text
data/report/
├── termbase/
├── xcomet-xxl-qe/
└── xcomet-xxl-qwenmax/
```

该目录存放术语库检查、XCOMET 评分和翻译结果对比分析报告。

---

#### 5.3.1 `data/report/termbase/`

```text
data/report/termbase/
└── termbase_v0.2_validation.xlsx
```

| 文件 | 说明 |
|---|---|
| `termbase_v0.2_validation.xlsx` | 术语库 v0.2 校验报告，用于检查术语库字段、内容和可用性 |

---

#### 5.3.2 `data/report/xcomet-xxl-qe/`

```text
data/report/xcomet-xxl-qe/
├── compare/
└── term-prompt/
```

该目录存放 XCOMET-XXL-QE 相关评分结果和分析文件。

---

##### `data/report/xcomet-xxl-qe/compare/`

```text
data/report/xcomet-xxl-qe/compare/
├── low_score_base_vs_term_acceptance_analysis.xlsx
└── qwenmax_base_vs_term_summary.xlsx
```

| 文件 | 说明 |
|---|---|
| `low_score_base_vs_term_acceptance_analysis.xlsx` | 普通翻译与术语约束翻译的低分样本对比分析 |
| `qwenmax_base_vs_term_summary.xlsx` | Qwen-Max 普通翻译与术语约束翻译的整体对比汇总 |

---

##### `data/report/xcomet-xxl-qe/term-prompt/`

```text
data/report/xcomet-xxl-qe/term-prompt/
├── qwen_max_term_prompt_analysis_summary.xlsx
├── qwen_max_term_prompt_xcomet_xxl_qe.xlsx
├── failed_rows/
└── metadata/
```

| 文件 / 目录 | 说明 |
|---|---|
| `qwen_max_term_prompt_analysis_summary.xlsx` | 术语 Prompt 翻译结果的评分分析汇总 |
| `qwen_max_term_prompt_xcomet_xxl_qe.xlsx` | 术语 Prompt 翻译结果的 XCOMET-XXL-QE 评分明细 |
| `failed_rows/` | 评分或处理失败样本目录 |
| `metadata/` | 有效评分样本的元数据目录 |

---

###### `data/report/xcomet-xxl-qe/term-prompt/failed_rows/`

```text
failed_rows/
└── qwen_max_term_prompt_failed_rows.xlsx
```

| 文件 | 说明 |
|---|---|
| `qwen_max_term_prompt_failed_rows.xlsx` | 术语 Prompt 评分过程中失败或异常的样本记录 |

---

###### `data/report/xcomet-xxl-qe/term-prompt/metadata/`

```text
metadata/
└── qwen_max_term_prompt_valid_rows_metadata.xlsx
```

| 文件 | 说明 |
|---|---|
| `qwen_max_term_prompt_valid_rows_metadata.xlsx` | 成功进入评分流程的术语 Prompt 样本元信息 |

---

#### 5.3.3 `data/report/xcomet-xxl-qwenmax/`

```text
data/report/xcomet-xxl-qwenmax/
└── qwen-max_xcomet-xxl-qe.xlsx
```

| 文件 | 说明 |
|---|---|
| `qwen-max_xcomet-xxl-qe.xlsx` | Qwen-Max 普通翻译结果的 XCOMET-XXL-QE 评分报告 |

---

## 6. `docs/`

```text
docs/
├── local_model_poc_plan.md
├── prompt_term_v1.md
├── prompt_v3_term_strategy.md
├── tcr_v0.2_conclusion.md
├── tcr_v0.3_conclusion.md
└── translation_speed_optimization_plan.md
```

该目录存放项目说明文档、Prompt 设计文档和实验方案文档。

| 文件 | 说明 |
|---|---|
| `local_model_poc_plan.md` | 本地模型 POC 方案文档，用于说明本地模型测试目标、候选模型和评估指标 |
| `prompt_term_v1.md` | 术语约束 Prompt V1 文档，记录早期术语注入 Prompt 设计 |
| `prompt_v3_term_strategy.md` | Prompt V3 术语策略文档，记录术语分层、Prompt 规则和翻译策略 |
| `tcr_v0.2_conclusion.md` | TCR V0.2 统计结论文档 |
| `tcr_v0.3_conclusion.md` | TCR V0.3 统计结论文档 |
| `translation_speed_optimization_plan.md` | 翻译速度优化方案文档，记录并发、缓存和吞吐优化思路 |

---

## 7. `notes/`

```text
notes/
├── 2026-06-03_xcomet-xl-npu-adaptation-daily.md
├── 2026-06-12_termbase-v0.1-and-term-prompt-evaluation-weekly.md
├── 2026-06-13_termbase-v0.2-change-log.md
├── 2026-06-22_api-concurrency-cache-plan.md
├── 2026-06-22_core-term-acceptance-scope.md
├── 2026-06-22_local-model-poc-design.md
├── 2026-06-22_prompt-v3-term-rules.md
└── 2026-06-22_termbase-v0.3-todo.md
```

该目录存放阶段性实验记录、问题记录、方案草稿和周报材料。

| 文件 | 说明 |
|---|---|
| `2026-06-03_xcomet-xl-npu-adaptation-daily.md` | XCOMET-XL 在 NPU 环境下适配的实验记录 |
| `2026-06-12_termbase-v0.1-and-term-prompt-evaluation-weekly.md` | 术语库 v0.1 与术语 Prompt 评估周报 |
| `2026-06-13_termbase-v0.2-change-log.md` | 术语库 v0.2 变更记录 |
| `2026-06-22_api-concurrency-cache-plan.md` | API 并发与缓存方案记录 |
| `2026-06-22_core-term-acceptance-scope.md` | 核心术语验收范围说明 |
| `2026-06-22_local-model-poc-design.md` | 本地模型 POC 设计记录 |
| `2026-06-22_prompt-v3-term-rules.md` | Prompt V3 术语规则记录 |
| `2026-06-22_termbase-v0.3-todo.md` | 术语库 V0.3 待处理事项和候选修改记录 |

---

## 8. `outputs/`

```text
outputs/
├── translation_concurrent_poc_cache.jsonl
├── translation_concurrent_poc_request_log.csv
├── translation_concurrent_poc_results.csv
└── translation_concurrent_poc_summary.json
```

该目录存放脚本运行生成的临时输出文件和 POC 实验结果。

| 文件 | 说明 |
|---|---|
| `translation_concurrent_poc_cache.jsonl` | 并发翻译 POC 的缓存文件 |
| `translation_concurrent_poc_request_log.csv` | 并发翻译 POC 的请求日志 |
| `translation_concurrent_poc_results.csv` | 并发翻译 POC 的结果明细 |
| `translation_concurrent_poc_summary.json` | 并发翻译 POC 的结果汇总 |

---

## 9. `scripts/`

```text
scripts/
├── docs/
├── evaluation/
├── mt/
├── preprocess/
├── termbase/
└── utils/
```

`scripts/` 是项目脚本目录，包含数据预处理、机器翻译、质量评估、术语库处理和通用工具脚本。

---

### 9.1 `scripts/docs/`

```text
scripts/docs/
└── termbase_schema.md
```

| 文件 | 说明 |
|---|---|
| `termbase_schema.md` | 术语库字段结构说明文档 |

---

### 9.2 `scripts/evaluation/`

```text
scripts/evaluation/
├── run_xcomet_xxl_score.py
├── run_xcomet_xxl_score_term_prompt.py
├── run_xcomet_xxl_score_term_prompt_parallel.py
├── score_qwen_max_qe.py
├── summarize_qwenmax_term_vs_base.py
└── test_xcomet_transfer_to_npu.py
```

该目录存放质量评分和评分结果分析脚本。

| 文件 | 说明 |
|---|---|
| `run_xcomet_xxl_score.py` | 对普通翻译结果运行 XCOMET-XXL-QE 评分 |
| `run_xcomet_xxl_score_term_prompt.py` | 对术语 Prompt 翻译结果运行 XCOMET-XXL-QE 评分 |
| `run_xcomet_xxl_score_term_prompt_parallel.py` | 并行执行术语 Prompt 翻译结果的 XCOMET-XXL-QE 评分 |
| `score_qwen_max_qe.py` | 对 Qwen-Max 翻译结果进行 QE 评分的脚本 |
| `summarize_qwenmax_term_vs_base.py` | 汇总普通翻译和术语约束翻译的对比结果 |
| `test_xcomet_transfer_to_npu.py` | 测试 XCOMET 模型迁移或运行到 NPU 环境的脚本 |

---

### 9.3 `scripts/mt/`

```text
scripts/mt/
├── mt_dashscope_qwenmax.py
├── mt_dashscope_qwenmax.py.bak_20260607_140823
├── mt_local_madlad400.py
├── translate_concurrent_poc.py
└── translate_local_qwen_fast.py
```

该目录存放机器翻译相关脚本。

| 文件 | 说明 |
|---|---|
| `mt_dashscope_qwenmax.py` | 调用 DashScope / Qwen-Max 进行机器翻译的主脚本 |
| `mt_dashscope_qwenmax.py.bak_20260607_140823` | Qwen-Max 翻译脚本的历史备份文件 |
| `mt_local_madlad400.py` | 调用本地 MADLAD400 模型进行翻译的脚本 |
| `translate_concurrent_poc.py` | 并发翻译与缓存机制 POC 脚本 |
| `translate_local_qwen_fast.py` | 本地 Qwen 模型快速翻译测试脚本 |

---

### 9.4 `scripts/preprocess/`

```text
scripts/preprocess/
├── align_ref_to_src_semantic.py
└── sent_split_batch.py
```

该目录存放数据预处理脚本。

| 文件 | 说明 |
|---|---|
| `align_ref_to_src_semantic.py` | 源文与参考译文语义对齐脚本 |
| `sent_split_batch.py` | 批量分句和文本切分脚本 |

---

### 9.5 `scripts/termbase/`

```text
scripts/termbase/
├── build_core_high_terms_v0.3.py
├── build_termbase_v0.3_todo_candidates.py
├── check_term_consistency.py
├── check_term_consistency_v0.3.py
├── load_terms.py
├── match_terms.py
├── merge_manual_terms_v0.2.py
└── validate_termbase_v02.py
```

该目录存放术语库加载、术语匹配、术语一致性检查和术语库构建脚本。

| 文件 | 说明 |
|---|---|
| `build_core_high_terms_v0.3.py` | 构建 V0.3 核心高优先级术语候选集 |
| `build_termbase_v0.3_todo_candidates.py` | 生成术语库 V0.3 待处理候选修改清单 |
| `check_term_consistency.py` | 检查译文是否使用术语库指定译法的基础脚本 |
| `check_term_consistency_v0.3.py` | V0.3 版本术语一致性检查脚本 |
| `load_terms.py` | 加载术语库文件的脚本 |
| `match_terms.py` | 在源文中匹配术语库术语的脚本 |
| `merge_manual_terms_v0.2.py` | 合并人工抽取术语到 V0.2 术语库的脚本 |
| `validate_termbase_v02.py` | 校验 V0.2 术语库格式和字段的脚本 |

---

### 9.6 `scripts/utils/`

```text
scripts/utils/
└── lang_map.py
```

| 文件 | 说明 |
|---|---|
| `lang_map.py` | 语种代码、语种名称和评分目标等语言映射工具 |

---

## 10. `termbase/`

```text
termbase/
├── alias_additions_v0.3_candidate.csv
├── auto_regulation_terms.csv
├── auto_regulation_terms_sample.csv
├── auto_regulation_terms_v0.2.backup.csv
├── auto_regulation_terms_v0.2.csv
├── bad_target_term_fixes_v0.3_candidate.csv
├── broad_term_review_v0.3_candidate.csv
├── core_high_terms_v0.3_candidate.csv
├── manual_extracted_ar_terms_v0.2.csv
├── manual_extracted_de_terms_v0.2.csv
├── manual_extracted_es_terms_v0.2.csv
├── manual_extracted_fr_terms_v0.2.csv
├── manual_extracted_id_terms_v0.2.csv
├── manual_extracted_it_terms_v0.2.csv
├── manual_extracted_ms_terms_v0.2.csv
├── manual_extracted_nl_terms_v0.2.csv
├── manual_extracted_no_terms_v0.2.csv
├── manual_extracted_pt_terms_v0.2.csv
├── manual_extracted_ru_terms_v0.2.csv
├── manual_extracted_sv_terms_v0.2.csv
├── manual_extracted_terms_v0.2.csv
├── manual_extracted_th_terms_v0.2.csv
├── manual_extracted_vi_terms_v0.2.csv
└── termbase_v0.3_candidate_updates.csv
```

`termbase/` 目录存放汽车标准法规术语库、人工抽取术语和术语库 V0.3 候选修改文件。

---

### 10.1 主术语库文件

| 文件 | 说明 |
|---|---|
| `auto_regulation_terms.csv` | 汽车法规术语库基础文件 |
| `auto_regulation_terms_sample.csv` | 术语库样例文件 |
| `auto_regulation_terms_v0.2.csv` | 当前主要使用的 V0.2 汽车法规术语库 |
| `auto_regulation_terms_v0.2.backup.csv` | V0.2 术语库备份文件 |

---

### 10.2 V0.3 候选术语与回流文件

| 文件 | 说明 |
|---|---|
| `core_high_terms_v0.3_candidate.csv` | V0.3 核心高优先级术语候选集 |
| `termbase_v0.3_candidate_updates.csv` | V0.3 术语库候选更新清单 |
| `alias_additions_v0.3_candidate.csv` | V0.3 alias 补充候选清单 |
| `bad_target_term_fixes_v0.3_candidate.csv` | V0.3 目标译法问题修正候选清单 |
| `broad_term_review_v0.3_candidate.csv` | V0.3 过宽术语复核候选清单 |

---

### 10.3 人工抽取术语文件

| 文件 | 说明 |
|---|---|
| `manual_extracted_terms_v0.2.csv` | 人工抽取术语总表 |
| `manual_extracted_ar_terms_v0.2.csv` | 阿拉伯语人工抽取术语 |
| `manual_extracted_de_terms_v0.2.csv` | 德语人工抽取术语 |
| `manual_extracted_es_terms_v0.2.csv` | 西班牙语人工抽取术语 |
| `manual_extracted_fr_terms_v0.2.csv` | 法语人工抽取术语 |
| `manual_extracted_id_terms_v0.2.csv` | 印尼语人工抽取术语 |
| `manual_extracted_it_terms_v0.2.csv` | 意大利语人工抽取术语 |
| `manual_extracted_ms_terms_v0.2.csv` | 马来语人工抽取术语 |
| `manual_extracted_nl_terms_v0.2.csv` | 荷兰语人工抽取术语 |
| `manual_extracted_no_terms_v0.2.csv` | 挪威语人工抽取术语 |
| `manual_extracted_pt_terms_v0.2.csv` | 葡萄牙语人工抽取术语 |
| `manual_extracted_ru_terms_v0.2.csv` | 俄语人工抽取术语 |
| `manual_extracted_sv_terms_v0.2.csv` | 瑞典语人工抽取术语 |
| `manual_extracted_th_terms_v0.2.csv` | 泰语人工抽取术语 |
| `manual_extracted_vi_terms_v0.2.csv` | 越南语人工抽取术语 |

---

## 11. 基本数据流

项目当前基本数据流如下：

```text
data/eval/
   ↓
scripts/mt/
   ↓
data/mt/qwen-max/ 或 data/mt/qwen-max-term/
   ↓
scripts/evaluation/
   ↓
data/report/
```

术语相关数据流如下：

```text
termbase/
   ↓
scripts/termbase/load_terms.py
   ↓
scripts/termbase/match_terms.py
   ↓
scripts/termbase/check_term_consistency.py
   ↓
data/report/termbase/
```

---

## 12. 文件命名说明

### 12.1 语种样本文件

```text
data/eval/{lang}.jsonl
```

示例：

```text
data/eval/en.jsonl
data/eval/de.jsonl
data/eval/fr.jsonl
```

---

### 12.2 翻译结果文件

```text
data/mt/{model_or_strategy}/mt_{lang}._{model}.jsonl
```

示例：

```text
data/mt/qwen-max/mt_en._qwen-max.jsonl
data/mt/qwen-max-term/mt_en._qwen-max.jsonl
```

---

### 12.3 报告文件

报告文件主要存放在：

```text
data/report/
```

常见格式包括：

```text
.xlsx
.csv
.json
.jsonl
```

---

## 13. 说明

本仓库主要用于汽车标准法规翻译实验验证，重点沉淀多语种样本、翻译结果、术语库、评分脚本和分析报告。

仓库中的部分文件属于阶段性实验产物或历史中间结果，保留用于结果追溯和实验复现。
```
