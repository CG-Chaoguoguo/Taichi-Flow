"""Result indexing, safe downloads, and asynchronous export jobs."""
from __future__ import annotations

from datetime import datetime, timezone
import csv
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import zipfile
from typing import Any, Dict, Iterable, Optional
from uuid import uuid4

from api.services.result_files import classify_result_family, is_result_file, taichi_result_name, edda_source_name
from api.services.workbench_store import ProjectDatabase, WorkbenchError, WorkbenchStore, json_loads, utc_now


def _safe_relative(value: str) -> PurePosixPath:
    candidate = PurePosixPath(str(value).replace("\\", "/"))
    if candidate.is_absolute() or not candidate.parts or any(part in {"", ".", ".."} for part in candidate.parts):
        raise WorkbenchError("invalid_result_path", "Result path is outside the simulation output.", status_code=422)
    return candidate


def simulation_output_dir(store: WorkbenchStore, project_id: str, simulation_id: str) -> Path:
    project = store.get_project(project_id)
    row = store.simulation_row(project_id, simulation_id)
    root = Path(project["root_path"]).resolve()
    output = Path(str(row["output_dir"])).expanduser().resolve()
    try:
        output.relative_to(root)
    except ValueError as exc:
        raise WorkbenchError("invalid_output_path", "Simulation output is outside the project root.", status_code=409) from exc
    scenario_id = str(row["scenario_id"])
    canonical_new = (root / "scenarios" / scenario_id / "outputs" / simulation_id).resolve()
    canonical_legacy = (root / "outputs" / simulation_id).resolve()
    if output not in {canonical_new, canonical_legacy}:
        raise WorkbenchError("invalid_output_path", "Simulation output path is not canonical.", status_code=409)
    return output


def iter_result_files(output_dir: Path) -> list[Path]:
    if not output_dir.exists():
        return []
    return [
        item
        for item in sorted(output_dir.rglob("*"))
        if item.is_file() and is_result_file(item, item.relative_to(output_dir).as_posix())
    ]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_info(output_dir: Path, path: Path) -> Dict[str, Any]:
    relative = path.relative_to(output_dir).as_posix()
    return {
        "filename": taichi_result_name(relative),
        "source_filename": relative,
        "family": classify_result_family(relative),
        "size": path.stat().st_size,
        "sha256": _sha256(path),
        "media_type": "application/octet-stream",
    }


def index_results(store: WorkbenchStore, project_id: str, simulation_id: str) -> Dict[str, Any]:
    output_dir = simulation_output_dir(store, project_id, simulation_id)
    groups: Dict[str, list[Dict[str, Any]]] = {}
    for path in iter_result_files(output_dir):
        info = _file_info(output_dir, path)
        groups.setdefault(str(info["family"]), []).append(info)
    database = store.project_database(project_id)
    with database.connect() as connection:
        connection.execute("DELETE FROM result_families WHERE simulation_id=?", (simulation_id,))
        for family, files in groups.items():
            connection.execute(
                """
                INSERT INTO result_families(
                    family_id, simulation_id, name, label, file_count, total_size,
                    files_json, metadata_json
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"fam-{simulation_id}-{family}",
                    simulation_id,
                    family,
                    family.replace("_", " "),
                    len(files),
                    sum(int(item["size"]) for item in files),
                    json.dumps(files, ensure_ascii=False),
                    json.dumps({"indexed_at": utc_now()}, ensure_ascii=False),
                ),
            )
    return {
        "simulation_id": simulation_id,
        "families": [
            {
                "name": family,
                "label": family.replace("_", " "),
                "file_count": len(files),
                "total_size": sum(int(item["size"]) for item in files),
                "files": files,
            }
            for family, files in sorted(groups.items())
        ],
        "count": sum(len(files) for files in groups.values()),
    }


def result_index(store: WorkbenchStore, project_id: str, simulation_id: str) -> Dict[str, Any]:
    indexed = index_results(store, project_id, simulation_id)
    indexed["metadata"] = result_metadata(store, project_id, simulation_id)
    return indexed


def resolve_result_file(store: WorkbenchStore, project_id: str, simulation_id: str, filename: str) -> tuple[Path, str]:
    output_dir = simulation_output_dir(store, project_id, simulation_id)
    requested = _safe_relative(filename)
    names = [requested.as_posix()]
    alias = edda_source_name(requested.as_posix())
    if alias != requested.as_posix():
        names.append(alias)
    root = output_dir.resolve()
    for name in names:
        candidate = _safe_relative(name)
        path = output_dir.joinpath(*candidate.parts).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            continue
        if path.is_file() and is_result_file(path, path.relative_to(output_dir).as_posix()):
            return path, PurePosixPath(taichi_result_name(candidate.as_posix())).name
    raise WorkbenchError("result_not_found", "Result file was not found.", status_code=404, details={"filename": filename})


def result_metadata(store: WorkbenchStore, project_id: str, simulation_id: str) -> Dict[str, Any]:
    output_dir = simulation_output_dir(store, project_id, simulation_id)
    payload: Dict[str, Any] = {"simulation_id": simulation_id, "output_dir": str(output_dir)}
    for name in (
        "request_payload.json",
        "job_metadata.json",
        "effective_config.json",
        "runtime_input_manifest.json",
        "runtime_provenance.json",
        "parameter_audit.json",
        "parameter_catalog.json",
        "runmode_capabilities.json",
        "numerical_diagnostics.json",
        "output_manifest.json",
    ):
        path = output_dir / name
        if path.is_file():
            try:
                payload[name.removesuffix(".json")] = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload[name.removesuffix(".json")] = None
    simulation = store.public_simulation(project_id, store.simulation_row(project_id, simulation_id))
    payload["simulation"] = simulation
    payload["effective_parameters"] = json_loads(
        store._scenario_row(project_id, simulation["scenario_id"])["effective_parameters_json"], {}
    )
    return payload


def _manifest_entries(paths: Iterable[tuple[Path, str]]) -> list[Dict[str, Any]]:
    entries = []
    for path, archive_name in paths:
        entries.append({"path": archive_name, "size": path.stat().st_size, "sha256": _sha256(path)})
    return entries


def _set_export_job(store: WorkbenchStore, project_id: str, export_id: str, **values: Any) -> None:
    database = store.project_database(project_id)
    allowed = {"status", "file_count", "total_size", "archive_path", "error", "completed_at"}
    fields = [(key, value) for key, value in values.items() if key in allowed]
    if not fields:
        return
    assignments = ", ".join(f"{key}=?" for key, _ in fields)
    with database.connect() as connection:
        connection.execute(f"UPDATE export_jobs SET {assignments} WHERE export_id=?", [value for _, value in fields] + [export_id])


def create_export_job(store: WorkbenchStore, project_id: str, simulation_id: str, options: Dict[str, Any]) -> Dict[str, Any]:
    simulation = store.public_simulation(project_id, store.simulation_row(project_id, simulation_id))
    if simulation["status"] != "completed":
        raise WorkbenchError("simulation_not_exportable", "Only completed simulations can be exported.", status_code=409)
    scenario_id = simulation["scenario_id"]
    export_id = f"exp-{uuid4().hex}"
    database = store.project_database(project_id)
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO export_jobs(export_id, scenario_id, simulation_id, status, options_json,
                file_count, total_size, archive_path, error, created_at, completed_at)
            VALUES(?, ?, ?, 'queued', ?, 0, 0, NULL, NULL, ?, NULL)
            """,
            (export_id, scenario_id, simulation_id, json.dumps(options, ensure_ascii=False), utc_now()),
        )
    return get_export_job(store, project_id, export_id)


def get_export_job(store: WorkbenchStore, project_id: str, export_id: str) -> Dict[str, Any]:
    database = store.project_database(project_id)
    with database.connect() as connection:
        row = connection.execute("SELECT * FROM export_jobs WHERE export_id=?", (export_id,)).fetchone()
    if not row:
        raise WorkbenchError("export_not_found", "Export job was not found.", status_code=404)
    data = dict(row)
    return {
        "export_id": data["export_id"],
        "project_id": project_id,
        "scenario_id": data["scenario_id"],
        "simulation_id": data["simulation_id"],
        "status": data["status"],
        "options": json_loads(data["options_json"], {}),
        "file_count": int(data["file_count"]),
        "total_size": int(data["total_size"]),
        "archive_path": data.get("archive_path"),
        "error": data.get("error"),
        "created_at": data["created_at"],
        "completed_at": data.get("completed_at"),
    }


