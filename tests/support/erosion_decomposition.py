"""Compact, tracked writers for solver erosion diagnostic fixtures.

The full paired-case comparison runner is intentionally local-only because it
also contains case paths, large reference inputs, and report orchestration.
These writers are the small deterministic surface required by unit tests.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ORIGINAL_600S_EROSION_DEPTH_SUM = {"20a": 0.027333, "50a": 0.021918}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _records(solver: Any) -> list[dict[str, Any]]:
    dynamic_wave = getattr(solver, "dfs_dynamic_wave", solver)
    if dynamic_wave is None or not hasattr(dynamic_wave, "get_erosion_step_diagnostics"):
        return []
    return list(dynamic_wave.get_erosion_step_diagnostics() or [])


def _sum_variant(records: list[dict[str, Any]], key: str, variant: str, field: str) -> float:
    return float(
        sum(
            float(((record.get(key, {}) or {}).get(variant, {}) or {}).get(field, 0.0) or 0.0)
            for record in records
        )
    )


def _count_variant(records: list[dict[str, Any]], key: str, variant: str, field: str) -> int:
    return int(
        sum(
            int(((record.get(key, {}) or {}).get(variant, {}) or {}).get(field, 0) or 0)
            for record in records
        )
    )


def _variant_rows(records: list[dict[str, Any]], key: str, variant_names: Iterable[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for step_index, record in enumerate(records):
        for name in variant_names:
            variant = (record.get(key, {}) or {}).get(name, {}) or {}
            row = {
                "step_index": step_index,
                "t_start_s": record.get("t_start_s"),
                "t_end_s": record.get("t_end_s"),
                "dt_s": record.get("dt_s"),
                "variant": name,
            }
            for field in (
                "source_valid",
                "count_tau_gt_taoc",
                "count_all_erosion_gates_true",
                "positive_erosion_cell_count",
                "erorate_raw_sum",
                "erorate_raw_max",
                "predicted_erosion_increment_sum",
                "overlap_with_active_gate_count",
                "audit_note",
            ):
                row[field] = variant.get(field)
            rows.append(row)
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    if not columns:
        columns = ["variant"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _write_top_cells(
    path: Path,
    records: list[dict[str, Any]],
    key: str,
    *,
    fallback_category: str,
) -> None:
    rows: list[dict[str, Any]] = []
    for step_index, record in enumerate(records):
        groups = record.get(key, {}) or {}
        for category, cells in groups.items():
            for rank, cell in enumerate(cells or [], start=1):
                row = {
                    "step_index": step_index,
                    "t_start_s": record.get("t_start_s"),
                    "t_end_s": record.get("t_end_s"),
                    "category": category,
                    "rank": rank,
                }
                if isinstance(cell, dict):
                    row.update(cell)
                rows.append(row)
    if not rows:
        rows.append(
            {
                "step_index": len(records) - 1 if records else 0,
                "category": fallback_category,
                "rank": 1,
                "metric_value": None,
            }
        )
    _write_csv(path, rows)


def _write_tau_component_decomposition_artifacts(
    solver: Any,
    case_key: str,
    report_dir: Path,
    *,
    artifact_suffix: str = "",
) -> dict[str, Any]:
    records = _records(solver)
    names = [
        "A_current_active",
        "B_sfy_scalar_depth_weighted_cvbar",
        "C_sfy_zero_cvbar_lte_cvtol",
        "D_sfy_local_cv_recomputed",
    ]
    aggregate = {
        name: {
            "count_tau_gt_taoc_sum": _count_variant(records, "tau_variants", name, "count_tau_gt_taoc"),
            "count_all_erosion_gates_true_sum": _count_variant(records, "tau_variants", name, "count_all_erosion_gates_true"),
            "erorate_raw_sum_accumulated": _sum_variant(records, "tau_variants", name, "erorate_raw_sum"),
            "predicted_erosion_increment_sum_0_600": _sum_variant(records, "tau_variants", name, "predicted_erosion_increment_sum"),
        }
        for name in names
    }
    suffix = artifact_suffix.strip()
    json_path = report_dir / f"current_tau_component_decomposition_{case_key}_600s{suffix}.json"
    csv_path = report_dir / f"current_tau_component_decomposition_{case_key}_600s{suffix}.csv"
    _write_json(json_path, {"case_key": case_key, "generated_at": _now(), "accepted_step_count": len(records), "variant_aggregate": aggregate, "records": records})
    rows = _variant_rows(records, "tau_variants", names)
    for row in rows:
        row["case_key"] = case_key
    _write_csv(csv_path, rows)
    return {"json_path": str(json_path), "csv_path": str(csv_path), "accepted_step_count": len(records), "variant_aggregate": aggregate}


def _write_sfmiu_absubar_decomposition_artifacts(
    solver: Any,
    case_key: str,
    report_dir: Path,
    *,
    artifact_suffix: str = "",
) -> dict[str, Any]:
    records = _records(solver)
    names = [
        "A_active_current_sfmiu",
        "B_absubar_fortran_fvpredi2_candidate",
        "B2_absubar_fortran_preflux_velocity_state",
        "C_absubar_accepted_velocity_only",
        "D_absubar_candidate_velocity_only",
        "E_miudebris_exact_fortran_branch",
        "F_sfmiu_absubar_squared_audit",
        "G_sfmiu_disabled",
        "H_sfmanning_only_tau",
    ]
    original_sum = ORIGINAL_600S_EROSION_DEPTH_SUM.get(case_key)
    aggregate: dict[str, dict[str, Any]] = {}
    for name in names:
        predicted = _sum_variant(records, "sfmiu_absubar_variants", name, "predicted_erosion_increment_sum")
        aggregate[name] = {
            "count_tau_gt_taoc_sum": _count_variant(records, "sfmiu_absubar_variants", name, "count_tau_gt_taoc"),
            "count_all_erosion_gates_true_sum": _count_variant(records, "sfmiu_absubar_variants", name, "count_all_erosion_gates_true"),
            "erorate_raw_sum_accumulated": _sum_variant(records, "sfmiu_absubar_variants", name, "erorate_raw_sum"),
            "predicted_erosion_increment_sum_0_600": predicted,
            "ratio_to_original_600s": predicted / original_sum if original_sum and original_sum > 0.0 else None,
        }
    suffix = artifact_suffix.strip()
    json_path = report_dir / f"current_sfmiu_absubar_decomposition_{case_key}_600s{suffix}.json"
    csv_path = report_dir / f"current_sfmiu_absubar_decomposition_{case_key}_600s{suffix}.csv"
    top_path = report_dir / f"current_sfmiu_absubar_top_cells_{case_key}_600s{suffix}.csv"
    _write_json(json_path, {"case_key": case_key, "generated_at": _now(), "accepted_step_count": len(records), "original_600s_erosion_depth_sum": original_sum, "variant_aggregate": aggregate, "records": records})
    _write_csv(csv_path, _variant_rows(records, "sfmiu_absubar_variants", names))
    _write_top_cells(top_path, records, "sfmiu_absubar_top_cells", fallback_category="diagnostic_record")
    return {"json_path": str(json_path), "csv_path": str(csv_path), "top_cells_csv_path": str(top_path), "accepted_step_count": len(records), "original_600s_erosion_depth_sum": original_sum, "variant_aggregate": aggregate}


def _write_sfmanning_decomposition_artifacts(
    solver: Any,
    case_key: str,
    report_dir: Path,
    *,
    artifact_suffix: str = "",
) -> dict[str, Any]:
    records = _records(solver)
    names = [
        "A_active_current_tau",
        "B_sfmanning_disabled",
        "C_sfmanning_only_current",
        "D_sfmanning_fortran_fvpredi2_absubar",
        "E_sfmanning_accepted_velocity",
        "F_sfmanning_candidate_velocity",
        "G_sfmanning_absubar_linear_audit",
        "H_sfmanning_fortran_depth_exponent",
        "I_sfmanning_raw_native_manning_source",
        "J_sfmanning_cv_correction_disabled_audit",
        "K_original_sfy_sfmiu_plus_fortran_sfmanning",
    ]
    original_sum = ORIGINAL_600S_EROSION_DEPTH_SUM.get(case_key)
    aggregate: dict[str, dict[str, Any]] = {}
    for name in names:
        predicted = _sum_variant(records, "sfmanning_variants", name, "predicted_erosion_increment_sum")
        aggregate[name] = {
            "count_tau_gt_taoc_sum": _count_variant(records, "sfmanning_variants", name, "count_tau_gt_taoc"),
            "count_all_erosion_gates_true_sum": _count_variant(records, "sfmanning_variants", name, "count_all_erosion_gates_true"),
            "positive_erosion_cell_count_sum": _count_variant(records, "sfmanning_variants", name, "positive_erosion_cell_count"),
            "erorate_raw_sum_accumulated": _sum_variant(records, "sfmanning_variants", name, "erorate_raw_sum"),
            "predicted_erosion_increment_sum_0_600": predicted,
            "ratio_to_original_600s": predicted / original_sum if original_sum and original_sum > 0.0 else None,
        }
    suffix = artifact_suffix.strip()
    json_path = report_dir / f"current_sfmanning_decomposition_{case_key}_600s{suffix}.json"
    csv_path = report_dir / f"current_sfmanning_decomposition_{case_key}_600s{suffix}.csv"
    top_path = report_dir / f"current_sfmanning_top_cells_{case_key}_600s{suffix}.csv"
    _write_json(json_path, {"case_key": case_key, "generated_at": _now(), "accepted_step_count": len(records), "original_600s_erosion_depth_sum": original_sum, "variant_aggregate": aggregate, "records": records})
    _write_csv(csv_path, _variant_rows(records, "sfmanning_variants", names))
    _write_top_cells(top_path, records, "sfmanning_top_cells", fallback_category="diagnostic_record")
    return {"json_path": str(json_path), "csv_path": str(csv_path), "top_cells_csv_path": str(top_path), "accepted_step_count": len(records), "original_600s_erosion_depth_sum": original_sum, "variant_aggregate": aggregate}


def _write_kero_zone_unit_decomposition_artifacts(
    solver: Any,
    case_key: str,
    report_dir: Path,
    *,
    artifact_suffix: str = "",
) -> dict[str, Any]:
    records = _records(solver)
    names = [
        "A_active_current",
        "B_kero_per_hour_div_3600",
        "C_kero_per_minute_div_60",
        "D_kero_percent_style_div_100",
        "E_kero_milli_style_div_1000",
        "F_zone_index_shift_minus_1",
        "G_zone_index_shift_plus_1",
        "H_top_layer_kero_only",
        "I_raw_native_zone_kero_table",
    ]
    original_sum = ORIGINAL_600S_EROSION_DEPTH_SUM.get(case_key)
    aggregate: dict[str, dict[str, Any]] = {}
    for name in names:
        first = next(
            (((record.get("kero_unit_zone_variants", {}) or {}).get(name, {}) or {}) for record in records),
            {},
        )
        predicted = _sum_variant(records, "kero_unit_zone_variants", name, "predicted_erosion_increment_sum")
        aggregate[name] = {
            "source_valid": bool(first.get("source_valid", False)),
            "audit_note": first.get("audit_note"),
            "count_tau_gt_taoc_sum": _count_variant(records, "kero_unit_zone_variants", name, "count_tau_gt_taoc"),
            "count_all_erosion_gates_true_sum": _count_variant(records, "kero_unit_zone_variants", name, "count_all_erosion_gates_true"),
            "positive_erosion_cell_count_sum": _count_variant(records, "kero_unit_zone_variants", name, "positive_erosion_cell_count"),
            "erorate_raw_sum_accumulated": _sum_variant(records, "kero_unit_zone_variants", name, "erorate_raw_sum"),
            "predicted_erosion_increment_sum_0_600": predicted,
            "ratio_to_original_600s": predicted / original_sum if original_sum and original_sum > 0.0 else None,
        }
    output_interpretation = dict((records[-1].get("erosion_output_interpretation_variants", {}) if records else {}) or {})
    output_interpretation.setdefault(
        "J_fortran_eleori_minus_ele_mask",
        {"status": "unavailable", "reason": "not present in the supplied diagnostic record"},
    )
    suffix = artifact_suffix.strip()
    json_path = report_dir / f"current_kero_zone_unit_decomposition_{case_key}_600s{suffix}.json"
    csv_path = report_dir / f"current_kero_zone_unit_decomposition_{case_key}_600s{suffix}.csv"
    top_path = report_dir / f"current_kero_zone_unit_top_cells_{case_key}_600s{suffix}.csv"
    _write_json(json_path, {"case_key": case_key, "generated_at": _now(), "accepted_step_count": len(records), "original_600s_erosion_depth_sum": original_sum, "variant_aggregate": aggregate, "output_interpretation_final_step": output_interpretation, "records": records})
    _write_csv(csv_path, _variant_rows(records, "kero_unit_zone_variants", names))
    _write_top_cells(top_path, records, "kero_zone_unit_top_cells", fallback_category="diagnostic_record")
    return {"json_path": str(json_path), "csv_path": str(csv_path), "top_cells_csv_path": str(top_path), "accepted_step_count": len(records), "original_600s_erosion_depth_sum": original_sum, "variant_aggregate": aggregate, "output_interpretation_final_step": output_interpretation}


__all__ = [
    "_write_kero_zone_unit_decomposition_artifacts",
    "_write_sfmiu_absubar_decomposition_artifacts",
    "_write_sfmanning_decomposition_artifacts",
    "_write_tau_component_decomposition_artifacts",
]
