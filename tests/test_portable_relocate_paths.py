"""Atomic portable SQLite path relocation."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

HELPER = Path(__file__).resolve().parents[1] / "scripts" / "portable" / "relocate_paths.py"


def _load_relocate():
    spec = importlib.util.spec_from_file_location("portable_relocate_paths", HELPER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def relocate_mod():
    return _load_relocate()


def _write_manifest(root: Path, old_root: Path, project_relative: str) -> Path:
    manifest = {
        "schema_version": 1,
        "portable_root": str(old_root),
        "project": {"relative_path": project_relative},
        "path_relocations": [],
    }
    path = root / "portable-manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


def _create_catalog_db(path: Path, root_path: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE projects (root_path TEXT)")
        connection.execute("INSERT INTO projects (root_path) VALUES (?)", (root_path,))
        connection.commit()
    finally:
        connection.close()


def _create_project_db(path: Path, blob_path: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE uploads (blob_path TEXT);
            CREATE TABLE simulation_runs (output_dir TEXT);
            CREATE TABLE export_jobs (archive_path TEXT);
            CREATE TABLE result_families (id INTEGER);
            """
        )
        connection.execute("INSERT INTO uploads (blob_path) VALUES (?)", (blob_path,))
        connection.commit()
    finally:
        connection.close()


def _text_values(path: Path, table: str, column: str) -> list[str]:
    connection = sqlite3.connect(path)
    try:
        return [str(row[0]) for row in connection.execute(f"SELECT {column} FROM {table}")]
    finally:
        connection.close()


def _leftover_temps(root: Path) -> list[Path]:
    return [path for path in root.rglob("*") if path.is_file() and ".portable-" in path.name]


def _two_db_bundle(tmp_path: Path) -> dict[str, Path | str]:
    old_root = (tmp_path / "old-root").resolve()
    root = (tmp_path / "bundle").resolve()
    project_relative = "demo"
    catalog_path = root / ".runtime" / "portable" / "state" / "catalog.sqlite3"
    project_db = root / project_relative / ".taichi-flow" / "state.sqlite3"
    old_project = old_root / project_relative
    old_blob = old_project / ".taichi-flow" / "blobs" / "file.bin"
    new_blob = root / project_relative / ".taichi-flow" / "blobs" / "file.bin"
    new_blob.parent.mkdir(parents=True, exist_ok=True)
    new_blob.write_bytes(b"blob")
    _create_catalog_db(catalog_path, str(old_project))
    _create_project_db(project_db, str(old_blob))
    manifest_path = _write_manifest(root, old_root, project_relative)
    return {
        "old_root": old_root,
        "root": root,
        "manifest_path": manifest_path,
        "catalog_path": catalog_path,
        "project_db": project_db,
        "old_project": str(old_project),
        "old_blob": str(old_blob),
        "new_project": root / project_relative,
        "new_blob": new_blob,
    }


def test_second_rewrite_failure_leaves_first_live_db_untouched(
    tmp_path: Path,
    relocate_mod,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _two_db_bundle(tmp_path)
    original = relocate_mod._rewrite_database

    def fail_project_rewrite(path, replace, verify_only):
        if path.resolve() == bundle["project_db"].resolve():
            raise RuntimeError("injected rewrite failure")
        return original(path, replace, verify_only)

    monkeypatch.setattr(relocate_mod, "_rewrite_database", fail_project_rewrite)

    with pytest.raises(RuntimeError, match="injected rewrite failure"):
        relocate_mod.relocate(bundle["root"], bundle["manifest_path"], verify_only=False)

    catalog_values = _text_values(bundle["catalog_path"], "projects", "root_path")
    assert catalog_values == [bundle["old_project"]]
    project_values = _text_values(bundle["project_db"], "uploads", "blob_path")
    assert project_values == [bundle["old_blob"]]
    manifest = json.loads(bundle["manifest_path"].read_text(encoding="utf-8"))
    assert relocate_mod._norm_path(manifest["portable_root"]) == relocate_mod._norm_path(
        str(bundle["old_root"])
    )
    assert _leftover_temps(bundle["root"]) == []


def test_successful_relocate_replaces_databases_and_updates_manifest(
    tmp_path: Path,
    relocate_mod,
) -> None:
    bundle = _two_db_bundle(tmp_path)

    report = relocate_mod.relocate(bundle["root"], bundle["manifest_path"], verify_only=False)

    assert report["manifest_updated"] is True
    catalog_values = _text_values(bundle["catalog_path"], "projects", "root_path")
    assert relocate_mod._norm_path(catalog_values[0]) == relocate_mod._norm_path(
        str(bundle["new_project"])
    )
    project_values = _text_values(bundle["project_db"], "uploads", "blob_path")
    assert relocate_mod._norm_path(project_values[0]) == relocate_mod._norm_path(
        str(bundle["new_blob"])
    )
    manifest = json.loads(bundle["manifest_path"].read_text(encoding="utf-8"))
    assert relocate_mod._norm_path(manifest["portable_root"]) == relocate_mod._norm_path(
        str(bundle["root"])
    )
    assert _leftover_temps(bundle["root"]) == []
