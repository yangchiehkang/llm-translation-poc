# Terminology-Constrained Translation for Standards & Regulations

Compliance review of automotive standards and regulations requires translations in which
*specified terminology is exactly right*. Aggregate machine-translation scores cannot certify
that property. This repository treats terminology as a process-level hard gate and measures the
two things separately.

---

## Motivation

A compliance reviewer does not need a translation that is *generally good*. They need one where
`REESS`, `high voltage bus`, and `type approval authority` are rendered in the exact terms the
regulation defines — because a downstream audit turns on those words and not on fluency.

Neural MT quality metrics are aggregate and reference-based. A translation can score well while
silently substituting a synonym for a controlled term, and can score poorly while being
terminologically perfect. Optimising the score therefore does not optimise the property the
client actually buys.

The pipeline here separates the two: a **term-consistency gate** (injection → check →
retry-repair → re-check) enforces the hard requirement, and **XCOMET-DA** measures general
quality independently. Both are reported. Where they disagree, the disagreement is the finding.

---

## Results

### English (UN R100-03 + R17-10)

Two reporting granularities are in use and both are given, because they answer different
questions. Sentence level is the acceptance basis agreed with the client; segment level is the
earlier frozen basis, retained for comparability.

| Metric | Value | n | Threshold |
| --- | --- | --- | --- |
| XCOMET-DA — sentence level, ≤199 chars | **0.9157** | 665 | 0.90 ✅ |
| XCOMET-DA — sentence level, full | 0.9009 | 911 | — |
| XCOMET-DA — segment level, strict full set | 0.8327 | 689 | — |
| XCOMET-DA — segment level, acceptance subset | 0.8564 | 627 | — |
| Term consistency (TCR) — term level | **97.56%** (1119/1147) | — | 95% ✅ |
| Term consistency (TCR) — sample level | 95.05% (518/545) | — | — |

The ≤199-character band covers 73.0% of all sentences. The acceptance subset removes 9.00% of
segments; every exclusion carries a fact-based, verifiable reason (source truncation, PDF
extraction noise, subscript collapse, reference over-coverage) recorded per row — not "low
score". Rules were defined before they were applied.

**Corpus scope.** English here means two regulations, not "all English". A third
(R016-08) is excluded at document level: 940 source segments against 1871 reference segments,
a count ratio of 0.50, below the alignment gate.

### Terminology gate, isolated

| Configuration | Term level | Sample level |
| --- | --- | --- |
| Before target-side aliases | 93.81% (1076/1147) | 87.89% (479/545) |
| Single-pass baseline | 96.51% (1107/1147) | 92.84% (506/545) |
| With reranking | 97.56% (1119/1147) | 95.05% (518/545) |

### Cross-language

Seven language pairs, each a different body of law with its own Chinese reference document —
not translations of one shared source.

| Pair | Alignment method | Aligned units | DA | TCR | Status |
| --- | --- | --- | --- | --- | --- |
| en–zh | scoped exact section match | 689 | 0.9157 (sent.) | 97.56% | ✅ delivered |
| ru–zh | exact + clause-number normalisation | 116 (135 sent.) | 0.8525 | 97.62% | ✅ meets 0.85 |
| fr–zh | exact + code-style clause IDs (`Article L541-9`) | 117 sent. | 0.7819 | 97.34% | ❌ DA short by 0.0181 |
| de–zh | `§ N` clause detection + enumeration merge | 32 (49 sent.) | 0.8399 | 64.7% | ❌ TCR short, n ≪ 100 |
| th–zh | Thai numeral transliteration + order-based | 21 | 0.4199 (seg.) | 80% (15 inst.) | ❌ far short |
| ar–zh | geometric extraction + bidi reordering | 0 | — | — | ❌ clause-ID location fails |
| es–zh | exact | 3 | — | — | ❌ source material insufficient |

The ru/fr/de/th DA figures, their length bands and their provenance are in
`results/cross_language_summary.json`; en is in `results/en_zh_689_summary.json`.

The binding constraint is almost never translation quality — it is **extraction and alignment**.
Source-side character recovery ranges from 91.6% (ru) to 2.8% (de) to 0% (ar). A pair with no
aligned units has no translation problem to measure yet.

### The number that does not ship

Every figure above comes from the *evaluation* configuration, which differs from production in
four respects. The fourth is load-bearing and is not a backlog item:

> The reranking stage cannot run in production. At 6000 characters × 4 candidates it exceeds the
> 120-second contractual latency ceiling. Falling back to the single-pass arm costs −0.0145
> sentence-level DA and drops the 100–199 character band below 0.90.

The single-pass arm that *does* ship has ample headroom — measured end-to-end over 40 requests,
all HTTP 200:

| Input length (chars) | n | p50 (s) | p95 (s) |
| --- | --- | --- | --- |
| 1000 | 8 | 4.32 | 5.07 |
| 2000 | 16 | 8.00 | 10.18 |
| 4000 | 8 | 16.89 | 18.23 |
| 6000 | 8 | 21.26 | 24.12 |

24.12s against a 120s ceiling at the worst supported input length. The ceiling is not what
blocks reranking at a single-candidate cost — four candidates is.

This is a capability limit, not an unshipped feature. Quoting 0.9157 without it would be
quoting a configuration that cannot be deployed.

