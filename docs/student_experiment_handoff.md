# Student Experiment Handoff

本说明给参与实验的学生使用。目标是复用仓库已有脚本，完成三组翻译、TCR、retry、retry recheck 和 XCOMET-DA/COMET 评分链路。

## 1. 分支和数据

```bash
git clone -b dev/yangjiekang https://github.com/yangchiehkang/llm-translation-poc.git
cd llm-translation-poc
```

本轮只使用两套配对 split：

| 用途 | 路径 |
|---|---|
| 翻译和 TCR 源文 | `data/eval/splits/source_only_300_by_lang/all_samples_source_only.jsonl` |
| DA/COMET 参考译文 | `data/eval/splits/reference_with_ref_300_by_lang/all_samples_with_reference.jsonl` |

注意：翻译阶段只能使用 source-only 文件，不能把 `ref_text` 放进 prompt 或翻译输入。

## 2. 建议分工

| 角色 | 负责内容 |
|---|---|
| 学生 A | 本地数据检查、生成三组 Prompt 输入、首译 TCR、retry recheck、构建 XCOMET 输入、汇总报告。 |
| 学生 B | 服务器首译、服务器 retry 翻译、服务器 XCOMET-DA/COMET 评分、运行日志记录。 |

两个人每一步都要共同确认 row count、success count 和 sample_id 是否一致。

## 3. 数据检查

```bash
python - <<'PY'
import json
from pathlib import Path

src = Path("data/eval/splits/source_only_300_by_lang/all_samples_source_only.jsonl")
ref = Path("data/eval/splits/reference_with_ref_300_by_lang/all_samples_with_reference.jsonl")
src_rows = [json.loads(line) for line in src.open(encoding="utf-8") if line.strip()]
ref_rows = [json.loads(line) for line in ref.open(encoding="utf-8") if line.strip()]
assert len(src_rows) == len(ref_rows), (len(src_rows), len(ref_rows))
assert not any("ref_text" in row for row in src_rows)
assert all(
    (s.get("sample_id"), s.get("da_reference_id"), s.get("source_text"))
    == (r.get("sample_id"), r.get("da_reference_id"), r.get("source_text"))
    for s, r in zip(src_rows, ref_rows)
)
print({"rows": len(src_rows), "paired": True, "source_has_ref_text": False})
PY
```

预期当前 rows 为 `1648`。

## 4. 生成三组 Prompt 输入

```bash
python scripts/termbase/term_recall.py \
  --mode build_prompt_experiment_inputs \
  --input data/eval/splits/source_only_300_by_lang/all_samples_source_only.jsonl \
  --output-dir outputs/experiment_inputs/source_only_300_by_lang
```

生成三组输入：

- `outputs/experiment_inputs/source_only_300_by_lang/no_term_baseline.jsonl`
- `outputs/experiment_inputs/source_only_300_by_lang/term_baseline.jsonl`
- `outputs/experiment_inputs/source_only_300_by_lang/graded_prompt.jsonl`

## 5. 三组首译

服务器本地模型示例：

```bash
python scripts/translation/run_prompt_compare_first_local_npu.py \
  --input-dir outputs/experiment_inputs/source_only_300_by_lang \
  --output-dir outputs/translations/source_only_300_by_lang/first \
  --split-name source_only_300_by_lang \
  --model-path /data/MODEL_DIR/Qwen2.5-14B-Instruct \
  --device npu:0 \
  --batch-size 1 \
  --resume
```

如果使用 DashScope/Qwen-Max，改用：

```bash
python scripts/translation/run_prompt_compare_first.py \
  --input-dir outputs/experiment_inputs/source_only_300_by_lang \
  --output-dir outputs/translations/source_only_300_by_lang/first \
  --split-name source_only_300_by_lang \
  --resume
```

运行前需要在服务器上设置 `DASHSCOPE_API_KEY`。

首译完成后必须确认三组输出都存在，且成功样本集合一致：

- `outputs/translations/source_only_300_by_lang/first/no_term_baseline_first_translations.jsonl`
- `outputs/translations/source_only_300_by_lang/first/term_baseline_first_translations.jsonl`
- `outputs/translations/source_only_300_by_lang/first/graded_prompt_first_translations.jsonl`

