# Prompt Design Summary

## Split
- split_name: source_only_300_by_lang
- total_samples: 300
- termbase_version: termbase_v1
- termbase_path: termbase/auto_regulation_terms_v1.csv

## Experiment Groups
- no_term_baseline: 300 samples, strategy=no_term_general
- term_baseline: 300 samples, strategy=term_general
- graded_prompt: 300 samples, strategy=graded

## Strategy Checks
- no_term_baseline 不注入术语: True
- term_baseline 注入术语但不分级: True
- graded_prompt 使用分级路由: True
- retry_repair 模板已定义但未执行: True

## Graded Prompt Mode Distribution
- lightweight: 8
- natural_legal: 84
- strict_term: 30
- structure: 178

## Language Counts
- de: 300

## Matched High Count Distribution By Language
- de: {'0': 195, '1': 49, '2': 31, '3': 12, '4': 8, '5': 2, '7': 1, '8': 2}

## Required Terms
- required_target_terms 非空样本数: 105
- required_target_terms 只来自 priority=high 且 status=active 的术语。
- status=review 可召回但不进入 required_target_terms。
- status=inactive 不参与召回。

## Fairness
- 同一批 source_text: True
- 同一批 sample_id: True
- 同一术语库: True
- 同一 required_target_terms 字段: True
- 后续应使用同一模型和同一参数。

## Not Executed In This Stage
- 未执行真实翻译。
- 未执行 TCR。
- 未运行 XCOMET。
- 未生成 retry 样本。
