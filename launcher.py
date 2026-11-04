#!/usr/bin/env python3
"""Compatibility entry point for source and packaged launchers."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.launcher import main
from backend.version import VERSION


if __name__ == "__main__":
    raise SystemExit(main())
