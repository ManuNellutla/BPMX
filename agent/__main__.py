#!/usr/bin/env python3
"""Allow `python3 -m agent ...` from the BPM directory."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
