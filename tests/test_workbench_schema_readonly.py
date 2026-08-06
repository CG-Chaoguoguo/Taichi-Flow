from __future__ import annotations

from pathlib import Path
import sqlite3

from api.services.workbench_store import ProjectDatabase, SCHEMA_VERSION


def test_ensure_schema_is_read_only_after_current_schema_is_installed(tmp_path: Path) -> None:
    database = ProjectDatabase(tmp_path / "project")
    database.initialize(
        project_id="tf-schema-readonly",
        name="Schema read-only project",
        description="",
        created_at="2026-08-06T00:00:00+00:00",
    )

    observer = sqlite3.connect(database.database_path)
    try:
        version_before = int(observer.execute("PRAGMA data_version").fetchone()[0])

        database.ensure_schema()

        version_after = int(observer.execute("PRAGMA data_version").fetchone()[0])
        schema_version = int(
            observer.execute(
                "SELECT value FROM schema_metadata WHERE key='schema_version'"
            ).fetchone()[0]
        )
        builtin_count = int(
            observer.execute(
                "SELECT COUNT(*) FROM parameter_templates WHERE source_kind='bundled_case'"
            ).fetchone()[0]
        )
    finally:
        observer.close()

    assert version_after == version_before
    assert schema_version == SCHEMA_VERSION
    assert builtin_count == 2
