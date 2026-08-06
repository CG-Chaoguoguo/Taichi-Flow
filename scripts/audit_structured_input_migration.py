#!/usr/bin/env python3
"""Audit a legacy EDDA case against Taichi-Flow's structured scenario contract."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from api.services.legacy_migration import build_legacy_migration_plan
from api.services.parameter_templates import builtin_bj_hxl_template, normalized_parameter_values
from api.services.reference_config_parser import parse_reference_config_file
from api.services.structured_input_resolver import validate_scenario_configuration
from api.services.workbench_store import RASTER_ASSET_FAMILIES, WorkbenchStore
from edda.io.spatial_input_loader import SpatialInputLoader


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _raster_metadata(path: Path) -> dict[str, Any]:
    data, metadata = SpatialInputLoader(str(path)).read()
    rows, cols = data.shape[:2]
    bounds = metadata.get("bounds")
    if bounds is not None and hasattr(bounds, "left"):
        extent = [float(bounds.left), float(bounds.bottom), float(bounds.right), float(bounds.top)]
    elif isinstance(bounds, (list, tuple)) and len(bounds) == 4:
        xmin, xmax, ymin, ymax = bounds
        extent = [float(xmin), float(ymin), float(xmax), float(ymax)]
    else:
        extent = None
    return {
        "rows": int(rows),
        "cols": int(cols),
        "cell_size": float(metadata.get("dx") or metadata.get("cellsize") or 1.0),
        "origin": {
            "x": float(metadata.get("xllcorner") or 0.0),
            "y": float(metadata.get("yllcorner") or 0.0),
        },
        "crs": None if metadata.get("crs") in (None, "", "None") else str(metadata.get("crs")),
        "nodata": metadata.get("nodata", metadata.get("nodata_value")),
        "extent": extent,
    }


def _differences(left: Any, right: Any, path: str = "$") -> list[dict[str, Any]]:
    if isinstance(left, dict) and isinstance(right, dict):
        differences: list[dict[str, Any]] = []
        for key in sorted(set(left) | set(right)):
            if key not in left or key not in right:
                differences.append({"path": f"{path}.{key}", "legacy": left.get(key), "structured": right.get(key)})
            else:
                differences.extend(_differences(left[key], right[key], f"{path}.{key}"))
        return differences
    if isinstance(left, list) and isinstance(right, list):
        differences = []
        if len(left) != len(right):
            differences.append({"path": f"{path}.length", "legacy": len(left), "structured": len(right)})
        for index, (left_item, right_item) in enumerate(zip(left, right)):
            differences.extend(_differences(left_item, right_item, f"{path}[{index}]"))
        return differences
    if (
        isinstance(left, (int, float))
        and not isinstance(left, bool)
        and isinstance(right, (int, float))
        and not isinstance(right, bool)
    ):
        if math.isclose(float(left), float(right), rel_tol=1e-12, abs_tol=1e-15):
            return []
    elif left == right:
        return []
    return [{"path": path, "legacy": left, "structured": right}]


def audit(case_dir: Path, output_path: Path, scratch_dir: Path) -> dict[str, Any]:
    case_dir = case_dir.expanduser().resolve()
    edda_in = case_dir / "edda_in.txt"
    if not edda_in.is_file():
        raise FileNotFoundError(f"Missing edda_in.txt: {edda_in}")

    source_hash = _sha256(edda_in)
    parsed = parse_reference_config_file(str(edda_in), str(case_dir))
    normalized = normalized_parameter_values(parsed)
    template = builtin_bj_hxl_template()
    parameter_differences = _differences(normalized, template["values"])
    plan = build_legacy_migration_plan(parsed, source_hash=source_hash)

    hash_cache: dict[str, str] = {}
    metadata_cache: dict[str, dict[str, Any]] = {}
    manifest: list[dict[str, Any]] = []
    asset_records: dict[tuple[str, str], dict[str, Any]] = {}
    for binding in plan["proposed_bindings"]:
        path = Path(str(binding["path"])).resolve()
        path_key = str(path).casefold()
        digest = hash_cache.setdefault(path_key, _sha256(path))
        family = str(binding["family"])
        asset_key = (family, digest)
        asset_id = f"audit-{family}-{digest[:20]}"
        if family in RASTER_ASSET_FAMILIES:
            metadata = metadata_cache.setdefault(path_key, _raster_metadata(path))
        else:
            metadata = {}
        asset_records.setdefault(
            asset_key,
            {
                "asset_id": asset_id,
                "family": family,
                "name": path.name,
                "sha256": digest,
                "size": path.stat().st_size,
                "path": str(path),
            },
        )
        manifest.append(
            {
                "upload_id": asset_id,
                "asset_id": asset_id,
                "family": family,
                "name": path.name,
                "sha256": digest,
                "size": path.stat().st_size,
                "blob_path": str(path),
                "raster_metadata": metadata,
                "binding_key": binding["binding_key"],
                "role": binding["role"],
                "period_id": binding.get("period_id"),
                "ordinal": binding.get("ordinal"),
                "active": bool(binding.get("active", True)),
                "metadata": {"migrated_from": binding["native_family"], "source_hash": digest},
            }
        )

    validation = validate_scenario_configuration(normalized, manifest)
    scenario = {
        "scenario_id": "audit-bj-hxl-structured",
        "name": "BJ_HXL structured migration audit",
        "parameter_template_id": template["template_id"],
        "effective_parameters_json": json.dumps(normalized, ensure_ascii=False),
    }
    store = WorkbenchStore(state_dir=scratch_dir)
    runtime_payload = store._build_claim_runtime_payload(
        project_id="audit-bj-hxl",
        project={"root_path": str(case_dir)},
        queue_item_id="audit-queue",
        simulation_id="audit-simulation",
        scenario=scenario,
        output_dir=str(output_path.parent / "runtime-output-not-created"),
        manifest=manifest,
    )

    original_periods = list(parsed.rainfall_period_sources or [])
    structured_periods = list((runtime_payload.get("overrides") or {}).get("structured_rainfall", {}).get("periods") or [])
    rainfall_bindings = sorted(
        (item for item in manifest if item.get("role") == "rainfall-period"),
        key=lambda item: int(item.get("ordinal") or 0),
    )
    period_differences: list[dict[str, Any]] = []
    for index in range(max(len(original_periods), len(structured_periods), len(rainfall_bindings))):
        original = original_periods[index] if index < len(original_periods) else None
        structured = structured_periods[index] if index < len(structured_periods) else None
        binding = rainfall_bindings[index] if index < len(rainfall_bindings) else None
        if not original or not structured or not binding:
            period_differences.append(
                {"index": index + 1, "legacy": original, "structured": structured, "binding": binding}
            )
            continue
        expected_path = str(Path(str(original.get("rifil_path") or "")).resolve())
        actual_path = str(Path(str(structured.get("path") or "")).resolve())
        expected = {
            "period_id": f"period-{index + 1:04d}",
            "index": index + 1,
            "start_s": float(original["capt_start_s"]),
            "end_s": float(original["capt_end_s"]),
            "source": "raster" if original.get("source") == "rifil_grid" else "uniform",
            "path": expected_path,
        }
        actual = {
            "period_id": structured.get("period_id"),
            "index": structured.get("index"),
            "start_s": structured.get("start_s"),
            "end_s": structured.get("end_s"),
            "source": structured.get("source"),
            "path": actual_path,
        }
        if _differences(expected, actual):
            period_differences.append({"index": index + 1, "legacy": expected, "structured": actual})

    rainfall_hashes = [
        {
            "period_id": item["period_id"],
            "source_path": item["blob_path"],
            "source_sha256": _sha256(Path(item["blob_path"])),
            "asset_sha256": item["sha256"],
            "match": _sha256(Path(item["blob_path"])) == item["sha256"],
        }
        for item in rainfall_bindings
    ]
    runtime_text = json.dumps(runtime_payload, ensure_ascii=False).lower()
    runtime_path_independent = (
        runtime_payload.get("case_config_file") is None
        and runtime_payload.get("case_base_dir") is None
        and "edda_in" not in runtime_text
    )
    active_manning_bindings = [
        item for item in manifest if item.get("binding_key") == "manning.raster" and item.get("active", True)
    ]
    checks = {
        "source_hash_matches_template": source_hash == template["source_hash"],
        "normalized_parameter_diff_count": len(parameter_differences),
        "rainfall_period_count_legacy": len(original_periods),
        "rainfall_period_count_structured": len(structured_periods),
        "rainfall_binding_count": len(rainfall_bindings),
        "rainfall_period_diff_count": len(period_differences),
        "rainfall_hash_mismatch_count": sum(not item["match"] for item in rainfall_hashes),
        "validation_valid": bool(validation["valid"]),
        "runtime_path_independent": runtime_path_independent,
        "manning_source": normalized.get("manning.source"),
        "active_manning_raster_binding_count": len(active_manning_bindings),
        "unresolved_active_binding_count": int(plan.get("unresolved_active_count") or 0),
    }
    passed = (
        checks["source_hash_matches_template"]
        and checks["normalized_parameter_diff_count"] == 0
        and checks["rainfall_period_count_legacy"] == 72
        and checks["rainfall_period_count_structured"] == 72
        and checks["rainfall_binding_count"] == 72
        and checks["rainfall_period_diff_count"] == 0
        and checks["rainfall_hash_mismatch_count"] == 0
        and checks["validation_valid"]
        and checks["runtime_path_independent"]
        and checks["manning_source"] == "global"
        and checks["active_manning_raster_binding_count"] == 0
        and checks["unresolved_active_binding_count"] == 0
    )
    report = {
        "schema": "taichi-flow.structured-input-migration-audit/v1",
        "compared_case": "BJ_HXL_Text",
        "case_dir": str(case_dir),
        "legacy_config": str(edda_in),
        "source_hash": source_hash,
        "parameter_template_id": template["template_id"],
        "checks": checks,
        "parameter_differences": parameter_differences,
        "period_differences": period_differences,
        "rainfall_asset_hashes": rainfall_hashes,
        "asset_count": len(asset_records),
        "binding_count": len(manifest),
        "validation": validation,
        "migration_plan": {
            "existing_file_count": plan["existing_file_count"],
            "missing_file_count": plan["missing_file_count"],
            "unresolved_active_count": plan.get("unresolved_active_count", 0),
            "unresolved_active_bindings": plan.get("unresolved_active_bindings", []),
            "warnings": plan["warnings"],
        },
        "generated_runtime_config": runtime_payload,
        "production_decision": "PASS" if passed else "BLOCK",
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scratch-dir", type=Path)
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    scratch = (args.scratch_dir or output.parent / "audit_store").expanduser().resolve()
    report = audit(args.case_dir, output, scratch)
    print(json.dumps({"production_decision": report["production_decision"], **report["checks"]}, ensure_ascii=False, indent=2))
    return 0 if report["production_decision"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
