"""Smoke tests for the Alembic baseline + pgvector migrations.

These tests are SQLite-only: CI does not have a live Postgres
instance, so the pgvector-specific DDL in
``versions/0002_pgvector_native_knn.py`` is exercised via its
non-postgres no-op branch. The point of running it here is to catch
revision-graph regressions (missing ``down_revision`` chain, syntax
errors in ``op.create_table`` calls, etc.) before they ever reach a
Postgres environment where they'd be far more expensive to debug.

Operators verify the Postgres branch separately via ``docker compose
up`` (the API container runs ``alembic upgrade head`` at boot — see
``docker-compose.yml``).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from alembic import command

REPO_API_DIR = Path(__file__).resolve().parent.parent
ALEMBIC_INI = REPO_API_DIR / "alembic.ini"


def _build_alembic_config(database_url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    # The default ``script_location`` is the relative path ``alembic``;
    # rewrite to absolute so the tests work regardless of the pytest
    # CWD.
    cfg.set_main_option("script_location", str(REPO_API_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


@pytest.fixture()
def fresh_sqlite_url(monkeypatch):
    """Throw-away SQLite file per test (Alembic can't run against
    a ``sqlite:///:memory:`` connection that disappears between
    DDL statements — the file-backed temp DB avoids that).

    Also overrides ``DATABASE_URL`` for the duration of the test so the
    Alembic ``env.py`` (which prefers ``DATABASE_URL`` over
    ``sqlalchemy.url`` from the config) targets the fresh file rather
    than the session-wide test database that ``conftest.py`` set up.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        path = tmp.name
    url = f"sqlite:///{path}"
    monkeypatch.setenv("DATABASE_URL", url)
    yield url
    # Best-effort cleanup; tests must not leak temp files but a missing
    # file isn't a failure (the test may have unlinked it itself).
    try:
        os.unlink(path)
    except OSError:
        pass


def test_alembic_script_directory_resolves_linear_revisions() -> None:
    """The baseline + pgvector + recipe-embedding migrations form a
    linear revision chain with a single head.
    """
    cfg = _build_alembic_config("sqlite://")
    script = ScriptDirectory.from_config(cfg)
    revisions = list(script.walk_revisions())
    assert {rev.revision for rev in revisions} == {
        "0001_baseline",
        "0002_pgvector_native_knn",
        "0003_recipe_embedding",
    }
    # Each revision points back to its immediate predecessor.
    assert script.get_revision("0002_pgvector_native_knn").down_revision == "0001_baseline"
    assert script.get_revision("0003_recipe_embedding").down_revision == "0002_pgvector_native_knn"


def test_upgrade_head_creates_full_baseline_schema(fresh_sqlite_url) -> None:
    """Running ``alembic upgrade head`` against a fresh SQLite DB must
    create every table referenced by the ORM models. We check the
    table list rather than each column to keep the assertion robust
    against future column-only migrations.
    """
    cfg = _build_alembic_config(fresh_sqlite_url)
    command.upgrade(cfg, "head")

    engine = create_engine(fresh_sqlite_url, future=True)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    expected = {
        "documents",
        "ingredients",
        "trends",
        "users",
        "vector_search_datapoints",
        "notifications",
        "recipes",
        "subscriptions",
        "user_favorite_keywords",
        "recipe_ingredients",
        "alembic_version",
    }
    assert expected.issubset(tables), f"missing tables: {expected - tables}"


def test_pgvector_migration_is_noop_on_sqlite(fresh_sqlite_url) -> None:
    """The pgvector migration's Postgres-only DDL must be skipped on
    SQLite. After upgrading to head the ``vector_search_datapoints``
    table must NOT have an ``embedding`` column (only the baseline's
    columns).
    """
    cfg = _build_alembic_config(fresh_sqlite_url)
    command.upgrade(cfg, "head")

    engine = create_engine(fresh_sqlite_url, future=True)
    try:
        cols = {c["name"] for c in inspect(engine).get_columns("vector_search_datapoints")}
    finally:
        engine.dispose()

    assert "embedding" not in cols
    # The baseline-defined columns are intact — sanity check that the
    # migration didn't accidentally drop them.
    assert {"id", "namespace", "datapoint_id", "values", "restricts", "metadata_json"} <= cols


def test_downgrade_to_base_drops_all_tables(fresh_sqlite_url) -> None:
    """The full ``upgrade head`` → ``downgrade base`` round trip
    should leave the DB clean of every model table (only Alembic's
    own ``alembic_version`` table remains, which Alembic clears
    automatically on the way down).
    """
    cfg = _build_alembic_config(fresh_sqlite_url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")

    engine = create_engine(fresh_sqlite_url, future=True)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    # ``alembic_version`` is kept by Alembic across downgrades; what
    # we really care about is that none of our model tables leaked.
    model_tables = {
        "documents",
        "ingredients",
        "trends",
        "users",
        "vector_search_datapoints",
        "notifications",
        "recipes",
        "subscriptions",
        "user_favorite_keywords",
        "recipe_ingredients",
    }
    assert tables.isdisjoint(model_tables), f"downgrade left tables behind: {tables & model_tables}"
