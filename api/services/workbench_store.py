"""Persistent Taichi-Flow workbench domain storage.

The public application owns a small global project catalog.  Each registered
project owns its scientific workflow metadata in ``.taichi-flow/state.sqlite3``
and keeps large files on disk beside that database.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Dict, Iterator, Mapping, Optional
from uuid import uuid4
import hashlib
import json
import os
import re
import sqlite3
import shutil


SCHEMA_VERSION = 10


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


def _legacy_binding_identity(family: str, ordinal: int) -> tuple[str, str]:
    """Give legacy manifest entries stable semantic slots during v3 migration."""
    normalized = str(family or "native").strip().lower()
    primary = {
        "dem": ("dem.primary", "primary"),
        "demfil": ("dem.primary", "primary"),
        "manning": ("manning.raster", "manning-raster"),
        "manningfil": ("manning.raster", "manning-raster"),
        "zones": ("zones.primary", "zones"),
        "zonfil": ("zones.primary", "zones"),
        "slope": ("slope.primary", "slope"),
        "slofil": ("slope.primary", "slope"),
        "thickness": ("thickness.primary", "thickness"),
        "zfil": ("thickness.primary", "thickness"),
        "trigger": ("trigger.primary", "trigger"),
        "triggerslide": ("trigger.primary", "trigger"),
        "config": ("legacy.config", "legacy-config"),
    }
    if normalized in {"rainfall", "rifil"}:
        return f"rainfall.period.{ordinal:04d}", "rainfall-period"
    if normalized in primary and ordinal == 1:
        return primary[normalized]
    return f"{normalized}.asset.{ordinal:04d}", normalized


ASSET_ROLE_BY_FAMILY = {
    "dem": "elevation",
    "rainfall": "rainfall-period",
    "rifil": "rainfall-period",
    "manning": "manning-raster",
    "manningfil": "manning-raster",
    "slope": "slope",
    "slofil": "slope",
    "zones": "zones",
    "zonfil": "zones",
    "thickness": "thickness",
    "zfil": "thickness",
    "trigger": "trigger",
    "triggerslide": "trigger",
    "config": "legacy-config",
}

RASTER_ASSET_FAMILIES = {
    "dem",
    "rainfall",
    "rifil",
    "manning",
    "manningfil",
    "slope",
    "slofil",
    "zones",
    "zonfil",
    "thickness",
    "zfil",
    "trigger",
    "triggerslide",
    "groundwater",
    "infiltration",
}


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
        self.scenarios_dir = self.root / "scenarios"

    def scenario_dir(self, scenario_id: str) -> Path:
        return self.scenarios_dir / str(scenario_id)

    def scenario_output_dir(self, scenario_id: str, simulation_id: str) -> Path:
        return self.scenario_dir(scenario_id) / "outputs" / str(simulation_id)

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
        for path in (self.state_dir, self.blob_dir, self.staging_dir, self.export_dir, self.output_dir, self.scenarios_dir):
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
                    roles_json TEXT NOT NULL DEFAULT '[]',
                    media_type TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    archived INTEGER NOT NULL DEFAULT 0,
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
                    parent_revision_id TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS input_revision_bindings (
                    revision_id TEXT NOT NULL REFERENCES input_revisions(revision_id) ON DELETE CASCADE,
                    binding_key TEXT NOT NULL,
                    asset_id TEXT NOT NULL,
                    family TEXT NOT NULL,
                    role TEXT NOT NULL,
                    period_id TEXT,
                    ordinal INTEGER,
                    active INTEGER NOT NULL DEFAULT 1,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY (revision_id, binding_key)
                );
                CREATE INDEX IF NOT EXISTS idx_input_revision_bindings_asset
                    ON input_revision_bindings(asset_id);
                CREATE TABLE IF NOT EXISTS scenario_draft_bindings (
                    scenario_id TEXT NOT NULL REFERENCES scenarios(scenario_id) ON DELETE CASCADE,
                    binding_key TEXT NOT NULL,
                    asset_id TEXT NOT NULL,
                    family TEXT NOT NULL,
                    role TEXT NOT NULL,
                    period_id TEXT,
                    ordinal INTEGER,
                    active INTEGER NOT NULL DEFAULT 1,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY (scenario_id, binding_key)
                );
                CREATE INDEX IF NOT EXISTS idx_scenario_draft_bindings_asset
                    ON scenario_draft_bindings(asset_id);
                CREATE TABLE IF NOT EXISTS parameter_templates (
                    template_id TEXT PRIMARY KEY,
                    version TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    source_hash TEXT,
                    values_json TEXT NOT NULL,
                    field_provenance_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS scenarios (
                    scenario_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    input_revision_id TEXT REFERENCES input_revisions(revision_id),
                    base_scenario_id TEXT REFERENCES scenarios(scenario_id),
                    parameter_template_id TEXT,
                    parameter_patch_json TEXT NOT NULL,
                    control_overrides_json TEXT NOT NULL DEFAULT '{}',
                    effective_parameters_json TEXT NOT NULL,
                    draft_validation_json TEXT NOT NULL DEFAULT '{}',
                    version INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL,
                    archived INTEGER NOT NULL DEFAULT 0,
                    latest_simulation_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS simulation_runs (
                    simulation_id TEXT PRIMARY KEY,
                    scenario_id TEXT NOT NULL REFERENCES scenarios(scenario_id),
                    input_revision_id TEXT REFERENCES input_revisions(revision_id),
                    status TEXT NOT NULL,
                    progress REAL NOT NULL DEFAULT 0,
                    current_time REAL NOT NULL DEFAULT 0,
                    end_time REAL NOT NULL DEFAULT 0,
                    step_count INTEGER NOT NULL DEFAULT 0,
                    output_count INTEGER NOT NULL DEFAULT 0,
                    start_time TEXT,
                    end_time_actual TEXT,
                    error TEXT,
                    error_code TEXT,
                    error_details_json TEXT NOT NULL DEFAULT '{}',
                    elapsed_seconds REAL NOT NULL DEFAULT 0,
                    output_dir TEXT,
                    runtime_profile_json TEXT NOT NULL DEFAULT '{}',
                    effective_config_json TEXT NOT NULL DEFAULT '{}',
                    compute_policy_resolution_json TEXT NOT NULL DEFAULT '{}',
                    resource_summary_json TEXT NOT NULL DEFAULT '{}',
                    terminal_log_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS queue_items (
                    queue_item_id TEXT PRIMARY KEY,
                    scenario_id TEXT NOT NULL REFERENCES scenarios(scenario_id),
                    scenario_version INTEGER,
                    input_revision_id TEXT REFERENCES input_revisions(revision_id),
                    position INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    simulation_id TEXT REFERENCES simulation_runs(simulation_id),
                    retry_of TEXT REFERENCES queue_items(queue_item_id),
                    runtime_profile TEXT NOT NULL DEFAULT 'cuda_production_default',
                    effective_config_json TEXT NOT NULL DEFAULT '{}',
                    compute_policy_resolution_json TEXT NOT NULL DEFAULT '{}',
                    enqueued_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    progress REAL NOT NULL DEFAULT 0,
                    summary TEXT NOT NULL,
                    cancel_reason TEXT
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
                CREATE TABLE IF NOT EXISTS raster_profiles (
                    profile_key TEXT PRIMARY KEY,
                    source_sha256 TEXT NOT NULL,
                    data_kind TEXT NOT NULL,
                    profile_version TEXT NOT NULL,
                    status TEXT NOT NULL,
                    profile_json TEXT NOT NULL DEFAULT '{}',
                    cache_path TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(source_sha256, data_kind, profile_version)
                );
                CREATE INDEX IF NOT EXISTS idx_raster_profiles_sha256
                    ON raster_profiles(source_sha256);
                CREATE TABLE IF NOT EXISTS project_map_state (
                    project_id TEXT PRIMARY KEY,
                    version INTEGER NOT NULL DEFAULT 1,
                    state_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL
                );
                """
            )
            self._migrate_schema(connection)
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

    def ensure_schema(self) -> None:
        """Apply schema migrations for an existing project database."""
        if not self.database_path.exists():
            return
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            self._migrate_schema(connection)

    @staticmethod
    def _schema_version(connection: sqlite3.Connection) -> int:
        row = connection.execute(
            "SELECT value FROM schema_metadata WHERE key='schema_version'"
        ).fetchone()
        if not row:
            return 0
        try:
            return int(row["value"])
        except (TypeError, ValueError):
            return 0

    def _migrate_schema(self, connection: sqlite3.Connection) -> None:
        version = self._schema_version(connection)
        if version < 2:
            # Allow draft scenarios without a bound input revision.
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS scenarios_v2 (
                    scenario_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    input_revision_id TEXT REFERENCES input_revisions(revision_id),
                    base_scenario_id TEXT,
                    parameter_patch_json TEXT NOT NULL,
                    effective_parameters_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    archived INTEGER NOT NULL DEFAULT 0,
                    latest_simulation_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            has_scenarios = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='scenarios'"
            ).fetchone()
            has_v2 = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='scenarios_v2'"
            ).fetchone()
            if has_scenarios and has_v2:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO scenarios_v2(
                        scenario_id, name, input_revision_id, base_scenario_id,
                        parameter_patch_json, effective_parameters_json, status,
                        archived, latest_simulation_id, created_at, updated_at
                    )
                    SELECT
                        scenario_id, name, input_revision_id, base_scenario_id,
                        parameter_patch_json, effective_parameters_json, status,
                        archived, latest_simulation_id, created_at, updated_at
                    FROM scenarios
                    """
                )
                connection.execute("DROP TABLE scenarios")
                connection.execute("ALTER TABLE scenarios_v2 RENAME TO scenarios")
            elif has_v2 and not has_scenarios:
                connection.execute("ALTER TABLE scenarios_v2 RENAME TO scenarios")
        if version < 3:
            upload_columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(uploads)").fetchall()
            }
            if "roles_json" not in upload_columns:
                connection.execute("ALTER TABLE uploads ADD COLUMN roles_json TEXT NOT NULL DEFAULT '[]'")
            if "media_type" not in upload_columns:
                connection.execute("ALTER TABLE uploads ADD COLUMN media_type TEXT")
            if "metadata_json" not in upload_columns:
                connection.execute("ALTER TABLE uploads ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'")
            if "archived" not in upload_columns:
                connection.execute("ALTER TABLE uploads ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")

            revision_columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(input_revisions)").fetchall()
            }
            if "parent_revision_id" not in revision_columns:
                connection.execute("ALTER TABLE input_revisions ADD COLUMN parent_revision_id TEXT")

            scenario_columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(scenarios)").fetchall()
            }
            if "parameter_template_id" not in scenario_columns:
                connection.execute("ALTER TABLE scenarios ADD COLUMN parameter_template_id TEXT")
            if "version" not in scenario_columns:
                connection.execute("ALTER TABLE scenarios ADD COLUMN version INTEGER NOT NULL DEFAULT 1")

            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS input_revision_bindings (
                    revision_id TEXT NOT NULL REFERENCES input_revisions(revision_id) ON DELETE CASCADE,
                    binding_key TEXT NOT NULL,
                    asset_id TEXT NOT NULL,
                    family TEXT NOT NULL,
                    role TEXT NOT NULL,
                    period_id TEXT,
                    ordinal INTEGER,
                    active INTEGER NOT NULL DEFAULT 1,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY (revision_id, binding_key)
                );
                CREATE INDEX IF NOT EXISTS idx_input_revision_bindings_asset
                    ON input_revision_bindings(asset_id);
                CREATE TABLE IF NOT EXISTS parameter_templates (
                    template_id TEXT PRIMARY KEY,
                    version TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    source_hash TEXT,
                    values_json TEXT NOT NULL,
                    field_provenance_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            revision_rows = connection.execute(
                "SELECT revision_id, manifest_json FROM input_revisions"
            ).fetchall()
            for revision_row in revision_rows:
                existing = connection.execute(
                    "SELECT COUNT(*) FROM input_revision_bindings WHERE revision_id=?",
                    (revision_row["revision_id"],),
                ).fetchone()[0]
                if existing:
                    continue
                family_counts: Dict[str, int] = {}
                for item in json_loads(revision_row["manifest_json"], []):
                    family = str(item.get("family") or "native")
                    family_counts[family] = family_counts.get(family, 0) + 1
                    ordinal = family_counts[family]
                    binding_key, role = _legacy_binding_identity(family, ordinal)
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO input_revision_bindings(
                            revision_id, binding_key, asset_id, family, role,
                            period_id, ordinal, active, metadata_json
                        ) VALUES(?, ?, ?, ?, ?, ?, ?, 1, '{}')
                        """,
                        (
                            revision_row["revision_id"],
                            binding_key,
                            item.get("upload_id") or item.get("asset_id") or "",
                            family,
                            role,
                            f"period-{ordinal:04d}" if family in {"rainfall", "rifil"} else None,
                            ordinal,
                        ),
                    )
        if version < 4:
            # v4 separates editable scenario input selections from immutable
            # runtime manifests.  A saved draft must not turn an uploaded file
            # into a permanent reference before a scheduler actually starts it.
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS scenario_draft_bindings (
                    scenario_id TEXT NOT NULL REFERENCES scenarios(scenario_id) ON DELETE CASCADE,
                    binding_key TEXT NOT NULL,
                    asset_id TEXT NOT NULL,
                    family TEXT NOT NULL,
                    role TEXT NOT NULL,
                    period_id TEXT,
                    ordinal INTEGER,
                    active INTEGER NOT NULL DEFAULT 1,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY (scenario_id, binding_key)
                );
                CREATE INDEX IF NOT EXISTS idx_scenario_draft_bindings_asset
                    ON scenario_draft_bindings(asset_id);
                """
            )
            simulation_columns = {
                str(column["name"])
                for column in connection.execute("PRAGMA table_info(simulation_runs)").fetchall()
            }
            if "input_revision_id" not in simulation_columns:
                connection.execute("ALTER TABLE simulation_runs ADD COLUMN input_revision_id TEXT")
            queue_columns = {
                str(column["name"])
                for column in connection.execute("PRAGMA table_info(queue_items)").fetchall()
            }
            if "scenario_version" not in queue_columns:
                connection.execute("ALTER TABLE queue_items ADD COLUMN scenario_version INTEGER")
            if "input_revision_id" not in queue_columns:
                connection.execute("ALTER TABLE queue_items ADD COLUMN input_revision_id TEXT")
            if "cancel_reason" not in queue_columns:
                connection.execute("ALTER TABLE queue_items ADD COLUMN cancel_reason TEXT")

            # Existing started runs remain pinned to the revision they used.
            # This is deliberately completed before mutable scenarios are
            # converted to draft bindings.
            connection.execute(
                """
                UPDATE simulation_runs
                SET input_revision_id=(
                    SELECT input_revision_id FROM scenarios s
                    WHERE s.scenario_id=simulation_runs.scenario_id
                )
                WHERE input_revision_id IS NULL
                """
            )
            connection.execute(
                """
                UPDATE queue_items
                SET input_revision_id=(
                    SELECT input_revision_id FROM simulation_runs r
                    WHERE r.simulation_id=queue_items.simulation_id
                )
                WHERE input_revision_id IS NULL AND simulation_id IS NOT NULL
                """
            )
            connection.execute(
                """
                UPDATE queue_items
                SET scenario_version=(
                    SELECT version FROM scenarios s WHERE s.scenario_id=queue_items.scenario_id
                )
                WHERE scenario_version IS NULL
                """
            )

            mutable_legacy_rows = connection.execute(
                """
                SELECT s.scenario_id, s.input_revision_id
                FROM scenarios s
                WHERE s.input_revision_id IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1 FROM simulation_runs r WHERE r.scenario_id=s.scenario_id
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM queue_items q
                    WHERE q.scenario_id=s.scenario_id
                      AND (q.simulation_id IS NOT NULL OR q.status IN ('starting', 'running', 'stopping'))
                  )
                """
            ).fetchall()
            now = utc_now()
            for legacy in mutable_legacy_rows:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO scenario_draft_bindings(
                        scenario_id, binding_key, asset_id, family, role,
                        period_id, ordinal, active, metadata_json
                    )
                    SELECT ?, binding_key, asset_id, family, role,
                           period_id, ordinal, active, metadata_json
                    FROM input_revision_bindings
                    WHERE revision_id=?
                    """,
                    (legacy["scenario_id"], legacy["input_revision_id"]),
                )
                connection.execute(
                    """
                    UPDATE scenarios
                    SET input_revision_id=NULL,
                        status=CASE WHEN archived=1 THEN status ELSE 'draft' END,
                        updated_at=?
                    WHERE scenario_id=?
                    """,
                    (now, legacy["scenario_id"]),
                )
                connection.execute(
                    """
                    UPDATE queue_items
                    SET status='cancelled', finished_at=?, summary='Draft inputs migrated; requeue after review.',
                        cancel_reason='migration_draft_input'
                    WHERE scenario_id=? AND status='queued' AND simulation_id IS NULL
                    """,
                    (now, legacy["scenario_id"]),
                )

            # Orphan draft-era revisions never represented a started run.  The
            # rows are safe to remove; no asset/blob is deleted by this migration.
            connection.execute(
                """
                DELETE FROM input_revisions
                WHERE revision_id NOT IN (
                    SELECT input_revision_id FROM scenarios WHERE input_revision_id IS NOT NULL
                )
                  AND revision_id NOT IN (
                    SELECT input_revision_id FROM simulation_runs WHERE input_revision_id IS NOT NULL
                )
                  AND revision_id NOT IN (
                    SELECT input_revision_id FROM queue_items WHERE input_revision_id IS NOT NULL
                )
                """
            )
        if version < 5:
            scenario_columns = {
                str(column["name"])
                for column in connection.execute("PRAGMA table_info(scenarios)").fetchall()
            }
            if "draft_validation_json" not in scenario_columns:
                connection.execute(
                    "ALTER TABLE scenarios ADD COLUMN draft_validation_json TEXT NOT NULL DEFAULT '{}'"
                )
        if version < 6:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS raster_profiles (
                    profile_key TEXT PRIMARY KEY,
                    source_sha256 TEXT NOT NULL,
                    data_kind TEXT NOT NULL,
                    profile_version TEXT NOT NULL,
                    status TEXT NOT NULL,
                    profile_json TEXT NOT NULL DEFAULT '{}',
                    cache_path TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(source_sha256, data_kind, profile_version)
                );
                CREATE INDEX IF NOT EXISTS idx_raster_profiles_sha256
                    ON raster_profiles(source_sha256);
                CREATE TABLE IF NOT EXISTS project_map_state (
                    project_id TEXT PRIMARY KEY,
                    version INTEGER NOT NULL DEFAULT 1,
                    state_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL
                );
                """
            )
        if version < 7:
            simulation_columns = {
                str(column["name"])
                for column in connection.execute("PRAGMA table_info(simulation_runs)").fetchall()
            }
            if "error_code" not in simulation_columns:
                connection.execute("ALTER TABLE simulation_runs ADD COLUMN error_code TEXT")
            if "error_details_json" not in simulation_columns:
                connection.execute(
                    "ALTER TABLE simulation_runs ADD COLUMN error_details_json TEXT NOT NULL DEFAULT '{}'"
                )
        if version < 8:
            queue_columns = {
                str(column["name"])
                for column in connection.execute("PRAGMA table_info(queue_items)").fetchall()
            }
            if "runtime_profile" not in queue_columns:
                connection.execute(
                    "ALTER TABLE queue_items ADD COLUMN runtime_profile TEXT NOT NULL DEFAULT 'cuda_production_default'"
                )
        if version < 9:
            simulation_columns = {
                str(column["name"])
                for column in connection.execute("PRAGMA table_info(simulation_runs)").fetchall()
            }
            if "compute_policy_resolution_json" not in simulation_columns:
                connection.execute(
                    "ALTER TABLE simulation_runs ADD COLUMN compute_policy_resolution_json TEXT NOT NULL DEFAULT '{}'"
                )
            queue_columns = {
                str(column["name"])
                for column in connection.execute("PRAGMA table_info(queue_items)").fetchall()
            }
            if "effective_config_json" not in queue_columns:
                connection.execute(
                    "ALTER TABLE queue_items ADD COLUMN effective_config_json TEXT NOT NULL DEFAULT '{}'"
                )
            if "compute_policy_resolution_json" not in queue_columns:
                connection.execute(
                    "ALTER TABLE queue_items ADD COLUMN compute_policy_resolution_json TEXT NOT NULL DEFAULT '{}'"
                )
            # Queue rows created before v9 cannot be safely reconstructed from
            # current Settings.  Keep the row for audit history, but cancel
            # any still-waiting item and make the required re-enqueue action
            # explicit instead of allowing the scheduler to reinterpret it.
            migration_now = utc_now()
            connection.execute(
                """
                UPDATE queue_items
                SET status='cancelled', finished_at=COALESCE(finished_at, ?),
                    cancel_reason='policy_snapshot_missing_after_upgrade',
                    summary='缺少升级后的计算策略快照，请重新加入队列。'
                WHERE status IN ('queued', 'waiting')
                  AND (effective_config_json='{}' OR compute_policy_resolution_json='{}')
                """,
                (migration_now,),
            )
        if version < 10:
            scenario_columns = {
                str(column["name"])
                for column in connection.execute("PRAGMA table_info(scenarios)").fetchall()
            }
            if "control_overrides_json" not in scenario_columns:
                connection.execute(
                    "ALTER TABLE scenarios ADD COLUMN control_overrides_json TEXT NOT NULL DEFAULT '{}'"
                )
        from api.services.parameter_templates import builtin_parameter_templates

        for template in builtin_parameter_templates():
            connection.execute(
                """
                INSERT OR IGNORE INTO parameter_templates(
                    template_id, version, name, description, source_kind, source_hash,
                    values_json, field_provenance_json, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    template["template_id"],
                    template["version"],
                    template["name"],
                    template["description"],
                    template["source_kind"],
                    template["source_hash"],
                    json.dumps(template["values"], ensure_ascii=False),
                    json.dumps(template["field_provenance"], ensure_ascii=False),
                    utc_now(),
                ),
            )
            # Upgrade older bundled templates in place with explicit
            # failure-source provenance.  User-created/imported templates are
            # intentionally left untouched.
            existing_template = connection.execute(
                "SELECT source_kind, field_provenance_json FROM parameter_templates WHERE template_id=?",
                (template["template_id"],),
            ).fetchone()
            if existing_template and str(existing_template["source_kind"] or "") == "bundled_case":
                existing_provenance = json_loads(existing_template["field_provenance_json"], {})
                builtin_policy = (template.get("field_provenance") or {}).get("_compute_policy")
                if isinstance(builtin_policy, dict) and "_compute_policy" not in existing_provenance:
                    upgraded_provenance = dict(existing_provenance)
                    upgraded_provenance["_compute_policy"] = builtin_policy
                    connection.execute(
                        "UPDATE parameter_templates SET field_provenance_json=? WHERE template_id=?",
                        (json.dumps(upgraded_provenance, ensure_ascii=False), template["template_id"]),
                    )
        connection.execute(
            "INSERT OR REPLACE INTO schema_metadata(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
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

    def get_compute_gate_defaults(self) -> Dict[str, Any]:
        from api.services.compute_gate_defaults import (
            COMPUTE_GATE_SETTINGS_KEY,
            compute_gate_baseline,
            compute_gate_merge_baseline,
            extract_gate_parameters,
            merge_compute_gate_defaults,
        )
        from api.services.parameter_catalog import build_static_parameter_catalog

        with self.catalog() as connection:
            row = connection.execute(
                "SELECT value_json FROM settings WHERE key=?",
                (COMPUTE_GATE_SETTINGS_KEY,),
            ).fetchone()
        stored = json_loads(row["value_json"], {}) if row else {}
        values = extract_gate_parameters(stored.get("values") if isinstance(stored, dict) else {})
        baseline = compute_gate_baseline()
        catalog = build_static_parameter_catalog()
        return {
            "catalog_version": catalog["catalog_version"],
            "values": values,
            "baseline": baseline,
            "effective": merge_compute_gate_defaults(compute_gate_merge_baseline(), {}, values),
            "updated_at": stored.get("updated_at") if isinstance(stored, dict) else None,
        }

    def get_compute_gate_values(self) -> Dict[str, Any]:
        return dict(self.get_compute_gate_defaults()["values"])

    def put_compute_gate_defaults(self, values: Dict[str, Any]) -> Dict[str, Any]:
        from api.services.compute_gate_defaults import (
            COMPUTE_GATE_SETTINGS_KEY,
            ComputeGateValidationError,
            EXPERIMENTAL_LIVE_KEY,
            POLICY_KEY,
            extract_gate_parameters,
            validate_compute_gate_values,
        )

        # PUT carries a sparse override map.  Validate the submitted map and
        # the resulting effective sparse state together so a caller cannot
        # bypass the live-experiment lock by sending only the unlock field.
        with self.catalog() as connection:
            current_row = connection.execute(
                "SELECT value_json FROM settings WHERE key=?",
                (COMPUTE_GATE_SETTINGS_KEY,),
            ).fetchone()
        current_payload = json_loads(current_row["value_json"], {}) if current_row else {}
        current_values = extract_gate_parameters(
            current_payload.get("values") if isinstance(current_payload, dict) else {}
        )
        try:
            cleaned = validate_compute_gate_values(values)
            effective_sparse = dict(current_values)
            if POLICY_KEY in values and str(values[POLICY_KEY]).strip().lower() == "auto":
                effective_sparse.pop(POLICY_KEY, None)
            elif POLICY_KEY in cleaned:
                effective_sparse[POLICY_KEY] = cleaned[POLICY_KEY]
            if EXPERIMENTAL_LIVE_KEY in cleaned:
                effective_sparse[EXPERIMENTAL_LIVE_KEY] = cleaned[EXPERIMENTAL_LIVE_KEY]
            if (
                effective_sparse.get(POLICY_KEY) == "live"
                and effective_sparse.get(EXPERIMENTAL_LIVE_KEY) is not True
            ):
                raise ComputeGateValidationError(
                    "live_unlock_required",
                    "当前策略为实时双层时不能关闭实验解锁，请先切换失稳源策略。",
                    {"key": EXPERIMENTAL_LIVE_KEY},
                )
        except ComputeGateValidationError as exc:
            raise WorkbenchError(exc.code, exc.message, status_code=422, details=exc.details) from exc
        payload = {
            "values": cleaned,
            "updated_at": utc_now(),
        }
        with self.catalog() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO settings(key, value_json) VALUES(?, ?)",
                (COMPUTE_GATE_SETTINGS_KEY, json.dumps(payload, ensure_ascii=False)),
            )
        return self.get_compute_gate_defaults()

    def _merged_effective_parameters(
        self,
        baseline: Dict[str, Any],
        patch: Dict[str, Any],
        *,
        gates: Optional[Dict[str, Any]] = None,
        template_id: Optional[str] = None,
        template_metadata: Optional[Mapping[str, Any]] = None,
        control_overrides: Optional[Mapping[str, Any]] = None,
        reference_owned: bool = False,
    ) -> Dict[str, Any]:
        from api.services.compute_gate_defaults import resolve_scenario_compute_snapshot, strip_gate_parameters

        metadata = dict(template_metadata or {})
        policy = metadata.get("_compute_policy")
        owned = bool(reference_owned or (isinstance(policy, Mapping) and policy.get("ownership") == "reference_case"))
        snapshot = resolve_scenario_compute_snapshot(
            baseline,
            strip_gate_parameters(patch),
            global_gates=gates if gates is not None else self.get_compute_gate_values(),
            scenario_controls=control_overrides,
            reference_owned=owned,
            template_id=template_id,
            template_metadata=metadata,
            source_mode="workbench",
            strict_reference=bool(template_id),
        )
        return dict(snapshot.effective_parameters)

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
        database = ProjectDatabase(Path(project["root_path"]))
        database.ensure_schema()
        return database

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

    @staticmethod
    def _case_config_path(source_root: Path) -> Path:
        for candidate in (source_root / "edda_in.txt", source_root / "EDDA_in.txt"):
            if candidate.is_file():
                return candidate
        raise WorkbenchError(
            "case_config_not_found",
            "指定目录中未找到 edda_in.txt。",
            status_code=422,
            details={"source_root": str(source_root)},
        )

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        try:
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as exc:
            raise WorkbenchError(
                "case_file_unreadable",
                f"无法读取兼容算例文件：{path.name}",
                status_code=422,
                details={"path": str(path), "error": str(exc)},
            ) from exc
        return digest.hexdigest()

    @classmethod
    def _case_fingerprint(cls, config_path: Path, plan: Mapping[str, Any]) -> str:
        """Hash config plus active existing inputs without hashing source paths."""
        digest = hashlib.sha256()
        digest.update(b"taichi-flow-reference-case-v1\0")
        digest.update(b"edda_in\0")
        try:
            with config_path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as exc:
            raise WorkbenchError(
                "case_file_unreadable",
                f"无法读取 edda_in.txt：{exc}",
                status_code=422,
            ) from exc
        references = sorted(
            (
                item
                for item in plan.get("file_references", [])
                if item.get("exists") and item.get("active") and Path(str(item.get("path") or "")).is_file()
            ),
            key=lambda item: (str(item.get("native_family")), int(item.get("ordinal") or 0)),
        )
        for item in references:
            label = f"{item.get('native_family')}:{int(item.get('ordinal') or 0)}\0".encode("utf-8")
            digest.update(label)
            path = Path(str(item["path"]))
            try:
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
            except OSError as exc:
                raise WorkbenchError(
                    "case_file_unreadable",
                    f"无法读取活动输入：{path.name}",
                    status_code=422,
                    details={"path": str(path), "error": str(exc)},
                ) from exc
        return digest.hexdigest()

    @staticmethod
    def _case_dimensions(config_path: Path) -> Dict[str, Any]:
        pattern = re.compile(r"^\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,")
        try:
            for line in config_path.read_text(encoding="utf-8", errors="replace").splitlines():
                match = pattern.match(line)
                if match:
                    return {
                        "imax": int(match.group(1)),
                        "rows": int(match.group(2)),
                        "cols": int(match.group(3)),
                    }
        except OSError:
            pass
        return {}

    @staticmethod
    def _case_sidecar_summary(path: Optional[Path], family: str) -> Dict[str, Any]:
        if not path or not path.is_file():
            return {"family": family, "exists": False, "line_count": 0, "preview": []}
        try:
            lines = [line.strip() for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
        except OSError:
            lines = []
        return {
            "family": family,
            "exists": True,
            "line_count": len(lines),
            "preview": lines[:4],
            "path_name": path.name,
        }

    def preview_case_import(self, source_root: str) -> Dict[str, Any]:
        """Parse a legacy case and expose a commit-safe, path-aware preview."""
        from api.services.edda_switch_registry import EDDA_SWITCH_REGISTRY
        from api.services.legacy_migration import build_legacy_migration_plan
        from api.services.parameter_templates import normalized_parameter_values
        from api.services.reference_config_parser import parse_reference_config_file

        source = Path(source_root).expanduser().resolve()
        if not source.is_dir():
            raise WorkbenchError("case_source_not_found", "兼容算例目录不存在或不可访问。", status_code=422, details={"source_root": str(source)})
        config_path = self._case_config_path(source)
        try:
            parsed = parse_reference_config_file(str(config_path), str(source))
        except Exception as exc:
            raise WorkbenchError("case_config_parse_failed", f"解析参考案例 edda_in 失败：{exc}", status_code=422) from exc
        config_hash = self._sha256_file(config_path)
        plan = build_legacy_migration_plan(parsed, source_hash=config_hash)
        fingerprint = self._case_fingerprint(config_path, plan)
        values = normalized_parameter_values(parsed)
        snapshot_values = dict(parsed.switch_snapshot.values)
        run_controls = {
            spec.key: snapshot_values.get(spec.key)
            for spec in EDDA_SWITCH_REGISTRY
            if spec.group == "run_control"
        }
        output_controls = {
            spec.key: snapshot_values.get(spec.key)
            for spec in EDDA_SWITCH_REGISTRY
            if spec.group in {"legacy_output", "process_output"}
        }
        unresolved = list(plan.get("unresolved_active_bindings") or [])
        issues: list[Dict[str, Any]] = [
            {
                "severity": "error",
                "code": "active_input_missing",
                "message": f"活动输入缺失：{item.get('native_family')} ({item.get('path')})",
                "binding_key": item.get("binding_key"),
            }
            for item in unresolved
        ]
        issues.extend(
            {
                "severity": "warning",
                "code": "unsupported_control",
                "message": f"原 EDDA 控制保持只读：{item.get('flag') or item.get('parameter')}",
            }
            for item in (parsed.unsupported_flags or [])
        )
        references_by_family = {
            family: [item for item in plan.get("file_references", []) if item.get("native_family") == family]
            for family in parsed.file_inputs
        }
        sidecar_paths = {
            family: next((Path(str(item["path"])) for item in plan.get("file_references", []) if item.get("native_family") == family and item.get("exists")), None)
            for family in ("inflow.txt", "outflow.txt")
        }
        active_bindings = [dict(item) for item in plan.get("proposed_bindings", [])]
        return {
            "source_root": str(source),
            "case_config_file": str(config_path),
            "case_name": source.name,
            "config_sha256": config_hash,
            "case_fingerprint": fingerprint,
            "case_summary": {
                "dimensions": self._case_dimensions(config_path),
                "nzon": int(parsed.nzon),
                "simul_s": float(parsed.simul),
                "tout_s": float(parsed.tout),
                "rainfall_period_count": int(parsed.nper),
                "rainfall_mode": parsed.rainfall_mode,
                "zmax": float(parsed.zmax),
                "ltstar_raw": float(parsed.ltstar_raw),
                "lbstar": float(parsed.lbstar),
                "active_binding_count": len(active_bindings),
                "missing_reference_count": int(plan.get("missing_file_count") or 0),
            },
            "controls": {
                "run": run_controls,
                "output": output_controls,
                "extension": dict(parsed.extension_flags or {}),
                "raw_flags": dict(parsed.flags or {}),
                "normalized_values": values,
            },
            "variants": {
                "face_flux": parsed.dfs_face_flux_variant,
                "manningbar": parsed.dfs_manningbar_variant,
                "dry_face_velocity": parsed.dfs_dry_face_velocity_variant,
                "artivis": parsed.dfs_artivis_variant,
                "absubar": parsed.dfs_absubar_variant,
                "failure_source": parsed.dfs_failure_source_variant,
                "failure_source_topology_status": parsed.dfs_failure_source_topology_status,
            },
            "capabilities": {
                "reference_output_expectations": parsed.reference_output_expectations,
                "unsupported_flags": list(parsed.unsupported_flags or []),
                "file_inputs": {
                    family: {
                        "active": any(bool(item.get("active")) for item in items),
                        "existing": sum(bool(item.get("exists")) for item in items),
                        "declared": len(items),
                        "runtime_status": getattr(parsed.file_inputs.get(family), "production_status", None),
                    }
                    for family, items in references_by_family.items()
                },
            },
            "bindings": active_bindings,
            "sidecars": {
                "inflow": self._case_sidecar_summary(sidecar_paths.get("inflow.txt"), "inflow"),
                "outflow": self._case_sidecar_summary(sidecar_paths.get("outflow.txt"), "outflow"),
            },
            "issues": issues,
            "commit_allowed": not unresolved and any(item.get("family") == "dem" for item in active_bindings),
            "plan": plan,
        }

    def _existing_reference_import(self, destination: Path, fingerprint: str) -> Optional[Dict[str, Any]]:
        database = ProjectDatabase(destination)
        if not database.database_path.is_file():
            return None
        database.ensure_schema()
        with database.connect() as connection:
            rows = connection.execute(
                "SELECT scenario_id, parameter_template_id FROM scenarios ORDER BY created_at"
            ).fetchall()
            match = None
            for row in rows:
                metadata = self._parameter_template_metadata(connection, row["parameter_template_id"])
                policy = metadata.get("_compute_policy") if isinstance(metadata, Mapping) else None
                if isinstance(policy, Mapping) and str(policy.get("case_fingerprint") or "") == fingerprint:
                    match = str(row["scenario_id"])
                    break
        if not match:
            return None
        metadata = database.metadata()
        if not metadata:
            return None
        project = self.create_or_open_project(
            name=str(metadata.get("name") or destination.name),
            root_path=str(destination),
            description=str(metadata.get("description") or ""),
        )
        return {
            "project": project,
            "scenario": self._public_scenario(project["project_id"], self._scenario_row(project["project_id"], match)),
            "case_fingerprint": fingerprint,
            "idempotent": True,
        }

    def commit_case_import(
        self,
        source_root: str,
        destination_root: str,
        *,
        expected_fingerprint: str,
        name: Optional[str] = None,
        description: str = "",
    ) -> Dict[str, Any]:
        """Atomically stage a path-free reference-case project and register it."""
        from api.services.legacy_migration import build_legacy_migration_plan
        from api.services.parameter_templates import normalized_parameter_values
        from api.services.reference_config_parser import parse_reference_config_file

        preview = self.preview_case_import(source_root)
        fingerprint = str(preview["case_fingerprint"])
        if fingerprint != str(expected_fingerprint):
            raise WorkbenchError(
                "case_fingerprint_mismatch",
                "源算例在预览后发生变化，请重新预览。",
                status_code=409,
                details={"expected_fingerprint": expected_fingerprint, "actual_fingerprint": fingerprint},
            )
        if not bool(preview.get("commit_allowed")):
            raise WorkbenchError(
                "case_import_not_ready",
                "活动输入或 DEM 绑定未通过校验，不能提交参考案例兼容项目。",
                status_code=422,
                details={
                    "issues": list(preview.get("issues") or []),
                    "bindings": list(preview.get("bindings") or []),
                },
            )
        source = Path(str(preview["source_root"])).resolve()
        destination = Path(destination_root).expanduser().resolve()
        if destination == source or source in destination.parents:
            raise WorkbenchError("case_destination_invalid", "目标目录必须独立于原始算例目录。", status_code=422)
        existing = self._existing_reference_import(destination, fingerprint) if destination.exists() else None
        if existing:
            return existing
        if destination.exists():
            try:
                next(destination.iterdir())
            except StopIteration:
                pass
            else:
                raise WorkbenchError("case_destination_not_empty", "目标目录必须为空，避免覆盖现有项目。", status_code=409)
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = destination.parent / f".{destination.name}.import-{uuid4().hex}"
        project_id: Optional[str] = None
        moved = False
        try:
            staged_project = self.create_or_open_project(
                name=(name or "").strip() or str(preview["case_name"]),
                root_path=str(staging),
                description=description,
            )
            project_id = str(staged_project["project_id"])
            parsed = parse_reference_config_file(str(preview["case_config_file"]), str(source))
            plan = build_legacy_migration_plan(parsed, source_hash=str(preview["config_sha256"]))
            assets: list[Dict[str, Any]] = []
            bindings: list[Dict[str, Any]] = []

            config_asset = self.ingest_upload_from_path(project_id, family="config", path=str(preview["case_config_file"]))
            assets.append(config_asset)
            bindings.append({
                "binding_key": "legacy.config",
                "asset_id": config_asset["asset_id"],
                "family": "config",
                "role": "legacy-config",
                "ordinal": 1,
                "active": True,
                "metadata": {"case_fingerprint": fingerprint, "source_kind": "reference_case"},
            })
            for item in plan["proposed_bindings"]:
                asset = self.ingest_upload_from_path(project_id, family=str(item["family"]), path=str(item["path"]))
                assets.append(asset)
                bindings.append({
                    "binding_key": item["binding_key"],
                    "asset_id": asset["asset_id"],
                    "family": item["family"],
                    "role": item["role"],
                    "period_id": item.get("period_id"),
                    "ordinal": item.get("ordinal"),
                    "active": bool(item.get("active", True)),
                    "metadata": {
                        "native_family": item.get("native_family"),
                        "source_hash": asset["sha256"],
                        "case_fingerprint": fingerprint,
                    },
                })
            database = self.project_database(project_id)
            with database.connect() as connection:
                resolved_bindings, manifest = self._resolve_binding_assets(connection, bindings)
                revision_id, revision_status, _, _ = self._insert_input_revision(
                    connection,
                    bindings=resolved_bindings,
                    manifest=manifest,
                    parent_revision_id=None,
                    version_tag="Chamoli reference v1",
                )
                if revision_status != "ready":
                    raise WorkbenchError("case_input_invalid", "导入的活动输入未通过内容校验。", status_code=422)
                values = normalized_parameter_values(parsed)
                template_id = f"pt-reference-{fingerprint[:24]}"
                provenance = {
                    key: {"source": "Chamoli/edda_in.txt", "source_hash": str(preview["config_sha256"])}
                    for key in values
                }
                provenance["_compute_policy"] = {
                    "ownership": "reference_case",
                    "source_mode": "reference_case_import",
                    "source_files": ["edda_in.txt"],
                    "case_fingerprint": fingerprint,
                    "original_fssimul": parsed.flags.get("simulate_shallow_landslide"),
                    "topology": parsed.dfs_failure_source_variant or None,
                    "topology_status": parsed.dfs_failure_source_topology_status,
                    "evidence": list(parsed.dfs_failure_source_evidence or []),
                    "detector_version": "reference-config-parser-v1",
                }
                now = utc_now()
                connection.execute(
                    """
                    INSERT OR IGNORE INTO parameter_templates(
                        template_id, version, name, description, source_kind,
                        source_hash, values_json, field_provenance_json, created_at
                    ) VALUES(?, 1, ?, ?, 'reference_case', ?, ?, ?, ?)
                    """,
                    (
                        template_id,
                        f"Chamoli reference {fingerprint[:8]}",
                        "由原始 Chamoli edda_in 导入；控制快照归方案所有，未注入 BJ 全局默认。",
                        str(preview["config_sha256"]),
                        json.dumps(values, ensure_ascii=False),
                        json.dumps(provenance, ensure_ascii=False),
                        now,
                    ),
                )
            scenario = self.create_scenario(
                project_id,
                name=(name or "").strip() or "Chamoli reference",
                input_revision_id=revision_id,
                base_scenario_id=None,
                parameter_patch={},
                parameter_template_id=template_id,
                control_overrides={},
            )
            old_root = str(staging)
            staging.replace(destination)
            moved = True
            new_database = ProjectDatabase(destination)

            # Uploaded blobs move with the staging directory.  The uploads
            # table stores plain paths, but input revision manifests store JSON
            # strings where Windows separators are escaped; SQL replace() on
            # the raw prefix therefore leaves stale staging paths behind.
            # Rebase parsed values instead, preserving reference files outside
            # the staging root and every non-path manifest field verbatim.
            old_normalized = os.path.normcase(os.path.normpath(old_root))
            destination_root = str(destination)

            def rebase_staging_path(value: Any) -> Any:
                if isinstance(value, str):
                    normalized = os.path.normcase(os.path.normpath(value))
                    if normalized == old_normalized:
                        return destination_root
                    prefix = old_normalized + os.sep
                    if normalized.startswith(prefix):
                        return destination_root + value[len(old_root):]
                    return value
                if isinstance(value, list):
                    return [rebase_staging_path(item) for item in value]
                if isinstance(value, dict):
                    return {key: rebase_staging_path(item) for key, item in value.items()}
                return value

            with new_database.connect() as connection:
                upload_rows = connection.execute("SELECT upload_id, blob_path FROM uploads").fetchall()
                for row in upload_rows:
                    rebased_path = rebase_staging_path(str(row["blob_path"]))
                    if rebased_path != row["blob_path"]:
                        connection.execute(
                            "UPDATE uploads SET blob_path=? WHERE upload_id=?",
                            (rebased_path, row["upload_id"]),
                        )
                revision_rows = connection.execute(
                    "SELECT revision_id, manifest_json FROM input_revisions"
                ).fetchall()
                for row in revision_rows:
                    manifest = json_loads(row["manifest_json"], [])
                    rebased_manifest = rebase_staging_path(manifest)
                    if rebased_manifest != manifest:
                        connection.execute(
                            "UPDATE input_revisions SET manifest_json=? WHERE revision_id=?",
                            (json.dumps(rebased_manifest, ensure_ascii=False), row["revision_id"]),
                        )
            with self.catalog() as connection:
                connection.execute(
                    "UPDATE projects SET root_path=?, state_path=?, updated_at=? WHERE project_id=?",
                    (str(destination), str(new_database.database_path), utc_now(), project_id),
                )
            project = self.get_project(project_id)
            final_scenario = self._public_scenario(project_id, self._scenario_row(project_id, scenario["scenario_id"]))
            return {
                "project": project,
                "scenario": final_scenario,
                "case_fingerprint": fingerprint,
                "input_revision_id": revision_id,
                "asset_count": len(assets),
                "idempotent": False,
            }
        except Exception:
            if not moved:
                if project_id:
                    with self.catalog() as connection:
                        connection.execute("DELETE FROM projects WHERE project_id=?", (project_id,))
                if staging.exists():
                    shutil.rmtree(staging, ignore_errors=True)
            raise

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

    @staticmethod
    def _public_parameter_template(row: sqlite3.Row | Dict[str, Any]) -> Dict[str, Any]:
        data = dict(row)
        return {
            "template_id": data["template_id"],
            "version": data["version"],
            "name": data["name"],
            "description": data["description"],
            "source_kind": data["source_kind"],
            "source_hash": data.get("source_hash"),
            "values": json_loads(data["values_json"], {}),
            "field_provenance": json_loads(data["field_provenance_json"], {}),
            "created_at": data["created_at"],
        }

    def list_parameter_templates(self, project_id: str) -> list[Dict[str, Any]]:
        database = self.project_database(project_id)
        with database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM parameter_templates ORDER BY created_at, template_id"
            ).fetchall()
        return [self._public_parameter_template(row) for row in rows]

    def preview_parameter_import(
        self,
        project_id: str,
        scenario_id: str,
        *,
        filename: str,
        stream: BinaryIO,
    ) -> Dict[str, Any]:
        """Parse an edda_in upload into parameters while intentionally dropping paths."""
        from api.services.parameter_templates import normalized_parameter_values
        from api.services.reference_config_parser import parse_reference_config_file

        project = self.get_project(project_id)
        scenario = self._scenario_row(project_id, scenario_id)
        database = self.project_database(project_id)
        preview_path = database.staging_dir / f"parameter-import-{uuid4().hex}.txt"
        digest = hashlib.sha256()
        try:
            with preview_path.open("wb") as target:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    target.write(chunk)
                    digest.update(chunk)
            if preview_path.stat().st_size == 0:
                raise WorkbenchError("empty_upload", "参数配置文件不能为空。", status_code=422)
            parsed = parse_reference_config_file(str(preview_path), str(project["root_path"]))
            values = normalized_parameter_values(parsed)
            compute_policy = {
                "source_mode": "edda_in_parameter_import",
                "source_files": [str(parsed.reference_config_file)] if getattr(parsed, "reference_config_file", None) else [],
                "original_fssimul": parsed.flags.get("simulate_shallow_landslide"),
                "topology": parsed.dfs_failure_source_variant or None,
                "topology_status": parsed.dfs_failure_source_topology_status,
                "evidence": list(parsed.dfs_failure_source_evidence or []),
                "detector_version": "reference-config-parser-v1",
            }
            current = json_loads(scenario["effective_parameters_json"], {})
            diff = [
                {"key": key, "before": current.get(key), "after": values.get(key)}
                for key in sorted(set(current) | set(values))
                if current.get(key) != values.get(key)
            ]
            ignored_families = sorted(
                family
                for family, ref in parsed.file_inputs.items()
                if list(ref.raw_paths or [])
            )
            ignored_count = sum(
                len(list(ref.raw_paths or []))
                for ref in parsed.file_inputs.values()
            )
            return {
                "source_kind": "edda_in_parameter_import",
                "source_name": Path(filename or "edda_in.txt").name,
                "source_hash": digest.hexdigest(),
                "values": values,
                "compute_policy": compute_policy,
                "diff": diff,
                "ignored_file_references": {
                    "count": ignored_count,
                    "families": ignored_families,
                },
            }
        except WorkbenchError:
            raise
        except Exception as exc:
            raise WorkbenchError(
                "config_parse_failed",
                f"解析 edda_in 参数失败：{exc}",
                status_code=422,
            ) from exc
        finally:
            preview_path.unlink(missing_ok=True)

    def apply_parameter_import(
        self,
        project_id: str,
        scenario_id: str,
        *,
        expected_version: int,
        filename: str,
        stream: BinaryIO,
    ) -> Dict[str, Any]:
        """Confirm a path-free parameter import without touching input bindings."""
        preview = self.preview_parameter_import(
            project_id,
            scenario_id,
            filename=filename,
            stream=stream,
        )
        source_hash = str(preview["source_hash"])
        template_id = f"pt-import-{source_hash[:16]}-params"
        values = dict(preview["values"])
        now = utc_now()
        database = self.project_database(project_id)
        provenance = {
            key: {"source": "edda_in_parameter_import", "source_hash": source_hash}
            for key in values
        }
        provenance["_compute_policy"] = dict(preview.get("compute_policy") or {})
        with database.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO parameter_templates(
                    template_id, version, name, description, source_kind,
                    source_hash, values_json, field_provenance_json, created_at
                ) VALUES(?, 1, ?, ?, 'edda_in_parameter_import', ?, ?, ?, ?)
                """,
                (
                    template_id,
                    f"Imported parameters {source_hash[:8]}",
                    "Path-free parameter import; all legacy file references were intentionally ignored.",
                    source_hash,
                    json.dumps(values, ensure_ascii=False),
                    json.dumps(provenance, ensure_ascii=False),
                    now,
                ),
            )
            template_row = connection.execute(
                "SELECT * FROM parameter_templates WHERE template_id=?",
                (template_id,),
            ).fetchone()
        updated = self.update_scenario(
            project_id,
            scenario_id,
            name=None,
            parameter_patch={},
            parameter_template_id=template_id,
            expected_version=expected_version,
        )
        assert template_row is not None
        return {
            "scenario": updated,
            "template": self._public_parameter_template(template_row),
            "diff": preview["diff"],
            "ignored_file_references": preview["ignored_file_references"],
        }

    def _legacy_scenario_config(
        self,
        project_id: str,
        scenario_id: str,
    ) -> tuple[sqlite3.Row, Dict[str, Any], Any]:
        """Return the legacy config manifest entry and parsed, path-aware model."""
        from api.services.reference_config_parser import parse_reference_config_file

        scenario = self._scenario_row(project_id, scenario_id)
        if not scenario["input_revision_id"]:
            raise WorkbenchError(
                "legacy_config_not_found",
                "The scenario has no legacy input revision to migrate.",
                status_code=409,
            )
        database = self.project_database(project_id)
        with database.connect() as connection:
            revision = connection.execute(
                "SELECT manifest_json FROM input_revisions WHERE revision_id=?",
                (scenario["input_revision_id"],),
            ).fetchone()
        manifest = json_loads(revision["manifest_json"], []) if revision else []
        config_item = next(
            (item for item in manifest if str(item.get("family") or "").lower() == "config"),
            None,
        )
        if not config_item:
            raise WorkbenchError(
                "legacy_config_not_found",
                "The scenario input revision does not contain an edda_in config asset.",
                status_code=409,
            )
        config_path = Path(str(config_item.get("blob_path") or ""))
        if not config_path.is_file():
            raise WorkbenchError(
                "legacy_config_unavailable",
                "The legacy edda_in config asset is unavailable.",
                status_code=409,
            )
        project = self.get_project(project_id)
        parsed = parse_reference_config_file(str(config_path), str(project["root_path"]))
        return scenario, dict(config_item), parsed

    def preview_legacy_migration(self, project_id: str, scenario_id: str) -> Dict[str, Any]:
        """Inspect legacy path references without collecting or binding any file."""
        from api.services.legacy_migration import build_legacy_migration_plan

        scenario, config_item, parsed = self._legacy_scenario_config(project_id, scenario_id)
        source_hash = str(config_item.get("sha256") or "")
        plan = build_legacy_migration_plan(parsed, source_hash=source_hash)
        plan.update(
            {
                "scenario_id": scenario_id,
                "scenario_version": int(scenario["version"] or 1),
                "input_revision_id": scenario["input_revision_id"],
                "requires_confirmation": True,
            }
        )
        return plan

    def commit_legacy_migration(
        self,
        project_id: str,
        scenario_id: str,
        *,
        expected_version: int,
    ) -> Dict[str, Any]:
        """Collect confirmed legacy files and replace path coupling with semantic bindings."""
        from api.services.legacy_migration import build_legacy_migration_plan
        from api.services.parameter_templates import normalized_parameter_values

        scenario, config_item, parsed = self._legacy_scenario_config(project_id, scenario_id)
        current_version = int(scenario["version"] or 1)
        if int(expected_version) != current_version:
            raise WorkbenchError(
                "scenario_version_conflict",
                "The scenario changed after migration preview; refresh and preview again.",
                status_code=409,
                details={"expected_version": expected_version, "current_version": current_version},
            )

        source_hash = str(config_item.get("sha256") or "")
        plan = build_legacy_migration_plan(parsed, source_hash=source_hash)
        assets: list[Dict[str, Any]] = []
        bindings: list[Dict[str, Any]] = []
        for item in plan["proposed_bindings"]:
            asset = self.ingest_upload_from_path(
                project_id,
                family=str(item["family"]),
                path=str(item["path"]),
            )
            assets.append(asset)
            bindings.append(
                {
                    "binding_key": item["binding_key"],
                    "asset_id": asset["asset_id"],
                    "family": item["family"],
                    "role": item["role"],
                    "period_id": item.get("period_id"),
                    "ordinal": item.get("ordinal"),
                    "active": bool(item.get("active", True)),
                    "metadata": {
                        "migrated_from": item["native_family"],
                        "source_hash": asset["sha256"],
                    },
                }
            )

        values = normalized_parameter_values(parsed)
        template_id = f"pt-import-{source_hash[:16]}"
        database = self.project_database(project_id)
        now = utc_now()
        provenance = {
            key: {"source": "legacy_edda_in", "source_hash": source_hash}
            for key in values
        }
        provenance["_compute_policy"] = {
            "source_mode": "legacy_migration",
            "source_files": [str(parsed.reference_config_file)] if getattr(parsed, "reference_config_file", None) else [],
            "original_fssimul": parsed.flags.get("simulate_shallow_landslide"),
            "topology": parsed.dfs_failure_source_variant or None,
            "topology_status": parsed.dfs_failure_source_topology_status,
            "evidence": list(parsed.dfs_failure_source_evidence or []),
            "detector_version": "reference-config-parser-v1",
        }
        with database.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO parameter_templates(
                    template_id, version, name, description, source_kind,
                    source_hash, values_json, field_provenance_json, created_at
                ) VALUES(?, 1, ?, ?, 'legacy_migration', ?, ?, ?, ?)
                """,
                (
                    template_id,
                    f"Imported edda_in {source_hash[:8]}",
                    "Path-free parameter template produced by the explicit legacy migration wizard.",
                    source_hash,
                    json.dumps(values, ensure_ascii=False),
                    json.dumps(provenance, ensure_ascii=False),
                    now,
                ),
            )

        migrated = self.update_scenario(
            project_id,
            scenario_id,
            name=None,
            parameter_patch={},
            input_bindings=bindings,
            parameter_template_id=template_id,
            expected_version=expected_version,
        )
        unresolved_active = list(plan.get("unresolved_active_bindings") or [])
        if unresolved_active:
            with database.connect() as connection:
                validation = {}
                validation.setdefault("warnings", [])
                validation.setdefault("errors", [])
                validation["valid"] = False
                validation["unresolved_bindings"] = unresolved_active
                validation["errors"].append(
                    f"Legacy migration has {len(unresolved_active)} unresolved active input binding(s)."
                )
                connection.execute(
                    "UPDATE scenarios SET draft_validation_json=? WHERE scenario_id=?",
                    (json.dumps(validation, ensure_ascii=False), scenario_id),
                )
        migration_id = f"mig-{uuid4().hex}"
        report = {
            "migration_id": migration_id,
            "created_at": now,
            "scenario_id": scenario_id,
            "source_hash": source_hash,
            "parameter_template_id": template_id,
            "input_revision_id": migrated["input_revision_id"],
            "asset_count": len(assets),
            "assets": [
                {
                    "asset_id": asset["asset_id"],
                    "family": asset["family"],
                    "name": asset["name"],
                    "sha256": asset["sha256"],
                }
                for asset in assets
            ],
            "warnings": plan["warnings"],
            "unresolved_active_bindings": unresolved_active,
            "production_blocked": bool(unresolved_active),
            "rollback": {
                "input_revision_id": scenario["input_revision_id"],
                "parameter_template_id": scenario["parameter_template_id"],
                "parameter_patch": json_loads(scenario["parameter_patch_json"], {}),
                "scenario_version": current_version,
            },
        }
        report_dir = database.state_dir / "migrations"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"{migration_id}.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "scenario": migrated,
            "report": report,
            "report_path": str(report_path),
        }

    @staticmethod
    def _parameter_template_values(
        connection: sqlite3.Connection,
        template_id: Optional[str],
    ) -> Dict[str, Any]:
        if not template_id:
            return {}
        row = connection.execute(
            "SELECT values_json FROM parameter_templates WHERE template_id=?",
            (template_id,),
        ).fetchone()
        if not row:
            raise WorkbenchError("parameter_template_not_found", "参数模板不存在。", status_code=404)
        return json_loads(row["values_json"], {})

    @staticmethod
    def _parameter_template_metadata(
        connection: sqlite3.Connection,
        template_id: Optional[str],
    ) -> Dict[str, Any]:
        if not template_id:
            return {}
        row = connection.execute(
            "SELECT template_id, source_kind, source_hash, field_provenance_json FROM parameter_templates WHERE template_id=?",
            (template_id,),
        ).fetchone()
        if not row:
            raise WorkbenchError("parameter_template_not_found", "参数模板不存在。", status_code=404)
        return {
            "template_id": row["template_id"],
            "source_kind": row["source_kind"],
            "source_hash": row["source_hash"],
            "field_provenance": json_loads(row["field_provenance_json"], {}),
            "_compute_policy": json_loads(row["field_provenance_json"], {}).get("_compute_policy", {}),
        }

    @staticmethod
    def _reference_case_owned(metadata: Optional[Mapping[str, Any]]) -> bool:
        policy = (metadata or {}).get("_compute_policy") if isinstance(metadata, Mapping) else None
        return bool(isinstance(policy, Mapping) and policy.get("ownership") == "reference_case")

    @staticmethod
    def _validate_control_overrides(values: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
        from api.services.compute_gate_defaults import ComputeGateValidationError, validate_compute_gate_values

        payload = dict(values or {})
        if not payload:
            return {}
        try:
            return validate_compute_gate_values(payload)
        except ComputeGateValidationError as exc:
            raise WorkbenchError(exc.code, exc.message, status_code=422, details=exc.details) from exc

    def _scenario_compute_snapshot(
        self,
        connection: sqlite3.Connection,
        scenario: sqlite3.Row | Dict[str, Any],
        *,
        global_gates: Optional[Mapping[str, Any]] = None,
    ):
        from api.services.compute_gate_defaults import (
            ScenarioComputeSnapshot,
            resolve_scenario_compute_snapshot,
            strip_gate_parameters,
        )
        from api.services.parameter_templates import canonicalize_edda_control_parameters
        from api.services.compute_policy_resolver import legacy_unrecorded_compute_policy_resolution

        template_id = scenario.get("parameter_template_id") if isinstance(scenario, dict) else scenario["parameter_template_id"]
        if not template_id:
            effective = json_loads(scenario.get("effective_parameters_json"), {}) if isinstance(scenario, dict) else json_loads(scenario["effective_parameters_json"], {})
            legacy_resolution = legacy_unrecorded_compute_policy_resolution()
            return ScenarioComputeSnapshot(
                effective_parameters=effective,
                resolution=legacy_resolution,
                validation_issues=[],
            )

        baseline = self._parameter_template_values(connection, str(template_id))
        metadata = self._parameter_template_metadata(connection, str(template_id))
        patch_json = scenario.get("parameter_patch_json") if isinstance(scenario, dict) else scenario["parameter_patch_json"]
        patch = strip_gate_parameters(canonicalize_edda_control_parameters(json_loads(patch_json, {})))
        control_json = scenario.get("control_overrides_json", "{}") if isinstance(scenario, dict) else scenario["control_overrides_json"]
        control_overrides = self._validate_control_overrides(json_loads(control_json, {}))
        return resolve_scenario_compute_snapshot(
            baseline,
            patch,
            global_gates=global_gates if global_gates is not None else self.get_compute_gate_values(),
            scenario_controls=control_overrides,
            reference_owned=self._reference_case_owned(metadata),
            template_id=str(template_id),
            template_metadata=metadata,
            source_mode="workbench",
            strict_reference=True,
        )

    def ingest_upload(
        self,
        project_id: str,
        *,
        family: str,
        filename: str,
        stream: BinaryIO,
        media_type: Optional[str] = None,
        roles: Optional[list[str]] = None,
    ) -> Dict[str, Any]:
        allowed_families = {
            "dem",
            "rainfall",
            "soil",
            "boundary",
            "config",
            "slope",
            "zones",
            "thickness",
            "trigger",
            "manning",
            "groundwater",
            "infiltration",
            "outflow",
            "inflow",
            "monitoring",
            "rifil",
            "zonfil",
            "zfil",
            "triggerslide",
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
        # Content addressing deduplicates the underlying blob, not the logical
        # asset.  Repeated rainfall periods may contain identical bytes yet must
        # remain independently bindable and deletable files.
        blob_path = database.blob_dir / sha256[:2] / sha256
        blob_path.parent.mkdir(parents=True, exist_ok=True)
        deduplicated = blob_path.exists()
        if deduplicated:
            staged_path.unlink(missing_ok=True)
        else:
            staged_path.replace(blob_path)

        summary = "内容校验完成"
        warnings: list[str] = []
        asset_roles = list(roles or [ASSET_ROLE_BY_FAMILY.get(normalized_family, normalized_family)])
        raster_metadata: Dict[str, Any] = {}
        if normalized_family in RASTER_ASSET_FAMILIES:
            metadata_path = blob_path
            metadata_probe: Optional[Path] = None
            source_suffix = Path(safe_name).suffix.lower()
            # Content-addressed blobs intentionally have no filename suffix.
            # Preserve the original raster suffix for ASCII grids so GDAL's
            # AAIGrid driver reads xllcorner/yllcorner instead of falling back
            # to an origin of (0, 0). This keeps draft and revision manifests
            # geometrically equivalent after a scenario is duplicated.
            if source_suffix in {".asc", ".tif", ".tiff", ".img", ".dem"} and blob_path.suffix.lower() != source_suffix:
                metadata_probe = database.staging_dir / f"{upload_id}{source_suffix}"
                shutil.copyfile(blob_path, metadata_probe)
                metadata_path = metadata_probe
            try:
                from edda.io.spatial_input_loader import SpatialInputLoader

                data, metadata = SpatialInputLoader(str(metadata_path)).read()
                rows, cols = data.shape[:2]
                bounds = metadata.get("bounds")
                if bounds is not None and hasattr(bounds, "left"):
                    normalized_bounds = [bounds.left, bounds.bottom, bounds.right, bounds.top]
                elif isinstance(bounds, (list, tuple)) and len(bounds) == 4:
                    xmin, xmax, ymin, ymax = bounds
                    normalized_bounds = [xmin, ymin, xmax, ymax]
                else:
                    normalized_bounds = None
                raster_metadata = {
                    "rows": int(rows),
                    "cols": int(cols),
                    "cell_size": float(metadata.get("dx") or metadata.get("cellsize") or 1.0),
                    "origin": {
                        "x": float(metadata.get("xllcorner") or 0.0),
                        "y": float(metadata.get("yllcorner") or 0.0),
                    },
                    "crs": None if metadata.get("crs") in (None, "", "None") else str(metadata.get("crs")),
                    "nodata": metadata.get("nodata", metadata.get("nodata_value")),
                    "extent": normalized_bounds,
                }
            except Exception as exc:
                warnings.append(f"栅格元数据读取失败：{exc}")
            finally:
                if metadata_probe is not None:
                    metadata_probe.unlink(missing_ok=True)
        parse_summary: Optional[Dict[str, Any]] = None
        if normalized_family == "config":
            parse_summary = self._try_parse_config_upload(project_id, blob_path)
            if parse_summary:
                summary = parse_summary.get("summary") or summary
                warnings = list(parse_summary.get("warnings") or [])

        created_at = utc_now()
        with database.connect() as connection:
            connection.execute(
                """
                INSERT INTO uploads(
                    upload_id, family, name, sha256, size, blob_path,
                    roles_json, media_type, metadata_json, archived, status,
                    summary, warnings_json, errors_json, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'ready', ?, ?, '[]', ?)
                """,
                (
                    upload_id,
                    normalized_family,
                    safe_name,
                    sha256,
                    size,
                    str(blob_path),
                    json.dumps(asset_roles, ensure_ascii=False),
                    media_type,
                    json.dumps(raster_metadata, ensure_ascii=False),
                    summary,
                    json.dumps(warnings, ensure_ascii=False),
                    created_at,
                ),
            )
        result = {
            "upload_id": upload_id,
            "project_id": project_id,
            "family": normalized_family,
            "name": safe_name,
            "sha256": sha256,
            "size": size,
            "status": "ready",
            "summary": summary,
            "warnings": warnings,
            "errors": [],
            "created_at": created_at,
            "deduplicated": deduplicated,
            "asset_id": upload_id,
            "roles": asset_roles,
            "media_type": media_type,
            "raster_metadata": raster_metadata,
            "archived": False,
        }
        if parse_summary:
            result["parse_summary"] = parse_summary
        return result

    def _try_parse_config_upload(self, project_id: str, blob_path: Path) -> Optional[Dict[str, Any]]:
        """Best-effort edda_in parse for config uploads; never fails the upload."""
        try:
            from api.services.reference_config_parser import parse_reference_config_file

            project = self.get_project(project_id)
            case_base_dir = str(project["root_path"])
            parsed = parse_reference_config_file(str(blob_path), case_base_dir)
            warnings: list[str] = []
            rifil = parsed.file_inputs.get("rifil")
            if rifil and parsed.rainfall_mode in {"raster_rifil", "mixed"}:
                missing = sum(1 for ok in rifil.exists if not ok)
                if missing:
                    warnings.append(f"降雨栅格缺失 {missing}/{len(rifil.exists)} 个时段文件。")
            manning = parsed.file_inputs.get("manningfil")
            if parsed.manning_source == "global_initiation_manning":
                warnings.append("未找到可用 manningfil，将使用全局曼宁系数。")
            elif manning and not any(manning.exists):
                warnings.append("manningfil 路径已声明但文件不存在。")
            return {
                "summary": f"已解析 edda_in：降雨={parsed.rainfall_mode}，曼宁={parsed.manning_source}",
                "warnings": warnings,
                "rainfall_mode": parsed.rainfall_mode,
                "manning_source": parsed.manning_source,
                "period_count": len(parsed.cri_mps),
                "manning_global": parsed.manning_global,
            }
        except Exception as exc:
            return {
                "summary": "配置已上传，但解析 edda_in 时出现警告",
                "warnings": [f"edda_in 解析警告：{exc}"],
            }

    def ingest_upload_from_path(self, project_id: str, *, family: str, path: str) -> Dict[str, Any]:
        """Ingest a local absolute file path into the shared project upload store."""
        from api.services.directory_picker import DirectoryPickerService

        resolved = DirectoryPickerService().resolve_local_path(path, expect_file=True)
        with resolved.open("rb") as stream:
            result = self.ingest_upload(
                project_id,
                family=family,
                filename=resolved.name,
                stream=stream,
            )
        result["source_path"] = str(resolved)
        return result

    @staticmethod
    def _public_upload(row: sqlite3.Row | Dict[str, Any]) -> Dict[str, Any]:
        data = dict(row)
        return {
            "upload_id": data["upload_id"],
            "asset_id": data["upload_id"],
            "family": data["family"],
            "name": data["name"],
            "sha256": data["sha256"],
            "size": data["size"],
            "status": data["status"],
            "summary": data.get("summary"),
            "warnings": json_loads(data.get("warnings_json"), []),
            "errors": json_loads(data.get("errors_json"), []),
            "roles": json_loads(data.get("roles_json"), [ASSET_ROLE_BY_FAMILY.get(str(data["family"]), str(data["family"]))]),
            "media_type": data.get("media_type"),
            "raster_metadata": json_loads(data.get("metadata_json"), {}),
            "archived": bool(data.get("archived", 0)),
            "created_at": data["created_at"],
        }

    @staticmethod
    def _normalize_asset_ids(asset_ids: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for asset_id in asset_ids:
            value = str(asset_id or "").strip()
            if value and value not in seen:
                normalized.append(value)
                seen.add(value)
        if not normalized:
            raise WorkbenchError("asset_ids_required", "Select at least one asset.", status_code=422)
        return normalized

    @classmethod
    def _asset_lifecycle_for_ids_connection(
        cls,
        connection: sqlite3.Connection,
        asset_ids: list[str],
    ) -> Dict[str, Dict[str, Any]]:
        """Return draft/queue/runtime state without treating terminal snapshots as locks."""
        normalized = cls._normalize_asset_ids(asset_ids)
        placeholders = ",".join("?" for _ in normalized)
        lifecycle = {
            asset_id: {
                "draft_reference_count": 0,
                "queued_reference_count": 0,
                "runtime_lock": {"locked": False, "simulation_ids": [], "statuses": []},
            }
            for asset_id in normalized
        }
        draft_rows = connection.execute(
            f"SELECT asset_id, COUNT(*) AS count FROM scenario_draft_bindings WHERE asset_id IN ({placeholders}) GROUP BY asset_id",
            tuple(normalized),
        ).fetchall()
        for row in draft_rows:
            lifecycle[str(row["asset_id"])]["draft_reference_count"] = int(row["count"])
        queued_rows = connection.execute(
            f"""
            SELECT b.asset_id, COUNT(DISTINCT q.queue_item_id) AS count
            FROM scenario_draft_bindings b
            JOIN queue_items q ON q.scenario_id=b.scenario_id
            WHERE b.asset_id IN ({placeholders}) AND q.status='queued'
            GROUP BY b.asset_id
            """,
            tuple(normalized),
        ).fetchall()
        for row in queued_rows:
            lifecycle[str(row["asset_id"])]["queued_reference_count"] = int(row["count"])
        runtime_rows = connection.execute(
            f"""
            SELECT b.asset_id, r.simulation_id, r.status
            FROM input_revision_bindings b
            JOIN simulation_runs r ON r.input_revision_id=b.revision_id
            WHERE b.asset_id IN ({placeholders})
              AND r.status IN ('starting', 'running', 'stopping')
            ORDER BY r.simulation_id
            """,
            tuple(normalized),
        ).fetchall()
        for row in runtime_rows:
            lock = lifecycle[str(row["asset_id"])]["runtime_lock"]
            lock["locked"] = True
            simulation_id = str(row["simulation_id"])
            status = str(row["status"])
            if simulation_id not in lock["simulation_ids"]:
                lock["simulation_ids"].append(simulation_id)
            if status not in lock["statuses"]:
                lock["statuses"].append(status)
        return lifecycle

    def _asset_delete_impact_connection(
        self,
        connection: sqlite3.Connection,
        asset_ids: list[str],
    ) -> Dict[str, Any]:
        normalized = self._normalize_asset_ids(asset_ids)
        placeholders = ",".join("?" for _ in normalized)
        rows = connection.execute(
            f"SELECT * FROM uploads WHERE upload_id IN ({placeholders}) AND archived=0",
            tuple(normalized),
        ).fetchall()
        by_id = {str(row["upload_id"]): row for row in rows}
        missing = [asset_id for asset_id in normalized if asset_id not in by_id]
        if missing:
            raise WorkbenchError(
                "upload_not_found",
                "One or more input assets do not exist.",
                status_code=404,
                details={"asset_ids": missing},
            )
        lifecycle = self._asset_lifecycle_for_ids_connection(connection, normalized)
        draft_rows = connection.execute(
            f"SELECT scenario_id, binding_key, asset_id FROM scenario_draft_bindings WHERE asset_id IN ({placeholders}) ORDER BY scenario_id, binding_key",
            tuple(normalized),
        ).fetchall()
        queued_rows = connection.execute(
            f"""
            SELECT DISTINCT q.queue_item_id, q.scenario_id
            FROM queue_items q
            JOIN scenario_draft_bindings b ON b.scenario_id=q.scenario_id
            WHERE q.status='queued' AND b.asset_id IN ({placeholders})
            ORDER BY q.queue_item_id
            """,
            tuple(normalized),
        ).fetchall()
        locked = [
            {
                "asset_id": asset_id,
                "name": by_id[asset_id]["name"],
                **lifecycle[asset_id]["runtime_lock"],
            }
            for asset_id in normalized
            if lifecycle[asset_id]["runtime_lock"]["locked"]
        ]
        return {
            "asset_ids": normalized,
            "assets": [
                {
                    **self._public_upload(by_id[asset_id]),
                    "deletable": not lifecycle[asset_id]["runtime_lock"]["locked"],
                    **lifecycle[asset_id],
                }
                for asset_id in normalized
            ],
            "runtime_locked": locked,
            "detached_binding_count": len(draft_rows),
            "affected_scenario_ids": sorted({str(row["scenario_id"]) for row in draft_rows}),
            "cancelled_queue_item_ids": [str(row["queue_item_id"]) for row in queued_rows],
        }

    def list_uploads(self, project_id: str) -> list[Dict[str, Any]]:
        database = self.project_database(project_id)
        with database.connect() as connection:
            rows = connection.execute("SELECT * FROM uploads WHERE archived=0 ORDER BY created_at, upload_id").fetchall()
            lifecycle = self._asset_lifecycle_for_ids_connection(
                connection,
                [str(row["upload_id"]) for row in rows],
            ) if rows else {}
        assets: list[Dict[str, Any]] = []
        for row in rows:
            asset_id = str(row["upload_id"])
            state = lifecycle.get(asset_id, {})
            runtime_lock = state.get("runtime_lock") or {"locked": False, "simulation_ids": [], "statuses": []}
            assets.append(
                {
                    **self._public_upload(row),
                    "deletable": not bool(runtime_lock["locked"]),
                    "runtime_lock": runtime_lock,
                    "draft_reference_count": int(state.get("draft_reference_count") or 0),
                    "queued_reference_count": int(state.get("queued_reference_count") or 0),
                }
            )
        return assets

    def _legacy_delete_asset(self, project_id: str, asset_id: str) -> None:
        database = self.project_database(project_id)
        with database.connect() as connection:
            row = connection.execute(
                "SELECT upload_id FROM uploads WHERE upload_id=? AND archived=0",
                (asset_id,),
            ).fetchone()
            if not row:
                raise WorkbenchError("upload_not_found", "输入资产不存在。", status_code=404)
            references = connection.execute(
                "SELECT revision_id, binding_key FROM input_revision_bindings WHERE asset_id=? LIMIT 20",
                (asset_id,),
            ).fetchall()
            if references:
                raise WorkbenchError(
                    "asset_in_use",
                    "资产已被输入快照引用，不能物理删除；请改为归档。",
                    status_code=409,
                    details={"references": [dict(item) for item in references]},
                )
        self.delete_upload(project_id, asset_id)

    def preview_asset_delete(self, project_id: str, asset_ids: list[str]) -> Dict[str, Any]:
        database = self.project_database(project_id)
        with database.connect() as connection:
            return self._asset_delete_impact_connection(connection, asset_ids)

    def batch_delete_assets(self, project_id: str, asset_ids: list[str]) -> Dict[str, Any]:
        """Delete logical assets atomically while retaining immutable snapshot blobs."""
        database = self.project_database(project_id)
        with database.connect() as connection:
            # Claiming a queue item takes this same lock before its snapshot is
            # created, so a deletion is all-or-nothing even under a scheduler race.
            connection.execute("BEGIN IMMEDIATE")
            impact = self._asset_delete_impact_connection(connection, asset_ids)
            if impact["runtime_locked"]:
                raise WorkbenchError(
                    "asset_runtime_locked",
                    "Assets used by an active calculation cannot be deleted.",
                    status_code=409,
                    details={"runtime_locked": impact["runtime_locked"]},
                )
            normalized = impact["asset_ids"]
            placeholders = ",".join("?" for _ in normalized)
            removed_rows = connection.execute(
                f"SELECT sha256 FROM uploads WHERE upload_id IN ({placeholders})",
                tuple(normalized),
            ).fetchall()
            now = utc_now()
            if impact["cancelled_queue_item_ids"]:
                queue_placeholders = ",".join("?" for _ in impact["cancelled_queue_item_ids"])
                connection.execute(
                    f"""
                    UPDATE queue_items
                    SET status='cancelled', finished_at=?, summary='Draft input deleted; queue item cancelled.',
                        cancel_reason='asset_deleted'
                    WHERE queue_item_id IN ({queue_placeholders}) AND status='queued'
                    """,
                    (now, *impact["cancelled_queue_item_ids"]),
                )
            connection.execute(
                f"DELETE FROM scenario_draft_bindings WHERE asset_id IN ({placeholders})",
                tuple(normalized),
            )
            if impact["affected_scenario_ids"]:
                scenario_placeholders = ",".join("?" for _ in impact["affected_scenario_ids"])
                connection.execute(
                    f"""
                    UPDATE scenarios
                    SET status='draft', version=version+1, updated_at=?
                    WHERE scenario_id IN ({scenario_placeholders})
                      AND archived=0 AND status IN ('draft', 'ready', 'queued')
                    """,
                    (now, *impact["affected_scenario_ids"]),
                )
            connection.execute(
                f"DELETE FROM uploads WHERE upload_id IN ({placeholders})",
                tuple(normalized),
            )
            manifests = connection.execute("SELECT manifest_json FROM input_revisions").fetchall()
            retained_snapshot_blob_count = sum(
                1
                for row in removed_rows
                if any(
                    any(str(entry.get("sha256") or "") == str(row["sha256"]) for entry in json_loads(manifest["manifest_json"], []))
                    for manifest in manifests
                )
            )
        return {
            "deleted_ids": impact["asset_ids"],
            "detached_binding_count": impact["detached_binding_count"],
            "cancelled_queue_item_ids": impact["cancelled_queue_item_ids"],
            "retained_snapshot_blob_count": retained_snapshot_blob_count,
        }

    def delete_asset(self, project_id: str, asset_id: str) -> None:
        self.batch_delete_assets(project_id, [asset_id])

    def get_raster_asset_context(self, project_id: str, asset_id: str) -> Dict[str, Any]:
        """Return the validated content-addressed source for one raster asset."""
        database = self.project_database(project_id)
        with database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM uploads WHERE upload_id=? AND archived=0",
                (asset_id,),
            ).fetchone()
        if not row:
            raise WorkbenchError("asset_not_found", "栅格资产不存在或已归档。", status_code=404)
        path = Path(str(row["blob_path"])).resolve()
        if not path.is_file():
            raise WorkbenchError("upload_blob_missing", "栅格资产内容不可用。", status_code=404)
        return {
            "project_id": project_id,
            "asset_id": str(row["upload_id"]),
            "family": str(row["family"]),
            "name": str(row["name"]),
            "sha256": str(row["sha256"]),
            "source_path": path,
            "database": database,
            "asset": self._public_upload(row),
        }

    @staticmethod
    def _raster_profile_key(sha256: str, data_kind: str, profile_version: str = "1") -> str:
        return f"{sha256}:{data_kind}:{profile_version}"

    def get_raster_profile_record(self, project_id: str, asset_id: str) -> Optional[Dict[str, Any]]:
        context = self.get_raster_asset_context(project_id, asset_id)
        from api.services.raster_engine import data_kind_for_family

        data_kind = data_kind_for_family(str(context["family"]))
        key = self._raster_profile_key(str(context["sha256"]), data_kind)
        with context["database"].connect() as connection:
            row = connection.execute(
                "SELECT * FROM raster_profiles WHERE profile_key=?",
                (key,),
            ).fetchone()
        if not row:
            return None
        data = dict(row)
        data["profile"] = json_loads(data.get("profile_json"), {})
        return data

    def save_raster_profile(
        self,
        project_id: str,
        asset_id: str,
        profile: Dict[str, Any],
        *,
        cache_path: Optional[Path] = None,
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        context = self.get_raster_asset_context(project_id, asset_id)
        source_sha256 = str(context["sha256"])
        data_kind = str(profile.get("data_kind") or "continuous")
        profile_version = str(profile.get("profile_version") or "1")
        key = self._raster_profile_key(source_sha256, data_kind, profile_version)
        now = utc_now()
        status = str(profile.get("status") or ("error" if error else "ready"))
        with context["database"].connect() as connection:
            connection.execute(
                """
                INSERT INTO raster_profiles(
                    profile_key, source_sha256, data_kind, profile_version, status,
                    profile_json, cache_path, error, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_sha256, data_kind, profile_version) DO UPDATE SET
                    status=excluded.status,
                    profile_json=excluded.profile_json,
                    cache_path=excluded.cache_path,
                    error=excluded.error,
                    updated_at=excluded.updated_at
                """,
                (
                    key,
                    source_sha256,
                    data_kind,
                    profile_version,
                    status,
                    json.dumps(profile, ensure_ascii=False),
                    str(cache_path) if cache_path else None,
                    error,
                    now,
                    now,
                ),
            )
            if profile.get("status") == "ready":
                metadata = json_loads(
                    connection.execute(
                        "SELECT metadata_json FROM uploads WHERE upload_id=?",
                        (asset_id,),
                    ).fetchone()[0],
                    {},
                )
                transform = profile.get("transform") or {}
                bounds = profile.get("bounds") or {}
                cell_x = abs(float(transform.get("a") or 0)) or None
                cell_y = abs(float(transform.get("e") or 0)) or None
                metadata.update(
                    {
                        "rows": profile.get("height"),
                        "cols": profile.get("width"),
                        "cell_size": cell_x,
                        "cell_size_x": cell_x,
                        "cell_size_y": cell_y,
                        "origin": {"x": bounds.get("xmin"), "y": bounds.get("ymin")},
                        "crs": profile.get("crs"),
                        "nodata": profile.get("nodata"),
                        "extent": [
                            bounds.get("xmin"),
                            bounds.get("ymin"),
                            bounds.get("xmax"),
                            bounds.get("ymax"),
                        ],
                        "geotransform": transform,
                        "raster_profile_version": profile_version,
                    }
                )
                connection.execute(
                    "UPDATE uploads SET metadata_json=? WHERE upload_id=?",
                    (json.dumps(metadata, ensure_ascii=False), asset_id),
                )
        saved = dict(profile)
        saved["status"] = status
        saved["profile_key"] = key
        saved["cache_path"] = str(cache_path) if cache_path else None
        if error:
            saved["error"] = error
        return saved

    def get_map_state(self, project_id: str) -> Dict[str, Any]:
        database = self.project_database(project_id)
        default_state = {
            "layers": [],
            "active_layer_id": None,
            "view": {"center": None, "resolution": None, "rotation": 0},
        }
        with database.connect() as connection:
            row = connection.execute(
                "SELECT project_id, version, state_json, updated_at FROM project_map_state WHERE project_id=?",
                (project_id,),
            ).fetchone()
            if not row:
                now = utc_now()
                connection.execute(
                    "INSERT INTO project_map_state(project_id, version, state_json, updated_at) VALUES(?, 1, ?, ?)",
                    (project_id, json.dumps(default_state, ensure_ascii=False), now),
                )
                return {"project_id": project_id, "version": 1, "state": default_state, "updated_at": now}
        return {
            "project_id": project_id,
            "version": int(row["version"]),
            "state": json_loads(row["state_json"], default_state),
            "updated_at": str(row["updated_at"]),
        }

    def update_map_state(
        self,
        project_id: str,
        state: Dict[str, Any],
        *,
        expected_version: Optional[int] = None,
    ) -> Dict[str, Any]:
        database = self.project_database(project_id)
        with database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT version FROM project_map_state WHERE project_id=?",
                (project_id,),
            ).fetchone()
            current_version = int(row["version"]) if row else 1
            if expected_version is not None and expected_version != current_version:
                raise WorkbenchError(
                    "map_state_conflict",
                    "图层状态已在其他窗口更新，请刷新后重试。",
                    status_code=409,
                    details={"expected_version": expected_version, "current_version": current_version},
                )
            now = utc_now()
            next_version = current_version + 1 if row else 1
            connection.execute(
                """
                INSERT INTO project_map_state(project_id, version, state_json, updated_at)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    version=excluded.version,
                    state_json=excluded.state_json,
                    updated_at=excluded.updated_at
                """,
                (project_id, next_version, json.dumps(state, ensure_ascii=False), now),
            )
        return {"project_id": project_id, "version": next_version, "state": state, "updated_at": now}

    def archive_asset(self, project_id: str, asset_id: str) -> Dict[str, Any]:
        database = self.project_database(project_id)
        with database.connect() as connection:
            row = connection.execute("SELECT * FROM uploads WHERE upload_id=?", (asset_id,)).fetchone()
            if not row:
                raise WorkbenchError("upload_not_found", "输入资产不存在。", status_code=404)
            connection.execute("UPDATE uploads SET archived=1 WHERE upload_id=?", (asset_id,))
        result = self._public_upload(row)
        result["archived"] = True
        return result

    def get_upload_blob_path(self, project_id: str, upload_id: str) -> Path:
        database = self.project_database(project_id)
        with database.connect() as connection:
            row = connection.execute(
                "SELECT blob_path, name FROM uploads WHERE upload_id=?", (upload_id,)
            ).fetchone()
        if not row:
            raise WorkbenchError("upload_not_found", "上传文件不存在。", status_code=404)
        path = Path(str(row["blob_path"]))
        if not path.is_file():
            raise WorkbenchError("upload_blob_missing", "上传文件内容不可用。", status_code=404)
        return path

    def _legacy_delete_upload(self, project_id: str, upload_id: str) -> None:
        """Remove an upload row. Revisions that already snapshotted the file remain valid."""
        database = self.project_database(project_id)
        with database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM uploads WHERE upload_id=?", (upload_id,)
            ).fetchone()
            if not row:
                raise WorkbenchError("upload_not_found", "上传文件不存在。", status_code=404)
            sha256 = str(row["sha256"])
            blob_path = Path(str(row["blob_path"]))
            connection.execute("DELETE FROM uploads WHERE upload_id=?", (upload_id,))

            still_referenced = connection.execute(
                "SELECT COUNT(*) FROM uploads WHERE sha256=?", (sha256,)
            ).fetchone()[0]
            if still_referenced:
                return

            revision_rows = connection.execute("SELECT manifest_json FROM input_revisions").fetchall()
            for revision_row in revision_rows:
                for item in json_loads(revision_row["manifest_json"], []):
                    if str(item.get("sha256") or "") == sha256:
                        return

        if blob_path.is_file():
            blob_path.unlink(missing_ok=True)

    def delete_upload(self, project_id: str, upload_id: str) -> None:
        """Compatibility endpoint with the same lifecycle rules as /assets."""
        self.delete_asset(project_id, upload_id)

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
            "parent_revision_id": data.get("parent_revision_id"),
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

    @staticmethod
    def _binding_projection(binding: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "binding_key": str(binding.get("binding_key") or ""),
            "asset_id": str(binding.get("asset_id") or binding.get("upload_id") or ""),
            "family": str(binding.get("family") or "native"),
            "role": str(binding.get("role") or binding.get("family") or "native"),
            "period_id": binding.get("period_id"),
            "ordinal": int(binding["ordinal"]) if binding.get("ordinal") is not None else None,
            "active": bool(binding.get("active", True)),
            "metadata": dict(binding.get("metadata") or {}),
        }

    @classmethod
    def _bindings_for_revision_connection(
        cls,
        connection: sqlite3.Connection,
        revision_id: Optional[str],
    ) -> list[Dict[str, Any]]:
        if not revision_id:
            return []
        rows = connection.execute(
            """
            SELECT binding_key, asset_id, family, role, period_id, ordinal,
                   active, metadata_json
            FROM input_revision_bindings
            WHERE revision_id=?
            ORDER BY CASE WHEN ordinal IS NULL THEN 0 ELSE ordinal END, binding_key
            """,
            (revision_id,),
        ).fetchall()
        return [
            {
                "binding_key": str(row["binding_key"]),
                "asset_id": str(row["asset_id"]),
                "family": str(row["family"]),
                "role": str(row["role"]),
                "period_id": row["period_id"],
                "ordinal": int(row["ordinal"]) if row["ordinal"] is not None else None,
                "active": bool(row["active"]),
                "metadata": json_loads(row["metadata_json"], {}),
            }
            for row in rows
        ]

    def input_revision_bindings(self, project_id: str, revision_id: str) -> list[Dict[str, Any]]:
        database = self.project_database(project_id)
        with database.connect() as connection:
            return self._bindings_for_revision_connection(connection, revision_id)

    @classmethod
    def _bindings_for_draft_connection(
        cls,
        connection: sqlite3.Connection,
        scenario_id: str,
    ) -> list[Dict[str, Any]]:
        rows = connection.execute(
            """
            SELECT binding_key, asset_id, family, role, period_id, ordinal,
                   active, metadata_json
            FROM scenario_draft_bindings
            WHERE scenario_id=?
            ORDER BY CASE WHEN ordinal IS NULL THEN 0 ELSE ordinal END, binding_key
            """,
            (scenario_id,),
        ).fetchall()
        return [
            {
                "binding_key": str(row["binding_key"]),
                "asset_id": str(row["asset_id"]),
                "family": str(row["family"]),
                "role": str(row["role"]),
                "period_id": row["period_id"],
                "ordinal": int(row["ordinal"]) if row["ordinal"] is not None else None,
                "active": bool(row["active"]),
                "metadata": json_loads(row["metadata_json"], {}),
            }
            for row in rows
        ]

    @classmethod
    def _replace_draft_bindings_connection(
        cls,
        connection: sqlite3.Connection,
        scenario_id: str,
        bindings: list[Dict[str, Any]],
    ) -> None:
        connection.execute("DELETE FROM scenario_draft_bindings WHERE scenario_id=?", (scenario_id,))
        for binding in bindings:
            connection.execute(
                """
                INSERT INTO scenario_draft_bindings(
                    scenario_id, binding_key, asset_id, family, role,
                    period_id, ordinal, active, metadata_json
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scenario_id,
                    binding["binding_key"],
                    binding["asset_id"],
                    binding["family"],
                    binding["role"],
                    binding.get("period_id"),
                    binding.get("ordinal"),
                    1 if binding.get("active", True) else 0,
                    json.dumps(binding.get("metadata") or {}, ensure_ascii=False),
                ),
            )

    @classmethod
    def _resolve_binding_assets(
        cls,
        connection: sqlite3.Connection,
        bindings: list[Dict[str, Any]],
    ) -> tuple[list[Dict[str, Any]], list[Dict[str, Any]]]:
        projected = [cls._binding_projection(binding) for binding in bindings]
        keys = [item["binding_key"] for item in projected]
        if any(not key for key in keys) or len(set(keys)) != len(keys):
            raise WorkbenchError(
                "invalid_input_bindings",
                "输入绑定键不能为空且必须唯一。",
                status_code=422,
            )
        asset_ids = [item["asset_id"] for item in projected]
        if any(not asset_id for asset_id in asset_ids):
            raise WorkbenchError("invalid_input_bindings", "输入绑定缺少资产 ID。", status_code=422)
        if not asset_ids:
            return [], []
        placeholders = ",".join("?" for _ in asset_ids)
        rows = connection.execute(
            f"SELECT * FROM uploads WHERE upload_id IN ({placeholders})",
            tuple(asset_ids),
        ).fetchall()
        by_id = {str(row["upload_id"]): row for row in rows}
        missing = [asset_id for asset_id in asset_ids if asset_id not in by_id]
        if missing:
            raise WorkbenchError(
                "upload_not_found",
                "部分输入资产不存在。",
                status_code=422,
                details={"asset_ids": missing},
            )
        manifest: list[Dict[str, Any]] = []
        for binding in projected:
            row = by_id[binding["asset_id"]]
            if binding["family"] != str(row["family"]):
                raise WorkbenchError(
                    "input_binding_family_mismatch",
                    "输入绑定声明的类型与资产类型不一致。",
                    status_code=422,
                    details={"binding_key": binding["binding_key"], "asset_id": binding["asset_id"]},
                )
            manifest.append(
                {
                    "upload_id": row["upload_id"],
                    "asset_id": row["upload_id"],
                    "family": row["family"],
                    "name": row["name"],
                    "sha256": row["sha256"],
                    "size": row["size"],
                    "blob_path": row["blob_path"],
                    "raster_metadata": json_loads(row["metadata_json"], {}),
                    **binding,
                }
            )
        return projected, manifest

    def _insert_input_revision(
        self,
        connection: sqlite3.Connection,
        *,
        bindings: list[Dict[str, Any]],
        manifest: list[Dict[str, Any]],
        parent_revision_id: Optional[str],
        version_tag: Optional[str] = None,
    ) -> tuple[str, str, Dict[str, Any], str]:
        validation = self._validate_manifest(manifest)
        revision_id = f"rev-{uuid4().hex}"
        count = connection.execute("SELECT COUNT(*) FROM input_revisions").fetchone()[0]
        tag = (version_tag or "").strip() or f"v{count + 1}"
        status = "ready" if validation["valid"] else "invalid"
        summary = f"{len(bindings)} 个绑定；{len(validation['warnings'])} 个警告"
        created_at = utc_now()
        connection.execute(
            """
            INSERT INTO input_revisions(
                revision_id, version_tag, status, summary, manifest_json,
                validation_json, parent_revision_id, created_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                revision_id,
                tag,
                status,
                summary,
                json.dumps(manifest, ensure_ascii=False),
                json.dumps(validation, ensure_ascii=False),
                parent_revision_id,
                created_at,
            ),
        )
        for binding in bindings:
            connection.execute(
                """
                INSERT INTO input_revision_bindings(
                    revision_id, binding_key, asset_id, family, role,
                    period_id, ordinal, active, metadata_json
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    revision_id,
                    binding["binding_key"],
                    binding["asset_id"],
                    binding["family"],
                    binding["role"],
                    binding.get("period_id"),
                    binding.get("ordinal"),
                    1 if binding.get("active", True) else 0,
                    json.dumps(binding.get("metadata") or {}, ensure_ascii=False),
                ),
            )
        return revision_id, status, validation, created_at

    def create_input_revision(
        self,
        project_id: str,
        *,
        version_tag: Optional[str],
        upload_ids: list[str],
        parent_revision_id: Optional[str],
        bindings: Optional[list[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        database = self.project_database(project_id)
        if not upload_ids and not parent_revision_id and not bindings:
            raise WorkbenchError("empty_input_revision", "输入修订至少需要一个上传文件。", status_code=422)

        binding_by_key: Dict[str, Dict[str, Any]] = {}
        if parent_revision_id:
            self._revision_row(project_id, parent_revision_id)
            with database.connect() as connection:
                for binding in self._bindings_for_revision_connection(connection, parent_revision_id):
                    binding_by_key[binding["binding_key"]] = binding

        if bindings is not None:
            for binding in bindings:
                projected = self._binding_projection(binding)
                binding_by_key[projected["binding_key"]] = projected

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
        family_counts: Dict[str, int] = {}
        for binding in binding_by_key.values():
            family = str(binding["family"])
            family_counts[family] = max(family_counts.get(family, 0), int(binding.get("ordinal") or 1))
        for upload_id in upload_ids:
            row = found[upload_id]
            family = str(row["family"])
            if family in {"rainfall", "rifil"}:
                ordinal = family_counts.get(family, 0) + 1
                family_counts[family] = ordinal
            else:
                ordinal = 1
            binding_key, role = _legacy_binding_identity(family, ordinal)
            binding_by_key[binding_key] = {
                "binding_key": binding_key,
                "asset_id": str(row["upload_id"]),
                "family": family,
                "role": role,
                "period_id": f"period-{ordinal:04d}" if family in {"rainfall", "rifil"} else None,
                "ordinal": ordinal,
                "active": True,
                "metadata": {},
            }

        requested_bindings = list(binding_by_key.values())
        with database.connect() as connection:
            bindings, manifest = self._resolve_binding_assets(connection, requested_bindings)
            revision_id, status, _, created_at = self._insert_input_revision(
                connection,
                bindings=bindings,
                manifest=manifest,
                parent_revision_id=parent_revision_id,
                version_tag=version_tag,
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
        previous_validation = json_loads(row["validation_json"], {})
        unresolved = list(previous_validation.get("unresolved_bindings") or [])
        if unresolved:
            validation["valid"] = False
            validation["unresolved_bindings"] = unresolved
            validation["errors"] = [
                *list(validation.get("errors") or []),
                f"Legacy migration has {len(unresolved)} unresolved active input binding(s).",
            ]
            validation.setdefault("issues", []).append({
                "code": "legacy_unresolved_binding",
                "severity": "error",
                "message": f"Legacy migration has {len(unresolved)} unresolved active input binding(s).",
            })
        status = "ready" if validation["valid"] else "invalid"
        with database.connect() as connection:
            connection.execute(
                "UPDATE input_revisions SET status=?, validation_json=? WHERE revision_id=?",
                (status, json.dumps(validation, ensure_ascii=False), revision_id),
            )
        return validation

    def get_config_interface(self, project_id: str, revision_id: str) -> Dict[str, Any]:
        """Parse the config-family edda_in from a revision into a frontend-safe interface."""
        from api.services.parameter_catalog import build_case_config_interface
        from api.services.reference_config_parser import parse_reference_config_file

        project = self.get_project(project_id)
        row = self._revision_row(project_id, revision_id)
        manifest = json_loads(row["manifest_json"], [])
        config_entry = next((item for item in manifest if str(item.get("family")) == "config"), None)
        if not config_entry:
            raise WorkbenchError(
                "config_not_found",
                "当前输入修订未包含参数配置（config / edda_in）文件。",
                status_code=404,
            )
        config_path = Path(str(config_entry["blob_path"]))
        if not config_path.is_file():
            raise WorkbenchError("config_blob_missing", "参数配置文件内容不可用。", status_code=404)
        case_base_dir = self._resolve_case_base_dir(project, manifest, config_entry)
        try:
            parsed = parse_reference_config_file(str(config_path), case_base_dir)
            interface = build_case_config_interface(parsed)
        except Exception as exc:
            raise WorkbenchError(
                "config_parse_failed",
                f"解析 edda_in 失败：{exc}",
                status_code=400,
                details={"case_config_file": str(config_path), "case_base_dir": case_base_dir},
            ) from exc
        interface["revision_id"] = revision_id
        interface["project_id"] = project_id
        return interface

    @staticmethod
    def _editable_parameter_keys() -> set[str]:
        from api.services.parameter_catalog import EDITABLE_PARAMETERS, build_static_parameter_catalog

        catalog = build_static_parameter_catalog()
        keys = {
            str(entry["key"])
            for entry in catalog["parameters"]
            if entry.get("editable")
            and entry.get("runtime_status") in {"production_consumed", "config_fallback_consumed"}
        }
        # Always allow input-source mode switches even if catalog status filtering drifts.
        keys.update(EDITABLE_PARAMETERS)
        return keys

    def _validate_parameter_patch(self, patch: Dict[str, Any]) -> None:
        from api.services.compute_gate_defaults import strip_gate_parameters

        allowed = self._editable_parameter_keys()
        scientific = strip_gate_parameters(patch)
        invalid = sorted(key for key in scientific if key not in allowed)
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

    def scenario_work_dir(self, project_id: str, scenario_id: str) -> Path:
        database = self.project_database(project_id)
        return database.scenario_dir(scenario_id)

    def ensure_scenario_workspace(
        self,
        project_id: str,
        scenario_id: str,
        *,
        name: Optional[str] = None,
        effective_parameters: Optional[Dict[str, Any]] = None,
    ) -> Path:
        """Create the on-disk scenario workspace and refresh its metadata snapshot."""
        database = self.project_database(project_id)
        row = self._scenario_row(project_id, scenario_id)
        work_dir = database.scenario_dir(scenario_id)
        (work_dir / "outputs").mkdir(parents=True, exist_ok=True)
        meta = {
            "scenario_id": scenario_id,
            "project_id": project_id,
            "name": name if name is not None else row["name"],
            "input_revision_id": row["input_revision_id"],
            "status": row["status"],
            "work_dir": str(work_dir.relative_to(database.root)).replace("\\", "/"),
            "updated_at": utc_now(),
        }
        (work_dir / "scenario.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        params = (
            effective_parameters
            if effective_parameters is not None
            else json_loads(row["effective_parameters_json"], {})
        )
        (work_dir / "effective_parameters.json").write_text(
            json.dumps(params, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return work_dir

    def ensure_all_scenario_workspaces(self, project_id: str) -> None:
        database = self.project_database(project_id)
        with database.connect() as connection:
            rows = connection.execute("SELECT scenario_id FROM scenarios").fetchall()
        for row in rows:
            self.ensure_scenario_workspace(project_id, str(row["scenario_id"]))

    @staticmethod
    def _is_corrupted_scenario_name(name: Any) -> bool:
        """Detect replacement-character or question-mark corruption of Chinese names."""
        if not isinstance(name, str) or not name:
            return False
        stripped = name.strip()
        if not stripped:
            return False
        if "\ufffd" in stripped:
            return True
        # Windows console/GBK mis-encoding often collapses CJK into literal "?".
        return bool(stripped) and all(ch == "?" for ch in stripped)

    def _repair_corrupted_scenario_name(
        self,
        project_id: str,
        scenario_id: str,
        current_name: str,
        work_dir: Path,
    ) -> str:
        """If SQLite name is corrupted, recover a valid name from scenario.json."""
        if not self._is_corrupted_scenario_name(current_name):
            return current_name
        meta_path = work_dir / "scenario.json"
        if not meta_path.is_file():
            return current_name
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return current_name
        recovered = meta.get("name") if isinstance(meta, dict) else None
        if not isinstance(recovered, str) or not recovered.strip():
            return current_name
        if self._is_corrupted_scenario_name(recovered):
            return current_name
        if recovered == current_name:
            return current_name
        database = self.project_database(project_id)
        with database.connect() as connection:
            connection.execute(
                "UPDATE scenarios SET name=?, updated_at=? WHERE scenario_id=?",
                (recovered, utc_now(), scenario_id),
            )
            connection.commit()
        return recovered

    def _public_scenario(
        self,
        project_id: str,
        row: sqlite3.Row | Dict[str, Any],
        *,
        global_gates: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        database = self.project_database(project_id)
        data = dict(row)
        work_dir = database.scenario_dir(str(data["scenario_id"]))
        if not work_dir.exists():
            self.ensure_scenario_workspace(project_id, str(data["scenario_id"]))
        data["name"] = self._repair_corrupted_scenario_name(
            project_id,
            str(data["scenario_id"]),
            str(data.get("name") or ""),
            work_dir,
        )
        with database.connect() as connection:
            revision = (
                connection.execute(
                    "SELECT manifest_json FROM input_revisions WHERE revision_id=?",
                    (data["input_revision_id"],),
                ).fetchone()
                if data.get("input_revision_id")
                else None
            )
            family_count = connection.execute(
                "SELECT COUNT(*) FROM result_families WHERE simulation_id=?",
                (data.get("latest_simulation_id"),),
            ).fetchone()[0] if data.get("latest_simulation_id") else 0
            progress_row = connection.execute(
                "SELECT progress FROM simulation_runs WHERE simulation_id=?",
                (data.get("latest_simulation_id"),),
            ).fetchone() if data.get("latest_simulation_id") else None
            binding_state = "runtime_snapshot" if data.get("input_revision_id") else "draft"
            input_bindings = (
                self._bindings_for_revision_connection(connection, data.get("input_revision_id"))
                if data.get("input_revision_id")
                else self._bindings_for_draft_connection(connection, str(data["scenario_id"]))
            )
            parameter_baseline = self._parameter_template_values(
                connection,
                data.get("parameter_template_id"),
            )
            parameter_metadata = self._parameter_template_metadata(
                connection,
                data.get("parameter_template_id"),
            )
            control_overrides = self._validate_control_overrides(
                json_loads(data.get("control_overrides_json"), {})
            )
            compute_snapshot = self._scenario_compute_snapshot(
                connection,
                row,
                global_gates=global_gates,
            )
        file_count = len(input_bindings) if input_bindings else (len(json_loads(revision["manifest_json"], [])) if revision else 0)
        relative_work = str(work_dir.relative_to(database.root)).replace("\\", "/")
        from api.services.parameter_templates import canonicalize_edda_control_parameters
        from api.services.compute_gate_defaults import strip_gate_parameters

        parameter_patch = strip_gate_parameters(
            canonicalize_edda_control_parameters(json_loads(data["parameter_patch_json"], {}))
        )
        return {
            "scenario_id": data["scenario_id"],
            "project_id": project_id,
            "name": data["name"],
            "input_revision_id": data.get("input_revision_id"),
            "base_scenario_id": data.get("base_scenario_id"),
            "parameter_template_id": data.get("parameter_template_id"),
            "parameter_baseline": parameter_baseline,
            "parameter_patch": parameter_patch,
            "control_overrides": control_overrides,
            "configuration_ownership": "reference_case" if self._reference_case_owned(parameter_metadata) else "global_defaults",
            "case_fingerprint": ((parameter_metadata.get("_compute_policy") or {}).get("case_fingerprint")
                                  if isinstance(parameter_metadata.get("_compute_policy"), Mapping) else None),
            "effective_parameters": compute_snapshot.effective_parameters,
            "compute_policy_resolution": compute_snapshot.resolution,
            "input_bindings": input_bindings,
            "binding_state": binding_state,
            "version": int(data.get("version") or 1),
            "status": data["status"],
            "progress": float(progress_row["progress"]) if progress_row else 0.0,
            "latest_simulation_id": data.get("latest_simulation_id"),
            "result_family_count": int(family_count),
            "file_count": file_count,
            "work_dir": relative_work,
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

    def get_scenario_configuration(self, project_id: str, scenario_id: str) -> Dict[str, Any]:
        from api.services.structured_input_resolver import validate_scenario_configuration

        scenario_row = self._scenario_row(project_id, scenario_id)
        scenario = self._public_scenario(project_id, scenario_row)
        database = self.project_database(project_id)
        manifest: list[Dict[str, Any]] = []
        revision_validation: Dict[str, Any] = {}
        draft_validation: Dict[str, Any] = json_loads(scenario_row["draft_validation_json"], {})
        if scenario.get("input_revision_id"):
            with database.connect() as connection:
                revision = connection.execute(
                    "SELECT manifest_json, validation_json FROM input_revisions WHERE revision_id=?",
                    (scenario["input_revision_id"],),
                ).fetchone()
            manifest = json_loads(revision["manifest_json"], []) if revision else []
            revision_validation = json_loads(revision["validation_json"], {}) if revision else {}
        else:
            with database.connect() as connection:
                draft_bindings = self._bindings_for_draft_connection(connection, scenario_id)
                _, manifest = self._resolve_binding_assets(connection, draft_bindings)
        validation = validate_scenario_configuration(scenario["effective_parameters"], manifest)
        resolution = scenario.get("compute_policy_resolution") or {}
        if str(resolution.get("status") or "resolved") != "resolved":
            issue = resolution.get("blocking_issue") or {
                "code": "compute_policy_resolution_blocked",
                "severity": "error",
                "message": "失稳源策略尚未通过严格参考配置解析。",
            }
            validation["valid"] = False
            validation.setdefault("errors", []).append(str(issue.get("message") or "失稳源策略解析失败。"))
            validation.setdefault("issues", []).append(issue)
        unresolved = list((revision_validation or draft_validation).get("unresolved_bindings") or [])
        if unresolved:
            validation["valid"] = False
            validation["unresolved_bindings"] = unresolved
            validation["errors"] = [
                *list(validation.get("errors") or []),
                f"Legacy migration has {len(unresolved)} unresolved active input binding(s).",
            ]
        return {
            "scenario_id": scenario_id,
            "parameter_template_id": scenario.get("parameter_template_id"),
            "baseline": scenario.get("parameter_baseline") or {},
            "overrides": scenario.get("parameter_patch") or {},
            "control_overrides": scenario.get("control_overrides") or {},
            "configuration_ownership": scenario.get("configuration_ownership") or "global_defaults",
            "case_fingerprint": scenario.get("case_fingerprint"),
            "effective": scenario.get("effective_parameters") or {},
            "bindings": scenario.get("input_bindings") or [],
            "binding_state": scenario.get("binding_state") or "draft",
            "validation": validation,
            "compute_policy_resolution": resolution,
            "version": scenario.get("version", 1),
        }

    def create_scenario(
        self,
        project_id: str,
        *,
        name: str,
        input_revision_id: Optional[str],
        base_scenario_id: Optional[str],
        parameter_patch: Dict[str, Any],
        parameter_template_id: Optional[str] = None,
        control_overrides: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        from api.services.parameter_templates import BJ_HXL_TEMPLATE_ID, merge_parameter_values, normalize_rainfall_patch
        from api.services.compute_gate_defaults import strip_gate_parameters

        database = self.project_database(project_id)
        base = self._scenario_row(project_id, base_scenario_id) if base_scenario_id else None
        selected_template_id = (
            parameter_template_id
            or (str(base["parameter_template_id"]) if base and base["parameter_template_id"] else None)
            or BJ_HXL_TEMPLATE_ID
        )
        with database.connect() as connection:
            if input_revision_id:
                revision = connection.execute(
                    "SELECT * FROM input_revisions WHERE revision_id=?", (input_revision_id,)
                ).fetchone()
                if not revision:
                    raise WorkbenchError("input_revision_not_found", "输入修订不存在。", status_code=404)
                if parameter_template_id is None and base is None:
                    revision_manifest = json_loads(revision["manifest_json"], [])
                    if any(str(item.get("family")) == "config" for item in revision_manifest):
                        # Existing config-bound scenarios remain on the legacy read-only
                        # compatibility path until the explicit migration wizard is used.
                        selected_template_id = None
            else:
                # New scenarios start from the parameter template only. Project assets
                # and old revisions never become implicit scenario inputs.
                revision = None
            baseline = self._parameter_template_values(connection, selected_template_id)
            template_metadata = self._parameter_template_metadata(connection, selected_template_id)
        if revision and revision["status"] != "ready":
            raise WorkbenchError("input_revision_invalid", "方案只能引用已通过校验的输入修订。", status_code=409)

        effective_patch = json_loads(base["parameter_patch_json"], {}) if base else {}
        effective_patch.update(parameter_patch)
        effective_patch = strip_gate_parameters(normalize_rainfall_patch(effective_patch))
        self._validate_parameter_patch(effective_patch)
        effective_controls = self._validate_control_overrides(
            control_overrides
            if control_overrides is not None
            else (json_loads(base["control_overrides_json"], {}) if base is not None else {})
        )
        effective_parameters = self._merged_effective_parameters(
            baseline,
            effective_patch,
            template_id=selected_template_id,
            template_metadata=template_metadata,
            control_overrides=effective_controls,
        )
        scenario_id = f"scn-{uuid4().hex}"
        now = utc_now()
        status = "ready" if revision else "draft"
        bound_revision_id = str(revision["revision_id"]) if revision else None
        with database.connect() as connection:
            connection.execute(
                """
                INSERT INTO scenarios(
                    scenario_id, name, input_revision_id, base_scenario_id,
                    parameter_template_id, parameter_patch_json, control_overrides_json,
                    effective_parameters_json, status, archived, latest_simulation_id, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, ?, ?)
                """,
                (
                    scenario_id,
                    name.strip(),
                    bound_revision_id,
                    base_scenario_id,
                    selected_template_id,
                    json.dumps(effective_patch, ensure_ascii=False),
                    json.dumps(effective_controls, ensure_ascii=False),
                    json.dumps(effective_parameters, ensure_ascii=False),
                    status,
                    now,
                    now,
                ),
            )
        self.ensure_scenario_workspace(
            project_id,
            scenario_id,
            name=name.strip(),
            effective_parameters=effective_parameters,
        )
        return self._public_scenario(project_id, self._scenario_row(project_id, scenario_id))

    def _legacy_update_scenario(
        self,
        project_id: str,
        scenario_id: str,
        *,
        name: Optional[str],
        parameter_patch: Optional[Dict[str, Any]],
        input_revision_id: Optional[str] = None,
        input_bindings: Optional[list[Dict[str, Any]]] = None,
        parameter_template_id: Optional[str] = None,
        control_overrides: Optional[Dict[str, Any]] = None,
        expected_version: Optional[int] = None,
    ) -> Dict[str, Any]:
        from api.services.parameter_templates import merge_parameter_values, normalize_rainfall_patch
        from api.services.compute_gate_defaults import strip_gate_parameters

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
        current_version = int(row["version"] or 1)
        if expected_version is not None and int(expected_version) != current_version:
            raise WorkbenchError(
                "scenario_version_conflict",
                "方案已被其他操作更新，请刷新后重试。",
                status_code=409,
                details={"expected_version": expected_version, "current_version": current_version},
            )
        patch = json_loads(row["parameter_patch_json"], {}) if parameter_patch is None else strip_gate_parameters(normalize_rainfall_patch(parameter_patch))
        self._validate_parameter_patch(patch)
        new_name = row["name"] if name is None else name.strip()
        if not new_name:
            raise WorkbenchError("invalid_scenario_name", "方案名称不能为空。", status_code=422)
        with database.connect() as connection:
            next_revision_id = str(row["input_revision_id"]) if row["input_revision_id"] else None
            if input_bindings is not None:
                bindings, manifest = self._resolve_binding_assets(connection, input_bindings)
                current_bindings = self._bindings_for_revision_connection(connection, next_revision_id)
                current_projection = sorted(
                    (self._binding_projection(item) for item in current_bindings),
                    key=lambda item: item["binding_key"],
                )
                next_projection = sorted(
                    (self._binding_projection(item) for item in bindings),
                    key=lambda item: item["binding_key"],
                )
                if current_projection != next_projection:
                    next_revision_id, _, _, _ = self._insert_input_revision(
                        connection,
                        bindings=bindings,
                        manifest=manifest,
                        parent_revision_id=next_revision_id,
                        version_tag=None,
                    )
            elif input_revision_id is not None:
                revision = connection.execute(
                    "SELECT revision_id FROM input_revisions WHERE revision_id=?",
                    (input_revision_id,),
                ).fetchone()
                if not revision:
                    raise WorkbenchError("input_revision_not_found", "输入修订不存在。", status_code=404)
                next_revision_id = input_revision_id

            revision_status = None
            if next_revision_id:
                revision_status_row = connection.execute(
                    "SELECT status FROM input_revisions WHERE revision_id=?",
                    (next_revision_id,),
                ).fetchone()
                revision_status = str(revision_status_row["status"]) if revision_status_row else None
            next_status = "ready" if revision_status == "ready" else "draft"
            next_template_id = (
                row["parameter_template_id"]
                if parameter_template_id is None
                else parameter_template_id
            )
            baseline = self._parameter_template_values(connection, next_template_id)
            template_metadata = self._parameter_template_metadata(connection, next_template_id)
            next_controls = self._validate_control_overrides(
                control_overrides
                if control_overrides is not None
                else json_loads(row["control_overrides_json"], {})
            )
            effective_parameters = self._merged_effective_parameters(
                baseline,
                patch,
                template_id=next_template_id,
                template_metadata=template_metadata,
                control_overrides=next_controls,
            )
            next_version = current_version + 1
            connection.execute(
                """
                UPDATE scenarios SET name=?, input_revision_id=?, parameter_template_id=?,
                    parameter_patch_json=?, control_overrides_json=?, effective_parameters_json=?, version=?,
                    status=?, updated_at=? WHERE scenario_id=?
                """,
                (
                    new_name,
                    next_revision_id,
                    next_template_id,
                    json.dumps(patch, ensure_ascii=False),
                    json.dumps(next_controls, ensure_ascii=False),
                    json.dumps(effective_parameters, ensure_ascii=False),
                    next_version,
                    next_status,
                    utc_now(),
                    scenario_id,
                ),
            )
        self.ensure_scenario_workspace(
            project_id,
            scenario_id,
            name=new_name,
            effective_parameters=effective_parameters,
        )
        return self._public_scenario(project_id, self._scenario_row(project_id, scenario_id))

    def update_scenario(
        self,
        project_id: str,
        scenario_id: str,
        *,
        name: Optional[str],
        parameter_patch: Optional[Dict[str, Any]],
        input_revision_id: Optional[str] = None,
        input_bindings: Optional[list[Dict[str, Any]]] = None,
        parameter_template_id: Optional[str] = None,
        control_overrides: Optional[Dict[str, Any]] = None,
        expected_version: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Atomically update only mutable draft state; snapshots are scheduler-owned."""
        from api.services.parameter_templates import merge_parameter_values, normalize_rainfall_patch
        from api.services.compute_gate_defaults import strip_gate_parameters

        database = self.project_database(project_id)
        with database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM scenarios WHERE scenario_id=?", (scenario_id,)).fetchone()
            if not row:
                raise WorkbenchError("scenario_not_found", "Scenario does not exist.", status_code=404)
            history_count = connection.execute(
                "SELECT COUNT(*) FROM simulation_runs WHERE scenario_id=?", (scenario_id,)
            ).fetchone()[0]
            active_queue_count = connection.execute(
                """
                SELECT COUNT(*) FROM queue_items
                WHERE scenario_id=? AND status IN ('starting', 'running', 'stopping')
                """,
                (scenario_id,),
            ).fetchone()[0]
            if row["archived"] or history_count or active_queue_count:
                raise WorkbenchError(
                    "scenario_immutable",
                    "Scenarios with started run history are immutable; duplicate one to edit it.",
                    status_code=409,
                )
            current_version = int(row["version"] or 1)
            if expected_version is not None and int(expected_version) != current_version:
                raise WorkbenchError(
                    "scenario_version_conflict",
                    "Scenario has changed; refresh before saving.",
                    status_code=409,
                    details={"expected_version": expected_version, "current_version": current_version},
                )
            new_name = str(row["name"]) if name is None else name.strip()
            if not new_name:
                raise WorkbenchError("invalid_scenario_name", "Scenario name cannot be empty.", status_code=422)
            patch = json_loads(row["parameter_patch_json"], {}) if parameter_patch is None else strip_gate_parameters(normalize_rainfall_patch(parameter_patch))
            self._validate_parameter_patch(patch)
            next_template_id = row["parameter_template_id"] if parameter_template_id is None else parameter_template_id
            baseline = self._parameter_template_values(connection, next_template_id)
            template_metadata = self._parameter_template_metadata(connection, next_template_id)
            next_controls = self._validate_control_overrides(
                control_overrides
                if control_overrides is not None
                else json_loads(row["control_overrides_json"], {})
            )
            effective_parameters = self._merged_effective_parameters(
                baseline,
                patch,
                template_id=next_template_id,
                template_metadata=template_metadata,
                control_overrides=next_controls,
            )

            current_draft = self._bindings_for_draft_connection(connection, scenario_id)
            legacy_bindings = self._bindings_for_revision_connection(connection, row["input_revision_id"])
            current_bindings = current_draft or legacy_bindings
            if input_bindings is not None:
                next_bindings, _ = self._resolve_binding_assets(connection, input_bindings)
            elif input_revision_id:
                next_bindings = self._bindings_for_revision_connection(connection, input_revision_id)
                self._resolve_binding_assets(connection, next_bindings)
            else:
                next_bindings = current_bindings
                self._resolve_binding_assets(connection, next_bindings)

            current_projection = sorted(
                (self._binding_projection(binding) for binding in current_bindings),
                key=lambda binding: binding["binding_key"],
            )
            next_projection = sorted(
                (self._binding_projection(binding) for binding in next_bindings),
                key=lambda binding: binding["binding_key"],
            )
            # Parameter-only edits must retain a ready immutable input revision.
            # The editor submits its current binding projection with every save;
            # turning that identical projection into a draft would lose input
            # provenance without any input mutation.  Inputs only return to
            # draft state when their projected binding identity actually changes.
            preserve_input_revision = bool(
                row["input_revision_id"]
                and not current_draft
                and current_projection == next_projection
                and input_revision_id is None
            )
            next_input_revision_id = row["input_revision_id"] if preserve_input_revision else None
            next_status = "ready" if preserve_input_revision else "draft"
            draft_changed = (
                current_projection != next_projection
                or json_loads(row["parameter_patch_json"], {}) != patch
                or json_loads(row["control_overrides_json"], {}) != next_controls
                or str(row["name"]) != new_name
                or row["parameter_template_id"] != next_template_id
            )
            if not preserve_input_revision:
                self._replace_draft_bindings_connection(connection, scenario_id, next_bindings)
            now = utc_now()
            next_version = current_version + 1
            connection.execute(
                """
                UPDATE scenarios
                SET name=?, input_revision_id=?, parameter_template_id=?,
                    parameter_patch_json=?, control_overrides_json=?, effective_parameters_json=?, draft_validation_json='{}', version=?,
                    status=?, updated_at=?
                WHERE scenario_id=?
                """,
                (
                    new_name,
                    next_input_revision_id,
                    next_template_id,
                    json.dumps(patch, ensure_ascii=False),
                    json.dumps(next_controls, ensure_ascii=False),
                    json.dumps(effective_parameters, ensure_ascii=False),
                    next_version,
                    next_status,
                    now,
                    scenario_id,
                ),
            )
            if draft_changed:
                connection.execute(
                    """
                    UPDATE queue_items
                    SET status='cancelled', finished_at=?, summary='Draft changed; queue item cancelled.',
                        cancel_reason='draft_changed'
                    WHERE scenario_id=? AND status='queued'
                    """,
                    (now, scenario_id),
                )
        self.ensure_scenario_workspace(
            project_id,
            scenario_id,
            name=new_name,
            effective_parameters=effective_parameters,
        )
        return self._public_scenario(project_id, self._scenario_row(project_id, scenario_id))

    def _legacy_duplicate_scenario(self, project_id: str, scenario_id: str) -> Dict[str, Any]:
        source = self._scenario_row(project_id, scenario_id)
        return self.create_scenario(
            project_id,
            name=f"{source['name']}（副本）",
            input_revision_id=source["input_revision_id"],
            base_scenario_id=scenario_id,
            parameter_patch=json_loads(source["parameter_patch_json"], {}),
            parameter_template_id=source["parameter_template_id"],
            control_overrides=json_loads(source["control_overrides_json"], {}),
        )

    def duplicate_scenario(self, project_id: str, scenario_id: str) -> Dict[str, Any]:
        """Copy any draft or historical bindings into a new mutable scenario."""
        source = self._public_scenario(project_id, self._scenario_row(project_id, scenario_id))
        if source.get("input_revision_id"):
            return self.create_scenario(
                project_id,
                name=f"{source['name']} (copy)",
                input_revision_id=str(source["input_revision_id"]),
                base_scenario_id=scenario_id,
                parameter_patch=dict(source["parameter_patch"]),
                parameter_template_id=source.get("parameter_template_id"),
                control_overrides=dict(source.get("control_overrides") or {}),
            )
        duplicate = self.create_scenario(
            project_id,
            name=f"{source['name']} (copy)",
            input_revision_id=None,
            base_scenario_id=scenario_id,
            parameter_patch=dict(source["parameter_patch"]),
            parameter_template_id=source.get("parameter_template_id"),
            control_overrides=dict(source.get("control_overrides") or {}),
        )
        bindings = list(source.get("input_bindings") or [])
        if not bindings:
            return duplicate
        return self.update_scenario(
            project_id,
            duplicate["scenario_id"],
            name=None,
            parameter_patch=dict(source["parameter_patch"]),
            input_bindings=bindings,
            parameter_template_id=source.get("parameter_template_id"),
            control_overrides=dict(source.get("control_overrides") or {}),
            expected_version=duplicate.get("version"),
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
            "scenario_version": int(data["scenario_version"]) if data.get("scenario_version") is not None else None,
            "input_revision_id": data.get("input_revision_id"),
            "cancel_reason": data.get("cancel_reason"),
            "retry_of": data.get("retry_of"),
            "runtime_profile": data.get("runtime_profile") or "cuda_production_default",
            "effective_config": json_loads(data.get("effective_config_json"), {}),
            "compute_policy_resolution": json_loads(data.get("compute_policy_resolution_json"), {}),
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

    @staticmethod
    def _resolve_enqueue_runtime_profile(runtime_profile: Optional[str]) -> str:
        from api.services.runtime_profile import resolve_user_runtime_profile

        try:
            return resolve_user_runtime_profile(runtime_profile).name
        except ValueError as exc:
            raise WorkbenchError(
                "runtime_profile_invalid",
                "不支持的计算后端。请选择 CUDA 加速或 CPU 兼容。",
                status_code=422,
                details={"runtime_profile": runtime_profile},
            ) from exc

    def _legacy_enqueue_scenario(
        self,
        project_id: str,
        scenario_id: str,
        *,
        retry_of: Optional[str] = None,
        runtime_profile: Optional[str] = None,
    ) -> Dict[str, Any]:
        database = self.project_database(project_id)
        scenario = self._scenario_row(project_id, scenario_id)
        if scenario["archived"]:
            raise WorkbenchError("scenario_archived", "已归档方案不能入队。", status_code=409)
        revision_id = scenario["input_revision_id"]
        if not revision_id:
            if scenario["parameter_template_id"]:
                raise WorkbenchError(
                    "input_revision_required",
                    "结构化方案尚未绑定输入快照。",
                    status_code=422,
                )
            with database.connect() as connection:
                latest = connection.execute(
                    "SELECT * FROM input_revisions WHERE status='ready' ORDER BY created_at DESC LIMIT 1"
                ).fetchone()
                if not latest:
                    raise WorkbenchError(
                        "input_revision_required",
                        "请先上传 DEM 等基础数据并发布输入修订，再加入队列。",
                        status_code=422,
                    )
                revision_id = latest["revision_id"]
                connection.execute(
                    """
                    UPDATE scenarios
                    SET input_revision_id=?, status='ready', updated_at=?
                    WHERE scenario_id=?
                    """,
                    (revision_id, utc_now(), scenario_id),
                )
        else:
            revision = self._revision_row(project_id, str(revision_id))
            if revision["status"] != "ready":
                raise WorkbenchError(
                    "input_revision_invalid",
                    "方案引用的输入修订未通过校验，请补齐 DEM 等基础数据后重新发布。",
                    status_code=409,
                )
        if scenario["parameter_template_id"]:
            validation = self.get_scenario_configuration(project_id, scenario_id)["validation"]
            if not validation["valid"]:
                semantic_gate = validation.get("edda_semantic_gate") or {}
                if semantic_gate.get("decision") == "reject" and semantic_gate.get("code"):
                    raise WorkbenchError(
                        str(semantic_gate["code"]),
                        next(
                            (
                                str(issue.get("message"))
                                for issue in validation.get("issues", [])
                                if issue.get("code") == semantic_gate.get("code")
                            ),
                            "EDDA semantic preflight rejected the scenario.",
                        ),
                        status_code=422,
                        details=validation,
                    )
                raise WorkbenchError(
                    "scenario_configuration_invalid",
                    "方案参数或输入绑定未通过运行预检。",
                    status_code=422,
                    details=validation,
                )
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
                    retry_of, runtime_profile, enqueued_at, started_at, finished_at, progress, summary
                ) VALUES(?, ?, ?, 'queued', NULL, ?, ?, ?, NULL, NULL, 0, '等待调度')
                """,
                (queue_item_id, scenario_id, position, retry_of, self._resolve_enqueue_runtime_profile(runtime_profile), now),
            )
            connection.execute(
                "UPDATE scenarios SET status='queued', updated_at=? WHERE scenario_id=?",
                (now, scenario_id),
            )
        return self._public_queue_item(project_id, self._queue_row(project_id, queue_item_id))

    def enqueue_scenario(
        self,
        project_id: str,
        scenario_id: str,
        *,
        retry_of: Optional[str] = None,
        snapshot_revision_id: Optional[str] = None,
        runtime_profile: Optional[str] = None,
        frozen_effective_config: Optional[Mapping[str, Any]] = None,
        frozen_compute_policy_resolution: Optional[Mapping[str, Any]] = None,
        frozen_scenario_version: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Queue a draft and freeze its compute policy at enqueue time."""
        from api.services.structured_input_resolver import validate_scenario_configuration

        has_frozen_policy = (
            isinstance(frozen_effective_config, Mapping)
            and bool(frozen_effective_config)
            and isinstance(frozen_compute_policy_resolution, Mapping)
            and bool(frozen_compute_policy_resolution)
        )
        # Settings are a sparse global override map.  Read them exactly once
        # for a new enqueue operation and carry that immutable snapshot through
        # preview, validation, and the queue INSERT.  Retry paths already carry
        # their original frozen policy and intentionally do not read Settings.
        enqueue_global_gates = None if has_frozen_policy else self.get_compute_gate_values()
        if has_frozen_policy:
            raw_scenario = self._scenario_row(project_id, scenario_id)
            scenario = {
                "scenario_id": str(raw_scenario["scenario_id"]),
                "status": raw_scenario["status"],
                "input_revision_id": raw_scenario["input_revision_id"],
                "binding_state": "runtime_snapshot" if raw_scenario["input_revision_id"] else "draft",
                "effective_parameters": dict(frozen_effective_config or {}),
                "compute_policy_resolution": dict(frozen_compute_policy_resolution or {}),
            }
        else:
            scenario = self._public_scenario(
                project_id,
                self._scenario_row(project_id, scenario_id),
                global_gates=enqueue_global_gates,
            )
        if scenario["status"] == "archived":
            raise WorkbenchError("scenario_archived", "Archived scenarios cannot be queued.", status_code=409)
        frozen_revision_id = snapshot_revision_id
        if frozen_revision_id is None and scenario.get("binding_state") == "runtime_snapshot":
            frozen_revision_id = scenario.get("input_revision_id")
        if frozen_revision_id:
            revision = self._revision_row(project_id, str(frozen_revision_id))
            if revision["status"] != "ready":
                raise WorkbenchError("input_revision_invalid", "The frozen input snapshot is invalid.", status_code=409)

        queue_effective = dict(frozen_effective_config or scenario.get("effective_parameters") or {})
        queue_resolution = dict(
            frozen_compute_policy_resolution
            or scenario.get("compute_policy_resolution")
            or {}
        )
        if frozen_effective_config is None or frozen_compute_policy_resolution is None:
            database = self.project_database(project_id)
            with database.connect() as connection:
                current_for_snapshot = connection.execute(
                    "SELECT * FROM scenarios WHERE scenario_id=?", (scenario_id,)
                ).fetchone()
                if current_for_snapshot:
                    snapshot = self._scenario_compute_snapshot(
                        connection,
                        current_for_snapshot,
                        global_gates=enqueue_global_gates,
                    )
                    queue_effective = dict(snapshot.effective_parameters)
                    queue_resolution = dict(snapshot.resolution)
        if str(queue_resolution.get("status") or "resolved") != "resolved":
            issue = queue_resolution.get("blocking_issue") or {}
            raise WorkbenchError(
                str(issue.get("code") or "compute_policy_resolution_blocked"),
                str(issue.get("message") or "失稳源策略未完成严格解析，不能入队。"),
                status_code=422,
                details=queue_resolution,
            )
        if frozen_revision_id:
            revision_manifest = json_loads(revision["manifest_json"], [])
            validation = validate_scenario_configuration(queue_effective, revision_manifest)
            if not validation["valid"]:
                raise WorkbenchError(
                    "scenario_configuration_invalid",
                    "冻结参数或输入修订未通过运行预检。",
                    status_code=422,
                    details=validation,
                )

        database = self.project_database(project_id)
        with database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute("SELECT * FROM scenarios WHERE scenario_id=?", (scenario_id,)).fetchone()
            if not current:
                raise WorkbenchError("scenario_not_found", "Scenario does not exist.", status_code=404)
            duplicate = connection.execute(
                """
                SELECT queue_item_id FROM queue_items
                WHERE scenario_id=? AND status IN ('queued', 'starting', 'running', 'stopping')
                """,
                (scenario_id,),
            ).fetchone()
            if duplicate:
                raise WorkbenchError("scenario_already_queued", "Scenario is already queued.", status_code=409)
            if frozen_revision_id is None:
                draft_bindings = self._bindings_for_draft_connection(connection, scenario_id)
                try:
                    bindings, snapshot_manifest = self._resolve_binding_assets(connection, draft_bindings)
                    validation = validate_scenario_configuration(queue_effective, snapshot_manifest)
                except WorkbenchError:
                    raise
                if not validation["valid"]:
                    raise WorkbenchError(
                        "scenario_configuration_invalid",
                        "Draft parameters or input bindings did not pass the run preflight.",
                        status_code=422,
                        details=validation,
                    )
                frozen_revision_id, revision_status, _, _ = self._insert_input_revision(
                    connection,
                    bindings=bindings,
                    manifest=snapshot_manifest,
                    parent_revision_id=None,
                    version_tag=None,
                )
                if revision_status != "ready":
                    raise WorkbenchError(
                        "input_revision_invalid",
                        "The input snapshot could not be frozen.",
                        status_code=409,
                    )
            position = connection.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM queue_items").fetchone()[0]
            queue_item_id = f"que-{uuid4().hex}"
            now = utc_now()
            profile_name = self._resolve_enqueue_runtime_profile(runtime_profile)
            connection.execute(
                """
                INSERT INTO queue_items(
                    queue_item_id, scenario_id, scenario_version, input_revision_id,
                    position, status, simulation_id, retry_of, runtime_profile,
                    effective_config_json, compute_policy_resolution_json, enqueued_at,
                    started_at, finished_at, progress, summary, cancel_reason
                ) VALUES(?, ?, ?, ?, ?, 'queued', NULL, ?, ?, ?, ?, ?, NULL, NULL, 0, 'Draft input and compute policy preflight passed.', NULL)
                """,
                (
                    queue_item_id,
                    scenario_id,
                    int(frozen_scenario_version if frozen_scenario_version is not None else current["version"] or 1),
                    frozen_revision_id,
                    position,
                    retry_of,
                    profile_name,
                    json.dumps(queue_effective, ensure_ascii=False),
                    json.dumps(queue_resolution, ensure_ascii=False),
                    now,
                ),
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

    def _legacy_retry_queue_item(self, project_id: str, queue_item_id: str) -> Dict[str, Any]:
        row = self._queue_row(project_id, queue_item_id)
        if row["status"] not in {"cancelled", "failed", "interrupted", "stopped"}:
            raise WorkbenchError("queue_item_not_retryable", "该队列项当前不能重试。", status_code=409)
        return self.enqueue_scenario(
            project_id,
            str(row["scenario_id"]),
            retry_of=queue_item_id,
        )

    def retry_queue_item(self, project_id: str, queue_item_id: str) -> Dict[str, Any]:
        row = self._queue_row(project_id, queue_item_id)
        if row["status"] not in {"cancelled", "failed", "interrupted", "stopped"}:
            raise WorkbenchError("queue_item_not_retryable", "Queue item cannot be retried in its current state.", status_code=409)
        if (
            "effective_config_json" not in row.keys()
            or "compute_policy_resolution_json" not in row.keys()
            or not json_loads(row["effective_config_json"], {})
            or not json_loads(row["compute_policy_resolution_json"], {})
        ):
            database = self.project_database(project_id)
            with database.connect() as connection:
                connection.execute(
                    """
                    UPDATE queue_items
                    SET cancel_reason='policy_snapshot_missing_after_upgrade',
                        summary='缺少升级后的计算策略快照，请重新加入队列。'
                    WHERE queue_item_id=?
                    """,
                    (queue_item_id,),
                )
            raise WorkbenchError(
                "policy_snapshot_missing_after_upgrade",
                "该旧队列项没有冻结的计算策略快照，请重新加入队列。",
                status_code=409,
            )
        return self.enqueue_scenario(
            project_id,
            str(row["scenario_id"]),
            retry_of=queue_item_id,
            snapshot_revision_id=row["input_revision_id"],
            runtime_profile=row["runtime_profile"] if "runtime_profile" in row.keys() else None,
            frozen_effective_config=json_loads(row["effective_config_json"], {})
            if "effective_config_json" in row.keys() and row["effective_config_json"]
            else None,
            frozen_compute_policy_resolution=json_loads(row["compute_policy_resolution_json"], {})
            if "compute_policy_resolution_json" in row.keys() and row["compute_policy_resolution_json"]
            else None,
            frozen_scenario_version=(
                int(row["scenario_version"])
                if "scenario_version" in row.keys() and row["scenario_version"] is not None
                else None
            ),
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
                candidate["runtime_profile"] = str(row["runtime_profile"] or "cuda_production_default") if "runtime_profile" in row.keys() else "cuda_production_default"
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

    # workbench upload family -> EDDA native input family key
    WORKBENCH_TO_NATIVE_FAMILY = {
        "manning": "manningfil",
        "slope": "slofil",
        "thickness": "zfil",
        "trigger": "triggerslide",
        "groundwater": "depfil",
        "infiltration": "rizerofil",
        "rainfall": "rifil",
        "zones": "zonfil",
        "soil": "zonfil",
        "dem": "demfil",
        "outflow": "outflow.txt",
        "inflow": "inflow.txt",
        "monitoring": "hydrograph.txt",
        "drainage": "drainage.txt",
        "swmm": "swmm.txt",
        # already-native aliases
        "manningfil": "manningfil",
        "slofil": "slofil",
        "zfil": "zfil",
        "triggerslide": "triggerslide",
        "depfil": "depfil",
        "rizerofil": "rizerofil",
        "rifil": "rifil",
        "zonfil": "zonfil",
        "demfil": "demfil",
    }

    def _resolve_case_base_dir(self, project: Dict[str, Any], manifest: list[Dict[str, Any]], config: Optional[Dict[str, Any]]) -> Optional[str]:
        """Prefer project root so relative edda_in paths (Data\\rainfall\\...) resolve correctly."""
        for entry in manifest:
            explicit = entry.get("reference_base_dir")
            if explicit:
                return str(explicit)
        root = project.get("root_path")
        if root:
            return str(root)
        if config and config.get("blob_path"):
            return str(Path(config["blob_path"]).parent)
        return None

    def _map_case_input_files(self, by_family: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
        """Map workbench families onto native EDDA keys for runtime_session consumption."""
        skip_top_level = {"dem", "boundary", "config"}
        case_input_files: Dict[str, str] = {}
        for family, entry in by_family.items():
            if family in skip_top_level:
                continue
            blob = entry.get("blob_path")
            if not blob:
                continue
            native = self.WORKBENCH_TO_NATIVE_FAMILY.get(family, family)
            case_input_files[native] = str(blob)
        return case_input_files

    def _build_claim_runtime_payload(
        self,
        *,
        project_id: str,
        project: Dict[str, Any],
        queue_item_id: str,
        simulation_id: str,
        scenario: sqlite3.Row | Dict[str, Any],
        output_dir: str,
        manifest: list[Dict[str, Any]],
        runtime_profile: Optional[str] = None,
    ) -> Dict[str, Any]:
        from api.services.structured_input_resolver import (
            _rainfall_is_active,
            build_structured_rainfall_payload,
        )

        scenario_dict = dict(scenario)
        stored_effective = json_loads(scenario_dict.get("effective_parameters_json"), {})
        frozen_effective = scenario_dict.pop("_frozen_effective_parameters", None)
        frozen_resolution = scenario_dict.pop("_frozen_compute_policy_resolution", None)
        if frozen_effective is None or frozen_resolution is None:
            queue_row = self._queue_row(project_id, queue_item_id)
            if "effective_config_json" in queue_row.keys() and queue_row["effective_config_json"]:
                frozen_effective = json_loads(queue_row["effective_config_json"], {})
            if "compute_policy_resolution_json" in queue_row.keys() and queue_row["compute_policy_resolution_json"]:
                frozen_resolution = json_loads(queue_row["compute_policy_resolution_json"], {})
        if scenario_dict.get("parameter_template_id") and (
            not isinstance(frozen_effective, dict)
            or not frozen_effective
            or not isinstance(frozen_resolution, dict)
            or not frozen_resolution
        ):
            raise WorkbenchError(
                "policy_snapshot_missing_after_upgrade",
                "该队列项没有冻结的计算策略快照，不能启动运行。",
                status_code=409,
            )
        effective_parameters = (
            dict(frozen_effective)
            if isinstance(frozen_effective, dict) and frozen_effective
            else stored_effective
        )
        compute_policy_resolution = (
            dict(frozen_resolution)
            if isinstance(frozen_resolution, dict)
            else {}
        )
        profile_name = str(runtime_profile or "cuda_production_default")
        template_metadata: Dict[str, Any] = {}
        if scenario_dict.get("parameter_template_id"):
            database = self.project_database(project_id)
            with database.connect() as connection:
                template_metadata = self._parameter_template_metadata(
                    connection,
                    str(scenario_dict["parameter_template_id"]),
                )
        reference_case_owned = self._reference_case_owned(template_metadata)
        if scenario_dict.get("parameter_template_id"):
            active_manifest = [dict(entry) for entry in manifest if bool(entry.get("active", True))]
            if str(effective_parameters.get("manning.source") or "global").lower() in {"global", "global_manning", "global_initiation_manning"}:
                active_manifest = [entry for entry in active_manifest if str(entry.get("binding_key")) != "manning.raster"]
            by_binding = {str(entry.get("binding_key") or ""): entry for entry in active_manifest}
            dem = by_binding.get("dem.primary")
            soil = by_binding.get("zones.primary") or by_binding.get("soil.primary")
            boundary = by_binding.get("boundary.primary")
            config = by_binding.get("legacy.config")
            if reference_case_owned and not (config and config.get("blob_path")):
                raise WorkbenchError(
                    "reference_case_config_missing",
                    "参考案例缺少冻结的 edda_in 配置，不能退回通用参数模板运行。",
                    status_code=409,
                )
            case_input_files = {}
            for entry in active_manifest:
                family = str(entry.get("family") or "")
                if family in {"dem", "demfil", "rainfall", "rifil", "config", "zones", "zonfil", "soil", "boundary"}:
                    continue
                blob = entry.get("blob_path")
                if blob:
                    case_input_files[self.WORKBENCH_TO_NATIVE_FAMILY.get(family, family)] = str(blob)
            overrides = self._expand_dotted_values(effective_parameters)
            overrides.pop("rainfall", None)
            overrides.pop("manning", None)
            if _rainfall_is_active(effective_parameters):
                try:
                    overrides["structured_rainfall"] = build_structured_rainfall_payload(
                        effective_parameters,
                        active_manifest,
                    )
                except ValueError as exc:
                    raise WorkbenchError(
                        "scenario_configuration_invalid",
                        str(exc),
                        status_code=422,
                    ) from exc
            return {
                "project_id": project_id,
                "project_root": str(project["root_path"]),
                "queue_item_id": queue_item_id,
                "simulation_id": simulation_id,
                "scenario_id": scenario_dict["scenario_id"],
                "scenario_name": scenario_dict["name"],
                "runtime_profile": profile_name,
                "output_dir": output_dir,
                "dem_file": str(dem["blob_path"]) if dem else None,
                "rainfall_file": None,
                "soil_zones_file": str(soil["blob_path"]) if soil else None,
                "boundary_file": str(boundary["blob_path"]) if boundary else None,
                # Reference-owned imports must traverse the original edda_in
                # mapper.  Their editable template is a UI projection, not a
                # replacement for unexposed EDDA controls and numeric variants.
                "case_config_file": str(config["blob_path"]) if reference_case_owned else None,
                "case_base_dir": self._resolve_case_base_dir(project, active_manifest, config)
                if reference_case_owned
                else None,
                "case_input_files": case_input_files,
                "overrides": overrides,
                "effective_config": effective_parameters,
                "compute_policy_resolution": compute_policy_resolution,
            }
        # Read-only compatibility adapter for pre-v3 revisions. Structured
        # scenarios above never collapse repeated families into one asset.
        effective_parameters = stored_effective
        legacy_by_family = {str(entry["family"]): dict(entry) for entry in manifest}
        case_input_files = self._map_case_input_files(legacy_by_family)
        dem = legacy_by_family.get("dem")
        rainfall = legacy_by_family.get("rainfall")
        soil = legacy_by_family.get("soil") or legacy_by_family.get("zones")
        boundary = legacy_by_family.get("boundary")
        config = legacy_by_family.get("config")
        return {
            "project_id": project_id,
            "project_root": str(project["root_path"]),
            "queue_item_id": queue_item_id,
            "simulation_id": simulation_id,
            "scenario_id": scenario_dict["scenario_id"],
            "scenario_name": scenario_dict["name"],
            "runtime_profile": profile_name,
            "output_dir": output_dir,
            "dem_file": str(dem["blob_path"]) if dem else None,
            "rainfall_file": str(rainfall["blob_path"]) if rainfall else None,
            "soil_zones_file": str(soil["blob_path"]) if soil else None,
            "boundary_file": str(boundary["blob_path"]) if boundary else None,
            "case_config_file": str(config["blob_path"]) if config else None,
            "case_base_dir": self._resolve_case_base_dir(project, manifest, config),
            "case_input_files": case_input_files,
            "overrides": self._expand_dotted_values(effective_parameters),
            "effective_config": effective_parameters,
            "compute_policy_resolution": compute_policy_resolution,
        }

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
        project = self.get_project(project_id)
        return self._build_claim_runtime_payload(
            project_id=project_id,
            project=project,
            queue_item_id=queue_item_id,
            simulation_id=simulation_id,
            scenario=scenario,
            output_dir=output_dir,
            manifest=manifest,
        )

    def update_run(self, project_id: str, simulation_id: str, values: Dict[str, Any]) -> None:
        database = self.project_database(project_id)
        normalized_values = dict(values)
        if "error_details" in normalized_values:
            normalized_values["error_details_json"] = json.dumps(
                normalized_values.pop("error_details") or {},
                ensure_ascii=False,
                default=str,
            )
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
            "error_code",
            "error_details_json",
            "elapsed_seconds",
            "runtime_profile_json",
            "effective_config_json",
            "resource_summary_json",
            "terminal_log_json",
        }
        fields = [(key, value) for key, value in normalized_values.items() if key in allowed]
        if not fields:
            return
        assignments = ", ".join(f"{key}=?" for key, _ in fields)
        params = [value for _, value in fields] + [simulation_id]
        with database.connect() as connection:
            connection.execute(f"UPDATE simulation_runs SET {assignments} WHERE simulation_id=?", params)
            status = normalized_values.get("status")
            if status in {"running", "starting", "stopping"}:
                connection.execute(
                    "UPDATE queue_items SET status=?, progress=?, summary=? WHERE simulation_id=?",
                    (
                        status,
                        float(normalized_values.get("progress") or 0),
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
                    error_code=?, error_details_json=?, resource_summary_json=?,
                    elapsed_seconds=? WHERE simulation_id=?
                """,
                (
                    status,
                    float(result.get("progress") if result.get("progress") is not None else (100.0 if status == "completed" else 0.0)),
                    now,
                    result.get("error"),
                    result.get("error_code"),
                    json.dumps(result.get("error_details") or {}, ensure_ascii=False, default=str),
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
        resolution = json_loads(data.get("compute_policy_resolution_json"), {})
        if not resolution:
            from api.services.compute_policy_resolver import legacy_unrecorded_compute_policy_resolution

            resolution = legacy_unrecorded_compute_policy_resolution()
        return {
            "simulation_id": data["simulation_id"],
            "project_id": project_id,
            "scenario_id": data["scenario_id"],
            "input_revision_id": data.get("input_revision_id"),
            "status": data["status"],
            "progress": float(data["progress"]),
            "current_time": float(data["current_time"]),
            "end_time": float(data["end_time"]),
            "step_count": int(data["step_count"]),
            "output_count": int(data["output_count"]),
            "start_time": data.get("start_time"),
            "end_time_actual": data.get("end_time_actual"),
            "error": data.get("error"),
            "error_code": data.get("error_code"),
            "error_details": json_loads(data.get("error_details_json"), {}),
            "elapsed_seconds": float(data["elapsed_seconds"]),
            "output_dir": data.get("output_dir"),
            "effective_config": json_loads(data.get("effective_config_json"), {}),
            "compute_policy_resolution": resolution,
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


def _legacy_claim_queue_item_without_fk_race(self: WorkbenchStore, project_id: str, queue_item_id: str) -> Dict[str, Any]:
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
    scenario_id = str(scenario["scenario_id"])
    work_dir = self.ensure_scenario_workspace(project_id, scenario_id)
    output_dir = str(work_dir / "outputs" / simulation_id)
    Path(output_dir).mkdir(parents=True, exist_ok=True)
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
    return self._build_claim_runtime_payload(
        project_id=project_id,
        project=project,
        queue_item_id=queue_item_id,
        simulation_id=simulation_id,
        scenario=scenario,
        output_dir=output_dir,
        manifest=manifest,
    )


def _claim_queue_item_without_fk_race(self: WorkbenchStore, project_id: str, queue_item_id: str) -> Dict[str, Any]:
    """Freeze a draft exactly when it crosses from queued to starting."""
    from api.services.structured_input_resolver import validate_scenario_configuration

    database = self.project_database(project_id)
    project = self.get_project(project_id)
    simulation_id = f"sim-{uuid4().hex}"
    now = utc_now()
    failure: Optional[WorkbenchError] = None
    payload_scenario: Optional[Dict[str, Any]] = None
    snapshot_manifest: list[Dict[str, Any]] = []
    output_dir = ""
    with database.connect() as connection:
        # Asset deletion obtains the same lock, which makes start-vs-delete
        # deterministic: either deletion cancels the queue first, or a frozen
        # run snapshot is present and deletion receives a 409 lock response.
        connection.execute("BEGIN IMMEDIATE")
        item = connection.execute(
            "SELECT * FROM queue_items WHERE queue_item_id=?", (queue_item_id,)
        ).fetchone()
        if not item or item["status"] != "queued":
            raise WorkbenchError("queue_item_not_claimable", "Queue item is no longer queued.", status_code=409)
        queue_effective = json_loads(item["effective_config_json"], {}) if "effective_config_json" in item.keys() else {}
        queue_resolution = (
            json_loads(item["compute_policy_resolution_json"], {})
            if "compute_policy_resolution_json" in item.keys()
            else {}
        )
        if not isinstance(queue_effective, dict) or not queue_effective or not isinstance(queue_resolution, dict) or not queue_resolution:
            failure = WorkbenchError(
                "policy_snapshot_missing_after_upgrade",
                "该旧队列项没有冻结的计算策略快照，请重新入队。",
                status_code=409,
            )
        elif str(queue_resolution.get("status") or "resolved") != "resolved":
            issue = queue_resolution.get("blocking_issue") or {}
            failure = WorkbenchError(
                str(issue.get("code") or "compute_policy_resolution_blocked"),
                str(issue.get("message") or "冻结的失稳源策略未通过运行预检。"),
                status_code=422,
                details=queue_resolution,
            )
        scenario = connection.execute(
            "SELECT * FROM scenarios WHERE scenario_id=?", (item["scenario_id"],)
        ).fetchone()
        if failure is not None:
            pass
        elif not scenario:
            failure = WorkbenchError("scenario_not_found", "Scenario does not exist.", status_code=404)
        else:
            queued_version = item["scenario_version"]
            current_version = scenario["version"]
            if (
                queued_version is not None
                and current_version is not None
                and int(queued_version) != int(current_version)
            ):
                failure = WorkbenchError(
                    "queue_item_draft_changed",
                    "Draft changed while waiting; the queue item was cancelled.",
                    status_code=409,
                    details={"queued_version": queued_version, "current_version": current_version},
                )
            else:
                revision_id = item["input_revision_id"]
            if failure is None and revision_id:
                revision = connection.execute(
                    "SELECT * FROM input_revisions WHERE revision_id=?", (revision_id,)
                ).fetchone()
                if not revision or revision["status"] != "ready":
                    failure = WorkbenchError(
                        "input_revision_invalid",
                        "The frozen input snapshot is invalid.",
                        status_code=409,
                    )
                else:
                    snapshot_manifest = json_loads(revision["manifest_json"], [])
                    validation = validate_scenario_configuration(queue_effective, snapshot_manifest)
                    if not validation["valid"]:
                        failure = WorkbenchError(
                            "scenario_configuration_invalid",
                            "冻结参数或输入修订未通过运行预检。",
                            status_code=422,
                            details=validation,
                        )
            elif failure is None and item["scenario_version"] is not None and int(item["scenario_version"]) != int(scenario["version"] or 1):
                failure = WorkbenchError(
                    "queue_item_draft_changed",
                    "Draft changed while waiting; the queue item was cancelled.",
                    status_code=409,
                    details={"queued_version": item["scenario_version"], "current_version": scenario["version"]},
                )
            elif failure is None:
                draft_bindings = self._bindings_for_draft_connection(connection, str(scenario["scenario_id"]))
                try:
                    bindings, snapshot_manifest = self._resolve_binding_assets(connection, draft_bindings)
                    validation = validate_scenario_configuration(
                        queue_effective,
                        snapshot_manifest,
                    )
                except WorkbenchError as exc:
                    failure = exc
                else:
                    if not validation["valid"]:
                        failure = WorkbenchError(
                            "scenario_configuration_invalid",
                            "Draft parameters or input bindings did not pass the run preflight.",
                            status_code=422,
                            details=validation,
                        )
                    else:
                        revision_id, revision_status, _, _ = self._insert_input_revision(
                            connection,
                            bindings=bindings,
                            manifest=snapshot_manifest,
                            parent_revision_id=None,
                            version_tag=None,
                        )
                        if revision_status != "ready":
                            failure = WorkbenchError(
                                "input_revision_invalid",
                                "The runtime input snapshot is invalid.",
                                status_code=409,
                            )
            if failure is None and scenario is not None:
                scenario_id = str(scenario["scenario_id"])
                work_dir = database.scenario_dir(scenario_id)
                output_dir = str(work_dir / "outputs" / simulation_id)
                Path(output_dir).mkdir(parents=True, exist_ok=True)
                profile_name = str(item["runtime_profile"] or "cuda_production_default") if "runtime_profile" in item.keys() else "cuda_production_default"
                connection.execute(
                    """
                    UPDATE queue_items
                    SET status='starting', started_at=?, summary='Runtime input snapshot frozen.'
                    WHERE queue_item_id=? AND status='queued'
                    """,
                    (now, queue_item_id),
                )
                connection.execute(
                    """
                    INSERT INTO simulation_runs(
                        simulation_id, scenario_id, input_revision_id, status, progress, current_time, end_time,
                        step_count, output_count, start_time, end_time_actual, error,
                        elapsed_seconds, output_dir, runtime_profile_json,
                        effective_config_json, compute_policy_resolution_json,
                        resource_summary_json, terminal_log_json, created_at
                    ) VALUES(?, ?, ?, 'starting', 0, 0, 0, 0, 0, ?, NULL, NULL, 0, ?, ?, ?, ?, '{}', '[]', ?)
                    """,
                    (
                        simulation_id,
                        scenario_id,
                        revision_id,
                        now,
                        output_dir,
                        json.dumps({"name": profile_name}),
                        json.dumps(queue_effective, ensure_ascii=False),
                        json.dumps(queue_resolution, ensure_ascii=False),
                        now,
                    ),
                )
                connection.execute(
                    """
                    UPDATE queue_items
                    SET simulation_id=?, input_revision_id=?
                    WHERE queue_item_id=?
                    """,
                    (simulation_id, revision_id, queue_item_id),
                )
                connection.execute(
                    """
                    UPDATE scenarios
                    SET input_revision_id=?, latest_simulation_id=?, status='running', updated_at=?
                    WHERE scenario_id=?
                    """,
                    (revision_id, simulation_id, now, scenario_id),
                )
                payload_scenario = dict(scenario)
                payload_scenario["input_revision_id"] = revision_id
                payload_scenario["effective_parameters_json"] = json.dumps(queue_effective, ensure_ascii=False)
                payload_scenario["_frozen_effective_parameters"] = queue_effective
                payload_scenario["_frozen_compute_policy_resolution"] = queue_resolution
                payload_scenario["_runtime_profile"] = profile_name
        if failure is not None and item:
            connection.execute(
                """
                UPDATE queue_items
                SET status='cancelled', finished_at=?, summary=?, cancel_reason=?
                WHERE queue_item_id=? AND status='queued'
                """,
                (
                    now,
                    failure.message,
                    (
                        "draft_changed"
                        if failure.code == "queue_item_draft_changed"
                        else "policy_snapshot_missing_after_upgrade"
                        if failure.code == "policy_snapshot_missing_after_upgrade"
                        else "preflight_failed"
                    ),
                    queue_item_id,
                ),
            )
            if scenario:
                connection.execute(
                    "UPDATE scenarios SET status='draft', updated_at=? WHERE scenario_id=?",
                    (now, scenario["scenario_id"]),
                )
    if failure is not None:
        raise failure
    if payload_scenario is None:
        raise WorkbenchError("queue_item_not_claimable", "Queue item could not be claimed.", status_code=409)
    self.ensure_scenario_workspace(
        project_id,
        str(payload_scenario["scenario_id"]),
        name=str(payload_scenario["name"]),
        effective_parameters=json_loads(payload_scenario["effective_parameters_json"], {}),
    )
    return self._build_claim_runtime_payload(
        project_id=project_id,
        project=project,
        queue_item_id=queue_item_id,
        simulation_id=simulation_id,
        scenario=payload_scenario,
        output_dir=output_dir,
        manifest=snapshot_manifest,
        runtime_profile=str(payload_scenario.pop("_runtime_profile", None) or "cuda_production_default"),
    )


# Keep the public method name stable while using the FK-safe implementation.
WorkbenchStore.claim_queue_item = _claim_queue_item_without_fk_race


def json_loads(value: Optional[str], fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback
