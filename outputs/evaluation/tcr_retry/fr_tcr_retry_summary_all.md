# TCR Retry Recheck Summary - All Splits

## Overall
| split | group | retry_input_count | recovered_count | still_fail_count | retry_recovery_rate | avg_tcr_before_retry | avg_tcr_after_retry | avg_tcr_gain | first_pass_pass_count | first_pass_fail_count | samples_with_hard_terms | final_pass_count | final_fail_count | final_pass_rate_on_hard_terms |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| all | all | 439 | 264 | 175 | 60.14% | 37.75 | 86.43 | 48.68 | 341 | 439 | 780 | 605 | 175 | 77.56% |

## Split And Group Details
| split | group | retry_input_count | recovered_count | still_fail_count | retry_recovery_rate | avg_tcr_before_retry | avg_tcr_after_retry | avg_tcr_gain | first_pass_pass_count | first_pass_fail_count | samples_with_hard_terms | final_pass_count | final_fail_count | final_pass_rate_on_hard_terms |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| source_only_300_by_lang | no_term_baseline | 221 | 152 | 69 | 68.78% | 27.62 | 90.15 | 62.53 | 39 | 221 | 260 | 191 | 69 | 73.46% |
| source_only_300_by_lang | term_baseline | 115 | 60 | 55 | 52.17% | 47.98 | 81.87 | 33.89 | 145 | 115 | 260 | 205 | 55 | 78.85% |
| source_only_300_by_lang | graded_prompt | 103 | 52 | 51 | 50.49% | 48.06 | 83.53 | 35.47 | 157 | 103 | 260 | 209 | 51 | 80.38% |

## Scope
- 本汇总仅覆盖 Step 7 retry translation outputs。
- first-pass 指标读取自 Step 6 TCR JSONL。
- 本步骤未执行 retry 翻译、DA/COMET，也未调用外部 API。
