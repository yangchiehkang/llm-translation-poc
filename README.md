# LLM Translation POC

## 1. 项目目标

本项目面向汽车标准法规场景，构建多语种到中文的机器翻译 baseline、自动化质量评估链路、术语一致性检查能力和后续模型优化实验基础。

当前阶段目标是完成一个可复现的翻译评估 POC，用于支撑后续标准法规翻译模块的技术方案、模型选型、Prompt 优化、术语约束、SFT / GRPO 训练和验收指标分析。

---

## 2. 当前 Baseline

| 项目 | 内容 |
|---|---|
| 项目名称 | LLM Translation POC |
| 翻译模型 | qwen-max |
| 评估模型 | Unbabel/XCOMET-XL |
| 评估方式 | XCOMET-XL QE |
| 是否依赖参考译文 | 否 |
| 运行设备 | Ascend NPU |
| 目标语言 | 中文 |
| 当前阶段 | 多语种翻译 baseline + 自动化 QE 评分 |

当前已经完成 Qwen-Max 多语种到中文翻译结果生成，并完成基于 XCOMET-XL QE 的自动化质量评分。

---

## 3. RFP 对应关系

本项目主要支撑标准法规翻译相关需求。

| RFP 条目 | 需求名称 | 对应能力 |
|---|---|---|
| 5.1.7 | 标准法规翻译 | 多语种法规文本翻译、术语一致性、翻译结果输出 |
| 6.1.2 | 标准法规文档翻译速度 | 后续支撑端到端翻译性能评估 |
| 6.1.6 | 模型并发支持-标准法规翻译 | 后续支撑多任务、多文档并发翻译 |

---

## 4. 当前支持语种

### 4.1 RFP 重点语种

| 语言代码 | 语言 | 翻译方向 | 验收目标 |
|---|---|---|---|
| en | English | English → Chinese | 90% |
| es | Spanish | Spanish → Chinese | 85% |
| ru | Russian | Russian → Chinese | 85% |
| de | German | German → Chinese | 80% |
| fr | French | French → Chinese | 80% |
| th | Thai | Thai → Chinese | 70% |
| ar | Arabic | Arabic → Chinese | 70% |

### 4.2 扩展评估语种

| 语言代码 | 语言 | 翻译方向 |
|---|---|---|
| ms | Malay | Malay → Chinese |
| id | Indonesian | Indonesian → Chinese |
| pt | Portuguese | Portuguese → Chinese |
| it | Italian | Italian → Chinese |
| nl | Dutch | Dutch → Chinese |
| no | Norwegian | Norwegian → Chinese |
| sv | Swedish | Swedish → Chinese |
| vi | Vietnamese | Vietnamese → Chinese |

说明：扩展语种当前用于 baseline 评估和横向对比，不默认等同于正式验收语种。

---

## 5. 当前项目结构

### 5.1 根目录结构

- `README.md`：项目说明文档。
- `configs/`：配置文件目录。
- `data/`：数据目录。
- `docs/`：项目文档目录。
- `logs/`：运行日志目录。
- `notes/`：日报、开发记录和问题记录。
- `scripts/`：核心脚本目录。
- `termbase/`：术语库目录。
- `outputs/`：临时输出目录。

### 5.2 详细目录结构

- `configs/`
  - `languages.yaml`：语种配置。
  - `qwen_max.yaml`：Qwen-Max 翻译配置。
  - `xcomet_xl_qe_npu.yaml`：XCOMET-XL QE 评分配置。

- `data/`
  - `raw/`：原始 PDF 文档。
  - `eval/`：分句、清洗、对齐后的评测样本。
  - `mt/`：机器翻译结果。
    - `qwen-max/`：Qwen-Max 翻译结果。
    - `madlad400/`：MADLAD400 本地模型翻译结果。
  - `report/`：评估报告和分析结果。
    - `xcomet-xl-qe/`：XCOMET-XL QE 评分结果。
    - `reference-metrics/`：BLEU、chrF、reference-based COMET 等参考译文指标。
    - `term-consistency/`：术语一致性检查结果。
    - `error-analysis/`：低分样本和人工错误归因结果。

