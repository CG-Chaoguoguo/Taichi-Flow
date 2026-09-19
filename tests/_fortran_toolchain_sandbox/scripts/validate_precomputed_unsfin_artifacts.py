from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np


SCRIPT_PATH = Path(__file__).resolve()
SANDBOX_ROOT = SCRIPT_PATH.parents[1]
REPO_ROOT = SCRIPT_PATH.parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from api.services.native_sidecar_loader import load_precomputed_unsfin_schedule  # noqa: E402


def _jsonable(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return {
            "shape": list(value.shape),
            "dtype": str(value.dtype),
        }
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _payload_summary(payload: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "family",
        "parse_status",
        "shape",
        "runtime_orientation",
        "artifact_paths",
        "missing_artifacts",
        "gindx_nonzero_count",
        "fdepth_nonzero_count",
        "fdepth_active_count",
        "fdepth_sum",
        "fdepth_max",
        "tfail_finite_count",
        "tfail_active_count",
        "tfail_min",
        "tfail_max",
        "tfail_lte_600_count",
        "tfail_histogram",
        "scheduled_cell_count",
        "meta",
    ]
    return {key: _jsonable(payload.get(key)) for key in keys if key in payload}


def _diff_array(a: np.ndarray, b: np.ndarray) -> dict[str, Any]:
    if a.shape != b.shape:
        return {
            "status": "shape_mismatch",
            "shape_a": list(a.shape),
            "shape_b": list(b.shape),
        }
    delta = b.astype(np.float64) - a.astype(np.float64)
    finite = delta[np.isfinite(delta)]
    return {
        "status": "ok",
        "shape": list(delta.shape),
        "nonzero_count": int(np.count_nonzero(np.abs(delta) > 1.0e-12)),
        "sum_delta": float(np.sum(finite)) if finite.size else 0.0,
        "sum_abs_delta": float(np.sum(np.abs(finite))) if finite.size else 0.0,
        "max_abs_delta": float(np.max(np.abs(finite))) if finite.size else 0.0,
    }


def _paired_diff(payload_a: dict[str, Any], payload_b: dict[str, Any]) -> dict[str, Any]:
    arrays_a = payload_a.get("runtime_arrays")
    arrays_b = payload_b.get("runtime_arrays")
    if not arrays_a or not arrays_b:
        return {
            "status": "blocked",
            "reason": "one or both cases lack runtime_arrays",
        }
    return {
        "status": "ok",
        "gindx_diff": _diff_array(arrays_a["gindx"], arrays_b["gindx"]),
        "fdepth_diff": _diff_array(arrays_a["fdepth_m"], arrays_b["fdepth_m"]),
        "tfail_diff": _diff_array(arrays_a["tfail_s"], arrays_b["tfail_s"]),
    }


def validate_case(case_dir: Path, dem_file: Path | None = None) -> dict[str, Any]:
    payload = load_precomputed_unsfin_schedule(case_dir, dem_file=dem_file)
    return payload


def build_validation_report(
    case_a_dir: Path,
    case_b_dir: Path,
    *,
    case_a_name: str = "20a",
    case_b_name: str = "50a",
    dem_a: Path | None = None,
    dem_b: Path | None = None,
) -> dict[str, Any]:
    payload_a = validate_case(case_a_dir, dem_file=dem_a)
    payload_b = validate_case(case_b_dir, dem_file=dem_b)
    return {
        "generated_by": str(SCRIPT_PATH),
        "case_a": {
            "name": case_a_name,
            "case_dir": str(case_a_dir),
            "dem_file": str(dem_a) if dem_a else None,
            "summary": _payload_summary(payload_a),
        },
        "case_b": {
            "name": case_b_name,
            "case_dir": str(case_b_dir),
            "dem_file": str(dem_b) if dem_b else None,
            "summary": _payload_summary(payload_b),
        },
        "paired_diff": _paired_diff(payload_a, payload_b),
    }


def write_reports(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "original_tfail_artifact_validation.json"
    md_path = output_dir / "original_tfail_artifact_validation.md"

    json_path.write_text(json.dumps(_jsonable(report), indent=2), encoding="utf-8")

    lines: list[str] = []
    lines.append("# Original Tfail Artifact Validation")
    lines.append("")
    for label in ("case_a", "case_b"):
        case = report[label]
        summary = case["summary"]
        lines.append(f"## {case['name']}")
        lines.append("")
        lines.append(f"- case_dir: `{case['case_dir']}`")
        lines.append(f"- parse_status: `{summary.get('parse_status')}`")
        lines.append(f"- shape: `{summary.get('shape')}`")
        lines.append(f"- orientation: `{summary.get('runtime_orientation')}`")
        lines.append(f"- gindx_nonzero_count: `{summary.get('gindx_nonzero_count')}`")
        lines.append(f"- fdepth_nonzero_count: `{summary.get('fdepth_nonzero_count')}`")
        lines.append(f"- fdepth_sum: `{summary.get('fdepth_sum')}`")
        lines.append(f"- fdepth_max: `{summary.get('fdepth_max')}`")
        lines.append(f"- tfail_finite_count: `{summary.get('tfail_finite_count')}`")
        lines.append(f"- tfail_min: `{summary.get('tfail_min')}`")
        lines.append(f"- tfail_max: `{summary.get('tfail_max')}`")
        lines.append(f"- tfail_lte_600_count: `{summary.get('tfail_lte_600_count')}`")
        lines.append("")

    lines.append("## Paired Diff")
    lines.append("")
    paired = report["paired_diff"]
    lines.append(f"- status: `{paired.get('status')}`")
    if paired.get("status") == "ok":
        for key in ("gindx_diff", "fdepth_diff", "tfail_diff"):
            diff = paired[key]
            lines.append(f"- {key}: nonzero_count={diff.get('nonzero_count')}, max_abs_delta={diff.get('max_abs_delta')}, sum_abs_delta={diff.get('sum_abs_delta')}")
    else:
        lines.append(f"- reason: `{paired.get('reason')}`")
    lines.append("")
    lines.append("## Guardrail")
    lines.append("")
    lines.append("This validator does not infer `tfail` from `LS_Scar` or `faildph`; it only validates explicit `precomputed_unsfin_*` artifacts.")

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    default_artifacts = SANDBOX_ROOT / "generated" / "original_reference_artifacts"
    parser = argparse.ArgumentParser(description="Validate original instrumented precomputed_unsfin artifacts.")
    parser.add_argument("--case-a-dir", type=Path, default=default_artifacts / "20a")
    parser.add_argument("--case-b-dir", type=Path, default=default_artifacts / "50a")
    parser.add_argument("--case-a-name", default="20a")
    parser.add_argument("--case-b-name", default="50a")
    parser.add_argument("--dem-a", type=Path, default=None)
    parser.add_argument("--dem-b", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=SANDBOX_ROOT / "generated")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_validation_report(
        args.case_a_dir,
        args.case_b_dir,
        case_a_name=args.case_a_name,
        case_b_name=args.case_b_name,
        dem_a=args.dem_a,
        dem_b=args.dem_b,
    )
    json_path, md_path = write_reports(report, args.output_dir)
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    if report["paired_diff"].get("status") != "ok":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
