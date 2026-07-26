# Translation Run Summary

- split_name: es
- translation_stage: first
- model_backend: local_npu
- model_name: /data/llm_models/Qwen2.5-14B-Instruct
- model_path: /data/llm_models/Qwen2.5-14B-Instruct
- device: npu:0
- temperature: 0.0
- max_new_tokens: 2048
- batch_size: 1
- started_at: 2026-07-13T05:32:19Z
- finished_at: 2026-07-13T05:46:52Z

## Counts

| group | expected | success | failed | skipped | avg_latency_ms |
|---|---:|---:|---:|---:|---:|
| no_term_baseline | 67 | 67 | 0 | 0 | 4027.91 |
| term_baseline | 67 | 67 | 0 | 0 | 4314.49 |
| graded_prompt | 67 | 67 | 0 | 0 | 4361.34 |

## Validation

- success_sample_sets_equal: True
- da_fields_preserved_by_group: {"no_term_baseline": {"ref_text": false, "page_ref": false, "order_ref": false, "alignment_method": false, "alignment_confidence": false, "use_for_da": false, "da_sample_role": false}, "term_baseline": {"ref_text": false, "page_ref": false, "order_ref": false, "alignment_method": false, "alignment_confidence": false, "use_for_da": false, "da_sample_role": false}, "graded_prompt": {"ref_text": false, "page_ref": false, "order_ref": false, "alignment_method": false, "alignment_confidence": false, "use_for_da": false, "da_sample_role": false}}

## Scope

- 未调用 API。
- 未使用 DASHSCOPE_API_KEY。
- 未执行 retry_repair。
- 未执行 TCR。
- 未执行 XCOMET。
- 未运行其他 split。