- `docs/`
  - `baseline_eval_report.md`：baseline 评估报告。
  - `data_schema.md`：数据格式说明。
  - `project_tree.txt`：项目结构记录。

- `notes/`
  - `2026-06-03_xcomet-xl-npu-adaptation-daily.md`：XCOMET-XL NPU 适配日报。

- `scripts/`
  - `preprocess/`：文档解析、分句、清洗和语义对齐脚本。
  - `mt/`：机器翻译脚本。
  - `evaluation/`：翻译质量评估脚本。
  - `termbase/`：术语库构建和术语一致性检查脚本。
  - `utils/`：通用工具脚本。

- `termbase/`
  - `auto_regulation_terms.csv`：汽车标准法规术语库初始文件。

---

## 6. 核心流程

当前 baseline 的核心流程如下：

1. 原始 PDF 文档进入 `data/raw/`。
2. 使用分句脚本抽取并切分文本。
3. 使用语义对齐脚本对齐源语言文本和中文参考译文。
4. 生成评测样本，保存到 `data/eval/`。
5. 调用 Qwen-Max 生成中文译文，保存到 `data/mt/qwen-max/`。
6. 使用 XCOMET-XL QE 对源文和机器译文进行质量评分。
7. 将评分结果输出到 `data/report/xcomet-xl-qe/`。
8. 基于评分结果进行低分样本分析、术语一致性检查和后续 Prompt 优化。

---

## 7. 数据目录说明

### 7.1 `data/raw/`

存放原始 PDF 文件。

文件命名建议：

- `{language_name}_src_{lang}.pdf`
- `{language_name}_ref_zh.pdf`

示例：

- `english_src_en.pdf`
- `english_ref_zh.pdf`
- `spanish_src_es.pdf`
- `spanish_ref_zh.pdf`
- `russian_src_ru.pdf`
- `russian_ref_zh.pdf`
- `thai_src_th.pdf`
- `thai_ref_zh.pdf`

---

### 7.2 `data/eval/`

存放分句、清洗、对齐后的评测样本。

文件命名：

- `{lang}.jsonl`

示例：

- `en.jsonl`
- `es.jsonl`
- `ru.jsonl`
- `de.jsonl`
- `fr.jsonl`
- `th.jsonl`
- `ar.jsonl`

建议每行 JSON 字段：

| 字段 | 说明 |
|---|---|
| `id` | 样本 ID |
| `src_lang` | 源语言代码 |
| `tgt_lang` | 目标语言代码，默认为 `zh` |
| `source` | 源语言文本 |
| `reference` | 中文参考译文 |
| `source_file` | 源语言 PDF 文件名 |
| `reference_file` | 中文参考 PDF 文件名 |
| `page` | 页码 |

---

### 7.3 `data/mt/`

存放机器翻译结果。

当前主要模型目录：

- `data/mt/qwen-max/`

建议文件命名：

- `mt_{src_lang}_zh_qwen-max.jsonl`

示例：

- `mt_en_zh_qwen-max.jsonl`
- `mt_es_zh_qwen-max.jsonl`
- `mt_ru_zh_qwen-max.jsonl`
- `mt_de_zh_qwen-max.jsonl`

建议每行 JSON 字段：

| 字段 | 说明 |
|---|---|
| `id` | 样本 ID |
| `src_lang` | 源语言代码 |
| `tgt_lang` | 目标语言代码，默认为 `zh` |
| `source` | 源语言文本 |
| `prediction` | 模型生成的中文译文 |
| `model` | 翻译模型名称 |
| `prompt_version` | Prompt 版本 |

---

### 7.4 `data/report/`

存放评估报告和分析结果。

