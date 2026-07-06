#!/usr/bin/env python3
"""Compatibility wrapper for the canonical XCOMET runner.

Use scripts/evaluation/run_xcomet.py for new workflows. This entrypoint stays
available so older commands do not silently break.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.evaluation.run_xcomet import main


if __name__ == "__main__":
    print(
        "[DEPRECATED] scripts/evaluation/xcomet_score.py now delegates to "
        "scripts/evaluation/run_xcomet.py.",
        file=sys.stderr,
    )
    main()
