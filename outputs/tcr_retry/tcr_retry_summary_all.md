# TCR Retry Recheck Summary - All Splits

## Overall
| split | group | retry_input_count | recovered_count | still_fail_count | retry_recovery_rate | avg_tcr_before_retry | avg_tcr_after_retry | avg_tcr_gain | first_pass_pass_count | first_pass_fail_count | samples_with_hard_terms | final_pass_count | final_fail_count | final_pass_rate_on_hard_terms |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| all | all | 624 | 498 | 126 | 79.81% | 29.17 | 91.63 | 62.45 | 483 | 624 | 1107 | 981 | 126 | 88.62% |

## Split And Group Details
| split | group | retry_input_count | recovered_count | still_fail_count | retry_recovery_rate | avg_tcr_before_retry | avg_tcr_after_retry | avg_tcr_gain | first_pass_pass_count | first_pass_fail_count | samples_with_hard_terms | final_pass_count | final_fail_count | final_pass_rate_on_hard_terms |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| source_only_300_by_lang | no_term_baseline | 311 | 252 | 59 | 81.03% | 18.43 | 91.50 | 73.07 | 58 | 311 | 369 | 310 | 59 | 84.01% |
| source_only_300_by_lang | term_baseline | 162 | 127 | 35 | 78.40% | 39.71 | 92.10 | 52.39 | 207 | 162 | 369 | 334 | 35 | 90.51% |
| source_only_300_by_lang | graded_prompt | 151 | 119 | 32 | 78.81% | 40.00 | 91.38 | 51.38 | 218 | 151 | 369 | 337 | 32 | 91.33% |

## Scope
- 本汇总仅覆盖 Step 7 retry translation outputs。
- first-pass 指标读取自 Step 6 TCR JSONL。
- 本步骤未执行 retry 翻译、DA/COMET，也未调用外部 API。
