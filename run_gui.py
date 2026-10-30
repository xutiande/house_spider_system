#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GUI 入口：python run_gui.py"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

sys.path.insert(0, str(ROOT))

from gui.app import run  # noqa: E402

if __name__ == "__main__":
    sys.exit(run())
