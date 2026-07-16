# Retry Recheck Summary - 阿拉伯语 → 中文

语言标识：`ar-zh`

## 恢复结果

| 组别 | Retry 数 | 修复成功 | 仍失败 | 修复率 | Retry 前平均 TCR | Retry 后平均 TCR | 平均增益 | 最终硬术语通过率 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| no_term_baseline | 62 | 38 | 24 | 61.29% | 3.74 | 80.68 | 76.94 | 63.08% |
| term_baseline | 57 | 46 | 11 | 80.70% | 46.41 | 91.27 | 44.86 | 83.08% |
| graded_prompt | 56 | 44 | 12 | 78.57% | 47.36 | 90.22 | 42.86 | 81.54% |

## 结论

- Retry 后最终硬术语通过率最高的是 `term_baseline`：83.08%。
- `recovered` 表示首译 fail、retry 后 pass；`still_fail` 表示两次均 fail。
