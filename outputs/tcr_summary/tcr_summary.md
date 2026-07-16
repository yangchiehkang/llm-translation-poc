# TCR Summary - source_only_300_by_lang

## Group Comparison
| group | total_samples | samples_with_hard_terms | no_terms_count | pass_count | fail_count | pass_rate_on_hard_terms | avg_tcr_on_hard_terms | failed_term_total | retry_needed_count | retry_rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| no_term_baseline | 681 | 369 | 312 | 58 | 311 | 15.72% | 31.25 | 488 | 311 | 45.67% |
| term_baseline | 681 | 369 | 312 | 207 | 162 | 56.10% | 73.53 | 185 | 162 | 23.79% |
| graded_prompt | 681 | 369 | 312 | 218 | 151 | 59.08% | 75.45 | 172 | 151 | 22.17% |

## Error Type Distribution
| group | error_type_distribution | sample_error_type_distribution |
|---|---|---|
| no_term_baseline | `{"alias_only": 42, "missing": 265, "partial": 181}` | `{"alias_only": 20, "missing": 160, "mixed": 56, "none": 370, "partial": 75}` |
| term_baseline | `{"alias_only": 50, "missing": 104, "partial": 31}` | `{"alias_only": 43, "missing": 88, "mixed": 7, "none": 519, "partial": 24}` |
| graded_prompt | `{"alias_only": 44, "missing": 96, "partial": 32}` | `{"alias_only": 43, "missing": 76, "mixed": 6, "none": 530, "partial": 26}` |

## Top Failed Terms
### no_term_baseline
- แบบ -> 型式: 95
- การทดสอบ -> 试验: 54
- GSO -> 海湾标准化组织: 53
- SASO GSO -> 沙特/海湾标准: 50
- климатическое исполнение -> 气候版本: 30
- การรับรองแบบ -> 型式认证: 22
- เครื่อง H-point สามมิติ -> 三维H点装置: 15
- อุปกรณ์ดึง -> 牵引装置: 14
- ไม่มี -> 无: 10
- จุดยึดเข็มขัดนิรภัย -> 安全带固定点: 10
### term_baseline
- GSO -> 海湾标准化组织: 48
- แบบ -> 型式: 33
- климатическое исполнение -> 气候版本: 22
- ไม่มี -> 无: 12
- кондиционер -> 空调器: 7
- สถานที่ตั้ง -> 地址: 6
- การทดสอบ -> 试验: 5
- การรับรองแบบ -> 型式认证: 5
- المركبة الكهربائية -> 电动汽车: 4
- ป้าย -> 标牌: 4
### graded_prompt
- GSO -> 海湾标准化组织: 45
- แบบ -> 型式: 29
- климатическое исполнение -> 气候版本: 22
- ไม่มี -> 无: 12
- การทดสอบ -> 试验: 6
- สถานที่ตั้ง -> 地址: 6
- кондиционер -> 空调器: 6
- SASO GSO -> 沙特/海湾标准: 5
- การรับรองแบบ -> 型式认证: 5
- المركبة الكهربائية -> 电动汽车: 4

## Retry Planning
| group | retry_input | retry_needed_count | retry_rate | retry_success_count | retry_fix_rate | tcr_before_retry | tcr_after_retry | da_delta_after_retry |
|---|---|---:|---:|---|---|---:|---|---|
| no_term_baseline | `/data/llm-translation-poc/lwz/student_experiment_repo/outputs/retry_inputs/source_only_300_by_lang/no_term_baseline_retry_inputs.jsonl` | 311 | 45.67% | not_run | not_run | 31.25 | not_run | not_run |
| term_baseline | `/data/llm-translation-poc/lwz/student_experiment_repo/outputs/retry_inputs/source_only_300_by_lang/term_baseline_retry_inputs.jsonl` | 162 | 23.79% | not_run | not_run | 73.53 | not_run | not_run |
| graded_prompt | `/data/llm-translation-poc/lwz/student_experiment_repo/outputs/retry_inputs/source_only_300_by_lang/graded_prompt_retry_inputs.jsonl` | 151 | 22.17% | not_run | not_run | 75.45 | not_run | not_run |

## Checks
- TCR 只检查 priority=high 且 status=active 的 hard required terms。
- tcr_status 只使用 pass / fail / no_terms。
- no_terms 样本的 tcr_sample 为 null；pass/fail 样本为 0 到 100。
- retry_inputs 只包含 tcr_status=fail 的样本。
- 当前未执行 retry 翻译、DA/COMET，也未调用 API。