| 目录 | 用途 |
|---|---|
| `xcomet-xl-qe/` | XCOMET-XL QE 评分结果 |
| `reference-metrics/` | BLEU、chrF、reference-based COMET 等参考译文指标 |
| `term-consistency/` | 术语一致性检查结果 |
| `error-analysis/` | 低分样本和人工错误归因结果 |

当前已有主要结果文件：

- `data/report/xcomet-xl-qe/score_xcomet_xl_npu.xlsx`
- `data/report/xcomet-xl-qe/test_xcomet_xl_npu.xlsx`
- `data/report/xcomet-xl-qe/qwen-max_xcomet-xl-pseudo-qe.xlsx`

---

## 8. 脚本目录说明

### 8.1 `scripts/preprocess/`

用于文档解析、分句、清洗和语义对齐。

| 脚本 | 作用 |
|---|---|
| `sent_split_batch.py` | 对原始文档抽取文本并进行批量分句 |
| `align_ref_to_src_semantic.py` | 将源语言句子与中文参考译文进行语义对齐 |

---

### 8.2 `scripts/mt/`

用于机器翻译生成。

| 脚本 | 作用 |
|---|---|
| `mt_dashscope_qwenmax.py` | 调用 DashScope Qwen-Max 生成中文译文 |
| `mt_local_madlad400.py` | 使用本地 MADLAD400 模型进行翻译 baseline |

---

### 8.3 `scripts/evaluation/`

用于翻译质量评估。

| 脚本 | 作用 |
|---|---|
| `score_qwen_max_qe.py` | 对 Qwen-Max 翻译结果进行 XCOMET-XL QE 评分 |
| `test_xcomet_transfer_to_npu.py` | 测试 XCOMET-XL 在 Ascend NPU 上的适配运行 |

---

### 8.4 `scripts/termbase/`

用于术语库构建、术语召回和术语一致性检查。

后续计划新增：

| 脚本 | 作用 |
|---|---|
| `build_term_index.py` | 构建术语检索索引 |
| `check_term_consistency.py` | 检查译文是否使用指定术语译法 |
| `export_term_errors.py` | 导出术语错误样本 |

---

### 8.5 `scripts/utils/`

存放通用工具代码。

| 脚本 | 作用 |
|---|---|
| `lang_map.py` | 统一维护语言代码、语言名称和 RFP 验收目标 |

---

## 9. 配置文件说明

### 9.1 `configs/languages.yaml`

维护当前项目的语种范围。

字段说明：

| 字段 | 说明 |
|---|---|
| `target_language` | 目标语言 |
| `rfp_languages` | RFP 重点语种 |
| `extended_languages` | 扩展评估语种 |

---

### 9.2 `configs/qwen_max.yaml`

维护 Qwen-Max 翻译配置。

字段说明：

| 字段 | 说明 |
|---|---|
| `model` | 翻译模型名称 |
| `provider` | 模型服务提供方 |
| `target_language` | 目标语言 |
| `prompt_version` | Prompt 版本 |
| `input_dir` | 输入目录 |
| `output_dir` | 输出目录 |

---

### 9.3 `configs/xcomet_xl_qe_npu.yaml`

维护 XCOMET-XL QE 评分配置。

字段说明：

| 字段 | 说明 |
|---|---|
| `metric` | 评估指标 |
| `metric_model` | 评估模型 |
| `device` | 运行设备 |
| `batch_size` | 批大小 |
| `input_dir` | 输入目录 |
| `output_dir` | 输出目录 |

---

## 10. 当前 XCOMET-XL QE 评估结果

当前已完成 15 个语言方向的 Qwen-Max 翻译质量 QE 评分。

| 语言方向 | 样本数 | XCOMET-XL QE Mean |
|---|---:|---:|
| Swedish → Chinese | 200 | 0.8079 |
| Malay → Chinese | 200 | 0.7835 |
| German → Chinese | 200 | 0.7799 |
| Norwegian → Chinese | 200 | 0.7674 |
| Thai → Chinese | 200 | 0.7584 |
| English → Chinese | 200 | 0.7539 |
| Dutch → Chinese | 135 | 0.7413 |
| Portuguese → Chinese | 200 | 0.6987 |
| Indonesian → Chinese | 200 | 0.6970 |
| Russian → Chinese | 180 | 0.6866 |
| Italian → Chinese | 200 | 0.6137 |
| Spanish → Chinese | 50 | 0.5952 |
| French → Chinese | 200 | 0.5639 |
| Arabic → Chinese | 118 | 0.3263 |

