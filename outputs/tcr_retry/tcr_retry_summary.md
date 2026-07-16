# TCR Retry Recheck Summary - source_only_300_by_lang

## Recovery Summary
| split | group | retry_input_count | recovered_count | still_fail_count | retry_recovery_rate | avg_tcr_before_retry | avg_tcr_after_retry | avg_tcr_gain | first_pass_pass_count | first_pass_fail_count | samples_with_hard_terms | final_pass_count | final_fail_count | final_pass_rate_on_hard_terms |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| source_only_300_by_lang | no_term_baseline | 311 | 252 | 59 | 81.03% | 18.43 | 91.50 | 73.07 | 58 | 311 | 369 | 310 | 59 | 84.01% |
| source_only_300_by_lang | term_baseline | 162 | 127 | 35 | 78.40% | 39.71 | 92.10 | 52.39 | 207 | 162 | 369 | 334 | 35 | 90.51% |
| source_only_300_by_lang | graded_prompt | 151 | 119 | 32 | 78.81% | 40.00 | 91.38 | 51.38 | 218 | 151 | 369 | 337 | 32 | 91.33% |

## Files
| group | retry_translation_input | first_pass_tcr_input | retry_tcr_output |
|---|---|---|---|
| no_term_baseline | `/data/llm-translation-poc/lwz/student_experiment_repo/outputs/translations_retry/source_only_300_by_lang/no_term_baseline_retry_translations.jsonl` | `/data/llm-translation-poc/lwz/student_experiment_repo/outputs/evaluation/tcr/source_only_300_by_lang/no_term_baseline_tcr.jsonl` | `/data/llm-translation-poc/lwz/student_experiment_repo/outputs/evaluation/tcr_retry/source_only_300_by_lang/no_term_baseline_retry_tcr.jsonl` |
| term_baseline | `/data/llm-translation-poc/lwz/student_experiment_repo/outputs/translations_retry/source_only_300_by_lang/term_baseline_retry_translations.jsonl` | `/data/llm-translation-poc/lwz/student_experiment_repo/outputs/evaluation/tcr/source_only_300_by_lang/term_baseline_tcr.jsonl` | `/data/llm-translation-poc/lwz/student_experiment_repo/outputs/evaluation/tcr_retry/source_only_300_by_lang/term_baseline_retry_tcr.jsonl` |
| graded_prompt | `/data/llm-translation-poc/lwz/student_experiment_repo/outputs/translations_retry/source_only_300_by_lang/graded_prompt_retry_translations.jsonl` | `/data/llm-translation-poc/lwz/student_experiment_repo/outputs/evaluation/tcr/source_only_300_by_lang/graded_prompt_tcr.jsonl` | `/data/llm-translation-poc/lwz/student_experiment_repo/outputs/evaluation/tcr_retry/source_only_300_by_lang/graded_prompt_retry_tcr.jsonl` |

## Checks
- TCR 口径复用 Step 6 hard-term TCR 逻辑。
- 只检查 priority=high 且 status=active 的 hard required terms。
- tcr_status_after_retry 只使用 pass / fail / no_terms。
- no_terms 样本的 tcr_sample_after_retry 为 null；pass/fail 样本为 0 到 100。
- recovered = tcr_status_before_retry == fail 且 tcr_status_after_retry == pass。
- still_fail = tcr_status_before_retry == fail 且 tcr_status_after_retry == fail。
- first-pass 指标读取自 Step 6 TCR JSONL，不手工硬编码。
- 本步骤未执行 retry 翻译、DA/COMET，也未调用外部 API。

Retry translation dir: `/data/llm-translation-poc/lwz/student_experiment_repo/outputs/translations_retry/source_only_300_by_lang`
First-pass TCR dir: `/data/llm-translation-poc/lwz/student_experiment_repo/outputs/evaluation/tcr/source_only_300_by_lang`
