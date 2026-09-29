#!/usr/bin/env python3
"""Verify that plain make still selects the normal build target."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]


def default_goal(directory: Path) -> Optional[str]:
    result = subprocess.run(
        ["make", "--no-print-directory", "-qp"],
        cwd=directory,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    for line in result.stdout.splitlines():
        if line.startswith(".DEFAULT_GOAL :="):
            return line.partition(":=")[2].strip()
    return None


def main() -> int:
    errors: list[str] = []
    for directory in (ROOT, ROOT / "aw-server"):
        goal = default_goal(directory)
        if goal != "build":
            errors.append(f"{directory}: plain make selects {goal!r}, expected 'build'")
    if errors:
        print("ERROR: " + "\n  ".join(errors), file=sys.stderr)
        return 1
    print("OK: plain make selects build in the bundle and aw-server")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