说明：

- XCOMET-XL QE 分数用于无参考译文质量估计。
- QE 分数不能直接等同于人工翻译准确率。
- 后续需要结合人工抽检建立自动指标与验收指标之间的对应关系。
- 当前结果显示 Arabic、French、Spanish、Italian、Russian 等语言方向需要重点分析。

---

## 11. Ascend NPU 适配说明

当前项目已完成 XCOMET-XL QE 评分脚本在 Ascend NPU 环境下的适配。

适配链路：

1. 加载 `Unbabel/XCOMET-XL`。
2. 调用 COMET `predict`。
3. 通过 PyTorch Lightning 执行预测流程。
4. 使用 `torch_npu` 的 CUDA-compatible path。
5. 在 Ascend NPU 上完成实际推理。
6. 输出句子级 QE 分数。

当前 NPU 适配特点：

- 支持 `cpu`、`cuda`、`npu` 三种设备模式。
- NPU 模式通过 `torch_npu` 的 CUDA-compatible 路径运行。
- 不修改 COMET 框架源码。
- 不修改 PyTorch Lightning 源码。
- 在业务脚本层完成设备检查、NPU 初始化和兼容处理。
- 已在 Ascend 910B2 上完成测试和全量评分。

主要产出文件：

- `notes/2026-06-03_xcomet-xl-npu-adaptation-daily.md`
- `data/report/xcomet-xl-qe/test_xcomet_xl_npu.xlsx`
- `data/report/xcomet-xl-qe/score_xcomet_xl_npu.xlsx`

---

## 12. 术语库规划

RFP 要求术语库中定义的术语在译文中以指定译法出现，术语一致率达到 95%。

当前术语库初始文件：

- `termbase/auto_regulation_terms.csv`

建议字段：

| 字段 | 说明 |
|---|---|
| `source_lang` | 源语言 |
| `source_term` | 源语言术语 |
| `target_term` | 指定中文译法 |
| `domain` | 所属领域 |
| `priority` | 术语优先级 |

后续术语一致性检查公式：

**术语一致率 = 译文中使用指定译法的术语出现次数 / 源文中命中术语库的术语总次数 × 100%**

后续处理链路：

1. 读取源文。
2. 匹配源语言术语。
3. 注入术语约束。
4. 执行模型翻译。
5. 检查译文术语一致性。
6. 导出术语错误样本。
7. 对可自动修正的术语错误进行后处理。

---

## 13. 后续计划

### 13.1 P0 任务

| 优先级 | 任务 | 输出 |
|---|---|---|
| P0 | 整理 baseline 评估报告 | `docs/baseline_eval_report.md` |
| P0 | 导出低分样本 | `data/report/error-analysis/low_score_samples.xlsx` |
| P0 | 对低分样本进行人工错误归因 | `data/report/error-analysis/error_analysis.xlsx` |
| P0 | 建立术语一致性检查脚本 | `scripts/termbase/check_term_consistency.py` |
| P0 | 输出术语一致性报告 | `data/report/term-consistency/term_consistency_report.xlsx` |

### 13.2 P1 任务

| 优先级 | 任务 | 输出 |
|---|---|---|
| P1 | 增加 BLEU 指标 | `data/report/reference-metrics/bleu_report.xlsx` |
| P1 | 增加 chrF 指标 | `data/report/reference-metrics/chrf_report.xlsx` |
| P1 | 增加 reference-based COMET 指标 | `data/report/reference-metrics/comet_ref_report.xlsx` |
| P1 | 设计法规专用 Prompt v1 | `docs/prompt_v1.md` |
| P1 | 运行 Prompt v1 对比实验 | `data/report/xcomet-xl-qe/prompt_v1_comparison.xlsx` |

