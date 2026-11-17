#!/usr/bin/env python3
"""Entry point so both `python3 atlas.py ...` and `python3 -m . ...` work from this folder."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
