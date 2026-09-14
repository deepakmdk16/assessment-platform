#!/usr/bin/env python
"""Gate G8: every field of every request body the API accepts must be bounded.

`api.py::_limit_body_size` caps a request at MAX_BODY_BYTES, and its docstring
says "the per-field `max_length` caps in schemas.py bound what gets stored". That
was aspiration, not fact: the 2026-09-14 audit found a megabyte candidate name
renders in the grid, the CSV and the results email (R2-073), an unbounded
`time_limit_s` holds the agent's execution lock for minutes (R2-022), and a test
case's `stdin` has no cap at all — which is half of the P0 where a grade is lost
because the result callback exceeds that same body cap (R2-001).

The models are reached through FastAPI itself — every route's `body_field`, then
every nested model — so this covers exactly what the API accepts, with no naming
convention to get wrong and no response model to false-positive on.

Rules, per field:
  * `str`            -> needs `max_length`
  * `list`           -> needs `max_length` (a bound on the number of items)
  * `int` / `float`  -> needs at least one of `gt` / `ge` / `lt` / `le`

**Baseline.** The gate ships before the fixes, so the fields unbounded today are
listed in `scripts/schema-limits-baseline.txt`. A field NOT in the baseline fails
immediately; a baseline line whose field is now bounded ALSO fails, so the file
shrinks and cannot rot. There is deliberately no flag to regenerate it — a new
unbounded field is a decision to argue for, not a baseline to refresh.

Run: `uv run python scripts/check-schema-limits.py` (part of scripts/checkpoints.sh).
"""

from __future__ import annotations

import sys
import typing
from pathlib import Path

from fastapi.routing import APIRoute
from pydantic import BaseModel

from assessment_platform.api import app

BASELINE = Path(__file__).resolve().parent / "schema-limits-baseline.txt"


def _leaf_types(annotation: object) -> list[object]:
    """Flatten `str | None`, `list[X]`, `Annotated[...]` down to their leaves."""
    if annotation is None:
        return []
    if typing.get_origin(annotation) is None:
        return [annotation]
    leaves: list[object] = []
    for arg in typing.get_args(annotation):
        leaves.extend(_leaf_types(arg))
    return leaves


def _request_models() -> dict[str, type[BaseModel]]:
    """Every model the API accepts in a request body, including nested ones."""
    found: dict[str, type[BaseModel]] = {}

    def collect(candidate: object) -> None:
        if not (isinstance(candidate, type) and issubclass(candidate, BaseModel)):
            return
        if candidate.__name__ in found:
            return
        found[candidate.__name__] = candidate
        for field in candidate.model_fields.values():
            for leaf in _leaf_types(field.annotation):
                collect(leaf)

    for route in app.routes:
        if isinstance(route, APIRoute) and route.body_field is not None:
            for leaf in _leaf_types(route.body_field.field_info.annotation):
                collect(leaf)
    return found


def _constrained(metadata: list[object], *names: str) -> bool:
    """True if any of pydantic's constraint objects on the field sets one of `names`."""
    return any(getattr(m, n, None) is not None for m in metadata for n in names)


def _unbounded() -> list[str]:
    """`Model.field — rule` for every field with no bound, sorted."""
    rows: list[str] = []
    for model_name, model in sorted(_request_models().items()):
        for field_name, field in model.model_fields.items():
            metadata = list(field.metadata)
            annotation = field.annotation
            is_list = any(
                typing.get_origin(a) is list
                for a in [annotation, *typing.get_args(annotation)]
            )
            leaves = _leaf_types(annotation)

            if is_list:
                if not _constrained(metadata, "max_length"):
                    rows.append(f"{model_name}.{field_name} — list needs max_length")
            elif str in leaves:
                if not _constrained(metadata, "max_length"):
                    rows.append(f"{model_name}.{field_name} — str needs max_length")
            elif int in leaves or float in leaves:
                if not _constrained(metadata, "gt", "ge", "lt", "le"):
                    rows.append(f"{model_name}.{field_name} — number needs gt/ge/lt/le")
    return sorted(rows)


def main() -> int:
    current = set(_unbounded())
    baseline = {
        line.strip()
        for line in BASELINE.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }

    new = sorted(current - baseline)
    fixed = sorted(baseline - current)

    if new:
        print("❌ unbounded field(s) in a request body the API accepts:")
        for row in new:
            print(f"     {row}")
        print(
            "\n   Every request field must be bounded — the body cap alone does not bound\n"
            "   what a single field can carry into the database, the CSV, an email or the\n"
            "   agent (R2-001, R2-022, R2-073). Add the constraint, e.g.\n"
            "     name: str = Field(max_length=120)"
        )
    if fixed:
        print("❌ these baseline entries are now bounded — delete their lines:")
        for row in fixed:
            print(f"     {row}")
        print(f"\n   File: {BASELINE.relative_to(Path.cwd()) if BASELINE.is_relative_to(Path.cwd()) else BASELINE}")

    if new or fixed:
        return 1
    print(f"check-schema-limits: {len(current)} known-unbounded field(s), none new ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
