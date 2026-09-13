"""The migrations and the models must describe the same database.

Every other test builds its schema with `SQLModel.metadata.create_all` (see
conftest), which means the suite has never once executed a migration — so a
column declared nullable on the model and NOT NULL in the migration passes every
test and then 500s in production the first time something writes NULL. That is
not hypothetical: `orginvite.invited_by` shipped exactly that way in the X01
branch and only a review caught it.

This walks the migrations to head on a scratch database, builds a second one from
the models, and compares them column by column.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

from sqlmodel import SQLModel, create_engine

import assessment_platform.models  # noqa: F401 — registers every table

REPO_ROOT = Path(__file__).resolve().parent.parent


def _columns(db_path: Path) -> dict[str, dict[str, tuple[str, int]]]:
    """{table: {column: (type, not_null)}} for a SQLite file."""
    conn = sqlite3.connect(db_path)
    try:
        tables = sorted(
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version'"
            )
        )
        return {
            table: {
                row[1]: (row[2].upper(), row[3])
                for row in conn.execute(f"PRAGMA table_info({table})")  # noqa: S608
            }
            for table in tables
        }
    finally:
        conn.close()


def _unique_sets(db_path: Path) -> dict[str, set[tuple[str, ...]]]:
    """{table: {(col, ...), ...}} for every UNIQUE index a database enforces.

    Columns alone are not the whole schema: a unique constraint that exists on
    the model and not in the migration is invisible to every test (they all build
    from the models) and only shows up in production, as a route whose 409 never
    fires. `CandidateFeedback.attempt_id` is exactly that shape.
    """
    conn = sqlite3.connect(db_path)
    try:
        tables = sorted(
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version'"
            )
        )
        out: dict[str, set[tuple[str, ...]]] = {}
        for table in tables:
            uniques = set()
            for row in conn.execute(f"PRAGMA index_list({table})"):  # noqa: S608
                name, is_unique = row[1], row[2]
                if not is_unique:
                    continue
                cols = tuple(r[2] for r in conn.execute(f"PRAGMA index_info({name})"))  # noqa: S608
                uniques.add(cols)
            out[table] = uniques
        return out
    finally:
        conn.close()


def test_migrations_and_models_agree(tmp_path: Path) -> None:
    migrated = tmp_path / "migrated.db"
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        env={"DATABASE_URL": f"sqlite:///{migrated}", "PATH": "/usr/bin:/bin"},
        check=True,
        capture_output=True,
    )

    declared = tmp_path / "declared.db"
    SQLModel.metadata.create_all(create_engine(f"sqlite:///{declared}"))

    from_migrations = _columns(migrated)
    from_models = _columns(declared)

    assert set(from_migrations) == set(from_models), (
        "a table exists in one and not the other: "
        f"{set(from_migrations) ^ set(from_models)}"
    )

    drift = [
        f"{table}.{column}: migration={from_migrations[table].get(column)} "
        f"model={from_models[table].get(column)}"
        for table in sorted(from_migrations)
        for column in sorted(set(from_migrations[table]) | set(from_models[table]))
        # Compare nullability and existence. SQLite's declared type strings vary
        # harmlessly between the two paths (VARCHAR vs TEXT), so they are not
        # compared — the failure this test exists for is a NOT NULL mismatch.
        if (
            column not in from_migrations[table]
            or column not in from_models[table]
            or from_migrations[table][column][1] != from_models[table][column][1]
        )
    ]
    assert not drift, "schema drift between migrations and models:\n  " + "\n  ".join(drift)

    migrated_uniques = _unique_sets(migrated)
    declared_uniques = _unique_sets(declared)
    unique_drift = [
        f"{table}: migration={sorted(migrated_uniques.get(table, set()))} "
        f"model={sorted(declared_uniques.get(table, set()))}"
        for table in sorted(set(migrated_uniques) | set(declared_uniques))
        if migrated_uniques.get(table, set()) != declared_uniques.get(table, set())
    ]
    assert not unique_drift, "unique-constraint drift between migrations and models:\n  " + "\n  ".join(
        unique_drift
    )
