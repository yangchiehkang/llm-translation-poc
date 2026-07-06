# Configs

This directory keeps only the active configuration files needed by the current POC.

| File | Purpose |
|---|---|
| `languages.yaml` | Required and optional language directions, priorities, and quality thresholds. |
| `translation.yaml` | Translation model defaults, termbase settings, prompt routing, retry, and output paths. |
| `evaluation.yaml` | TCR, QE, DA, speed, concurrency, and report field definitions. |

Rules:

- Do not store API keys or local secrets here. Use environment variables.
- Do not add one-off experiment configs unless they are reused by scripts.
- Prefer extending these files instead of adding versioned config copies.
