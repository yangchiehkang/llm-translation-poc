# TCR Retry Recheck Summary - All Splits

## Overall
| split | group | retry_input_count | recovered_count | still_fail_count | retry_recovery_rate | avg_tcr_before_retry | avg_tcr_after_retry | avg_tcr_gain | first_pass_pass_count | first_pass_fail_count | samples_with_hard_terms | final_pass_count | final_fail_count | final_pass_rate_on_hard_terms |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| all | all | 48 | 38 | 10 | 79.17% | 25.94 | 94.58 | 68.65 | 63 | 48 | 111 | 101 | 10 | 90.99% |

## Split And Group Details
| split | group | retry_input_count | recovered_count | still_fail_count | retry_recovery_rate | avg_tcr_before_retry | avg_tcr_after_retry | avg_tcr_gain | first_pass_pass_count | first_pass_fail_count | samples_with_hard_terms | final_pass_count | final_fail_count | final_pass_rate_on_hard_terms |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| source_only_300_by_lang | no_term_baseline | 33 | 29 | 4 | 87.88% | 16.21 | 96.87 | 80.66 | 4 | 33 | 37 | 33 | 4 | 89.19% |
| source_only_300_by_lang | term_baseline | 8 | 5 | 3 | 62.50% | 45.42 | 89.17 | 43.75 | 29 | 8 | 37 | 34 | 3 | 91.89% |
| source_only_300_by_lang | graded_prompt | 7 | 4 | 3 | 57.14% | 49.52 | 90.00 | 40.48 | 30 | 7 | 37 | 34 | 3 | 91.89% |

## Scope
- 本汇总仅覆盖 Step 7 retry translation outputs。
- first-pass 指标读取自 Step 6 TCR JSONL。
- 本步骤未执行 retry 翻译、DA/COMET，也未调用外部 API。
