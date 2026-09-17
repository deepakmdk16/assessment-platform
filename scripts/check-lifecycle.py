#!/usr/bin/env python
"""Gate G7 — the lifecycle matrix in docs/LIFECYCLE.md names a real test for
every entity edge, or says why there is nothing to test.

The audit's G7 class is eight findings with one shape: a surface kept working
from a row another surface had moved on from (an invite expiring under a live
sitting, a duration edit moving a deadline, a removed member still receiving
results). A matrix is the cheap way to enumerate those edges; this script is what
stops it rotting into prose.

Fails when:
  * a cell cites `path::name` and the file is gone or no longer contains `name`;
  * a cell is empty, or is none of the three allowed forms;
  * the owed list grows past OWED_BASELINE — and when it shrinks, so the
    baseline cannot silently stay high.

Run from anywhere; paths are resolved against the repo root.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MATRIX = ROOT / "docs" / "LIFECYCLE.md"

# Owed cells today. Each names the session that closes it; lower this number in
# the commit that fills one, exactly like the other gates' baselines.
OWED_BASELINE = 14

OWED = re.compile(r"^owed → S\d{2}$")
NA = re.compile(r"^n/a — \S.*$")
CITE = re.compile(r"^(?P<path>[\w./-]+)::(?P<name>\S.*)$")


def cells(line: str) -> list[str]:
    """The cells of a markdown table row, without the leading/trailing pipes."""
    return [c.strip() for c in line.strip().strip("|").split("|")]


def main() -> int:
    if not MATRIX.exists():
        print(f"❌ {MATRIX.relative_to(ROOT)} is missing — gate G7 needs it")
        return 1

    rows: list[list[str]] = []
    header: list[str] = []
    for line in MATRIX.read_text().splitlines():
        if not line.startswith("|"):
            continue
        row = cells(line)
        if not header:
            header = row
            continue
        if all(set(c) <= {"-", ":"} for c in row):  # the |---|---| separator
            continue
        rows.append(row)

    problems: list[str] = []
    owed = 0
    checked = 0

    for row in rows:
        entity = row[0]
        if len(row) != len(header):
            problems.append(f"{entity}: {len(row)} cells, header has {len(header)}")
            continue
        for column, cell in zip(header[1:], row[1:], strict=True):
            where = f"{entity} × {column}"
            if not cell:
                problems.append(f"{where}: empty — every edge is a test or a reason")
            elif OWED.match(cell):
                owed += 1
            elif NA.match(cell):
                continue
            elif m := CITE.match(cell):
                path, name = ROOT / m["path"], m["name"]
                if not path.exists():
                    problems.append(f"{where}: {m['path']} does not exist")
                elif name not in path.read_text():
                    problems.append(f"{where}: {m['path']} no longer contains {name!r}")
                else:
                    checked += 1
            else:
                problems.append(
                    f"{where}: {cell!r} is not `path::name`, `n/a — reason` or `owed → Snn`"
                )

    if owed > OWED_BASELINE:
        problems.append(
            f"owed cells: {owed} > baseline {OWED_BASELINE} — a new lifecycle edge "
            "was left untested; write the test rather than raising the baseline"
        )
    elif owed < OWED_BASELINE:
        problems.append(
            f"owed cells: {owed} < baseline {OWED_BASELINE} — lower OWED_BASELINE to "
            f"{owed} in this commit, so the list cannot rot"
        )

    if problems:
        print("❌ lifecycle matrix (docs/LIFECYCLE.md):")
        for p in problems:
            print(f"   {p}")
        return 1

    print(f"  ✓ {checked} cells cite a live test, {owed} owed (baseline {OWED_BASELINE})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
