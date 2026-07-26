# TCR Summary - de

## Group Comparison
| group | total_samples | samples_with_hard_terms | no_terms_count | pass_count | fail_count | pass_rate_on_hard_terms | avg_tcr_on_hard_terms | failed_term_total | retry_needed_count | retry_rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| no_term_baseline | 300 | 234 | 66 | 22 | 212 | 9.40% | 17.75 | 355 | 212 | 70.67% |
| term_baseline | 300 | 234 | 66 | 89 | 145 | 38.03% | 42.46 | 249 | 145 | 48.33% |
| graded_prompt | 300 | 234 | 66 | 90 | 144 | 38.46% | 43.02 | 247 | 144 | 48.00% |

## Error Type Distribution
| group | error_type_distribution | sample_error_type_distribution |
|---|---|---|
| no_term_baseline | `{"alias_only": 5, "missing": 269, "partial": 81}` | `{"alias_only": 3, "missing": 142, "mixed": 26, "none": 88, "partial": 41}` |
| term_baseline | `{"alias_only": 2, "missing": 210, "partial": 37}` | `{"alias_only": 1, "missing": 114, "mixed": 13, "none": 155, "partial": 17}` |
| graded_prompt | `{"alias_only": 6, "missing": 200, "partial": 41}` | `{"alias_only": 5, "missing": 108, "mixed": 12, "none": 156, "partial": 19}` |

## Top Failed Terms
### no_term_baseline
- Betriebserlaubnis -> 运行许可: 115
- Allgemeine Betriebserlaubnis -> 一般运行许可: 38
- Betriebserlaubnis für Einzelfahrzeuge -> 单车运行许可: 32
- Abfall -> 废弃物: 22
- Prüfung -> 试验: 19
- Nachweis -> 证明文件: 13
- Abfallvermeidung -> 废弃物预防: 8
- Vermeidung -> 预防: 7
- Entsorgungsträger -> 废弃物处理主体: 7
- Verwertung -> 利用: 4
### term_baseline
- Betriebserlaubnis -> 运行许可: 114
- Allgemeine Betriebserlaubnis -> 一般运行许可: 37
- Betriebserlaubnis für Einzelfahrzeuge -> 单车运行许可: 31
- Prüfung -> 试验: 15
- Nachweis -> 证明文件: 8
- Abfall -> 废弃物: 8
- Abfallvermeidung -> 废弃物预防: 4
- Vermeidung -> 预防: 3
- Bereifung -> 轮胎配置: 3
- Vermüllung -> 乱扔垃圾: 2
### graded_prompt
- Betriebserlaubnis -> 运行许可: 114
- Allgemeine Betriebserlaubnis -> 一般运行许可: 37
- Betriebserlaubnis für Einzelfahrzeuge -> 单车运行许可: 31
- Prüfung -> 试验: 15
- Nachweis -> 证明文件: 8
- Abfall -> 废弃物: 7
- Abfallvermeidung -> 废弃物预防: 3
- Bereifung -> 轮胎配置: 3
- Entsorgungsträger -> 废弃物处理主体: 2
- Kreislaufwirtschaftsgesetz -> 循环经济法: 2

## Retry Planning
| group | retry_input | retry_needed_count | retry_rate | retry_success_count | retry_fix_rate | tcr_before_retry | tcr_after_retry | da_delta_after_retry |
|---|---|---:|---:|---|---|---:|---|---|
| no_term_baseline | `/data/yht/llm-translation-poc-dev-yangjiekang/outputs/retry_inputs/de/no_term_baseline_retry_inputs.jsonl` | 212 | 70.67% | not_run | not_run | 17.75 | not_run | not_run |
| term_baseline | `/data/yht/llm-translation-poc-dev-yangjiekang/outputs/retry_inputs/de/term_baseline_retry_inputs.jsonl` | 145 | 48.33% | not_run | not_run | 42.46 | not_run | not_run |
| graded_prompt | `/data/yht/llm-translation-poc-dev-yangjiekang/outputs/retry_inputs/de/graded_prompt_retry_inputs.jsonl` | 144 | 48.00% | not_run | not_run | 43.02 | not_run | not_run |

## Checks
- TCR 只检查 priority=high 且 status=active 的 hard required terms。
- tcr_status 只使用 pass / fail / no_terms。
- no_terms 样本的 tcr_sample 为 null；pass/fail 样本为 0 到 100。
- retry_inputs 只包含 tcr_status=fail 的样本。
- 当前未执行 retry 翻译、DA/COMET，也未调用 API。
