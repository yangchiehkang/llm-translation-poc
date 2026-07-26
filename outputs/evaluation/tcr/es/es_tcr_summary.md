# TCR Summary - source_only_300_by_lang

## Group Comparison
| group | total_samples | samples_with_hard_terms | no_terms_count | pass_count | fail_count | pass_rate_on_hard_terms | avg_tcr_on_hard_terms | failed_term_total | retry_needed_count | retry_rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| no_term_baseline | 67 | 37 | 30 | 4 | 33 | 10.81% | 25.27 | 57 | 33 | 49.25% |
| term_baseline | 67 | 37 | 30 | 29 | 8 | 78.38% | 88.20 | 9 | 8 | 11.94% |
| graded_prompt | 67 | 37 | 30 | 30 | 7 | 81.08% | 90.45 | 8 | 7 | 10.45% |

## Error Type Distribution
| group | error_type_distribution | sample_error_type_distribution |
|---|---|---|
| no_term_baseline | `{"missing": 12, "partial": 45}` | `{"missing": 6, "mixed": 4, "none": 34, "partial": 23}` |
| term_baseline | `{"missing": 3, "partial": 6}` | `{"missing": 3, "none": 59, "partial": 5}` |
| graded_prompt | `{"missing": 2, "partial": 6}` | `{"missing": 2, "none": 60, "partial": 5}` |

## Top Failed Terms
### no_term_baseline
- elementos de seguridad -> 安全配置: 12
- elementos de seguridad optativos -> 选装安全配置: 6
- rótulo de elementos de seguridad optativos -> 选装安全配置标签: 3
- accionamiento -> 作动: 2
- protección contra la utilización no autorizada -> 防止未经授权使用的保护: 2
- dispositivo de protección -> 保护装置: 2
- Reglamento No 13-H -> 第13-H号法规: 2
- equipamiento certificado por el fabricante -> 制造商认证装备: 1
- equipamiento original -> 原厂装备: 1
- bloqueado -> 锁止: 1
### term_baseline
- utilización no autorizada -> 未经授权使用: 3
- equipamiento certificado por el fabricante -> 制造商认证装备: 1
- neutralizarse -> 失效: 1
- dispositivo contra la utilización no autorizada -> 防未经授权使用装置: 1
- componentes del vehículo -> 车辆部件: 1
- elementos de seguridad -> 安全配置: 1
- punto ciego -> 盲区: 1
### graded_prompt
- utilización no autorizada -> 未经授权使用: 2
- elementos de seguridad -> 安全配置: 2
- equipamiento certificado por el fabricante -> 制造商认证装备: 1
- dispositivo contra la utilización no autorizada -> 防未经授权使用装置: 1
- punto ciego -> 盲区: 1
- elementos de seguridad optativos -> 选装安全配置: 1

## Retry Planning
| group | retry_input | retry_needed_count | retry_rate | retry_success_count | retry_fix_rate | tcr_before_retry | tcr_after_retry | da_delta_after_retry |
|---|---|---:|---:|---|---|---:|---|---|
| no_term_baseline | `/data/yht/llm-translation-poc-dev-yangjiekang/outputs/retry_inputs/source_only_300_by_lang/no_term_baseline_retry_inputs.jsonl` | 33 | 49.25% | not_run | not_run | 25.27 | not_run | not_run |
| term_baseline | `/data/yht/llm-translation-poc-dev-yangjiekang/outputs/retry_inputs/source_only_300_by_lang/term_baseline_retry_inputs.jsonl` | 8 | 11.94% | not_run | not_run | 88.20 | not_run | not_run |
| graded_prompt | `/data/yht/llm-translation-poc-dev-yangjiekang/outputs/retry_inputs/source_only_300_by_lang/graded_prompt_retry_inputs.jsonl` | 7 | 10.45% | not_run | not_run | 90.45 | not_run | not_run |

## Checks
- TCR 只检查 priority=high 且 status=active 的 hard required terms。
- tcr_status 只使用 pass / fail / no_terms。
- no_terms 样本的 tcr_sample 为 null；pass/fail 样本为 0 到 100。
- retry_inputs 只包含 tcr_status=fail 的样本。
- 当前未执行 retry 翻译、DA/COMET，也未调用 API。
