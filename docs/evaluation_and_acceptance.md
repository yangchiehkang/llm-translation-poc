# 评价与验收口径

## 1. 总体原则

法规翻译不能只看一个自动分数。本项目采用组合评价：

| 指标 | 作用 |
|---|---|
| TCR | 检查硬术语是否使用指定译法，是法规翻译的硬门禁。 |
| XCOMET-QE | 无参考质量估计，用于覆盖 all_eval 样本的整体质量监控。 |
| XCOMET-DA / COMET | 有参考评价，只在可信 ref_text 样本上使用。 |
| retry 效果 | 观察 TCR fail 样本经过局部修复后能否恢复。 |
| 人工复核 | 用于判断自动指标冲突、术语争议和高风险法规表达。 |

当前阶段最主要的两个报告维度是 TCR 和 XCOMET-QE/DA。

## 2. TCR 口径

TCR 只统计源文命中的硬术语，即 `priority=high` 且 `status=active` 的术语。一个硬术语通过的条件是：译文中出现术语库指定的 required target term。

样本级状态：

| 状态 | 含义 |
|---|---|
| `pass` | 样本包含硬术语，且所有 required target terms 均通过。 |
| `fail` | 样本包含硬术语，但至少一个 required target term 未通过。 |
| `no_terms` | 样本没有硬术语，不计入 hard-term pass rate。 |

报告中优先看：

- hard-term pass rate
- avg TCR on hard terms
- failed term total
- retry_needed_count
- final pass rate after retry

## 3. Retry 口径

retry 只针对首译 TCR fail 样本。它的目的不是重写整句，而是尽量在保持原译文整体表达的基础上修复明确失败的术语。

主要指标：

| 指标 | 含义 |
|---|---|
| retry_input_count | 进入 retry 的样本数。 |
| recovered_count | retry 后从 fail 变为 pass 的样本数。 |
| still_fail_count | retry 后仍为 fail 的样本数。 |
| retry_recovery_rate | recovered_count / retry_input_count。 |
| final_pass_rate | 首译已 pass 样本加 retry recovered 样本后的最终通过率。 |

解读时要同时看 XCOMET：如果 retry 明显提升 TCR 但降低 QE / DA，需要抽检是否出现表达生硬、局部替换破坏语义或法规语气变化。

## 4. XCOMET-QE 口径

XCOMET-QE 不使用参考译文，适合覆盖全部可翻译样本。它主要用于观察不同 Prompt 策略下译文整体质量、自然度和明显错误风险。

使用限制：

- QE 不能替代 TCR，因为法规术语必须满足指定译法。
- QE 不能替代 DA 或人工复核，因为无参考评价可能偏好自然表达而忽略术语硬约束。
- 当 no-term baseline 的 QE 更高但 TCR 更低时，应优先说明这是“自然质量与术语一致性”的权衡。

## 5. XCOMET-DA / COMET 口径

DA / COMET 需要参考译文，因此只在可信对齐样本上使用。当前实验区分：

| 范围 | 用途 |
|---|---|
| all_eval_samples | 用于翻译、TCR 和 QE。 |
| aligned_da_samples | 用于 DA / COMET，有较可靠 ref_text。 |

DA 结果不应强行外推到没有可靠参考译文的语种或样本类型。报告中必须说明 DA 的样本范围。

## 6. 三组结果解释口径

| 组别 | 推荐解释 |
|---|---|
| `no_term_baseline` | 自动质量分可能较高，但术语一致性风险最大。 |
| `term_baseline` | 注入术语后 TCR 明显提升，是主要 baseline。 |
| `graded_prompt` | 在术语 baseline 基础上观察分层路由是否继续提升 TCR、减少 retry 或保护 XCOMET。 |

如果 `graded_prompt` 的 TCR 提升但 XCOMET 未提升，应表述为“分层 Prompt 对硬术语一致性有收益，但整体自动质量分未显示稳定优势”。

## 7. 当前阶段验收重点

当前阶段不按生产验收阈值做最终判定，而看实验问题是否被回答：

- 三组是否使用同一批样本、同一模型、同一术语库和同一评价口径。
- 三组是否都有 TCR 首译、retry 后 recheck、XCOMET-QE 和 XCOMET-DA / COMET。
- 分层 Prompt 是否在 TCR 上优于不分层术语 Prompt。
- 分层 Prompt 是否带来 QE / DA 副作用。
- retry 是否提高 final TCR，同时是否降低自动质量分。

当前本轮报告已经覆盖上述核心问题；数字一致率、格式保持率和人工复核仍属于后续补充评价。