Measured single-pass latency (40 requests, all HTTP 200) shows where the headroom goes:

| Input chars | n | p50 (s) | p95 (s) |
| --- | --- | --- | --- |
| 1000 | 8 | 4.32 | 5.07 |
| 2000 | 16 | 8.00 | 10.18 |
| 4000 | 8 | 16.89 | 18.23 |
| 6000 | 8 | 21.26 | 24.12 |

Single-pass at 6000 characters has ample margin against the 120-second ceiling. Four candidates
do not.

---

## Method

```
termbase (three-tier)
      │
      ├─► term injection ──► first translation
      │                            │
      │                      TCR check ──── pass ──► accept
      │                            │
      │                          fail
      │                            │
      └─────────────► retry-repair (source + current translation + missed terms)
                                   │
                             TCR re-check ──► accept only if the failure set strictly shrinks
```

Two design decisions worth naming:

- **Longest-match span occupancy in term matching.** A naive word-boundary matcher counts
  `shall` as required inside `shall not`, and `cell` inside `single cell internal short
  circuit`. The matcher assigns text spans to the longest matching term and suppresses shorter
  terms fully contained in an occupied span. This is a denominator correction, not a target
  relaxation — the affected terms were never genuinely required.
- **Strict-subset guardrail on retry.** Retry-repair returns a full translation, not a patch, so
  a repair can fix one term and break another. A repaired output is accepted only when its
  failure set is a strict subset of the original. Without the guard, gross recovery is partly
  cancelled by regressions.

Evaluation uses XCOMET-XXL for DA. QE is used only as a data-cleaning signal, never as a
reported metric.

---

## Repository layout

```
api/          FastAPI service — contract layer, auth, backends, deploy units
  backends/     DashScope and local-NPU translation backends
  examples/     request/response fixtures and a regression harness
configs/      language, translation and evaluation configuration
docs/         pipeline design, acceptance criteria, experiment plans, backlog
results/      aggregate result files backing every number in this README
scripts/      preprocessing, translation, termbase, evaluation, analysis, reporting
termbase/     termbase schema and documentation
```

Corpora, model outputs, per-row scores and the termbase itself are not published. `results/`
contains only aggregate figures; each file names the run it came from.

---

## How to run

```bash
pip install -r scripts/requirements.txt   # pipeline; versions pinned deliberately
pip install -r api/requirements.txt       # service only
cp api/.env.example .env                  # project root, not api/ — fill in tokens
```

Alignment and corpus construction:

```bash
python scripts/evaluation/prepare_da_pairs.py --mode from_raw \
    --raw-dir data/raw --only-language-pair en-zh --output-dir data/eval
python scripts/evaluation/prepare_da_pairs.py --mode selftest_canonical   # 18 unit checks
```

Term recall, then translation through the terminology gate:

```bash
python scripts/termbase/term_recall.py --mode build_prompt_experiment_inputs \
    --input <split>.jsonl --output-dir outputs/experiment_inputs/<split> \
    --termbase termbase/auto_regulation_terms_v1.csv

python scripts/translation/run_prompt_compare_first.py \
    --input-dir outputs/experiment_inputs/<split> \
    --output-dir outputs/translations/<split>/first \
    --split-name <split> --model qwen-max --temperature 0.0
```

Term-consistency check, then DA scoring:

```bash
python scripts/evaluation/check_tcr.py \
    --input <translations>.jsonl --output <tcr>.jsonl --summary <tcr_summary>.json \
    --termbase termbase/auto_regulation_terms_v1.csv --scope hard

python scripts/evaluation/run_xcomet.py --mode da \
    --input <xcomet_inputs>.jsonl --output <da_scores>.jsonl \
    --model-path <XCOMET-XXL>/checkpoints/model.ckpt --device npu:0 --batch-size 8

python scripts/evaluation/build_sentence_pairs.py \
    --scores <da_scores>.jsonl --out-pairs <sent_pairs>.jsonl --out-map <sent_map>.jsonl
```

The XCOMET-XXL checkpoint (~40 GB) is not included; its path is passed with `--model-path`,
not read from a config file. `--device` defaults to `cuda` and accepts `npu:N` (requires
`torch_npu`). Scoring was run on Ascend NPU in bf16; the bf16-vs-fp32 calibration offset is
+0.0015 mean.

Service:

```bash
API_VENV=<venv> bash api/deploy/run.sh
```

`run.sh` reads `.env` from the project root. `PORT` has no default — the script refuses to
start rather than silently bind the wrong port.

---

## Notes

- Source PDFs, extracted references and the termbase are client materials and are not
  redistributed here.
- The DA target of 0.90 is treated as a metric-calibration question rather than a pure
  translation target. XCOMET-XXL systematically underscores Chinese legal translation, and in
  reviewed cases the translation was better than the reference while scoring lower. The strict
  full-set number and the defect-removed subset are both reported so the gap is auditable.
- Superseded figures that appear in older commits and must not be reused: the 615-row
  (DA 0.8567) and 432-row English corpora, and the pre-fix TCR of 88.79%.

---

## Author

**Jiekang Yang** — project lead, MSc Computer & Information Engineering,
The Chinese University of Hong Kong, Shenzhen. Advisor: Prof. Xiaoying Tang.
Three-person team; March 2026 – present.