## 6. 首译 TCR 和 retry 输入

```bash
python scripts/evaluation/tcr_check.py \
  --mode first_pass \
  --split-name source_only_300_by_lang \
  --translation-dir outputs/translations/source_only_300_by_lang/first \
  --output-dir outputs/evaluation/tcr/source_only_300_by_lang \
  --retry-output-dir outputs/retry_inputs/source_only_300_by_lang
```

重点产物：

- `outputs/evaluation/tcr/source_only_300_by_lang/tcr_summary.md`
- `outputs/retry_inputs/source_only_300_by_lang/*_retry_inputs.jsonl`

## 7. retry 翻译

对三个 group 分别跑：

```bash
for group in no_term_baseline term_baseline graded_prompt; do
  python scripts/translation/retry_translate_local.py \
    --split source_only_300_by_lang \
    --group "$group" \
    --model-path /data/MODEL_DIR/Qwen2.5-14B-Instruct \
    --device npu:0 \
    --batch-size 1 \
    --resume
done
```

retry 输出默认写入：

- `outputs/translations_retry/source_only_300_by_lang/*_retry_translations.jsonl`

## 8. retry recheck

```bash
python scripts/evaluation/tcr_check.py \
  --mode retry_recheck \
  --split-name source_only_300_by_lang \
  --first-tcr-dir outputs/evaluation/tcr \
  --retry-translation-dir outputs/translations_retry \
  --output-dir outputs/evaluation/tcr_retry
```

重点产物：

- `outputs/evaluation/tcr_retry/source_only_300_by_lang/tcr_retry_summary.md`
- `outputs/evaluation/tcr_retry/tcr_retry_summary_all.md`

## 9. 构建 XCOMET-DA/COMET 输入

```bash
python scripts/evaluation/build_xcomet_inputs.py \
  --splits source_only_300_by_lang \
  --reference-split reference_with_ref_300_by_lang \
  --stages first_pass final \
  --strict
```

输出：

- `outputs/evaluation/xcomet/inputs/da_source_only_300_by_lang.jsonl`
- `outputs/evaluation/xcomet/inputs/build_xcomet_inputs_summary.json`

## 10. XCOMET-DA/COMET 评分

服务器评分示例：

```bash
python scripts/evaluation/run_xcomet.py \
  --mode da \
  --input outputs/evaluation/xcomet/inputs/da_source_only_300_by_lang.jsonl \
  --output outputs/evaluation/xcomet/da/da_source_only_300_by_lang.jsonl \
  --model-path /path/to/local/xcomet/checkpoint \
  --device npu:0 \
  --batch-size 8 \
  --resume
```

`--model-path` 必须是服务器本地已有的 COMET/XCOMET checkpoint；脚本不会联网下载模型。

## 11. 汇总 XCOMET

```bash
python scripts/evaluation/summarize_xcomet.py \
  --inputs outputs/evaluation/xcomet/da/da_source_only_300_by_lang.jsonl \
  --output outputs/evaluation/xcomet/summary/xcomet_summary.md
```

## 12. 最终交付

完成后至少交付这些文件或截图：

- `outputs/evaluation/tcr/source_only_300_by_lang/tcr_summary.md`
- `outputs/evaluation/tcr_retry/source_only_300_by_lang/tcr_retry_summary.md`
- `outputs/evaluation/tcr_retry/tcr_retry_summary_all.md`
- `outputs/evaluation/xcomet/inputs/build_xcomet_inputs_summary.json`
- `outputs/evaluation/xcomet/summary/xcomet_summary.md`
- 三组首译、retry 和 XCOMET 运行日志

## 13. 必查项

- 三组首译使用同一批 `sample_id`。
- source-only 翻译输入不包含 `ref_text`。
- retry 输出行数等于 retry input 行数，且成功样本没有空译文。
- `tcr_status_after_retry` 只允许 `pass`、`fail`、`no_terms`。
- `recovered` 必须表示 before=`fail` 且 after=`pass`。
- `still_fail` 必须表示 before=`fail` 且 after=`fail`。
- XCOMET 输入必须有 `source_text`、`hypothesis_translation`、`ref_text`。
