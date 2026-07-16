# Retry Recheck Summary - 俄语 → 中文

语言标识：`ru-zh`

## 恢复结果

| 组别 | Retry 数 | 修复成功 | 仍失败 | 修复率 | Retry 前平均 TCR | Retry 后平均 TCR | 平均增益 | 最终硬术语通过率 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| no_term_baseline | 71 | 59 | 12 | 83.10% | 11.55 | 90.70 | 79.15 | 87.23% |
| term_baseline | 40 | 32 | 8 | 80.00% | 26.00 | 92.13 | 66.12 | 91.49% |
| graded_prompt | 36 | 29 | 7 | 80.56% | 22.87 | 90.79 | 67.92 | 92.55% |

## 结论

- Retry 后最终硬术语通过率最高的是 `graded_prompt`：92.55%。
- `recovered` 表示首译 fail、retry 后 pass；`still_fail` 表示两次均 fail。
