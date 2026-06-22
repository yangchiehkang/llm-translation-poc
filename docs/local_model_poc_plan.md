# 9.6 Local Model POC Plan

Date: 2026-06-22  
Project: 广汽标准法规翻译项目 V0.3 优化实验计划  
Task: 9.6 任务五：设计本地模型 POC 方案

---

## 1. 任务目标

本任务利用服务器上的 8 张 Ascend 910B 进行本地模型 POC 验证。

本周重点是方案设计和小样本测试准备，不直接替换当前 Qwen-Max API 主实验引擎。

本地模型 POC 的目标是验证本地大模型在标准法规翻译场景中的可用性、速度、稳定性和后续评估接入能力。

---

## 2. POC 边界

### 2.1 本阶段包含

- 使用服务器本地模型进行小样本翻译验证；
- 验证 Qwen2.5-14B-Instruct 在 Ascend 910B 上是否可加载和推理；
- 设计 API 与本地模型的对比指标；
- 明确本地模型输出 JSONL 格式；
- 明确后续接入 TCR 和 XCOMET-QE 的方式；
- 形成混合翻译架构草案。

### 2.2 本阶段不包含

- 不替换当前 Qwen-Max API 主流程；
- 不覆盖已有 API 翻译结果；
- 不将本地模型结果直接作为 V0.3 正式结论；
- 不直接进行全量多语种实验。

---

## 3. 本地模型与服务器环境

项目目录：

```text
/data/llm-translation-poc
```

模型目录：

```text
/data/MODEL_DIR
```

本次 smoke test 模型：

```text
/data/MODEL_DIR/Qwen2.5-14B-Instruct
```

XCOMET 模型路径：

```text
/data/MODEL_DIR/xcomet-xxl
/data/MODEL_DIR/hf_home/hub/models--Unbabel--XCOMET-XL
/data/MODEL_DIR/torch_cache/unbabel_comet
```

本地环境变量：

```text
LLM_TRANSLATION_HOME=/data/llm-translation-poc
LLM_MODELS_HOME=/data/MODEL_DIR
HF_HOME=/data/MODEL_DIR/hf_home
TRANSFORMERS_CACHE=/data/MODEL_DIR/hf_home
HF_HUB_CACHE=/data/MODEL_DIR/hf_home/hub
MODELSCOPE_CACHE=/data/MODEL_DIR/modelscope
TORCH_HOME=/data/MODEL_DIR/torch_cache
```

---

## 4. 已完成的本地模型 smoke test

### 4.1 测试命令摘要

本次测试显式使用：

```text
device = npu:0
torch_npu
Qwen2.5-14B-Instruct
```

### 4.2 测试结果

```text
model_path: /data/MODEL_DIR/Qwen2.5-14B-Instruct
device: npu:0
npu available: True
npu count: 8
Model loaded. seconds: 10.25
latency_sec: 1.256
translation: 该车辆应符合型式批准要求。
```

### 4.3 结论

本地模型已成功在 Ascend 910B 单卡上完成推理。

该结果证明本地模型 POC 具备继续开展小样本翻译测试的基础。

---

## 5. 小规模测试语种和样本

### 5.1 初始测试语种

| 语种方向 | 用途 |
|---|---|
| en -> zh | 基线验证 |
| de -> zh | 欧洲法规句式验证 |
| fr -> zh | 欧洲法规术语验证 |
| ar -> zh | 非拉丁文字验证 |
| th -> zh | 东南亚语种验证 |

### 5.2 样本规模

| 阶段 | 每语种样本数 | 总样本数 |
|---|---:|---:|
| smoke test | 1-5 | 5-25 |
| 小样本 POC | 20 | 100 |
| 扩展 POC | 50 | 250 |

### 5.3 样本选择标准

样本应覆盖：

- 短句；
- 中等长度句；
- 长句；
- 法规义务句；
- REESS / battery / type approval / compliance / test 等术语；
- high priority terms；
- 复杂从句；
- 容易出现术语不一致的句子。

---

## 6. API 与本地模型对比指标

| 指标 | 说明 |
|---|---|
| 单条平均耗时 | 每条样本平均推理耗时 |
| 总体吞吐量 | 单位时间内完成的样本数 |
| XCOMET-QE 得分 | 使用同一 XCOMET-QE 流程评估 |
| TCR | 术语一致性整体得分 |
| high priority TCR | 高优先级术语一致性得分 |
| 失败率 | 空输出、异常、超时、格式错误等失败比例 |
| 格式稳定性 | JSONL 字段完整性、是否输出额外解释 |
| 长句处理能力 | 长句是否完整、是否截断、是否重复 |

---

## 7. 本地模型输出格式

本地模型输出统一为 JSONL。

单条记录格式：

```json
{
  "sample_id": "en_0001",
  "source_lang": "en",
  "target_lang": "zh",
  "source_text": "The vehicle shall comply with the type approval requirements.",
  "translation": "该车辆应符合型式批准要求。",
  "model": "Qwen2.5-14B-Instruct",
  "model_path": "/data/MODEL_DIR/Qwen2.5-14B-Instruct",
  "engine": "local",
  "device": "ascend_910b",
  "num_cards": 8,
  "active_device": "npu:0",
  "prompt_version": "prompt_v3",
  "termbase_version": "termbase_v0.3_candidate",
  "injected_terms": [],
  "latency_ms": 1256,
  "status": "success",
  "error_type": "",
  "error_message": "",
  "created_at": "2026-06-22T00:00:00Z"
}
```