def list_export_jobs(store: WorkbenchStore, project_id: str) -> list[Dict[str, Any]]:
    database = store.project_database(project_id)
    with database.connect() as connection:
        rows = connection.execute("SELECT export_id FROM export_jobs ORDER BY created_at DESC, export_id DESC").fetchall()
    return [get_export_job(store, project_id, str(row["export_id"])) for row in rows]


def run_export_job(store: WorkbenchStore, project_id: str, export_id: str) -> Dict[str, Any]:
    job = get_export_job(store, project_id, export_id)
    _set_export_job(store, project_id, export_id, status="running", error=None)
    try:
        output_dir = simulation_output_dir(store, project_id, job["simulation_id"])
        scenario = store._scenario_row(project_id, job["scenario_id"])
        options = job["options"]
        selected_families = {str(value) for value in options.get("families", []) if value}
        selected_names = {str(value).replace("\\", "/") for value in options.get("filenames", []) if value}
        files: list[tuple[Path, str]] = []
        for path in iter_result_files(output_dir):
            relative = path.relative_to(output_dir).as_posix()
            family = classify_result_family(relative)
            if selected_families and family not in selected_families:
                continue
            if selected_names and relative not in selected_names and taichi_result_name(relative) not in selected_names:
                continue
            files.append((path, f"results/{taichi_result_name(relative)}"))

        params = json_loads(scenario["effective_parameters_json"], {})
        params_json = output_dir / "_export_effective_parameters.json"
        params_csv = output_dir / "_export_effective_parameters.csv"
        params_json.write_text(json.dumps(params, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        with params_csv.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["parameter", "value"])
            for key, value in sorted(params.items()):
                writer.writerow([key, json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value])
        files.extend([(params_json, "effective_parameters.json"), (params_csv, "effective_parameters.csv")])
        manifest = _manifest_entries(files)
        manifest_path = output_dir / "_export_manifest.json"
        manifest_path.write_text(json.dumps({"export_id": export_id, "files": manifest}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        files.append((manifest_path, "manifest.json"))

        archive_path = store.project_database(project_id).export_dir / f"{export_id}.zip"
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path, name in files:
                archive.write(path, arcname=name)
        _set_export_job(
            store,
            project_id,
            export_id,
            status="completed",
            file_count=len(files),
            total_size=archive_path.stat().st_size,
            archive_path=str(archive_path),
            completed_at=utc_now(),
        )
        params_json.unlink(missing_ok=True)
        params_csv.unlink(missing_ok=True)
        manifest_path.unlink(missing_ok=True)
        return get_export_job(store, project_id, export_id)
    except Exception as exc:  # noqa: BLE001 - persist export failures
        _set_export_job(store, project_id, export_id, status="failed", error=str(exc), completed_at=utc_now())
        raise


def delete_results(store: WorkbenchStore, project_id: str, simulation_id: str) -> None:
    simulation = store.public_simulation(project_id, store.simulation_row(project_id, simulation_id))
    if simulation["status"] in {"starting", "running", "stopping"}:
        raise WorkbenchError("simulation_active", "Active simulation results cannot be deleted.", status_code=409)
    output_dir = simulation_output_dir(store, project_id, simulation_id)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    database = store.project_database(project_id)
    with database.connect() as connection:
        connection.execute("DELETE FROM result_families WHERE simulation_id=?", (simulation_id,))


__all__ = [
    "create_export_job",
    "delete_results",
    "get_export_job",
    "index_results",
    "iter_result_files",
    "list_export_jobs",
    "result_index",
    "result_metadata",
    "resolve_result_file",
    "run_export_job",
    "simulation_output_dir",
]
