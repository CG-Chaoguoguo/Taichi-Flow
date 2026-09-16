"""Disjoint pytest node shards with fail-closed execution inventory validation.

Usage: python scripts/edda_audit_ci.py run --index 0 --count 4 --output audit-ci
       python scripts/edda_audit_ci.py verify audit-ci --count 4
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET


def partition(nodeids: list[str], index: int, count: int) -> list[str]:
    if count <= 0 or not 0 <= index < count:
        raise ValueError("Invalid shard index/count")
    if len(set(nodeids)) != len(nodeids):
        raise ValueError("Duplicate pytest node IDs")
    selected = sorted(nodeids)[index::count]
    if not selected:
        raise ValueError("Empty shard: refusing a vacuous pass")
    return selected


def validate_manifests(manifests: list[dict], count: int) -> dict:
    if len(manifests) != count or {m["index"] for m in manifests} != set(range(count)):
        raise ValueError("Missing or duplicate shard inventory")
    ordered = sorted(manifests, key=lambda m: m["index"])
    reference = ordered[0]["all_nodeids"]
    source_sha = ordered[0]["source_sha"]
    if not source_sha or any(m["source_sha"] != source_sha for m in ordered):
        raise ValueError("Mixed source commits")
    all_executed = []
    totals = Counter()
    for m in ordered:
        expected = partition(reference, m["index"], count)
        if m["count"] != count or m["all_nodeids"] != reference or m["selected_nodeids"] != expected:
            raise ValueError("Inconsistent collection or selected shard")
        completed = m["completed_nodeids"]
        if len(completed) != len(set(completed)) or set(completed) != set(expected):
            raise ValueError("Incomplete/duplicate execution: a test shard stopped early")
        if set(m["outcomes"]) != set(expected):
            raise ValueError("Missing test outcomes")
        if set(m["outcomes"].values()) - {"passed", "failed", "skipped", "error"}:
            raise ValueError("Incomplete test outcome")
        all_executed.extend(completed)
        totals.update(m["outcomes"].values())
        if m["exit_code"] != 0:
            raise ValueError(f"Shard {m['index']} failed with exit code {m['exit_code']}")
    if len(set(all_executed)) != len(all_executed) or set(all_executed) != set(reference):
        raise ValueError("Shards are not a disjoint, complete cover")
    if totals["failed"] or totals["error"]:
        raise ValueError("Failed tests cannot pass the inventory gate")
    return {"source_sha": source_sha, "collected": len(reference), "executed": len(all_executed), **totals}


def run(index: int, count: int, output: Path) -> int:
    import pytest

    output.mkdir(parents=True, exist_ok=True)
    # Executing a script sets sys.path to scripts/, not the repository root.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    manifest = {
        "schema": 1, "index": index, "count": count,
        "source_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "all_nodeids": [], "selected_nodeids": [], "completed_nodeids": [], "outcomes": {},
    }

    class Inventory:
        @pytest.hookimpl(trylast=True)
        def pytest_collection_modifyitems(self, config, items):
            all_ids = sorted(item.nodeid for item in items)
            selected = partition(all_ids, index, count)
            chosen = set(selected)
            rejected = [item for item in items if item.nodeid not in chosen]
            items[:] = sorted((item for item in items if item.nodeid in chosen), key=lambda item: item.nodeid)
            manifest.update(all_nodeids=all_ids, selected_nodeids=selected)
            config.hook.pytest_deselected(items=rejected)

        def pytest_runtest_logreport(self, report):
            outcomes = manifest["outcomes"]
            if report.failed:
                outcomes[report.nodeid] = "failed" if report.when == "call" else "error"
            elif outcomes.get(report.nodeid) not in {"failed", "error"}:
                if report.skipped:
                    outcomes[report.nodeid] = "skipped"
                elif report.when == "call":
                    outcomes[report.nodeid] = "passed"

        def pytest_runtest_logfinish(self, nodeid, location):
            manifest["completed_nodeids"].append(nodeid)

    code = pytest.main(["-q", "tests", f"--junitxml={output}/shard-{index}.xml"], plugins=[Inventory()])
    manifest["exit_code"] = int(code)
    (output / f"shard-{index}.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return int(code)


def verify(directory: Path, count: int) -> dict:
    manifests = []
    for index in range(count):
        path = directory / f"shard-{index}.json"
        m = json.loads(path.read_text(encoding="utf-8"))
        # JUnit is a second inventory, not a replacement for exact pytest IDs.
        cases = ET.parse(directory / f"shard-{index}.xml").findall(".//testcase")
        if len(cases) != len(m["selected_nodeids"]):
            raise ValueError(f"JUnit execution count mismatch in shard {index}")
        if any(case.find("failure") is not None or case.find("error") is not None for case in cases):
            raise ValueError(f"JUnit failures in shard {index}")
        manifests.append(m)
    result = validate_manifests(manifests, count)
    (directory / "coverage-summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    runner = sub.add_parser("run")
    runner.add_argument("--index", type=int, required=True)
    runner.add_argument("--count", type=int, required=True)
    runner.add_argument("--output", type=Path, required=True)
    validator = sub.add_parser("verify")
    validator.add_argument("directory", type=Path)
    validator.add_argument("--count", type=int, required=True)
    args = parser.parse_args()
    if args.command == "run":
        return run(args.index, args.count, args.output)
    print(json.dumps(verify(args.directory, args.count), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