### 13.3 P2 任务

| 优先级 | 任务 | 输出 |
|---|---|---|
| P2 | 检查 PDF 解析质量 | `docs/parse_quality_report.md` |
| P2 | 检查源文-参考译文对齐质量 | `docs/alignment_quality_report.md` |
| P2 | 加入更多本地模型 baseline | `docs/model_comparison_report.md` |
| P2 | 准备 SFT 数据格式 | `data/sft/` |
| P2 | 准备 GRPO 奖励指标设计 | `docs/grpo_reward_design.md` |

---

## 14. 低分样本错误类型

后续人工错误归因建议使用以下错误类型标签。

| 错误类型 | 说明 |
|---|---|
| `mistranslation` | 误译 |
| `omission` | 漏译 |
| `addition` | 增译或幻觉 |
| `term_error` | 术语错误 |
| `number_error` | 数字、单位、日期、标准号错误 |
| `format_error` | 条款编号、列表、表格结构错误 |
| `language_error` | 未输出中文或中外文混杂 |
| `style_error` | 不符合法规中文表达风格 |
| `ocr_error` | OCR 或 PDF 抽取错误 |
| `alignment_error` | 源文和参考译文对齐错误 |
| `source_quality_error` | 源文质量问题 |

---

## 15. 风险语种

根据当前 XCOMET-XL QE baseline，以下语种需要优先分析。

| 优先级 | 语种 | 原因 |
|---|---|---|
| 高 | Arabic | QE 分数最低，可能存在源文抽取、方向性、分词或模型能力问题 |
| 高 | French | QE 分数偏低，且属于 RFP 重点语种 |
| 高 | Spanish | QE 分数偏低，且属于 RFP 重点语种，当前样本数较少 |
| 中高 | Russian | QE 分数中等偏低，且验收目标为 85% |
| 中 | English | 核心语种，验收目标最高，需要进一步提升 |
| 中 | Thai | 当前 QE 表现尚可，但属于长尾语种，需要确认人工准确率 |
| 中 | German | 当前 QE 表现较好，但仍需术语一致性验证 |

---

## 16. Prompt 优化方向

后续 Prompt v1 应围绕法规翻译场景优化。

建议 Prompt 要求包含：

1. 保持法规原意，不得增删事实。
2. 保留条款编号、数字、单位、日期和标准号。
3. 使用正式、严谨的中文法规表达。
4. 对 `shall`、`must`、`may`、`should` 等法规情态词进行稳定翻译。
5. 严格使用术语库中指定译法。
6. 不输出解释、注释、总结或额外说明。
7. 只输出中文译文。

---

## 17. 当前可汇报结论

当前翻译模块已经完成 Qwen-Max 多语种到中文翻译 baseline，并搭建了基于 XCOMET-XL QE 的自动化质量评估链路。

评估脚本已完成 Ascend NPU 适配，可以在服务器上直接运行 XCOMET-XL 评分。

本轮共完成 15 个语言方向的翻译质量评估。结果显示，德语、泰语、英语等语种表现相对稳定，阿拉伯语、法语、西班牙语等语种存在明显优化风险。

下一阶段将重点开展低分样本错误归因、术语一致性检查、参考译文指标补充和法规专用 Prompt 对比实验。

---

## 18. 注意事项

1. XCOMET-XL QE 分数不能直接等同于人工准确率。
2. RFP 验收语种和扩展评估语种需要分开说明。
3. 当前 baseline 主要用于模型和 Prompt 的相对质量比较。
4. 后续正式验收仍需人工抽检。
5. 术语一致性是硬指标，需要单独建设检查链路。
6. Arabic、French、Spanish、Russian 是当前重点风险语种。
7. 所有实验结果应保留模型版本、Prompt 版本、数据版本和评估时间。
