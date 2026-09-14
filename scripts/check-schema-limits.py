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

Rules, applied to every node of a field's type — a list's element type and a
dict's value type are checked as well as the container, because a cap on the
number of items says nothing about how big one item may be:
  * `str`            -> needs `max_length` (unless its format self-bounds, e.g. a date-time)
  * `list`           -> needs `max_length`, and its element type must be bounded too
  * `dict`           -> needs a key-count cap, and its value type must be bounded too
  * `int` / `float`  -> needs at least one of `gt` / `ge` / `lt` / `le`

Paths read `Model.field`, `Model.field[]` for a list's elements and
`Model.field{}` for a dict's values.

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


# A string whose format already bounds it: a timestamp or a uuid cannot be a
# megabyte long whatever the caller sends, because parsing rejects it first.
_SELF_BOUNDING_FORMATS = frozenset(
    {"date-time", "date", "time", "duration", "uuid", "ipv4", "ipv6"}
)


def _check_node(path: str, node: dict[str, object], rows: list[str]) -> None:
    """Walk one JSON-schema node, recording every unbounded string/array/dict/number.

    The schema pydantic itself emits is the substrate, not the python annotation,
    because the annotation lies about the useful cases: `EmailStr` is neither a
    `str` nor a generic (it is its own class, so an `is str` test silently exempts
    every email field), and a `list[str]` bounded only by `maxItems` still carries
    unbounded strings. The schema says `{"type": "string", "format": "email"}` and
    `{"type": "array", "items": {"type": "string"}}`, which is exactly what needs
    checking — and it keeps working for `SecretStr`, `HttpUrl` and whatever gets
    added next.
    """
    # `str | None` and friends: every branch has to be bounded on its own.
    for branch_key in ("anyOf", "oneOf"):
        branches = node.get(branch_key)
        if isinstance(branches, list):
            for branch in branches:
                if isinstance(branch, dict) and branch.get("type") != "null":
                    _check_node(path, branch, rows)
            return

    # A nested model ($ref) is reached as a request model in its own right.
    if "$ref" in node:
        return
    # A closed set of values is bounded by definition.
    if "enum" in node or "const" in node:
        return

    node_type = node.get("type")

    if node_type == "string":
        if node.get("format") in _SELF_BOUNDING_FORMATS:
            return
        if node.get("maxLength") is None:
            rows.append(f"{path} — str needs max_length")
    elif node_type == "array":
        if node.get("maxItems") is None:
            rows.append(f"{path} — list needs max_length")
        items = node.get("items")
        if isinstance(items, dict):
            _check_node(f"{path}[]", items, rows)
    elif node_type == "object":
        values = node.get("additionalProperties")
        if isinstance(values, dict):
            if node.get("maxProperties") is None:
                rows.append(f"{path} — dict needs a cap on how many keys it may carry")
            _check_node(f"{path}{{}}", values, rows)
    elif node_type in ("integer", "number"):
        bounds = ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum")
        if all(node.get(b) is None for b in bounds):
            rows.append(f"{path} — number needs gt/ge/lt/le")


def _unbounded() -> list[str]:
    """`Model.field — rule` for every unbounded field, sorted.

    A path may nest: `X.items[]` is the element type of a list, `X.map{}` the
    value type of a dict. Both must be bounded — a cap on the number of items
    says nothing about how big one item may be (R2-073).
    """
    rows: list[str] = []
    for model_name, model in sorted(_request_models().items()):
        schema = model.model_json_schema(ref_template="{model}")
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            continue
        for field_name, node in properties.items():
            if isinstance(node, dict):
                _check_node(f"{model_name}.{field_name}", node, rows)
    return sorted(rows)


def main() -> int:
    current = set(_unbounded())
    # utf-8 explicitly: the baseline carries em dashes and this output carries
    # ❌/✓, and the pre-push hook can run under a POSIX locale.
    baseline = set()
    for raw in BASELINE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            baseline.add(line)

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
