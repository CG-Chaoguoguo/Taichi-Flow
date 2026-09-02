"""Capture immutable pre-run provenance for the local Chamoli validation project.

This helper only reads the repository and the original reference-case inputs. It
writes one JSON record beneath the caller-supplied isolated project root.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ACTIVE_INPUTS = (
    "edda_in.txt",
    "data/tutorial/dem.asc",
    "data/tutorial/slope.asc",
    "data/tutorial/zones.asc",
    "data/tutorial/glacier.asc",
    "data/tutorial/landslide.asc",
    "inflow.txt",
    "outflow.txt",
)
PRODUCTION_ROOTS = ("api", "edda", "frontend/taichi-flow/src")


def _run(command: list[str], *, cwd: Path) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def _run_bytes(command: list[str], *, cwd: Path) -> dict[str, Any]:
    """Run commands whose output is evidence and may not be text (git --binary)."""
    completed = subprocess.run(command, cwd=cwd, capture_output=True, check=False)
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr.decode("utf-8", errors="replace").strip(),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _command_text(command: list[str], *, cwd: Path) -> str | None:
    result = _run(command, cwd=cwd)
    return result["stdout"] if result["returncode"] == 0 else None


def _untracked_production_files(repo_root: Path) -> list[dict[str, str]]:
    result = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        return []
    entries: list[dict[str, str]] = []
    for encoded in result.stdout.split(b"\0"):
        if not encoded:
            continue
        relative = encoded.decode("utf-8", errors="surrogateescape").replace("\\", "/")
        if not any(relative == root or relative.startswith(f"{root}/") for root in PRODUCTION_ROOTS):
            continue
        path = repo_root / relative
        if path.is_file():
            entries.append({"path": relative, "sha256": _sha256_file(path)})
    return sorted(entries, key=lambda item: item["path"])


def _gpu_probe(repo_root: Path) -> dict[str, Any]:
    return _run(
        [
            "nvidia-smi",
            "--query-gpu=name,driver_version,memory.total",
            "--format=csv,noheader",
        ],
        cwd=repo_root,
    )


def _nvidia_smi_banner(repo_root: Path) -> dict[str, Any]:
    """Keep the driver-reported CUDA compatibility version with the GPU probe."""
    return _run(["nvidia-smi"], cwd=repo_root)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--full-scenario-id", required=True)
    parser.add_argument("--qualification-scenario-id", required=True)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    project_root = args.project_root.resolve()
    source_root = args.source_root.resolve()
    if not project_root.is_dir():
        raise SystemExit(f"Project root does not exist: {project_root}")
    if not source_root.is_dir():
        raise SystemExit(f"Source root does not exist: {source_root}")

    inputs: list[dict[str, Any]] = []
    for relative in ACTIVE_INPUTS:
        path = source_root / relative
        if not path.is_file():
            raise SystemExit(f"Active input missing: {path}")
        inputs.append(
            {
                "relative_path": relative,
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )

    git_diff = _run_bytes(["git", "diff", "--binary", "--", *PRODUCTION_ROOTS], cwd=repo_root)
    taichi_version: str | None
    try:
        import taichi  # type: ignore

        taichi_version = str(taichi.__version__)
    except Exception as error:  # pragma: no cover - provenance must still be written
        taichi_version = f"unavailable: {type(error).__name__}: {error}"

    payload = {
        "schema_version": 1,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "repository": {
            "root": str(repo_root),
            "head": _command_text(["git", "rev-parse", "HEAD"], cwd=repo_root),
            "branch": _command_text(["git", "branch", "--show-current"], cwd=repo_root),
            "production_diff_sha256": hashlib.sha256(git_diff["stdout"]).hexdigest(),
            "production_diff_command": git_diff["command"],
            "production_diff_returncode": git_diff["returncode"],
            "untracked_production_files": _untracked_production_files(repo_root),
        },
        "runtime": {
            "python": sys.version,
            "python_executable": sys.executable,
            "taichi_version": taichi_version,
            "node_version": _command_text(["node", "--version"], cwd=repo_root),
            "platform": platform.platform(),
            "gpu_probe": _gpu_probe(repo_root),
            "nvidia_smi_banner": _nvidia_smi_banner(repo_root),
            "project_disk_usage": {
                "total_bytes": shutil.disk_usage(project_root).total,
                "free_bytes": shutil.disk_usage(project_root).free,
            },
        },
        "ui_import": {
            "project_id": args.project_id,
            "full_scenario_id": args.full_scenario_id,
            "qualification_scenario_id": args.qualification_scenario_id,
            "project_root": str(project_root),
            "source_root_read_only": str(source_root),
            "active_inputs": inputs,
        },
    }
    audit_dir = project_root / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    output = audit_dir / "run_provenance.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