---

## 8. TCR 和 XCOMET-QE 接入方案

### 8.1 TCR

本地模型输出完成 JSONL 标准化后，可进入现有 TCR 评估流程。

建议分别统计：

```text
overall TCR
high priority TCR
medium priority TCR
strict term TCR
```

### 8.2 XCOMET-QE

本地模型输出稳定后，接入 XCOMET-QE。

规则：

```text
API 与本地模型使用同一批源文；
使用相同 XCOMET-QE 脚本；
保留 engine 字段区分 api/local；
分别输出 API 与 local 的质量得分。
```

---

## 9. 混合翻译架构草案

```text
输入样本
  |
  v
样本分类器
  |
  +-- 简单低风险样本 --> 本地模型
  |
  +-- 无核心术语样本 --> 本地模型
  |
  +-- high priority 术语样本 --> API 或严格本地模式
  |
  +-- 外部验收范围样本 --> API
  |
  +-- 长句/复杂法规句 --> API 优先，本地模型对比
  |
  v
输出标准化 JSONL
  |
  v
TCR 评估
  |
  v
XCOMET-QE 评估
  |
  v
API vs Local 对比报告
```

---

## 10. 风险控制

- 本地模型结果不覆盖 Qwen-Max API 输出；
- 本地模型结果不直接进入正式 V0.3 结论；
- 所有本地输出必须标记 `engine=local`；
- 所有 API 输出必须标记 `engine=api`；
- 所有结果保留 `model_path`、`prompt_version`、`termbase_version`；
- 小样本验证通过后再扩大规模；
- 8 卡并行或服务化部署作为后续阶段，不影响当前 API 主流程。

---

## 11. 建议输出路径

本地翻译结果：

```text
data/mt/local-poc/local_model_poc_outputs.jsonl
```

速度对比报告：

```text
data/report/local-model-poc/local_vs_api_speed_summary.xlsx
```

质量对比报告：

```text
data/report/local-model-poc/local_vs_api_quality_summary.xlsx
```

---

## 12. 完成标准检查

| 完成标准 | 状态 |
|---|---|
| 明确本地模型 POC 的目标和边界 | 已完成 |
| 明确小样本测试方案 | 已完成 |
| 明确 API 与本地模型的对比方式 | 已完成 |
| 不影响当前 API 主流程实验结论 | 已完成 |
| 本地模型在 NPU 上完成 smoke test | 已完成 |

---

# 2026-06-22 Local Model POC Design Note

## 1. Task

9.6 任务五：设计本地模型 POC 方案。

本任务目标是利用 8 张 Ascend 910B 进行本地模型 POC 验证。本周以方案设计和小样本测试准备为主，不直接替换当前 Qwen-Max API 主实验引擎。

---

## 2. Completed Work

已完成：

```text
本地模型 POC 目标定义
POC 边界定义
小样本语种设计
小样本规模设计
API 与 local 对比指标设计
本地模型输出格式设计
TCR 接入方案
XCOMET-QE 接入方案
混合翻译架构草案
Qwen2.5-14B-Instruct NPU smoke test
```

---

## 3. Smoke Test Result

模型：

```text
/data/MODEL_DIR/Qwen2.5-14B-Instruct
```

设备：

```text
npu:0
Ascend 910B
```

NPU 状态：

```text
npu available: True
npu count: 8
```

测试输入：

```text
The vehicle shall comply with the type approval requirements.
```

测试输出：

```text
该车辆应符合型式批准要求。
```

耗时：

```text
latency_sec: 1.256
```

结论：

```text
本地 Qwen2.5-14B-Instruct 已可在 Ascend 910B 上完成法规翻译推理。
```

---

## 4. Comparison Metrics

后续 API 与本地模型对比指标：

```text
单条平均耗时
总体吞吐量
XCOMET-QE 得分
TCR
high priority TCR
失败率
格式稳定性
长句处理能力
```

---

## 5. Small Sample Plan

初始语种：

```text
en -> zh
de -> zh
fr -> zh
ar -> zh
th -> zh
```

初始样本规模：

```text
5 languages × 20 samples = 100 samples
```

---

## 6. Hybrid Translation Draft

路由原则：

```text
简单样本 -> local
低风险样本 -> local
无核心术语样本 -> local
high priority 术语样本 -> API 或严格 local
外部验收样本 -> API
长句复杂法规样本 -> API 优先，local 对比
正式 V0.3 结论样本 -> API 主流程
```

---

## 7. Risk Control

```text
不覆盖 API 输出
不替换 Qwen-Max API 主流程
local 输出必须标记 engine=local
保留 model_path
保留 prompt_version
保留 termbase_version
小样本验证通过后再扩大实验
```

---

## 8. Status

9.6 任务五的方案设计已完成，且本地模型 NPU smoke test 已完成。

下一阶段可以进入小样本批量翻译 POC。
