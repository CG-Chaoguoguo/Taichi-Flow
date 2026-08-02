"""Persistent Taichi-Flow workbench domain storage.

The public application owns a small global project catalog.  Each registered
project owns its scientific workflow metadata in ``.taichi-flow/state.sqlite3``
and keeps large files on disk beside that database.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Dict, Iterator, Optional
from uuid import uuid4
import hashlib
import json
import os
import sqlite3


SCHEMA_VERSION = 1


class WorkbenchError(Exception):
    """A domain error safe to expose through the public API."""

    def __init__(self, code: str, message: str, *, status_code: int = 400, details: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_state_dir() -> Path:
    configured = os.environ.get("TAICHI_FLOW_STATE_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return (Path(local_app_data) / "Taichi-Flow").resolve()
    return (Path.home() / ".taichi-flow").resolve()


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=10.0, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=10000")
    return connection


class ProjectDatabase:
    """Owns one project's transactional metadata and filesystem layout."""

    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()
        self.state_dir = self.root / ".taichi-flow"
        self.database_path = self.state_dir / "state.sqlite3"
        self.blob_dir = self.state_dir / "blobs" / "sha256"
        self.staging_dir = self.state_dir / "staging"
        self.export_dir = self.state_dir / "exports"
        self.output_dir = self.root / "outputs"

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = _connect(self.database_path)
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self, *, project_id: str, name: str, description: str, created_at: str) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        for path in (self.state_dir, self.blob_dir, self.staging_dir, self.export_dir, self.output_dir):
            path.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS project_metadata (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    project_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS uploads (
                    upload_id TEXT PRIMARY KEY,
                    family TEXT NOT NULL,
                    name TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    blob_path TEXT NOT NULL,
                    status TEXT NOT NULL,
                    summary TEXT,
                    warnings_json TEXT NOT NULL DEFAULT '[]',
                    errors_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_uploads_sha256 ON uploads(sha256);
                CREATE TABLE IF NOT EXISTS input_revisions (
                    revision_id TEXT PRIMARY KEY,
                    version_tag TEXT NOT NULL,
                    status TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    manifest_json TEXT NOT NULL,
                    validation_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS scenarios (
                    scenario_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    input_revision_id TEXT NOT NULL REFERENCES input_revisions(revision_id),
                    base_scenario_id TEXT REFERENCES scenarios(scenario_id),
                    parameter_patch_json TEXT NOT NULL,
                    effective_parameters_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    archived INTEGER NOT NULL DEFAULT 0,
                    latest_simulation_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS simulation_runs (
                    simulation_id TEXT PRIMARY KEY,
                    scenario_id TEXT NOT NULL REFERENCES scenarios(scenario_id),
                    status TEXT NOT NULL,
                    progress REAL NOT NULL DEFAULT 0,
                    current_time REAL NOT NULL DEFAULT 0,
                    end_time REAL NOT NULL DEFAULT 0,
                    step_count INTEGER NOT NULL DEFAULT 0,
                    output_count INTEGER NOT NULL DEFAULT 0,
                    start_time TEXT,
                    end_time_actual TEXT,
                    error TEXT,
                    elapsed_seconds REAL NOT NULL DEFAULT 0,
                    output_dir TEXT,
                    runtime_profile_json TEXT NOT NULL DEFAULT '{}',
                    effective_config_json TEXT NOT NULL DEFAULT '{}',
                    resource_summary_json TEXT NOT NULL DEFAULT '{}',
                    terminal_log_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS queue_items (
                    queue_item_id TEXT PRIMARY KEY,
                    scenario_id TEXT NOT NULL REFERENCES scenarios(scenario_id),
                    position INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    simulation_id TEXT REFERENCES simulation_runs(simulation_id),
                    retry_of TEXT REFERENCES queue_items(queue_item_id),
                    enqueued_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    progress REAL NOT NULL DEFAULT 0,
                    summary TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS result_families (
                    family_id TEXT PRIMARY KEY,
                    simulation_id TEXT NOT NULL REFERENCES simulation_runs(simulation_id),
                    name TEXT NOT NULL,
                    label TEXT NOT NULL,
                    file_count INTEGER NOT NULL,
                    total_size INTEGER NOT NULL,
                    files_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS export_jobs (
                    export_id TEXT PRIMARY KEY,
                    scenario_id TEXT NOT NULL REFERENCES scenarios(scenario_id),
                    simulation_id TEXT NOT NULL REFERENCES simulation_runs(simulation_id),
                    status TEXT NOT NULL,
                    options_json TEXT NOT NULL,
                    file_count INTEGER NOT NULL DEFAULT 0,
                    total_size INTEGER NOT NULL DEFAULT 0,
                    archive_path TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                );
                """
            )
            connection.execute(
                "INSERT OR REPLACE INTO schema_metadata(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            existing = connection.execute(
                "SELECT project_id, created_at FROM project_metadata WHERE singleton=1"
            ).fetchone()
            stable_id = str(existing["project_id"]) if existing else project_id
            stable_created = str(existing["created_at"]) if existing else created_at
            connection.execute(
                """
                INSERT OR REPLACE INTO project_metadata(
                    singleton, project_id, name, description, created_at, updated_at
                ) VALUES(1, ?, ?, ?, ?, ?)
                """,
                (stable_id, name, description, stable_created, utc_now()),
            )

    def metadata(self) -> Optional[Dict[str, Any]]:
        if not self.database_path.exists():
            return None
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM project_metadata WHERE singleton=1").fetchone()
        return dict(row) if row else None


class WorkbenchStore:
    """Deep module for project discovery and per-project stores."""

    def __init__(self, state_dir: Optional[Path] = None):
        self.state_dir = Path(state_dir or default_state_dir()).expanduser().resolve()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.catalog_path = self.state_dir / "catalog.sqlite3"
        self._initialize_catalog()

    @contextmanager
    def catalog(self) -> Iterator[sqlite3.Connection]:
        connection = _connect(self.catalog_path)
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize_catalog(self) -> None:
        with self.catalog() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    project_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    root_path TEXT NOT NULL UNIQUE,
                    state_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL
                );
                """
            )

    @staticmethod
    def _project_info(row: sqlite3.Row | Dict[str, Any]) -> Dict[str, Any]:
        data = dict(row)
        root = Path(str(data["root_path"]))
        data["available"] = root.exists() and Path(str(data["state_path"])).exists()
        return data

    def list_projects(self) -> list[Dict[str, Any]]:
        with self.catalog() as connection:
            rows = connection.execute("SELECT * FROM projects ORDER BY created_at, project_id").fetchall()
        return [self._project_info(row) for row in rows]

    def get_project(self, project_id: str) -> Dict[str, Any]:
        with self.catalog() as connection:
            row = connection.execute("SELECT * FROM projects WHERE project_id=?", (project_id,)).fetchone()
        if not row:
            raise WorkbenchError("project_not_found", "项目不存在。", status_code=404)
        return self._project_info(row)

    def project_database(self, project_id: str) -> ProjectDatabase:
        project = self.get_project(project_id)
        if not project["available"]:
            raise WorkbenchError(
                "project_unavailable",
                "项目目录不可用；目录记录已保留，未自动删除。",
                status_code=409,
                details={"root_path": project["root_path"]},
            )
        return ProjectDatabase(Path(project["root_path"]))

    def create_or_open_project(self, *, name: str, root_path: str, description: str = "") -> Dict[str, Any]:
        root = Path(root_path).expanduser().resolve()
        database = ProjectDatabase(root)
        existing_metadata = database.metadata()
        now = utc_now()
        project_id = str(existing_metadata["project_id"]) if existing_metadata else f"tf-{uuid4().hex}"
        project_name = name.strip() or (str(existing_metadata["name"]) if existing_metadata else root.name)
        project_description = description if description != "" else (
            str(existing_metadata["description"]) if existing_metadata else ""
        )
        created_at = str(existing_metadata["created_at"]) if existing_metadata else now
        database.initialize(
            project_id=project_id,
            name=project_name,
            description=project_description,
            created_at=created_at,
        )
        metadata = database.metadata()
        assert metadata is not None
        with self.catalog() as connection:
            connection.execute(
                """
                INSERT INTO projects(project_id, name, description, root_path, state_path, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(root_path) DO UPDATE SET
                    project_id=excluded.project_id,
                    name=excluded.name,
                    description=excluded.description,
                    state_path=excluded.state_path,
                    updated_at=excluded.updated_at
                """,
                (
                    metadata["project_id"],
                    metadata["name"],
                    metadata["description"],
                    str(root),
                    str(database.database_path),
                    metadata["created_at"],
                    metadata["updated_at"],
                ),
            )
        return self.get_project(str(metadata["project_id"]))

    def update_project(self, project_id: str, *, name: Optional[str], description: Optional[str]) -> Dict[str, Any]:
        current = self.get_project(project_id)
        database = self.project_database(project_id)
        new_name = (name or current["name"]).strip()
        if not new_name:
            raise WorkbenchError("invalid_project_name", "项目名称不能为空。", status_code=422)
        new_description = current["description"] if description is None else description
        database.initialize(
            project_id=project_id,
            name=new_name,
            description=new_description,
            created_at=current["created_at"],
        )
        metadata = database.metadata()
        assert metadata is not None
        with self.catalog() as connection:
            connection.execute(
                "UPDATE projects SET name=?, description=?, updated_at=? WHERE project_id=?",
                (new_name, new_description, metadata["updated_at"], project_id),
            )
        return self.get_project(project_id)

    def ingest_upload(self, project_id: str, *, family: str, filename: str, stream: BinaryIO) -> Dict[str, Any]:
        allowed_families = {
            "dem",
            "rainfall",
            "soil",
            "boundary",
            "config",
            "slope",
            "zones",
            "thickness",
            "manning",
            "groundwater",
            "infiltration",
            "outflow",
            "inflow",
            "monitoring",
            "rifil",
            "zonfil",
            "zfil",
            "slofil",
            "drainage",
            "swmm",
        }
        normalized_family = family.strip().lower()
        if normalized_family not in allowed_families:
            raise WorkbenchError(
                "unsupported_input_family",
                f"不支持的输入族：{family}",
                status_code=422,
            )
        safe_name = Path((filename or "").replace("\\", "/")).name
        if not safe_name:
            raise WorkbenchError("invalid_filename", "上传文件名不能为空。", status_code=422)

        database = self.project_database(project_id)
        upload_id = f"upl-{uuid4().hex}"
        staged_path = database.staging_dir / upload_id
        digest = hashlib.sha256()
        size = 0
        with staged_path.open("wb") as target:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                target.write(chunk)
                digest.update(chunk)
                size += len(chunk)
        if size == 0:
            staged_path.unlink(missing_ok=True)
            raise WorkbenchError("empty_upload", "上传文件不能为空。", status_code=422)

        sha256 = digest.hexdigest()
        blob_path = database.blob_dir / sha256[:2] / sha256
        blob_path.parent.mkdir(parents=True, exist_ok=True)
        deduplicated = blob_path.exists()
        if deduplicated:
            staged_path.unlink(missing_ok=True)
        else:
            staged_path.replace(blob_path)

        created_at = utc_now()
        with database.connect() as connection:
            connection.execute(
                """
                INSERT INTO uploads(
                    upload_id, family, name, sha256, size, blob_path, status,
                    summary, warnings_json, errors_json, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, 'ready', ?, '[]', '[]', ?)
                """,
                (
                    upload_id,
                    normalized_family,
                    safe_name,
                    sha256,
                    size,
                    str(blob_path),
                    "内容校验完成",
                    created_at,
                ),
            )
        return {
            "upload_id": upload_id,
            "project_id": project_id,
            "family": normalized_family,
            "name": safe_name,
            "sha256": sha256,
            "size": size,
            "status": "ready",
            "summary": "内容校验完成",
            "warnings": [],
            "errors": [],
            "created_at": created_at,
            "deduplicated": deduplicated,
        }

    @staticmethod
    def _public_upload(row: sqlite3.Row | Dict[str, Any]) -> Dict[str, Any]:
        data = dict(row)
        return {
            "upload_id": data["upload_id"],
            "family": data["family"],
            "name": data["name"],
            "sha256": data["sha256"],
            "size": data["size"],
            "status": data["status"],
            "summary": data.get("summary"),
            "warnings": json_loads(data.get("warnings_json"), []),
            "errors": json_loads(data.get("errors_json"), []),
            "created_at": data["created_at"],
        }

    def list_uploads(self, project_id: str) -> list[Dict[str, Any]]:
        database = self.project_database(project_id)
        with database.connect() as connection:
            rows = connection.execute("SELECT * FROM uploads ORDER BY created_at, upload_id").fetchall()
        return [self._public_upload(row) for row in rows]

    def _revision_row(self, project_id: str, revision_id: str) -> sqlite3.Row:
        database = self.project_database(project_id)
        with database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM input_revisions WHERE revision_id=?", (revision_id,)
            ).fetchone()
        if not row:
            raise WorkbenchError("input_revision_not_found", "输入修订不存在。", status_code=404)
        return row

    @staticmethod
    def _public_revision(project_id: str, row: sqlite3.Row | Dict[str, Any]) -> Dict[str, Any]:
        data = dict(row)
        manifest = json_loads(data["manifest_json"], [])
        return {
            "revision_id": data["revision_id"],
            "project_id": project_id,
            "version_tag": data["version_tag"],
            "created_at": data["created_at"],
            "status": data["status"],
            "file_count": len(manifest),
            "summary": data["summary"],
            "validation": json_loads(data["validation_json"], {}),
        }

    @staticmethod
    def _validate_manifest(manifest: list[Dict[str, Any]]) -> Dict[str, Any]:
        errors: list[str] = []
        warnings: list[str] = []
        families = {str(item.get("family")) for item in manifest}
        if "dem" not in families:
            errors.append("缺少必需的 DEM 输入。")
        for item in manifest:
            path = Path(str(item.get("blob_path") or ""))
            if not path.is_file():
                errors.append(f"内容文件不可用：{item.get('name')}")
            elif path.stat().st_size != int(item.get("size") or -1):
                errors.append(f"内容大小不匹配：{item.get('name')}")
        if "rainfall" not in families and "rifil" not in families and "config" not in families:
            warnings.append("未提供降雨输入；运行时必须由配置或参数明确提供降雨。")
        return {"valid": not errors, "errors": errors, "warnings": warnings}

    def create_input_revision(
        self,
        project_id: str,
        *,
        version_tag: Optional[str],
        upload_ids: list[str],
        parent_revision_id: Optional[str],
    ) -> Dict[str, Any]:
        database = self.project_database(project_id)
        if not upload_ids and not parent_revision_id:
            raise WorkbenchError("empty_input_revision", "输入修订至少需要一个上传文件。", status_code=422)

        manifest_by_family: Dict[str, Dict[str, Any]] = {}
        if parent_revision_id:
            parent = self._revision_row(project_id, parent_revision_id)
            for item in json_loads(parent["manifest_json"], []):
                manifest_by_family[str(item["family"])] = dict(item)

        with database.connect() as connection:
            placeholders = ",".join("?" for _ in upload_ids)
            rows = (
                connection.execute(
                    f"SELECT * FROM uploads WHERE upload_id IN ({placeholders})", tuple(upload_ids)
                ).fetchall()
                if upload_ids
                else []
            )
        found = {str(row["upload_id"]): row for row in rows}
        missing = [upload_id for upload_id in upload_ids if upload_id not in found]
        if missing:
            raise WorkbenchError(
                "upload_not_found",
                "部分上传记录不存在。",
                status_code=422,
                details={"upload_ids": missing},
            )
        for upload_id in upload_ids:
            row = found[upload_id]
            manifest_by_family[str(row["family"])] = {
                "upload_id": row["upload_id"],
                "family": row["family"],
                "name": row["name"],
                "sha256": row["sha256"],
                "size": row["size"],
                "blob_path": row["blob_path"],
            }

        manifest = list(manifest_by_family.values())
        validation = self._validate_manifest(manifest)
        revision_id = f"rev-{uuid4().hex}"
        with database.connect() as connection:
            count = connection.execute("SELECT COUNT(*) FROM input_revisions").fetchone()[0]
            tag = (version_tag or "").strip() or f"v{count + 1}"
            status = "ready" if validation["valid"] else "invalid"
            summary = f"{len(manifest)} 个文件；{len(validation['warnings'])} 个警告"
            created_at = utc_now()
            connection.execute(
                """
                INSERT INTO input_revisions(
                    revision_id, version_tag, status, summary, manifest_json,
                    validation_json, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    revision_id,
                    tag,
                    status,
                    summary,
                    json.dumps(manifest, ensure_ascii=False),
                    json.dumps(validation, ensure_ascii=False),
                    created_at,
                ),
            )
        return self.get_input_revision(project_id, revision_id)

    def list_input_revisions(self, project_id: str) -> list[Dict[str, Any]]:
        database = self.project_database(project_id)
        with database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM input_revisions ORDER BY created_at DESC, revision_id DESC"
            ).fetchall()
        return [self._public_revision(project_id, row) for row in rows]

    def get_input_revision(self, project_id: str, revision_id: str) -> Dict[str, Any]:
        return self._public_revision(project_id, self._revision_row(project_id, revision_id))

    def input_revision_files(self, project_id: str, revision_id: str) -> list[Dict[str, Any]]:
        row = self._revision_row(project_id, revision_id)
        files = []
        for item in json_loads(row["manifest_json"], []):
            files.append({key: value for key, value in item.items() if key != "blob_path"})
        return files

    def validate_input_revision(self, project_id: str, revision_id: str) -> Dict[str, Any]:
        database = self.project_database(project_id)
        row = self._revision_row(project_id, revision_id)
        validation = self._validate_manifest(json_loads(row["manifest_json"], []))
        status = "ready" if validation["valid"] else "invalid"
        with database.connect() as connection:
            connection.execute(
                "UPDATE input_revisions SET status=?, validation_json=? WHERE revision_id=?",
                (status, json.dumps(validation, ensure_ascii=False), revision_id),
            )
        return validation

    @staticmethod
    def _editable_parameter_keys() -> set[str]:
        from api.services.parameter_catalog import build_static_parameter_catalog

        catalog = build_static_parameter_catalog()
        return {
            str(entry["key"])
            for entry in catalog["parameters"]
            if entry.get("editable")
            and entry.get("runtime_status") in {"production_consumed", "config_fallback_consumed"}
        }

    def _validate_parameter_patch(self, patch: Dict[str, Any]) -> None:
        allowed = self._editable_parameter_keys()
        invalid = sorted(key for key in patch if key not in allowed)
        if invalid:
            raise WorkbenchError(
                "parameter_not_editable",
                "参数没有可执行消费证据，不能写入方案。",
                status_code=422,
                details={"keys": invalid},
            )

    def _scenario_row(self, project_id: str, scenario_id: str) -> sqlite3.Row:
        database = self.project_database(project_id)
        with database.connect() as connection:
            row = connection.execute("SELECT * FROM scenarios WHERE scenario_id=?", (scenario_id,)).fetchone()
        if not row:
            raise WorkbenchError("scenario_not_found", "方案不存在。", status_code=404)
        return row

    def _public_scenario(self, project_id: str, row: sqlite3.Row | Dict[str, Any]) -> Dict[str, Any]:
        database = self.project_database(project_id)
        data = dict(row)
        with database.connect() as connection:
            revision = connection.execute(
                "SELECT manifest_json FROM input_revisions WHERE revision_id=?",
                (data["input_revision_id"],),
            ).fetchone()
            family_count = connection.execute(
                "SELECT COUNT(*) FROM result_families WHERE simulation_id=?",
                (data.get("latest_simulation_id"),),
            ).fetchone()[0] if data.get("latest_simulation_id") else 0
            progress_row = connection.execute(
                "SELECT progress FROM simulation_runs WHERE simulation_id=?",
                (data.get("latest_simulation_id"),),
            ).fetchone() if data.get("latest_simulation_id") else None
        file_count = len(json_loads(revision["manifest_json"], [])) if revision else 0
        return {
            "scenario_id": data["scenario_id"],
            "project_id": project_id,
            "name": data["name"],
            "input_revision_id": data["input_revision_id"],
            "base_scenario_id": data.get("base_scenario_id"),
            "parameter_patch": json_loads(data["parameter_patch_json"], {}),
            "effective_parameters": json_loads(data["effective_parameters_json"], {}),
            "status": data["status"],
            "progress": float(progress_row["progress"]) if progress_row else 0.0,
            "latest_simulation_id": data.get("latest_simulation_id"),
            "result_family_count": int(family_count),
            "file_count": file_count,
            "created_at": data["created_at"],
            "updated_at": data["updated_at"],
        }

    def list_scenarios(self, project_id: str) -> list[Dict[str, Any]]:
        database = self.project_database(project_id)
        with database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM scenarios ORDER BY created_at, scenario_id"
            ).fetchall()
        return [self._public_scenario(project_id, row) for row in rows]

    def create_scenario(
        self,
        project_id: str,
        *,
        name: str,
        input_revision_id: Optional[str],
        base_scenario_id: Optional[str],
        parameter_patch: Dict[str, Any],
    ) -> Dict[str, Any]:
        database = self.project_database(project_id)
        base = self._scenario_row(project_id, base_scenario_id) if base_scenario_id else None
        with database.connect() as connection:
            revision = (
                connection.execute(
                    "SELECT * FROM input_revisions WHERE revision_id=?", (input_revision_id,)
                ).fetchone()
                if input_revision_id
                else connection.execute(
                    "SELECT * FROM input_revisions WHERE status='ready' ORDER BY created_at DESC LIMIT 1"
                ).fetchone()
            )
        if not revision:
            raise WorkbenchError("input_revision_required", "创建方案前需要可用的输入修订。", status_code=422)
        if revision["status"] != "ready":
            raise WorkbenchError("input_revision_invalid", "方案只能引用已通过校验的输入修订。", status_code=409)

        effective_patch = json_loads(base["parameter_patch_json"], {}) if base else {}
        effective_patch.update(parameter_patch)
        self._validate_parameter_patch(effective_patch)
        scenario_id = f"scn-{uuid4().hex}"
        now = utc_now()
        with database.connect() as connection:
            connection.execute(
                """
                INSERT INTO scenarios(
                    scenario_id, name, input_revision_id, base_scenario_id,
                    parameter_patch_json, effective_parameters_json, status,
                    archived, latest_simulation_id, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, 'ready', 0, NULL, ?, ?)
                """,
                (
                    scenario_id,
                    name.strip(),
                    revision["revision_id"],
                    base_scenario_id,
                    json.dumps(effective_patch, ensure_ascii=False),
                    json.dumps(effective_patch, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return self._public_scenario(project_id, self._scenario_row(project_id, scenario_id))

    def update_scenario(
        self,
        project_id: str,
        scenario_id: str,
        *,
        name: Optional[str],
        parameter_patch: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        database = self.project_database(project_id)
        row = self._scenario_row(project_id, scenario_id)
        with database.connect() as connection:
            history_count = connection.execute(
                "SELECT COUNT(*) FROM simulation_runs WHERE scenario_id=?", (scenario_id,)
            ).fetchone()[0]
            queue_count = connection.execute(
                "SELECT COUNT(*) FROM queue_items WHERE scenario_id=?", (scenario_id,)
            ).fetchone()[0]
        if row["archived"] or row["status"] in {"completed", "archived"} or history_count or queue_count:
            raise WorkbenchError(
                "scenario_immutable",
                "已有运行或队列历史的方案不可修改，请复制后修改。",
                status_code=409,
            )
        patch = json_loads(row["parameter_patch_json"], {}) if parameter_patch is None else parameter_patch
        self._validate_parameter_patch(patch)
        new_name = row["name"] if name is None else name.strip()
        if not new_name:
            raise WorkbenchError("invalid_scenario_name", "方案名称不能为空。", status_code=422)
        with database.connect() as connection:
            connection.execute(
                """
                UPDATE scenarios SET name=?, parameter_patch_json=?,
                    effective_parameters_json=?, updated_at=? WHERE scenario_id=?
                """,
                (
                    new_name,
                    json.dumps(patch, ensure_ascii=False),
                    json.dumps(patch, ensure_ascii=False),
                    utc_now(),
                    scenario_id,
                ),
            )
        return self._public_scenario(project_id, self._scenario_row(project_id, scenario_id))

    def duplicate_scenario(self, project_id: str, scenario_id: str) -> Dict[str, Any]:
        source = self._scenario_row(project_id, scenario_id)
        return self.create_scenario(
            project_id,
            name=f"{source['name']}（副本）",
            input_revision_id=source["input_revision_id"],
            base_scenario_id=scenario_id,
            parameter_patch=json_loads(source["parameter_patch_json"], {}),
        )

    def archive_scenario(self, project_id: str, scenario_id: str) -> Dict[str, Any]:
        database = self.project_database(project_id)
        self._scenario_row(project_id, scenario_id)
        with database.connect() as connection:
            connection.execute(
                "UPDATE scenarios SET archived=1, status='archived', updated_at=? WHERE scenario_id=?",
                (utc_now(), scenario_id),
            )
        return self._public_scenario(project_id, self._scenario_row(project_id, scenario_id))

    def delete_scenario(self, project_id: str, scenario_id: str) -> None:
        database = self.project_database(project_id)
        self._scenario_row(project_id, scenario_id)
        with database.connect() as connection:
            history_count = connection.execute(
                "SELECT COUNT(*) FROM simulation_runs WHERE scenario_id=?", (scenario_id,)
            ).fetchone()[0]
            queue_count = connection.execute(
                "SELECT COUNT(*) FROM queue_items WHERE scenario_id=?", (scenario_id,)
            ).fetchone()[0]
            if history_count or queue_count:
                raise WorkbenchError(
                    "scenario_has_history",
                    "已有运行或队列历史的方案只能归档。",
                    status_code=409,
                )
            connection.execute("DELETE FROM scenarios WHERE scenario_id=?", (scenario_id,))

    def _queue_row(self, project_id: str, queue_item_id: str) -> sqlite3.Row:
        database = self.project_database(project_id)
        with database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM queue_items WHERE queue_item_id=?", (queue_item_id,)
            ).fetchone()
        if not row:
            raise WorkbenchError("queue_item_not_found", "队列项不存在。", status_code=404)
        return row

    def _public_queue_item(self, project_id: str, row: sqlite3.Row | Dict[str, Any]) -> Dict[str, Any]:
        database = self.project_database(project_id)
        data = dict(row)
        with database.connect() as connection:
            scenario = connection.execute(
                "SELECT name FROM scenarios WHERE scenario_id=?", (data["scenario_id"],)
            ).fetchone()
        return {
            "queue_item_id": data["queue_item_id"],
            "project_id": project_id,
            "scenario_id": data["scenario_id"],
            "scenario_name": scenario["name"] if scenario else data["scenario_id"],
            "position": data["position"],
            "status": data["status"],
            "simulation_id": data.get("simulation_id"),
            "retry_of": data.get("retry_of"),
            "enqueued_at": data["enqueued_at"],
            "started_at": data.get("started_at"),
            "finished_at": data.get("finished_at"),
            "progress": float(data["progress"]),
            "summary": data["summary"],
        }

    def list_queue(self, project_id: str) -> list[Dict[str, Any]]:
        database = self.project_database(project_id)
        with database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM queue_items ORDER BY position, enqueued_at, queue_item_id"
            ).fetchall()
        return [self._public_queue_item(project_id, row) for row in rows]

    def enqueue_scenario(
        self,
        project_id: str,
        scenario_id: str,
        *,
        retry_of: Optional[str] = None,
    ) -> Dict[str, Any]:
        database = self.project_database(project_id)
        scenario = self._scenario_row(project_id, scenario_id)
        if scenario["archived"]:
            raise WorkbenchError("scenario_archived", "已归档方案不能入队。", status_code=409)
        with database.connect() as connection:
            duplicate = connection.execute(
                """
                SELECT queue_item_id FROM queue_items
                WHERE scenario_id=? AND status IN ('queued', 'starting', 'running', 'stopping')
                """,
                (scenario_id,),
            ).fetchone()
            if duplicate:
                raise WorkbenchError("scenario_already_queued", "方案已在队列中。", status_code=409)
            position = connection.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM queue_items").fetchone()[0]
            queue_item_id = f"que-{uuid4().hex}"
            now = utc_now()
            connection.execute(
                """
                INSERT INTO queue_items(
                    queue_item_id, scenario_id, position, status, simulation_id,
                    retry_of, enqueued_at, started_at, finished_at, progress, summary
                ) VALUES(?, ?, ?, 'queued', NULL, ?, ?, NULL, NULL, 0, '等待调度')
                """,
                (queue_item_id, scenario_id, position, retry_of, now),
            )
            connection.execute(
                "UPDATE scenarios SET status='queued', updated_at=? WHERE scenario_id=?",
                (now, scenario_id),
            )
        return self._public_queue_item(project_id, self._queue_row(project_id, queue_item_id))

    def reorder_queue(self, project_id: str, queue_item_id: str, new_position: int) -> list[Dict[str, Any]]:
        database = self.project_database(project_id)
        row = self._queue_row(project_id, queue_item_id)
        if row["status"] != "queued":
            raise WorkbenchError("queue_item_not_reorderable", "只有等待中的队列项可以重排。", status_code=409)
        with database.connect() as connection:
            queued = connection.execute(
                "SELECT queue_item_id FROM queue_items WHERE status='queued' ORDER BY position, enqueued_at"
            ).fetchall()
            ordered_ids = [str(item["queue_item_id"]) for item in queued]
            ordered_ids.remove(queue_item_id)
            index = max(0, min(len(ordered_ids), new_position - 1))
            ordered_ids.insert(index, queue_item_id)
            for position, item_id in enumerate(ordered_ids, start=1):
                connection.execute(
                    "UPDATE queue_items SET position=? WHERE queue_item_id=?", (position, item_id)
                )
        return self.list_queue(project_id)

    def cancel_queue_item(self, project_id: str, queue_item_id: str) -> Dict[str, Any]:
        database = self.project_database(project_id)
        row = self._queue_row(project_id, queue_item_id)
        if row["status"] != "queued":
            raise WorkbenchError("queue_item_not_cancelable", "只有等待中的队列项可以取消。", status_code=409)
        now = utc_now()
        with database.connect() as connection:
            connection.execute(
                """
                UPDATE queue_items SET status='cancelled', finished_at=?, summary='已取消'
                WHERE queue_item_id=?
                """,
                (now, queue_item_id),
            )
            connection.execute(
                "UPDATE scenarios SET status='ready', updated_at=? WHERE scenario_id=?",
                (now, row["scenario_id"]),
            )
        return self._public_queue_item(project_id, self._queue_row(project_id, queue_item_id))

    def retry_queue_item(self, project_id: str, queue_item_id: str) -> Dict[str, Any]:
        row = self._queue_row(project_id, queue_item_id)
        if row["status"] not in {"cancelled", "failed", "interrupted", "stopped"}:
            raise WorkbenchError("queue_item_not_retryable", "该队列项当前不能重试。", status_code=409)
        return self.enqueue_scenario(
            project_id,
            str(row["scenario_id"]),
            retry_of=queue_item_id,
        )

    def recover_interrupted_runs(self) -> int:
        recovered = 0
        now = utc_now()
        for project in self.list_projects():
            if not project["available"]:
                continue
            database = ProjectDatabase(Path(project["root_path"]))
            with database.connect() as connection:
                queue_rows = connection.execute(
                    "SELECT queue_item_id, scenario_id, simulation_id FROM queue_items WHERE status IN ('starting', 'running', 'stopping')"
                ).fetchall()
                for row in queue_rows:
                    connection.execute(
                        "UPDATE queue_items SET status='interrupted', finished_at=?, summary='服务重启后中断' WHERE queue_item_id=?",
                        (now, row["queue_item_id"]),
                    )
                    connection.execute(
                        "UPDATE scenarios SET status='stopped', updated_at=? WHERE scenario_id=?",
                        (now, row["scenario_id"]),
                    )
                    if row["simulation_id"]:
                        connection.execute(
                            "UPDATE simulation_runs SET status='interrupted', end_time_actual=?, error='service_restart' WHERE simulation_id=?",
                            (now, row["simulation_id"]),
                        )
                    recovered += 1
        return recovered

    def queue_candidates(self, active_projects: set[str]) -> list[Dict[str, Any]]:
        """Return at most one waiting head per project, ordered globally by enqueue time."""
        candidates: list[Dict[str, Any]] = []
        for project in self.list_projects():
            project_id = str(project["project_id"])
            if project_id in active_projects or not project["available"]:
                continue
            database = ProjectDatabase(Path(project["root_path"]))
            with database.connect() as connection:
                row = connection.execute(
                    """
                    SELECT q.*, s.input_revision_id, s.parameter_patch_json,
                           s.effective_parameters_json, s.name AS scenario_name
                    FROM queue_items q
                    JOIN scenarios s ON s.scenario_id=q.scenario_id
                    WHERE q.status='queued'
                    ORDER BY q.position, q.enqueued_at, q.queue_item_id
                    LIMIT 1
                    """
                ).fetchone()
            if row:
                candidate = dict(row)
                candidate["project_id"] = project_id
                candidate["project_root"] = project["root_path"]
                candidate["runtime_profile"] = "cuda_production_default"
                candidates.append(candidate)
        candidates.sort(key=lambda item: (str(item["enqueued_at"]), str(item["queue_item_id"])))
        return candidates

    @staticmethod
    def _expand_dotted_values(values: Dict[str, Any]) -> Dict[str, Any]:
        expanded: Dict[str, Any] = {}
        for key, value in values.items():
            current = expanded
            parts = str(key).split(".")
            for part in parts[:-1]:
                child = current.get(part)
                if not isinstance(child, dict):
                    child = {}
                    current[part] = child
                current = child
            current[parts[-1]] = value
        return expanded

    def claim_queue_item(self, project_id: str, queue_item_id: str) -> Dict[str, Any]:
        """Atomically create a run and move a queued item into starting."""
        database = self.project_database(project_id)
        item = self._queue_row(project_id, queue_item_id)
        if item["status"] != "queued":
            raise WorkbenchError("queue_item_not_claimable", "队列项已经被其他执行器领取。", status_code=409)
        scenario = self._scenario_row(project_id, str(item["scenario_id"]))
        revision = self._revision_row(project_id, str(scenario["input_revision_id"]))
        if revision["status"] != "ready":
            raise WorkbenchError("input_revision_invalid", "队列项引用的输入修订未通过校验。", status_code=409)
        simulation_id = f"sim-{uuid4().hex}"
        output_dir = str(Path(self.get_project(project_id)["root_path"]) / "outputs" / simulation_id)
        now = utc_now()
        with database.connect() as connection:
            connection.execute(
                """
                UPDATE queue_items SET status='starting', simulation_id=?, started_at=?, summary='准备运行'
                WHERE queue_item_id=? AND status='queued'
                """,
                (simulation_id, now, queue_item_id),
            )
            if connection.total_changes == 0:
                raise WorkbenchError("queue_item_not_claimable", "队列项已经被其他执行器领取。", status_code=409)
            connection.execute(
                """
                INSERT INTO simulation_runs(
                    simulation_id, scenario_id, status, progress, current_time, end_time,
                    step_count, output_count, start_time, end_time_actual, error,
                    elapsed_seconds, output_dir, runtime_profile_json,
                    effective_config_json, resource_summary_json, terminal_log_json, created_at
                ) VALUES(?, ?, 'starting', 0, 0, 0, 0, 0, ?, NULL, NULL, 0, ?, ?, ?, '{}', '[]', ?)
                """,
                (
                    simulation_id,
                    scenario["scenario_id"],
                    now,
                    output_dir,
                    json.dumps({"name": "cuda_production_default"}),
                    json.dumps(json_loads(scenario["effective_parameters_json"], {}), ensure_ascii=False),
                    now,
                ),
            )
            connection.execute(
                "UPDATE scenarios SET latest_simulation_id=?, status='running', updated_at=? WHERE scenario_id=?",
                (simulation_id, now, scenario["scenario_id"]),
            )
        manifest = json_loads(revision["manifest_json"], [])
        by_family: Dict[str, Dict[str, Any]] = {}
        for entry in manifest:
            by_family[str(entry["family"])] = dict(entry)
        case_input_files = {
            family: str(entry["blob_path"])
            for family, entry in by_family.items()
            if family not in {"dem", "rainfall", "soil", "zones", "boundary", "config"}
        }
        dem = by_family.get("dem")
        rainfall = by_family.get("rainfall")
        soil = by_family.get("soil") or by_family.get("zones")
        boundary = by_family.get("boundary")
        config = by_family.get("config")
        return {
            "project_id": project_id,
            "project_root": str(self.get_project(project_id)["root_path"]),
            "queue_item_id": queue_item_id,
            "simulation_id": simulation_id,
            "scenario_id": scenario["scenario_id"],
            "scenario_name": scenario["name"],
            "runtime_profile": "cuda_production_default",
            "output_dir": output_dir,
            "dem_file": str(dem["blob_path"]) if dem else None,
            "rainfall_file": str(rainfall["blob_path"]) if rainfall else None,
            "soil_zones_file": str(soil["blob_path"]) if soil else None,
            "boundary_file": str(boundary["blob_path"]) if boundary else None,
            "case_config_file": str(config["blob_path"]) if config else None,
            "case_base_dir": str(Path(config["blob_path"]).parent) if config else None,
            "case_input_files": case_input_files,
            "overrides": self._expand_dotted_values(json_loads(scenario["effective_parameters_json"], {})),
        }

    def update_run(self, project_id: str, simulation_id: str, values: Dict[str, Any]) -> None:
        database = self.project_database(project_id)
        allowed = {
            "status",
            "progress",
            "current_time",
            "end_time",
            "step_count",
            "output_count",
            "start_time",
            "end_time_actual",
            "error",
            "elapsed_seconds",
            "runtime_profile_json",
            "effective_config_json",
            "resource_summary_json",
            "terminal_log_json",
        }
        fields = [(key, value) for key, value in values.items() if key in allowed]
        if not fields:
            return
        assignments = ", ".join(f"{key}=?" for key, _ in fields)
        params = [value for _, value in fields] + [simulation_id]
        with database.connect() as connection:
            connection.execute(f"UPDATE simulation_runs SET {assignments} WHERE simulation_id=?", params)
            status = values.get("status")
            if status in {"running", "starting", "stopping"}:
                connection.execute(
                    "UPDATE queue_items SET status=?, progress=?, summary=? WHERE simulation_id=?",
                    (
                        status,
                        float(values.get("progress") or 0),
                        "正在模拟中" if status == "running" else "准备运行",
                        simulation_id,
                    ),
                )

    def finish_run(self, project_id: str, simulation_id: str, result: Dict[str, Any]) -> None:
        database = self.project_database(project_id)
        status = str(result.get("status") or "failed")
        if status not in {"completed", "failed", "stopped", "interrupted"}:
            status = "failed"
        now = utc_now()
        with database.connect() as connection:
            row = connection.execute(
                "SELECT scenario_id FROM simulation_runs WHERE simulation_id=?", (simulation_id,)
            ).fetchone()
            if not row:
                raise WorkbenchError("simulation_not_found", "模拟记录不存在。", status_code=404)
            connection.execute(
                """
                UPDATE simulation_runs SET status=?, progress=?, end_time_actual=?, error=?,
                    resource_summary_json=?, elapsed_seconds=? WHERE simulation_id=?
                """,
                (
                    status,
                    float(result.get("progress") if result.get("progress") is not None else (100.0 if status == "completed" else 0.0)),
                    now,
                    result.get("error"),
                    json.dumps(result.get("resource_summary") or {}, ensure_ascii=False),
                    float(result.get("elapsed_seconds") or 0),
                    simulation_id,
                ),
            )
            connection.execute(
                """
                UPDATE queue_items SET status=?, finished_at=?, progress=?, summary=?
                WHERE simulation_id=?
                """,
                (status, now, float(result.get("progress") or 0), status, simulation_id),
            )
            scenario_status = "completed" if status == "completed" else status
            connection.execute(
                "UPDATE scenarios SET status=?, updated_at=? WHERE scenario_id=?",
                (scenario_status, now, row["scenario_id"]),
            )

    def simulation_row(self, project_id: str, simulation_id: str) -> sqlite3.Row:
        database = self.project_database(project_id)
        with database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM simulation_runs WHERE simulation_id=?", (simulation_id,)
            ).fetchone()
        if not row:
            raise WorkbenchError("simulation_not_found", "模拟记录不存在。", status_code=404)
        return row

    @staticmethod
    def public_simulation(project_id: str, row: sqlite3.Row | Dict[str, Any]) -> Dict[str, Any]:
        data = dict(row)
        return {
            "simulation_id": data["simulation_id"],
            "project_id": project_id,
            "scenario_id": data["scenario_id"],
            "status": data["status"],
            "progress": float(data["progress"]),
            "current_time": float(data["current_time"]),
            "end_time": float(data["end_time"]),
            "step_count": int(data["step_count"]),
            "output_count": int(data["output_count"]),
            "start_time": data.get("start_time"),
            "end_time_actual": data.get("end_time_actual"),
            "error": data.get("error"),
            "elapsed_seconds": float(data["elapsed_seconds"]),
            "output_dir": data.get("output_dir"),
            "resource_summary": json_loads(data.get("resource_summary_json"), {}),
            "terminal_log": json_loads(data.get("terminal_log_json"), []),
        }

    def list_simulations(self, project_id: str) -> list[Dict[str, Any]]:
        database = self.project_database(project_id)
        with database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM simulation_runs ORDER BY created_at DESC, simulation_id DESC"
            ).fetchall()
        return [self.public_simulation(project_id, row) for row in rows]

    def find_simulation(self, simulation_id: str) -> tuple[str, Dict[str, Any]]:
        for project in self.list_projects():
            if not project["available"]:
                continue
            database = ProjectDatabase(Path(project["root_path"]))
            with database.connect() as connection:
                row = connection.execute(
                    "SELECT * FROM simulation_runs WHERE simulation_id=?", (simulation_id,)
                ).fetchone()
            if row:
                return str(project["project_id"]), self.public_simulation(str(project["project_id"]), row)
        raise WorkbenchError("simulation_not_found", "模拟记录不存在。", status_code=404)


def _claim_queue_item_without_fk_race(self: WorkbenchStore, project_id: str, queue_item_id: str) -> Dict[str, Any]:
    """Claim a queued item without assigning an FK before its run exists.

    SQLite enforces the ``queue_items.simulation_id`` foreign key immediately;
    the queue row therefore moves to ``starting`` first, the run row is
    inserted second, and the simulation id is attached in the same transaction.
    """
    database = self.project_database(project_id)
    item = self._queue_row(project_id, queue_item_id)
    if item["status"] != "queued":
        raise WorkbenchError("queue_item_not_claimable", "Queue item is no longer queued.", status_code=409)
    scenario = self._scenario_row(project_id, str(item["scenario_id"]))
    revision = self._revision_row(project_id, str(scenario["input_revision_id"]))
    if revision["status"] != "ready":
        raise WorkbenchError("input_revision_invalid", "Queued input revision is not ready.", status_code=409)
    simulation_id = f"sim-{uuid4().hex}"
    project = self.get_project(project_id)
    output_dir = str(Path(project["root_path"]) / "outputs" / simulation_id)
    now = utc_now()
    with database.connect() as connection:
        claim = connection.execute(
            "UPDATE queue_items SET status='starting', started_at=?, summary=? WHERE queue_item_id=? AND status='queued'",
            (now, "Preparing run", queue_item_id),
        )
        if claim.rowcount == 0:
            raise WorkbenchError("queue_item_not_claimable", "Queue item is no longer queued.", status_code=409)
        connection.execute(
            """
            INSERT INTO simulation_runs(
                simulation_id, scenario_id, status, progress, current_time, end_time,
                step_count, output_count, start_time, end_time_actual, error,
                elapsed_seconds, output_dir, runtime_profile_json,
                effective_config_json, resource_summary_json, terminal_log_json, created_at
            ) VALUES(?, ?, 'starting', 0, 0, 0, 0, 0, ?, NULL, NULL, 0, ?, ?, ?, '{}', '[]', ?)
            """,
            (
                simulation_id,
                scenario["scenario_id"],
                now,
                output_dir,
                json.dumps({"name": "cuda_production_default"}),
                json.dumps(json_loads(scenario["effective_parameters_json"], {}), ensure_ascii=False),
                now,
            ),
        )
        connection.execute(
            "UPDATE queue_items SET simulation_id=? WHERE queue_item_id=?",
            (simulation_id, queue_item_id),
        )
        connection.execute(
            "UPDATE scenarios SET latest_simulation_id=?, status='running', updated_at=? WHERE scenario_id=?",
            (simulation_id, now, scenario["scenario_id"]),
        )

    manifest = json_loads(revision["manifest_json"], [])
    by_family = {str(entry["family"]): dict(entry) for entry in manifest}
    case_input_files = {
        family: str(entry["blob_path"])
        for family, entry in by_family.items()
        if family not in {"dem", "rainfall", "soil", "zones", "boundary", "config"}
    }
    dem = by_family.get("dem")
    rainfall = by_family.get("rainfall")
    soil = by_family.get("soil") or by_family.get("zones")
    boundary = by_family.get("boundary")
    config = by_family.get("config")
    return {
        "project_id": project_id,
        "project_root": str(project["root_path"]),
        "queue_item_id": queue_item_id,
        "simulation_id": simulation_id,
        "scenario_id": scenario["scenario_id"],
        "scenario_name": scenario["name"],
        "runtime_profile": "cuda_production_default",
        "output_dir": output_dir,
        "dem_file": str(dem["blob_path"]) if dem else None,
        "rainfall_file": str(rainfall["blob_path"]) if rainfall else None,
        "soil_zones_file": str(soil["blob_path"]) if soil else None,
        "boundary_file": str(boundary["blob_path"]) if boundary else None,
        "case_config_file": str(config["blob_path"]) if config else None,
        "case_base_dir": str(Path(config["blob_path"]).parent) if config else None,
        "case_input_files": case_input_files,
        "overrides": self._expand_dotted_values(json_loads(scenario["effective_parameters_json"], {})),
    }


# Keep the public method name stable while using the FK-safe implementation.
WorkbenchStore.claim_queue_item = _claim_queue_item_without_fk_race


def json_loads(value: Optional[str], fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback
