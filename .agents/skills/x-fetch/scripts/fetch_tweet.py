#!/usr/bin/env python3
"""Compatibility shim — v1 entry point, forwards to the xtf package.

Vendored into X-Tiller under .agents/skills/x-fetch/scripts/
(upstream: https://github.com/ythx-101/x-tweet-fetcher, MIT).
"""
import sys
from pathlib import Path

_src = Path(__file__).resolve().parent
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from xtf.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
