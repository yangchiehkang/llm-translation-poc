# Local Model POC Design

Date: 2026-06-22  
Owner: 杨杰康  
Branch: dev/yangjiekang

---

## 1. Output Files

```text
docs/local_model_poc_plan.md
notes/2026-06-22_local-model-poc-design.md
```

---

## 2. Goal

Use 8 Ascend 910B cards to validate local model translation feasibility.

This task is limited to design and small-sample preparation.

It does not replace the current Qwen-Max API translation workflow.

---

## 3. Server Paths

Project:

```text
/data/llm-translation-poc
```

Models:

```text
/data/llm_models
```

XCOMET:

```text
/data/llm_models/xcomet-xxl
/data/llm_models/hf_home/hub/models--Unbabel--XCOMET-XL
/data/llm_models/torch_cache/unbabel_comet
```

---

## 4. Candidate Models

Initial candidates:

```text
/data/llm_models/Qwen2.5-7B-Instruct
/data/llm_models/Qwen2.5-14B-Instruct
/data/llm_models/Qwen3-14B
/data/llm_models/Qwen3-32B
/data/llm_models/Llama-3.3-70B-Instruct
```

Recommended first model:

```text
/data/llm_models/Qwen2.5-14B-Instruct
```

Fallback model:

```text
/data/llm_models/Qwen2.5-7B-Instruct
```

---

## 5. Small Sample Plan

Test languages:

```text
en -> zh
de -> zh
fr -> zh
ar -> zh
th -> zh
```

Initial sample size:

```text
5 languages × 20 samples = 100 samples
```

Sample types:

```text
short sentence
medium sentence
long sentence
high-priority terminology sample
regulatory modal verb sample
REESS sample
battery sample
approval sample
testing sample
compliance sample
```

---

## 6. Comparison Metrics

Compare Qwen-Max API and local model by:

```text
average latency per sample
total throughput
XCOMET-QE score
TCR
high priority TCR
failure rate
format stability
long sentence handling
```

---

## 7. Output Format

Required output fields:

```text
sample_id
source_lang
target_lang
source_text
translation
model
model_path
engine
device
num_cards
prompt_version
termbase_version
injected_terms
latency_ms
status
error_type
error_message
created_at
```

Required local tags:

```text
engine=local
device=ascend_910b
num_cards=8
```

---

## 8. TCR and XCOMET-QE

Local model outputs should be normalized first.

Then they can enter:

```text
TCR evaluation
XCOMET-QE evaluation
```

Rules:

```text
Use same samples as API outputs.
Use same termbase version.
Use same XCOMET-QE script.
Report API and local model separately.
```

---

## 9. Hybrid Architecture Draft

Routing idea:

```text
simple samples -> local model
low-risk samples -> local model
high-priority term samples -> API or strict local mode
external acceptance samples -> API
long complex samples -> API first, local comparison second
formal V0.3 conclusion samples -> API main flow
```

---

## 10. Risk Control

Rules:

```text
do not overwrite API outputs
do not replace main API engine
mark local outputs with engine=local
keep model path
keep prompt_version
keep termbase_version
keep timestamps
evaluate local outputs separately
```

---

## 11. Completion Status

| Item | Status |
|---|---|
| POC target | Done |
| POC boundary | Done |
| Small sample plan | Done |
| Comparison metrics | Done |
| Output format | Done |
| TCR integration plan | Done |
| XCOMET-QE integration plan | Done |
| Hybrid architecture draft | Done |
