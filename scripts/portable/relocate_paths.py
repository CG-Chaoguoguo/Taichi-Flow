"""Relocate portable Taichi-Flow SQLite paths transactionally.

The workbench deliberately stores absolute paths because project databases can
be opened by more than one process.  A removable drive changes its letter on
different hosts, so the portable launcher runs this small stdlib-only helper
before starting FastAPI.  Only exact path prefixes from the manifest are
rewritten; prose, hashes, and unrelated external paths are left untouched.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tempfile
from typing import Any, Iterable


def _norm_path(value: str) -> str:
    return os.path.normcase(os.path.abspath(value)).rstrip("\\/")


def _display_path(value: str) -> str:
    return os.path.abspath(value).rstrip("\\/")


def _path_replacer(mappings: list[tuple[str, str]]):
    # Longest-first prevents a broad project root from consuming a more
    # specific legacy import directory mapping.
    normalized = sorted(
        ((_norm_path(old), _display_path(new)) for old, new in mappings if old and new),
        key=lambda item: len(item[0]),
        reverse=True,
    )

    def replace(value: str) -> tuple[str, bool]:
        if not value:
            return value, False
        result = value
        changed = False
        for old, new in normalized:
            # SQLite values use either slash style; database JSON encodes the
            # backslashes only after this function has parsed its JSON value.
            pattern = re.compile(re.escape(old).replace(r"\\", r"[\\\\/]"), re.IGNORECASE)

            def callback(match: re.Match[str]) -> str:
                nonlocal changed
                start, end = match.span()
                before = result[start - 1] if start else ""
                after = result[end] if end < len(result) else ""
                if before and (before.isalnum() or before in "_.-"):
                    return match.group(0)
                if after and after not in "\\/":
                    return match.group(0)
                changed = True
                return new.replace("\\", match.group(0)[0] if match.group(0) and match.group(0)[0] == "/" else "\\")

            result = pattern.sub(callback, result)
        return result, changed

    return replace


def _rewrite_json(value: Any, replace) -> tuple[Any, bool]:
    if isinstance(value, str):
        return replace(value)
    if isinstance(value, list):
        changed = False
        output = []
        for item in value:
            rewritten, item_changed = _rewrite_json(item, replace)
            output.append(rewritten)
            changed = changed or item_changed
        return output, changed
    if isinstance(value, dict):
        changed = False
        output = {}
        for key, item in value.items():
            rewritten, item_changed = _rewrite_json(item, replace)
            output[key] = rewritten
            changed = changed or item_changed
        return output, changed
    return value, False


def _rewrite_text(value: str, replace) -> tuple[str, bool]:
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return replace(value)
    rewritten, changed = _rewrite_json(parsed, replace)
    if not changed:
        return value, False
    return json.dumps(rewritten, ensure_ascii=False, separators=(",", ":")), True


def _sqlite_tables(connection: sqlite3.Connection) -> Iterable[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return [str(row[0]) for row in rows]


def _discard_temporary_path(temporary_path: Path) -> None:
    try:
        temporary_path.unlink()
    except FileNotFoundError:
        pass
    for suffix in ("-wal", "-shm"):
        try:
            Path(f"{temporary_path}{suffix}").unlink()
        except FileNotFoundError:
            pass


def _discard_temporary_databases(replacements: Iterable[tuple[Path, Path]]) -> None:
    for _, temporary_path in replacements:
        _discard_temporary_path(temporary_path)


def _replace_live_databases(replacements: list[tuple[Path, Path]]) -> None:
    """Publish rewritten copies over live databases only after every rewrite."""
    for live_path, temporary_path in replacements:
        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{live_path}{suffix}")
            if sidecar.exists():
                sidecar.unlink()
        os.replace(temporary_path, live_path)


def _rewrite_database(path: Path, replace, verify_only: bool) -> tuple[dict[str, Any], Path | None]:
    # Work on a same-directory copy.  SQLite's transaction protects a normal
    # failure, while the copy also protects against an interrupted process or
    # an unexpected filesystem error during a drive-letter move. Live files
    # stay untouched until every database rewrite and project verification
    # succeed; relocate() then replaces them together.
    temporary_path: Path | None = None
    target_path = path
    connection: sqlite3.Connection | None = None
    changed = 0
    try:
        if not verify_only:
            source = sqlite3.connect(path, timeout=30.0)
            try:
                source.execute("PRAGMA busy_timeout=30000")
                # A previous clean run may leave a WAL file. Checkpointing
                # first makes the copied database self-contained and avoids a
                # stale sidecar being omitted from the transaction copy.
                checkpoint = source.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                if checkpoint and int(checkpoint[0]) != 0:
                    raise RuntimeError(f"SQLite WAL is busy for {path}")
            finally:
                # sqlite3.Connection's context manager does not close the
                # connection; close explicitly so Windows releases -wal/-shm
                # handles before a later atomic replacement.
                source.close()
            fd, temporary_name = tempfile.mkstemp(
                prefix=f".{path.stem}.portable-",
                suffix=".sqlite3",
                dir=path.parent,
            )
            os.close(fd)
            temporary_path = Path(temporary_name)
            shutil.copy2(path, temporary_path)
            target_path = temporary_path

        connection = sqlite3.connect(target_path, timeout=30.0)
        connection.execute("PRAGMA busy_timeout=30000")
        if not verify_only:
            # Use a rollback journal for the transaction copy. This keeps the
            # replacement self-contained and avoids Windows holding a -wal or
            # -shm sidecar open while the main file is atomically replaced.
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("BEGIN IMMEDIATE")
        for table in _sqlite_tables(connection):
            columns = [
                str(row[1])
                for row in connection.execute(f'PRAGMA table_info("{table}")').fetchall()
                if str(row[2]).upper() in {"TEXT", ""}
            ]
            if not columns:
                continue
            quoted_table = '"' + table.replace('"', '""') + '"'
            for column in columns:
                quoted_column = '"' + column.replace('"', '""') + '"'
                rows = connection.execute(
                    f"SELECT rowid, {quoted_column} FROM {quoted_table} WHERE {quoted_column} IS NOT NULL"
                ).fetchall()
                for rowid, value in rows:
                    if not isinstance(value, str):
                        continue
                    rewritten, did_change = _rewrite_text(value, replace)
                    if not did_change:
                        continue
                    changed += 1
                    if not verify_only:
                        connection.execute(
                            f"UPDATE {quoted_table} SET {quoted_column}=? WHERE rowid=?",
                            (rewritten, rowid),
                        )
        if not verify_only:
            connection.commit()
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity.lower() != "ok":
            raise RuntimeError(f"SQLite integrity check failed for {target_path}: {integrity}")
        report = {"path": str(path), "changed_values": changed, "integrity": integrity}
        if not verify_only and temporary_path is not None:
            connection.close()
            connection = None
            for suffix in ("-wal", "-shm"):
                sidecar = Path(f"{temporary_path}{suffix}")
                if sidecar.exists():
                    sidecar.unlink()
            kept = temporary_path
            temporary_path = None
            return report, kept
        return report, None
    except Exception:
        if connection is not None:
            connection.rollback()
        raise
    finally:
        if connection is not None:
            connection.close()
        if temporary_path is not None:
            _discard_temporary_path(temporary_path)


def _path_values(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _path_values(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _path_values(item)


def _verify_project(project_root: Path, database_path: Path | None = None) -> dict[str, Any]:
    live_path = project_root / ".taichi-flow" / "state.sqlite3"
    if not live_path.is_file():
        raise RuntimeError(f"Project database is missing: {live_path}")
    if database_path is None:
        database_path = live_path
    if not database_path.is_file():
        raise RuntimeError(f"Project database is missing: {database_path}")
    connection = sqlite3.connect(database_path)
    try:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity.lower() != "ok":
            raise RuntimeError(f"Project database is corrupt: {integrity}")
        checks = {
            "uploads": "SELECT blob_path FROM uploads WHERE blob_path IS NOT NULL",
            "simulations": "SELECT output_dir FROM simulation_runs WHERE output_dir IS NOT NULL",
            "exports": "SELECT archive_path FROM export_jobs WHERE archive_path IS NOT NULL",
        }
        missing: list[str] = []
        counts: dict[str, int] = {}
        for label, query in checks.items():
            values = [str(row[0]) for row in connection.execute(query).fetchall() if row[0]]
            counts[label] = len(values)
            for value in values:
                if not Path(value).exists():
                    missing.append(value)
        if missing:
            raise RuntimeError(
                "Portable project references missing files: " + "; ".join(missing[:8])
            )
        result_families = int(connection.execute("SELECT COUNT(*) FROM result_families").fetchone()[0])
        return {"integrity": integrity, "path_counts": counts, "result_families": result_families}
    finally:
        connection.close()


def _update_manifest_root(manifest_path: Path, manifest: dict[str, Any], root: Path) -> None:
    """Persist the latest bundle root only after database validation succeeds."""
    manifest["portable_root"] = str(root)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{manifest_path.stem}.portable-",
        suffix=".json",
        dir=manifest_path.parent,
    )
    os.close(fd)
    temporary_path = Path(temporary_name)
    try:
        temporary_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary_path, manifest_path)
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def relocate(root: Path, manifest_path: Path, verify_only: bool = False) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if int(manifest.get("schema_version", 0)) != 1:
        raise RuntimeError("Unsupported portable manifest schema.")
    current_root = root.resolve()
    mappings: list[tuple[str, str]] = []
    recorded_root = str(manifest.get("portable_root") or "")
    if recorded_root and _norm_path(recorded_root) != _norm_path(str(current_root)):
        mappings.append((recorded_root, str(current_root)))
    for item in manifest.get("path_relocations", []):
        old = str(item.get("from") or "")
        relative = str(item.get("to_relative") or "")
        if old and relative:
            mappings.append((old, str(current_root / relative)))
    replace = _path_replacer(mappings)
    database_paths = sorted(
        path
        for path in current_root.rglob("*.sqlite3")
        if ".runtime\\portable\\staging" not in str(path).lower()
        and ".runtime/portable/staging" not in str(path).lower()
        and ".git" not in path.parts
        and ".portable-" not in path.name
    )
    reports: list[dict[str, Any]] = []
    replacements: list[tuple[Path, Path]] = []
    project_info = manifest.get("project") or {}
    relative_project = str(project_info.get("relative_path") or "")
    project_root = (current_root / relative_project).resolve()
    project_database = project_root / ".taichi-flow" / "state.sqlite3"
    try:
        for path in database_paths:
            report, temporary_path = _rewrite_database(path, replace, verify_only)
            reports.append(report)
            if temporary_path is not None:
                replacements.append((path, temporary_path))
        rewritten_project = next(
            (
                temporary_path
                for live_path, temporary_path in replacements
                if live_path.resolve() == project_database.resolve()
            ),
            None,
        )
        validation = _verify_project(project_root, rewritten_project)
        manifest_updated = False
        if not verify_only:
            _replace_live_databases(replacements)
            replacements = []
            if recorded_root and _norm_path(recorded_root) != _norm_path(str(current_root)):
                _update_manifest_root(manifest_path, manifest, current_root)
                manifest_updated = True
        return {
            "root": str(current_root),
            "mappings": [{"from": old, "to": new} for old, new in mappings],
            "databases": reports,
            "project": validation,
            "manifest_updated": manifest_updated,
            "verify_only": verify_only,
        }
    finally:
        _discard_temporary_databases(replacements)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    try:
        report = relocate(args.root, args.manifest, args.verify_only)
        print("TAICHI_FLOW_RELOCATION=" + json.dumps(report, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f"portable relocation failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
