"""Verify the private portable Python against the checked-in runtime lock."""
from __future__ import annotations

import argparse
from collections import defaultdict
from importlib import metadata
import json
from pathlib import Path
import platform
import re
import sys
from typing import Any, Iterable


REPORT_PREFIX = "TAICHI_FLOW_RUNTIME_LOCK="


def canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def read_lock(path: Path) -> dict[str, str]:
    expected: dict[str, str] = {}
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.count("==") != 1:
            raise ValueError(f"Invalid runtime lock entry at line {line_number}: {raw}")
        name, version = (part.strip() for part in line.split("==", 1))
        key = canonical_name(name)
        if not name or not version:
            raise ValueError(f"Invalid runtime lock entry at line {line_number}: {raw}")
        if key in expected:
            raise ValueError(f"Duplicate runtime lock entry: {name}")
        expected[key] = version
    if "python" not in expected:
        raise ValueError("Runtime lock must declare python==<version>")
    return expected


def _distribution_source(distribution: Any) -> str:
    path = getattr(distribution, "_path", None)
    return str(path) if path is not None else "unknown"


def verify_runtime_lock(
    path: Path,
    *,
    python_version: str | None = None,
    distributions: Iterable[Any] | None = None,
) -> dict[str, Any]:
    expected = read_lock(path)
    installed: dict[str, list[dict[str, str]]] = defaultdict(list)
    for distribution in distributions if distributions is not None else metadata.distributions():
        name = distribution.metadata.get("Name")
        if not name:
            continue
        installed[canonical_name(str(name))].append(
            {"version": str(distribution.version), "source": _distribution_source(distribution)}
        )

    entries: list[dict[str, Any]] = []
    errors: list[str] = []
    actual_python = python_version or platform.python_version()
    for name, expected_version in expected.items():
        if name == "python":
            matches = [{"version": actual_python, "source": str(Path(sys.executable).resolve())}]
        else:
            matches = installed.get(name, [])
        actual_versions = sorted({item["version"] for item in matches})
        if not matches:
            status = "missing"
            errors.append(f"{name}: expected {expected_version}, distribution is missing")
        elif len(matches) > 1:
            status = "conflict"
            errors.append(
                f"{name}: expected one {expected_version} distribution, found {len(matches)} metadata records"
            )
        elif matches[0]["version"] != expected_version:
            status = "version_mismatch"
            errors.append(f"{name}: expected {expected_version}, found {matches[0]['version']}")
        else:
            status = "ok"
        entries.append(
            {
                "name": name,
                "expected": expected_version,
                "actual": actual_versions,
                "sources": [item["source"] for item in matches],
                "status": status,
            }
        )
    return {
        "valid": not errors,
        "lock_path": str(path.resolve()),
        "python": actual_python,
        "entries": entries,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", required=True, type=Path)
    args = parser.parse_args()
    try:
        report = verify_runtime_lock(args.lock)
    except Exception as exc:
        report = {
            "valid": False,
            "lock_path": str(args.lock.resolve()),
            "entries": [],
            "errors": [str(exc)],
        }
    print(REPORT_PREFIX + json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
