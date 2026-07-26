# TCR Retry Recheck Summary - All Splits

## Overall
| split | group | retry_input_count | recovered_count | still_fail_count | retry_recovery_rate | avg_tcr_before_retry | avg_tcr_after_retry | avg_tcr_gain | first_pass_pass_count | first_pass_fail_count | samples_with_hard_terms | final_pass_count | final_fail_count | final_pass_rate_on_hard_terms |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| all | all | 501 | 332 | 169 | 66.27% | 8.10 | 78.28 | 70.18 | 201 | 501 | 702 | 533 | 169 | 75.93% |

## Split And Group Details
| split | group | retry_input_count | recovered_count | still_fail_count | retry_recovery_rate | avg_tcr_before_retry | avg_tcr_after_retry | avg_tcr_gain | first_pass_pass_count | first_pass_fail_count | samples_with_hard_terms | final_pass_count | final_fail_count | final_pass_rate_on_hard_terms |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| source_only_300_by_lang | no_term_baseline | 212 | 152 | 60 | 71.70% | 9.22 | 82.31 | 73.09 | 22 | 212 | 234 | 174 | 60 | 74.36% |
| source_only_300_by_lang | term_baseline | 145 | 94 | 51 | 64.83% | 7.15 | 77.95 | 70.80 | 89 | 145 | 234 | 183 | 51 | 78.21% |
| source_only_300_by_lang | graded_prompt | 144 | 86 | 58 | 59.72% | 7.42 | 72.68 | 65.27 | 90 | 144 | 234 | 176 | 58 | 75.21% |

## Scope
- 本汇总仅覆盖 Step 7 retry translation outputs。
- first-pass 指标读取自 Step 6 TCR JSONL。
- 本步骤未执行 retry 翻译、DA/COMET，也未调用外部 API。
