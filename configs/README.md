# Configs

This directory keeps only the active configuration files needed by the current POC.

| File | Purpose |
|---|---|
| `languages.yaml` | Required and optional language directions, priorities, and quality thresholds. |
| `translation.yaml` | Translation model defaults, termbase settings, prompt routing, retry, and output paths. |
| `evaluation.yaml` | TCR, DA/COMET, speed, concurrency, and report field definitions. |

Active split defaults:

- Translation and TCR use `data/eval/splits/source_only_300_by_lang/`.
- DA/COMET reference lookup uses `data/eval/splits/reference_with_ref_300_by_lang/`.

Rules:

- Do not store API keys or local secrets here. Use environment variables.
- Do not add one-off experiment configs unless they are reused by scripts.
- Prefer extending these files instead of adding versioned config copies.
