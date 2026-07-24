#!/usr/bin/env python3
"""Shared pytest setup: make full/*.py importable as plain modules."""

import sys
from pathlib import Path

FULL_DIR = Path(__file__).resolve().parent.parent / "full"
if str(FULL_DIR) not in sys.path:
    sys.path.insert(0, str(FULL_DIR))
