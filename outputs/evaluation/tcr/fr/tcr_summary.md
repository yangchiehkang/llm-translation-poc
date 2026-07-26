# TCR Summary - source_only_300_by_lang

## Group Comparison
| group | total_samples | samples_with_hard_terms | no_terms_count | pass_count | fail_count | pass_rate_on_hard_terms | avg_tcr_on_hard_terms | failed_term_total | retry_needed_count | retry_rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| no_term_baseline | 300 | 260 | 40 | 39 | 221 | 15.00% | 38.48 | 504 | 221 | 73.67% |
| term_baseline | 300 | 260 | 40 | 145 | 115 | 55.77% | 76.99 | 171 | 115 | 38.33% |
| graded_prompt | 300 | 260 | 40 | 157 | 103 | 60.38% | 79.42 | 149 | 103 | 34.33% |

## Error Type Distribution
| group | error_type_distribution | sample_error_type_distribution |
|---|---|---|
| no_term_baseline | `{"missing": 257, "partial": 247}` | `{"missing": 72, "mixed": 90, "none": 79, "partial": 59}` |
| term_baseline | `{"missing": 88, "partial": 83}` | `{"missing": 53, "mixed": 14, "none": 185, "partial": 48}` |
| graded_prompt | `{"alias_only": 1, "missing": 81, "partial": 67}` | `{"alias_only": 1, "missing": 49, "mixed": 9, "none": 197, "partial": 44}` |

## Top Failed Terms
### no_term_baseline
- déchet -> 废弃物: 52
- responsabilité élargie du producteur -> 生产者责任延伸: 43
- prévention et gestion des déchets -> 废弃物预防和管理: 36
- gestion des déchets -> 废弃物管理: 36
- producteur -> 生产者: 31
- économie sociale et solidaire -> 社会和团结经济: 21
- opérations de contrôle -> 检验操作: 18
- recyclage -> 回收利用: 18
- contribution -> 缴款: 16
- chronotachygraphe -> 行驶记录仪: 15
### term_baseline
- prévention et gestion des déchets -> 废弃物预防和管理: 25
- responsabilité élargie du producteur -> 生产者责任延伸: 24
- gestion des déchets -> 废弃物管理: 22
- économie sociale et solidaire -> 社会和团结经济: 18
- déchet -> 废弃物: 12
- opérations de contrôle -> 检验操作: 11
- recyclage -> 回收利用: 8
- distance parcourue -> 行驶距离: 4
- chronotachygraphe -> 行驶记录仪: 3
- émissions de gaz à effet de serre -> 温室气体排放: 3
### graded_prompt
- prévention et gestion des déchets -> 废弃物预防和管理: 24
- responsabilité élargie du producteur -> 生产者责任延伸: 20
- gestion des déchets -> 废弃物管理: 19
- économie sociale et solidaire -> 社会和团结经济: 18
- opérations de contrôle -> 检验操作: 11
- déchet -> 废弃物: 7
- recyclage -> 回收利用: 5
- chronotachygraphe -> 行驶记录仪: 4
- émissions de gaz à effet de serre -> 温室气体排放: 3
- gaz à effet de serre -> 温室气体: 3

## Retry Planning
| group | retry_input | retry_needed_count | retry_rate | retry_success_count | retry_fix_rate | tcr_before_retry | tcr_after_retry | da_delta_after_retry |
|---|---|---:|---:|---|---|---:|---|---|
| no_term_baseline | `/data/yht/llm-translation-poc-dev-yangjiekang/outputs/retry_inputs/source_only_300_by_lang/no_term_baseline_retry_inputs.jsonl` | 221 | 73.67% | not_run | not_run | 38.48 | not_run | not_run |
| term_baseline | `/data/yht/llm-translation-poc-dev-yangjiekang/outputs/retry_inputs/source_only_300_by_lang/term_baseline_retry_inputs.jsonl` | 115 | 38.33% | not_run | not_run | 76.99 | not_run | not_run |
| graded_prompt | `/data/yht/llm-translation-poc-dev-yangjiekang/outputs/retry_inputs/source_only_300_by_lang/graded_prompt_retry_inputs.jsonl` | 103 | 34.33% | not_run | not_run | 79.42 | not_run | not_run |

## Checks
- TCR 只检查 priority=high 且 status=active 的 hard required terms。
- tcr_status 只使用 pass / fail / no_terms。
- no_terms 样本的 tcr_sample 为 null；pass/fail 样本为 0 到 100。
- retry_inputs 只包含 tcr_status=fail 的样本。
- 当前未执行 retry 翻译、DA/COMET，也未调用 API。
