# Retry Recheck Summary - 泰语 → 中文

语言标识：`th-zh`

## 恢复结果

| 组别 | Retry 数 | 修复成功 | 仍失败 | 修复率 | Retry 前平均 TCR | Retry 后平均 TCR | 平均增益 | 最终硬术语通过率 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| no_term_baseline | 178 | 155 | 23 | 87.08% | 26.29 | 95.59 | 69.30 | 89.05% |
| term_baseline | 65 | 49 | 16 | 75.38% | 42.27 | 92.80 | 50.53 | 92.38% |
| graded_prompt | 59 | 46 | 13 | 77.97% | 43.46 | 92.83 | 49.38 | 93.81% |

## 结论

- Retry 后最终硬术语通过率最高的是 `graded_prompt`：93.81%。
- `recovered` 表示首译 fail、retry 后 pass；`still_fail` 表示两次均 fail。
