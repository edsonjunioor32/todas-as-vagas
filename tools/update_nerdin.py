#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compatibility entry point for a Nerdin-only pipeline refresh."""
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main():
    command = [
        sys.executable,
        str(ROOT / "jobs-dashboard" / "pipeline.py"),
        "--sources",
        "nerdin",
        "--max-age-months",
        "2",
    ]
    raise SystemExit(subprocess.call(command, cwd=ROOT))


if __name__ == "__main__":
    main()
