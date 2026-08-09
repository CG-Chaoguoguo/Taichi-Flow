"""Disabled-by-default dry-run provider for native unsfin schedules.

This module is production-facing, but it does not feed DFS runtime state.  Its
first responsibility is to expose the native unsfin ledger through a provider
contract with explicit provenance, fail-closed state, and manifest hashes.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from edda.solver.native_unsfin_types import LedgerArrays


PROVIDER_NAME = "production_native_unsfin"
SOURCE_PROVENANCE = "production_native_unsfin"
MODE_DRY_RUN = "dry_run"
MODE_RUNTIME_SMOKE = "runtime_smoke"
DEFAULT_FULL_WINDOW_S = 64800.0
RUNTIME_FEED_ENV = "EDDA_NATIVE_UNSFIN_RUNTIME_FEED"
RUNTIME_FEED_ALIAS_ENV = "EDDA_ENABLE_PRODUCTION_NATIVE_UNSFIN_RUNTIME"
PROVIDER_ARTIFACT_DIR_ENV = "EDDA_NATIVE_UNSFIN_PROVIDER_ARTIFACT_DIR"
RNOFF_TOPOINDEX_ENV = "EDDA_EXPERIMENT_RNOFF_TOPOINDEX"
RNOFF_NATIVE_UNSFIN_FEED_ENV = "EDDA_EXPERIMENT_RNOFF_NATIVE_UNSFIN_FEED"
RNOFF_DFS_SHADOW_FEED_ENV = "EDDA_EXPERIMENT_RNOFF_DFS_SHADOW_FEED"
RNOFF_GPU_FIELD_FEED_ENV = "EDDA_EXPERIMENT_RNOFF_GPU_FIELD_FEED"
DFS_SOURCE_STAGING_FIELD_ENV = "EDDA_EXPERIMENT_DFS_SOURCE_STAGING_FIELD"
DFS_SOURCE_STAGING_FAST_CONSUME_ENV = "EDDA_EXPERIMENT_DFS_SOURCE_STAGING_FAST_CONSUME"
DFS_SOURCE_STAGING_KERNEL_ENV = "EDDA_EXPERIMENT_DFS_SOURCE_STAGING_KERNEL"
PROJECT_CUDA_BACKEND_STAGE1_ENV = "EDDA_EXPERIMENT_PROJECT_CUDA_BACKEND_STAGE1"
GPU_ONLY_PRODUCTION_SMOKE_ENV = "EDDA_EXPERIMENT_GPU_ONLY_PRODUCTION_SMOKE"
PROJECT_CUDA_BACKEND_STAGE1_COMPONENTS = (
    "rnoff_gpu_field_feed",
    "dfs_source_staging_field",
    "dfs_source_staging_fast_consume",
)
PROJECT_CUDA_BACKEND_STAGE1_FIELD_LIFECYCLE = {
    "rnoff_gpu_field_feed": {
        "fields": (
            "dfs_dynamic_wave.precomputed_failure_tfail_field",
            "dfs_dynamic_wave.precomputed_failure_gindx_field",
            "dfs_dynamic_wave.precomputed_failure_fdepth_field",
        ),
        "ownership": "taichi_mirror_of_cpu_reference_schedule",
        "reset_policy": "recreated_by_configure_precomputed_failure_schedule",
        "checkpoint_policy": "transient_recomputed_from_source_backed_provider_schedule",
    },
    "dfs_source_staging_field": {
        "fields": (
            "dfs_dynamic_wave.precomputed_failure_committed_fire_mask_field",
            "dfs_dynamic_wave.precomputed_failure_source_depth_staging_field",
            "dfs_dynamic_wave.precomputed_failure_source_density_staging_field",
        ),
        "ownership": "taichi_source_staging_with_cpu_reference_fail_closed_validation",
        "reset_policy": "candidate_buffers_reset_each_stage",
        "checkpoint_policy": "committed_fire_mask_tracks accepted runtime feed lifecycle",
    },
    "dfs_source_staging_fast_consume": {
        "fields": (
            "dfs_dynamic_wave.precomputed_failure_candidate_fire_mask_field",
            "dfs_dynamic_wave.precomputed_failure_candidate_count_field",
            "dfs_dynamic_wave.precomputed_failure_candidate_depth_sum_field",
            "dfs_dynamic_wave.precomputed_failure_candidate_mass_sum_field",
        ),
        "ownership": "taichi_stage_summary_after_first_stage_parity_validation",
        "reset_policy": "candidate summary reset before each stage",
        "checkpoint_policy": "transient_recomputed_or reset with source-staging fields",
    },
}


def project_cuda_backend_stage1_flag_enabled(env: Mapping[str, str]) -> bool:
    """Return whether the default-off project CUDA backend Stage-1 bundle is requested."""

    return _truthy(env.get(PROJECT_CUDA_BACKEND_STAGE1_ENV)) or _truthy(
        env.get(GPU_ONLY_PRODUCTION_SMOKE_ENV)
    )

DISABLED_REASON = "PROVIDER_DISABLED_BY_DEFAULT"
RUNTIME_FEED_BLOCKED_REASON = "RUNTIME_FEED_FORBIDDEN_IN_DRY_RUN_PHASE"
RUNTIME_FEED_FLAG_DISABLED_REASON = "RUNTIME_FEED_FLAG_NOT_SET"
RNOFF_NATIVE_FEED_FLAG_DISABLED_REASON = "RNOFF_NATIVE_UNSFIN_FEED_FLAG_NOT_SET"
RNOFF_DFS_SHADOW_FEED_FLAG_DISABLED_REASON = "RNOFF_DFS_SHADOW_FEED_FLAG_NOT_SET"
RNOFF_CONTRACT_MISSING_REASON = "RNOFF_PRECOMPUTE_CONTRACT_MISSING"
RNOFF_CONTRACT_INVALID_REASON = "RNOFF_PRECOMPUTE_CONTRACT_INVALID"
RNOFF_Q_ORACLE_NOT_ACCEPTED_REASON = "RNOFF_Q_RUNTIME_ORACLE_NOT_ACCEPTED"
RNOFF_RUNTIME_FEED_SCHEDULE_NOT_SOURCE_BACKED_REASON = "RNOFF_RUNTIME_FEED_SCHEDULE_NOT_SOURCE_BACKED"
RNOFF_SCHEDULE_TARGETS_MISSING_REASON = "RNOFF_SCHEDULE_TARGETS_MISSING"
RNOFF_SCHEDULE_DIAGNOSTIC_FAILED_REASON = "RNOFF_SCHEDULE_DIAGNOSTIC_FAILED"
DRY_RUN_DISABLED_REASON = "DRY_RUN_NOT_ENABLED"
MISSING_INPUT_REASON = "REQUIRED_INPUT_MISSING"
INVALID_METADATA_REASON = "INVALID_PROVIDER_METADATA"
GENERATION_FAILED_REASON = "PROVIDER_DRY_RUN_GENERATION_FAILED"
SCHEDULE_VALIDATION_FAILED_REASON = "PROVIDER_SCHEDULE_VALIDATION_FAILED"
SCHEDULE_CONFIGURATION_FAILED_REASON = "PROVIDER_SCHEDULE_CONFIGURATION_FAILED"
PROVIDER_ARTIFACT_PROVENANCE_MISMATCH_REASON = "PROVIDER_ARTIFACT_PROVENANCE_MISMATCH"
ACCEPTED_RNOFF_Q_ORACLE_STATUSES = frozenset(
    {
        "ORIGINAL_Q_RUNTIME_ORACLE_READY",
        "Q_RUNTIME_MATCHES_FORMULA_REPLAY",
        "RNOFF_Q_ORACLE_READY_PROVIDER_PLUMBING_DESIGN_READY",
    }
)


@dataclass(frozen=True)
class NativeUnsfinDryRunRequest:
    case_dir: Path
    output_dir: Path
    provider_selected: bool = False
    dry_run_enabled: bool = False
    runtime_feed_enabled: bool = False
    ledger_window_s: float = DEFAULT_FULL_WINDOW_S
    checkpoint_dir: Path | None = None
    resume: bool = False
    checkpoint_interval: int = 5000
    metadata_overrides: dict[str, Any] = field(default_factory=dict)
    rnoff_native_unsfin_feed_enabled: bool = False
    rnoff_contract: Any | None = None
    rnoff_contract_kst: Mapping[int | str, float] | Sequence[float] | None = None
    rnoff_contract_rikzero: Mapping[int | str, float] | Sequence[float] | None = None
    rnoff_contract_bkgrof: bool = True
    rnoff_q_runtime_oracle_status: str | None = None
    rnoff_provider_schedule_generation_enabled: bool = False
    rnoff_schedule_target_cells: Sequence[int] | None = None
    rnoff_schedule_initial_ts: float = 60.0


@dataclass(frozen=True)
class NativeUnsfinProviderResult:
    status: str
    provider_available: bool
    provider_selected: bool
    dry_run_enabled: bool
    runtime_feed_enabled: bool
    schedule_generated: bool
    schedule_validated: bool
    schedule_consumed_by_dfs: bool
    blocked_reason: str | None
    meta: dict[str, Any]
    manifest: dict[str, Any] | None
    artifact_paths: dict[str, str]

    @property
    def ok(self) -> bool:
        return self.status == "generated"


@dataclass(frozen=True)
class NativeUnsfinRuntimeFeedResult:
    status: str
    provider_available: bool
    provider_selected: bool
    dry_run_enabled: bool
    runtime_feed_enabled: bool
    schedule_generated: bool
    schedule_validated: bool
    schedule_configured_into_solver: bool
    schedule_consumed_by_dfs: bool
    blocked_reason: str | None
    meta: dict[str, Any]
    manifest: dict[str, Any] | None
    artifact_paths: dict[str, str]

    @property
    def ok(self) -> bool:
        return self.status == "configured"


GeneratorFn = Callable[[NativeUnsfinDryRunRequest], tuple[LedgerArrays, dict[str, Any]]]
RnoffScheduleGeneratorFn = Callable[
    [NativeUnsfinDryRunRequest, Mapping[int, Sequence[Mapping[str, Any]]]],
    tuple[list[dict[str, Any]], dict[str, Any]],
]


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def runtime_feed_flag_enabled(env: dict[str, str] | None = None) -> bool:
    source = env if env is not None else os.environ
    return (
        _truthy(source.get(RUNTIME_FEED_ENV))
        or _truthy(source.get(RUNTIME_FEED_ALIAS_ENV))
        or _truthy(source.get(GPU_ONLY_PRODUCTION_SMOKE_ENV))
    )


def rnoff_native_unsfin_feed_flag_enabled(env: dict[str, str] | None = None) -> bool:
    source = env if env is not None else os.environ
    return (
        _truthy(source.get(RNOFF_TOPOINDEX_ENV)) and _truthy(source.get(RNOFF_NATIVE_UNSFIN_FEED_ENV))
    ) or _truthy(source.get(GPU_ONLY_PRODUCTION_SMOKE_ENV))


def rnoff_dfs_shadow_feed_flag_enabled(env: dict[str, str] | None = None) -> bool:
    source = env if env is not None else os.environ
    return rnoff_native_unsfin_feed_flag_enabled(source) and _truthy(source.get(RNOFF_DFS_SHADOW_FEED_ENV))


def _contract_manifest(contract: Any) -> dict[str, Any] | None:
    if contract is None:
        return None
    if isinstance(contract, dict):
        return contract
    manifest = getattr(contract, "manifest", None)
    return manifest if isinstance(manifest, dict) else None


def _coerce_one_based_values(
    values: Mapping[int | str, float] | Sequence[float] | None,
    *,
    name: str,
    cell_count: int,
) -> tuple[dict[int, float] | None, str | None]:
    if values is None:
        return None, f"{name} is required"
    if isinstance(values, Mapping):
        result: dict[int, float] = {}
        for raw_key, raw_value in values.items():
            try:
                key = int(raw_key)
                value = float(raw_value)
            except (TypeError, ValueError):
                return None, f"{name} contains nonnumeric key/value"
            if key < 1 or key > cell_count:
                return None, f"{name} contains out-of-range one-based cell id {key}"
            result[key] = value
        return result, None
    if isinstance(values, (str, bytes)):
        return None, f"{name} must be numeric values, not text"
    try:
        sequence = [float(value) for value in values]
    except (TypeError, ValueError):
        return None, f"{name} contains nonnumeric values"
    if len(sequence) == cell_count:
        return {index + 1: value for index, value in enumerate(sequence)}, None
    if len(sequence) == cell_count + 1:
        return {index: value for index, value in enumerate(sequence) if index > 0}, None
    return None, f"{name} length {len(sequence)} does not match cell_count {cell_count}"


def _coerce_target_cells(
    values: Sequence[int] | None,
    *,
    cell_count: int,
) -> tuple[list[int] | None, str | None]:
    if values is None:
        return None, "schedule target cells are required"
    if isinstance(values, (str, bytes)):
        return None, "schedule target cells must be numeric, not text"
    result: list[int] = []
    seen: set[int] = set()
    try:
        raw_values = list(values)
    except TypeError:
        return None, "schedule target cells must be a sequence"
    for raw_value in raw_values:
        try:
            cell_id = int(raw_value)
        except (TypeError, ValueError):
            return None, "schedule target cells contain nonnumeric values"
        if cell_id < 1 or cell_id > cell_count:
            return None, f"schedule target cell id {cell_id} is out of range"
        if cell_id not in seen:
            result.append(cell_id)
            seen.add(cell_id)
    if not result:
        return None, "schedule target cells are empty"
    return result, None


def _skip_event_type(reason: str | None) -> str:
    if reason == "slope_below_slomin":
        return "SkippedSlopeGate"
    if reason == "ltstar_le_0_01" or str(reason or "").startswith("ltstar_gt_"):
        return "SkippedLtstarGate"
    if reason == "ct_zone_gt_1e6":
        return "SkippedCtGate"
    return "SkippedEligibilityGate"


def _write_dict_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)
    if not fieldnames:
        fieldnames = ["case", "one_based_cell_id", "event_type"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(row))


def _summarize_schedule_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    event_counts: dict[str, int] = {}
    branch_counts: dict[str, int] = {}
    tfail_positive = 0
    tfail_negative = 0
    skipped = 0
    q_rows = 0
    for row in rows:
        event_type = str(row.get("event_type") or row.get("branch") or "")
        branch = str(row.get("branch") or "")
        event_counts[event_type] = event_counts.get(event_type, 0) + 1
        branch_counts[branch] = branch_counts.get(branch, 0) + 1
        try:
            tfail = float(row.get("tfail", 0.0))
        except (TypeError, ValueError):
            tfail = 0.0
        if tfail > 0.0:
            tfail_positive += 1
        elif tfail < 0.0:
            tfail_negative += 1
        if event_type.startswith("Skipped"):
            skipped += 1
        try:
            q_count = int(row.get("q_period_count", 0))
        except (TypeError, ValueError):
            q_count = 0
        q_rows += max(q_count, 0)
    return {
        "schedule_diagnostic_row_count": len(rows),
        "event_type_counts": event_counts,
        "branch_counts": branch_counts,
        "tfail_positive_count": tfail_positive,
        "tfail_negative_count": tfail_negative,
        "skip_or_no_failure_count": skipped,
        "q_period_rows_used": q_rows,
    }


def _rnoff_q_rows_by_cell(
    request: NativeUnsfinDryRunRequest,
) -> tuple[dict[int, list[dict[str, Any]]] | None, int | None, str | None]:
    manifest = _contract_manifest(request.rnoff_contract)
    if manifest is None:
        return None, None, "missing RNOFF pre-DFS precompute contract"
    periods = manifest.get("periods")
    if not isinstance(periods, list) or not periods:
        return None, None, "contract periods must be a nonempty list"
    cell_count = int(manifest.get("imax") or periods[0].get("cell_count") or 0)
    if cell_count <= 0:
        return None, None, "contract cell_count must be positive"
    kst, error = _coerce_one_based_values(request.rnoff_contract_kst, name="kst", cell_count=cell_count)
    if error is not None:
        return None, None, error
    rikzero, error = _coerce_one_based_values(
        request.rnoff_contract_rikzero,
        name="rikzero",
        cell_count=cell_count,
    )
    if error is not None:
        return None, None, error

    rows_by_cell: dict[int, list[dict[str, Any]]] = {}
    for period in periods:
        if not isinstance(period, dict):
            return None, None, "contract period entries must be objects"
        period_index = int(period.get("period_index") or 0)
        rik_values, error = _coerce_one_based_values(
            period.get("rik_period"),
            name=f"rik_period[{period_index}]",
            cell_count=cell_count,
        )
        if error is not None:
            return None, None, error
        for cell_id in sorted(rik_values):
            if cell_id not in kst:
                return None, None, f"missing kst for one-based cell id {cell_id}"
            if cell_id not in rikzero:
                return None, None, f"missing rikzero for one-based cell id {cell_id}"
            kst_value = kst[cell_id]
            rik_value = rik_values[cell_id]
            rikzero_value = rikzero[cell_id]
            q_before_cap = (
                kst_value * (rik_value + rikzero_value)
                if request.rnoff_contract_bkgrof
                else kst_value * rik_value
            )
            q_after_cap = min(q_before_cap, kst_value)
            rows_by_cell.setdefault(cell_id, []).append(
                {
                    "period": period_index,
                    "one_based_cell_id": cell_id,
                    "kst": kst_value,
                    "rik": rik_value,
                    "rikzero": rikzero_value,
                    "q_before_cap": q_before_cap,
                    "q_after_cap": q_after_cap,
                    "cap_applied": q_after_cap != q_before_cap,
                    "bkgrof": bool(request.rnoff_contract_bkgrof),
                }
            )
    for rows in rows_by_cell.values():
        rows.sort(key=lambda row: int(row["period"]))
    return rows_by_cell, cell_count, None


def default_rnoff_schedule_generator(
    request: NativeUnsfinDryRunRequest,
    q_rows_by_cell: Mapping[int, Sequence[Mapping[str, Any]]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from tools.diagnostics.native_unsfin_analytic_cell import (
        build_active_context,
        eligibility_for_cell,
        make_field_pack_for_cell,
        native_tfirst_search_cell,
        roota,
        rootb,
        rootc,
        unsfin_coefficients,
    )

    context = build_active_context(request.case_dir)
    active_count = len(context.slope_values_deg)
    targets, error = _coerce_target_cells(request.rnoff_schedule_target_cells, cell_count=active_count)
    if error is not None:
        raise ValueError(error)
    rows: list[dict[str, Any]] = []
    root_cache: dict[tuple[float, float, float, float, float], tuple[Any, Any, Any, Any]] = {}
    for cell_id in targets or []:
        eligible, reason = eligibility_for_cell(context, cell_id)
        mapping = context.active_mapping[cell_id - 1] if 0 <= cell_id - 1 < len(context.active_mapping) else ("", "")
        row_index, col_index = mapping if isinstance(mapping, tuple) else ("", "")
        zone = int(context.zone_values[cell_id - 1]) if 0 <= cell_id - 1 < len(context.zone_values) else None
        slope = float(context.slope_values_deg[cell_id - 1]) if 0 <= cell_id - 1 < len(context.slope_values_deg) else None
        q_rows = list(q_rows_by_cell.get(cell_id, []))
        if not eligible:
            event_type = _skip_event_type(reason)
            rows.append(
                {
                    "case": request.case_dir.name,
                    "one_based_cell_id": cell_id,
                    "active_row_index": row_index,
                    "active_col_index": col_index,
                    "period": int(q_rows[-1]["period"]) if q_rows else 0,
                    "zone": zone,
                    "slope_deg": slope,
                    "q_period_count": 0,
                    "q_after_cap": np.nan,
                    "tfail": 0.0,
                    "gindx": 0,
                    "fdepth": 0.0,
                    "branch": event_type,
                    "event_type": event_type,
                    "skip_reason": reason,
                    "source": "provider_rnoff_schedule_dry_run",
                }
            )
            continue
        if not q_rows:
            raise ValueError(f"missing q diagnostics for eligible one-based cell id {cell_id}")
        pack = make_field_pack_for_cell(context, cell_id)
        q_period = [float(row["q_after_cap"]) for row in q_rows]
        rikzero = float(q_rows[0]["rikzero"])
        pack = replace(pack, q=q_period, rikzero=rikzero)
        root_key = (pack.beta, pack.lt, pack.lb, pack.zone.kst, pack.zone.ksb)
        cached = root_cache.get(root_key)
        if cached is None:
            roots_a = roota(10, pack.beta, pack.lt, pack.lb, pack.zone.kst, pack.zone.ksb)
            roots_b = rootb(10, pack.beta, pack.lt, pack.lb, pack.zone.kst, pack.zone.ksb)
            roots_c = rootc(10, pack.beta, pack.lt, pack.lb, pack.zone.kst, pack.zone.ksb)
            coeffs = unsfin_coefficients(
                roots_a,
                roots_b,
                roots_c,
                beta=pack.beta,
                lt=pack.lt,
                lb=pack.lb,
                kst=pack.zone.kst,
                ksb=pack.zone.ksb,
            )
            root_cache[root_key] = (roots_a, roots_b, roots_c, coeffs)
        else:
            roots_a, roots_b, roots_c, coeffs = cached
        _trace, native = native_tfirst_search_cell(
            pack,
            roots_a,
            roots_b,
            roots_c,
            coeffs,
            initial_ts=float(request.rnoff_schedule_initial_ts),
            collect_trace=False,
        )
        branch = str(native.get("exit_reason", ""))
        event_type = "TFailAssignment" if branch == "tfail_assigned" else "NoFailureInSearch"
        last_q = q_rows[-1]
        rows.append(
            {
                "case": request.case_dir.name,
                "one_based_cell_id": cell_id,
                "active_row_index": row_index,
                "active_col_index": col_index,
                "period": int(last_q["period"]),
                "zone": zone,
                "slope_deg": slope,
                "kst": float(last_q["kst"]),
                "rik": float(last_q["rik"]),
                "rikzero": float(last_q["rikzero"]),
                "q_before_cap": float(last_q["q_before_cap"]),
                "q_after_cap": float(last_q["q_after_cap"]),
                "cap_applied": bool(last_q["cap_applied"]),
                "q_period_count": len(q_rows),
                "tfail": float(native.get("tfail", 0.0) or 0.0),
                "gindx": int(native.get("gindx", 0)),
                "fdepth": float(native.get("fdepth", 0.0) or 0.0),
                "branch": branch,
                "event_type": event_type,
                "fsmin": native.get("fsmin"),
                "iterations": native.get("iterations"),
                "refinements": native.get("refinement_count"),
                "source": "provider_rnoff_schedule_dry_run",
            }
        )
    return rows, _summarize_schedule_rows(rows)


def _prepare_rnoff_provider_feed(
    request: NativeUnsfinDryRunRequest,
) -> tuple[dict[str, Any] | None, str | None, str | None]:
    manifest = _contract_manifest(request.rnoff_contract)
    if manifest is None:
        return None, RNOFF_CONTRACT_MISSING_REASON, "missing RNOFF pre-DFS precompute contract"
    if request.rnoff_q_runtime_oracle_status not in ACCEPTED_RNOFF_Q_ORACLE_STATUSES:
        return (
            None,
            RNOFF_Q_ORACLE_NOT_ACCEPTED_REASON,
            f"q_runtime_oracle_status={request.rnoff_q_runtime_oracle_status!r}",
        )
    if manifest.get("sidecar_shape_validated") is not True:
        return None, RNOFF_CONTRACT_INVALID_REASON, "contract sidecar_shape_validated must be true"
    if manifest.get("runtime_mutation") is not False:
        return None, RNOFF_CONTRACT_INVALID_REASON, "contract runtime_mutation must be false"
    periods = manifest.get("periods")
    if not isinstance(periods, list) or not periods:
        return None, RNOFF_CONTRACT_INVALID_REASON, "contract periods must be a nonempty list"

    cell_count = int(manifest.get("imax") or periods[0].get("cell_count") or 0)
    if cell_count <= 0:
        return None, RNOFF_CONTRACT_INVALID_REASON, "contract cell_count must be positive"
    kst, error = _coerce_one_based_values(request.rnoff_contract_kst, name="kst", cell_count=cell_count)
    if error is not None:
        return None, RNOFF_CONTRACT_INVALID_REASON, error
    rikzero, error = _coerce_one_based_values(
        request.rnoff_contract_rikzero,
        name="rikzero",
        cell_count=cell_count,
    )
    if error is not None:
        return None, RNOFF_CONTRACT_INVALID_REASON, error

    cap_applied_count = 0
    row_count = 0
    q_after_min: float | None = None
    q_after_max: float | None = None
    sample_rows: list[dict[str, Any]] = []
    for period in periods:
        if not isinstance(period, dict):
            return None, RNOFF_CONTRACT_INVALID_REASON, "contract period entries must be objects"
        period_index = int(period.get("period_index") or 0)
        rik_values, error = _coerce_one_based_values(
            period.get("rik_period"),
            name=f"rik_period[{period_index}]",
            cell_count=cell_count,
        )
        if error is not None:
            return None, RNOFF_CONTRACT_INVALID_REASON, error
        for cell_id in sorted(rik_values):
            if cell_id not in kst:
                return None, RNOFF_CONTRACT_INVALID_REASON, f"missing kst for one-based cell id {cell_id}"
            if cell_id not in rikzero:
                return None, RNOFF_CONTRACT_INVALID_REASON, f"missing rikzero for one-based cell id {cell_id}"
            kst_value = kst[cell_id]
            rik_value = rik_values[cell_id]
            rikzero_value = rikzero[cell_id]
            q_before_cap = kst_value * (rik_value + rikzero_value) if request.rnoff_contract_bkgrof else kst_value * rik_value
            q_after_cap = min(q_before_cap, kst_value)
            cap_applied = q_after_cap != q_before_cap
            cap_applied_count += int(cap_applied)
            row_count += 1
            q_after_min = q_after_cap if q_after_min is None else min(q_after_min, q_after_cap)
            q_after_max = q_after_cap if q_after_max is None else max(q_after_max, q_after_cap)
            if len(sample_rows) < 20:
                sample_rows.append(
                    {
                        "period": period_index,
                        "one_based_cell_id": cell_id,
                        "kst": kst_value,
                        "rik": rik_value,
                        "rikzero": rikzero_value,
                        "q_before_cap": q_before_cap,
                        "q_after_cap": q_after_cap,
                        "cap_applied": cap_applied,
                    }
                )

    return (
        {
            "rnoff_contract_loaded": True,
            "rik_period_loaded": True,
            "q_formula_validated": True,
            "q_runtime_oracle_status": request.rnoff_q_runtime_oracle_status,
            "fallback_reason": None,
            "native_unsfin_rnoff_feed_active": True,
            "schedule_generated_with_rnoff": False,
            "provider_schedule_generation_active": False,
            "dfs_runtime_feed_blocked": True,
            "final_state_mutated": False,
            "rnoff_provider_feed": {
                "semantic_payload": "rik_period",
                "q_payload_role": "diagnostic_check_only",
                "period_count": len(periods),
                "cell_count": cell_count,
                "q_diagnostic_row_count": row_count,
                "cap_applied_count": cap_applied_count,
                "bkgrof": bool(request.rnoff_contract_bkgrof),
                "q_after_cap_min": q_after_min,
                "q_after_cap_max": q_after_max,
                "q_diagnostic_sample_rows": sample_rows,
            },
        },
        None,
        None,
    )


def _git_head() -> str | None:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def _file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _artifact_entry(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "exists": path.exists(),
        "bytes": path.stat().st_size if path.exists() else 0,
        "sha256": _file_sha256(path) if path.exists() else None,
    }


def _blocked_result(
    request: NativeUnsfinDryRunRequest,
    *,
    reason: str,
    detail: str | None = None,
) -> NativeUnsfinProviderResult:
    meta = _base_meta(request)
    meta.update(
        {
            "status": "blocked",
            "blocked_reason": reason,
            "blocked_detail": detail,
            "fallback_reason": reason,
            "schedule_generated": False,
            "schedule_validated": False,
            "schedule_consumed_by_dfs": False,
        }
    )
    return NativeUnsfinProviderResult(
        status="blocked",
        provider_available=True,
        provider_selected=request.provider_selected,
        dry_run_enabled=request.dry_run_enabled,
        runtime_feed_enabled=request.runtime_feed_enabled,
        schedule_generated=False,
        schedule_validated=False,
        schedule_consumed_by_dfs=False,
        blocked_reason=reason,
        meta=meta,
        manifest=None,
        artifact_paths={},
    )


def _base_meta(request: NativeUnsfinDryRunRequest) -> dict[str, Any]:
    return {
        "provider": PROVIDER_NAME,
        "mode": MODE_DRY_RUN,
        "provider_available": True,
        "provider_selected": bool(request.provider_selected),
        "dry_run_enabled": bool(request.dry_run_enabled),
        "runtime_feed_enabled": bool(request.runtime_feed_enabled),
        "rnoff_native_unsfin_feed_enabled": bool(request.rnoff_native_unsfin_feed_enabled),
        "rnoff_contract_loaded": False,
        "rik_period_loaded": False,
        "q_formula_validated": False,
        "q_runtime_oracle_status": request.rnoff_q_runtime_oracle_status,
        "native_unsfin_rnoff_feed_active": False,
        "schedule_generated_with_rnoff": False,
        "provider_schedule_generation_active": False,
        "dfs_runtime_feed_blocked": False,
        "final_state_mutated": False,
        "fallback_reason": None,
        "schedule_generated": False,
        "schedule_validated": False,
        "schedule_consumed_by_dfs": False,
        "source_provenance": SOURCE_PROVENANCE,
        "output_inferred": False,
        "active_order_mode": True,
        "per_cell_fitted_ts": False,
        "dfs_runtime_modified": False,
        "rootc_deltamiu_default_real": True,
        "full_window_s": float(request.ledger_window_s),
        "case_dir": str(request.case_dir),
        "output_dir": str(request.output_dir),
        "checkpoint_dir": str(request.checkpoint_dir) if request.checkpoint_dir else None,
        "resume": bool(request.resume),
        "git_head": _git_head(),
        "legacy_parity_flags": {
            "EDDA_LEGACY_PARITY_MODE": os.environ.get("EDDA_LEGACY_PARITY_MODE"),
            "EDDA_LEGACY_CVBAR_EROSION_PARITY": os.environ.get("EDDA_LEGACY_CVBAR_EROSION_PARITY"),
            "EDDA_EXPERIMENT_CVBAR_EROSION_PARITY": os.environ.get("EDDA_EXPERIMENT_CVBAR_EROSION_PARITY"),
            "EDDA_EXPERIMENT_FIRST_REJECT_SHORT_CIRCUIT": os.environ.get("EDDA_EXPERIMENT_FIRST_REJECT_SHORT_CIRCUIT"),
        },
    }


def validate_provider_metadata(meta: dict[str, Any]) -> tuple[bool, str | None]:
    if meta.get("provider") != PROVIDER_NAME:
        return False, "provider must be production_native_unsfin"
    if meta.get("source_provenance") != SOURCE_PROVENANCE:
        return False, "source_provenance must be production_native_unsfin"
    if meta.get("output_inferred") is not False:
        return False, "output_inferred must be false"
    if meta.get("runtime_feed_enabled") is not False:
        return False, "runtime_feed_enabled must be false in dry-run phase"
    if meta.get("schedule_consumed_by_dfs") is not False:
        return False, "schedule_consumed_by_dfs must be false in dry-run phase"
    if meta.get("final_state_mutated") is not False:
        return False, "final_state_mutated must be false in dry-run phase"
    if meta.get("schedule_generated_with_rnoff") is not False:
        if meta.get("provider_schedule_generation_active") is not True:
            return False, "schedule_generated_with_rnoff requires provider_schedule_generation_active"
        if meta.get("runtime_feed_enabled") is not False:
            return False, "RNOFF schedule-generation diagnostics must remain runtime-feed disabled"
        if meta.get("schedule_consumed_by_dfs") is not False:
            return False, "RNOFF schedule-generation diagnostics must not be consumed by DFS"
        if meta.get("final_state_mutated") is not False:
            return False, "RNOFF schedule-generation diagnostics must not mutate final state"
        if meta.get("dfs_runtime_feed_blocked") is not True:
            return False, "RNOFF schedule-generation diagnostics must keep DFS runtime feed blocked"
    if meta.get("active_order_mode") is not True:
        return False, "active_order_mode must be true"
    if meta.get("per_cell_fitted_ts") is not False:
        return False, "per_cell_fitted_ts must be false"
    return True, None


def _same_resolved_path(left: Any, right: Any) -> bool:
    try:
        return Path(left).resolve() == Path(right).resolve()
    except Exception:
        return str(left) == str(right)


def _validate_loaded_artifact_runtime_compatibility(
    meta: dict[str, Any],
    request: NativeUnsfinDryRunRequest,
) -> tuple[bool, str | None]:
    artifact_case_dir = meta.get("case_dir")
    if artifact_case_dir and not _same_resolved_path(artifact_case_dir, request.case_dir):
        return (
            False,
            "provider artifact case_dir does not match current runtime case_dir: "
            f"artifact={artifact_case_dir!r}; runtime={str(request.case_dir)!r}",
        )
    artifact_window = meta.get("full_window_s")
    if artifact_window is not None:
        try:
            if float(artifact_window) + 1.0e-9 < float(request.ledger_window_s):
                return (
                    False,
                    "provider artifact full_window_s is shorter than current runtime ledger_window_s: "
                    f"artifact={artifact_window!r}; runtime={request.ledger_window_s!r}",
                )
        except Exception:
            return False, f"provider artifact full_window_s is not numeric: {artifact_window!r}"
    return True, None


def _blocked_runtime_result(
    request: NativeUnsfinDryRunRequest,
    *,
    reason: str,
    detail: str | None = None,
    provider_selected: bool | None = None,
    runtime_feed_enabled: bool | None = None,
) -> NativeUnsfinRuntimeFeedResult:
    meta = _base_meta(request)
    meta.update(
        {
            "mode": MODE_RUNTIME_SMOKE,
            "status": "blocked",
            "provider_selected": bool(request.provider_selected if provider_selected is None else provider_selected),
            "runtime_feed_enabled": bool(
                request.runtime_feed_enabled if runtime_feed_enabled is None else runtime_feed_enabled
            ),
            "schedule_generated": False,
            "schedule_validated": False,
            "schedule_configured_into_solver": False,
            "schedule_consumed_by_dfs": False,
            "blocked_reason": reason,
            "blocked_detail": detail,
        }
    )
    return NativeUnsfinRuntimeFeedResult(
        status="blocked",
        provider_available=True,
        provider_selected=bool(meta["provider_selected"]),
        dry_run_enabled=bool(request.dry_run_enabled),
        runtime_feed_enabled=bool(meta["runtime_feed_enabled"]),
        schedule_generated=False,
        schedule_validated=False,
        schedule_configured_into_solver=False,
        schedule_consumed_by_dfs=False,
        blocked_reason=reason,
        meta=meta,
        manifest=None,
        artifact_paths={},
    )


def _load_npz_array(path: Path, key: str) -> np.ndarray:
    with np.load(path) as loaded:
        if key not in loaded:
            raise KeyError(f"{path} does not contain key {key!r}")
        return np.asarray(loaded[key])


def load_provider_dry_run_artifacts(artifact_dir: Path) -> tuple[LedgerArrays, dict[str, Any], dict[str, str]]:
    artifact_dir = Path(artifact_dir)
    paths = {
        "gindx": artifact_dir / "provider_dry_run_gindx.npz",
        "tfail_s": artifact_dir / "provider_dry_run_tfail_s.npz",
        "fdepth_m": artifact_dir / "provider_dry_run_fdepth_m.npz",
        "meta": artifact_dir / "provider_dry_run_meta.json",
        "manifest": artifact_dir / "provider_dry_run_manifest.json",
    }
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise FileNotFoundError(f"missing provider dry-run artifacts: {missing}")

    meta = json.loads(paths["meta"].read_text(encoding="utf-8"))
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    for key in ("gindx", "tfail_s", "fdepth_m"):
        expected_hash = ((manifest.get("artifacts") or {}).get(key) or {}).get("sha256")
        if expected_hash and _file_sha256(paths[key]) != expected_hash:
            raise ValueError(f"{key} artifact hash does not match provider manifest")

    ledger = LedgerArrays(
        gindx=np.asarray(_load_npz_array(paths["gindx"], "gindx"), dtype=np.int32),
        tfail_s=np.asarray(_load_npz_array(paths["tfail_s"], "tfail_s"), dtype=np.float64),
        fdepth_m=np.asarray(_load_npz_array(paths["fdepth_m"], "fdepth_m"), dtype=np.float64),
        fsdepth_m=None,
        meta=meta,
    )
    return ledger, manifest, {key: str(path) for key, path in paths.items()}


def _solver_shape(solver: Any) -> tuple[int, int]:
    fields = getattr(solver, "fields", None)
    if fields is None:
        raise ValueError("solver fields are not initialized")
    return int(fields.nx), int(fields.ny)


def _solver_dem_file(solver: Any) -> Path:
    config = getattr(solver, "config", None)
    dem_file = getattr(config, "dem_file", None)
    if dem_file is None:
        raise ValueError("solver config does not expose dem_file")
    return Path(dem_file)


def _active_vector_to_solver_grid(vector: np.ndarray, *, dem_file: Path, solver_shape: tuple[int, int]) -> np.ndarray:
    from edda.io.spatial_input_loader import SpatialInputLoader

    dem_grid, dem_metadata = SpatialInputLoader(str(dem_file)).read()
    nodata = dem_metadata.get("nodata")
    if nodata is None:
        valid_mask = np.isfinite(dem_grid)
    else:
        valid_mask = ~np.isclose(dem_grid, nodata)
    valid_count = int(np.count_nonzero(valid_mask))
    vector = np.asarray(vector)
    if vector.size != valid_count:
        raise ValueError(f"active-cell vector length {vector.size} does not match DEM valid-cell count {valid_count}")
    dem_grid_values = np.zeros(dem_grid.shape, dtype=np.float64)
    dem_grid_values[valid_mask] = vector.astype(np.float64, copy=False)
    solver_grid = dem_grid_values.T
    if solver_grid.shape != solver_shape:
        raise ValueError(f"mapped solver grid shape {solver_grid.shape} does not match solver shape {solver_shape}")
    return solver_grid


def _ledger_to_solver_arrays(
    ledger: LedgerArrays,
    *,
    solver: Any,
    dem_file: Path | None = None,
) -> dict[str, np.ndarray]:
    solver_shape = _solver_shape(solver)
    dem_file = dem_file or _solver_dem_file(solver)

    def convert(array: np.ndarray, name: str) -> np.ndarray:
        values = np.asarray(array)
        if values.ndim == 1:
            return _active_vector_to_solver_grid(values, dem_file=dem_file, solver_shape=solver_shape)
        if values.shape == solver_shape:
            return values.astype(np.float64, copy=False)
        if values.ndim == 2 and values.T.shape == solver_shape:
            return values.T.astype(np.float64, copy=False)
        raise ValueError(f"{name} shape {values.shape} cannot be mapped to solver shape {solver_shape}")

    return {
        "gindx": convert(ledger.gindx, "gindx").astype(np.int32, copy=False),
        "tfail_s": convert(ledger.tfail_s, "tfail_s").astype(np.float64, copy=False),
        "fdepth_m": convert(ledger.fdepth_m, "fdepth_m").astype(np.float64, copy=False),
    }


def _provider_schedule_rows_to_solver_arrays(
    schedule_rows: Sequence[Mapping[str, Any]],
    *,
    solver: Any,
    dem_file: Path | None = None,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    solver_shape = _solver_shape(solver)
    fields = getattr(solver, "fields", None)
    cell_id_field = getattr(fields, "cell_id", None)
    cell_id_grid = None
    if cell_id_field is not None and hasattr(cell_id_field, "to_numpy"):
        cell_id_grid = np.asarray(cell_id_field.to_numpy(), dtype=np.int64)
        if cell_id_grid.shape != solver_shape:
            cell_id_grid = None

    dem_file = dem_file or _solver_dem_file(solver)
    active_count = None
    if cell_id_grid is None:
        from edda.io.spatial_input_loader import SpatialInputLoader

        dem_grid, dem_metadata = SpatialInputLoader(str(dem_file)).read()
        nodata = dem_metadata.get("nodata")
        valid_mask = np.isfinite(dem_grid) if nodata is None else ~np.isclose(dem_grid, nodata)
        active_count = int(np.count_nonzero(valid_mask))

    tfail_vector = np.zeros(active_count or 0, dtype=np.float64)
    gindx_vector = np.zeros(active_count or 0, dtype=np.int32)
    fdepth_vector = np.zeros(active_count or 0, dtype=np.float64)
    tfail_grid = np.zeros(solver_shape, dtype=np.float64)
    gindx_grid = np.zeros(solver_shape, dtype=np.int32)
    fdepth_grid = np.zeros(solver_shape, dtype=np.float64)

    gindx_zero_no_feed = 0
    inactive_no_feed = 0
    malformed_no_feed = 0
    duplicate_active = 0
    consumed_cell_ids: set[int] = set()
    diagnostic_rows = 0

    for row in schedule_rows:
        diagnostic_rows += 1
        try:
            cell_id = int(float(row.get("one_based_cell_id") or row.get("cell_id") or 0))
            gindx_value = int(float(row.get("gindx") or 0))
            tfail_value = float(row.get("tfail", row.get("tfail_s", 0.0)))
            fdepth_value = float(row.get("fdepth", row.get("fdepth_m", 0.0)))
        except (TypeError, ValueError):
            malformed_no_feed += 1
            continue
        if cell_id <= 0:
            malformed_no_feed += 1
            continue
        if gindx_value <= 0:
            gindx_zero_no_feed += 1
            continue
        if not np.isfinite(tfail_value) or tfail_value <= 0.0 or not np.isfinite(fdepth_value) or fdepth_value <= 0.0:
            inactive_no_feed += 1
            continue
        if cell_id in consumed_cell_ids:
            duplicate_active += 1
            raise ValueError(f"duplicate active RNOFF schedule row for one-based cell id {cell_id}")
        consumed_cell_ids.add(cell_id)

        if cell_id_grid is not None:
            mask = cell_id_grid == cell_id
            if not np.any(mask):
                malformed_no_feed += 1
                consumed_cell_ids.remove(cell_id)
                continue
            tfail_grid[mask] = tfail_value
            gindx_grid[mask] = 1
            fdepth_grid[mask] = fdepth_value
        else:
            if active_count is None or cell_id > active_count:
                malformed_no_feed += 1
                consumed_cell_ids.remove(cell_id)
                continue
            index = cell_id - 1
            tfail_vector[index] = tfail_value
            gindx_vector[index] = 1
            fdepth_vector[index] = fdepth_value

    if cell_id_grid is None:
        tfail_grid = _active_vector_to_solver_grid(tfail_vector, dem_file=dem_file, solver_shape=solver_shape)
        gindx_grid = _active_vector_to_solver_grid(gindx_vector, dem_file=dem_file, solver_shape=solver_shape).astype(
            np.int32,
            copy=False,
        )
        fdepth_grid = _active_vector_to_solver_grid(fdepth_vector, dem_file=dem_file, solver_shape=solver_shape)

    summary = {
        "schedule_diagnostic_row_count": diagnostic_rows,
        "consumed_schedule_row_count": int(len(consumed_cell_ids)),
        "gindx_zero_no_feed_count": int(gindx_zero_no_feed),
        "inactive_or_nonpositive_tfail_no_feed_count": int(inactive_no_feed),
        "malformed_no_feed_count": int(malformed_no_feed),
        "duplicate_active_row_count": int(duplicate_active),
        "semantic_payload": "tfail/gindx/fdepth",
        "q_payload_role": "diagnostic_check_only",
        "fdepth_consumption_rule": "gindx==1 and tfail>0 and fdepth>0 only",
        "gindx_zero_fdepth_role": "diagnostic_only_do_not_feed",
    }
    return (
        {
            "tfail_s": tfail_grid.astype(np.float64, copy=False),
            "gindx": gindx_grid.astype(np.int32, copy=False),
            "fdepth_m": fdepth_grid.astype(np.float64, copy=False),
        },
        summary,
    )


def _validate_runtime_schedule(meta: dict[str, Any], ledger: LedgerArrays) -> tuple[bool, str | None]:
    valid, reason = validate_provider_metadata(meta)
    if not valid:
        return False, reason
    if meta.get("performance_truncated") is True:
        return False, "performance_truncated must be false before runtime feed"
    if ledger.gindx.shape != ledger.tfail_s.shape or ledger.gindx.shape != ledger.fdepth_m.shape:
        return False, "provider schedule array shapes must match"
    if np.count_nonzero(np.asarray(ledger.gindx) > 0) <= 0:
        return False, "provider gindx has no positive cells"
    if np.count_nonzero(np.isfinite(ledger.tfail_s) & (ledger.tfail_s > 0.0)) <= 0:
        return False, "provider tfail has no positive finite cells"
    return True, None


def configure_provider_runtime_feed(
    solver: Any,
    request: NativeUnsfinDryRunRequest,
    *,
    env: dict[str, str] | None = None,
    artifact_dir: Path | None = None,
    generator: GeneratorFn | None = None,
    rnoff_schedule_generator: RnoffScheduleGeneratorFn | None = None,
) -> NativeUnsfinRuntimeFeedResult:
    env_source = env if env is not None else os.environ
    project_cuda_backend_stage1_enabled = project_cuda_backend_stage1_flag_enabled(env_source)
    runtime_flag = runtime_feed_flag_enabled(env_source)
    provider_selected = bool(request.provider_selected or runtime_flag)
    if not runtime_flag:
        return _blocked_runtime_result(
            request,
            reason=RUNTIME_FEED_FLAG_DISABLED_REASON,
            provider_selected=provider_selected,
            runtime_feed_enabled=False,
        )
    if not provider_selected:
        return _blocked_runtime_result(request, reason=DISABLED_REASON, runtime_feed_enabled=True)
    if not request.dry_run_enabled:
        return _blocked_runtime_result(request, reason=DRY_RUN_DISABLED_REASON, runtime_feed_enabled=True)
    if request.rnoff_native_unsfin_feed_enabled:
        if not rnoff_native_unsfin_feed_flag_enabled(env_source):
            return _blocked_runtime_result(
                request,
                reason=RNOFF_NATIVE_FEED_FLAG_DISABLED_REASON,
                provider_selected=True,
                runtime_feed_enabled=True,
            )
        if not request.rnoff_provider_schedule_generation_enabled:
            return _blocked_runtime_result(
                request,
                reason=RNOFF_RUNTIME_FEED_SCHEDULE_NOT_SOURCE_BACKED_REASON,
                detail="RNOFF DFS runtime feed requires source-backed provider schedule generation",
                provider_selected=True,
                runtime_feed_enabled=True,
            )
        dry_request = replace(request, runtime_feed_enabled=False)
        dry_result = run_provider_dry_run(
            dry_request,
            generator=generator,
            rnoff_schedule_generator=rnoff_schedule_generator,
        )
        if not dry_result.ok:
            return _blocked_runtime_result(
                request,
                reason=dry_result.blocked_reason or GENERATION_FAILED_REASON,
                detail=dry_result.meta.get("blocked_detail"),
                provider_selected=True,
                runtime_feed_enabled=True,
            )
        schedule_json = dry_result.artifact_paths.get("rnoff_schedule_summary")
        if not schedule_json:
            return _blocked_runtime_result(
                request,
                reason=RNOFF_SCHEDULE_DIAGNOSTIC_FAILED_REASON,
                detail="provider RNOFF schedule summary artifact is missing",
                provider_selected=True,
                runtime_feed_enabled=True,
            )
        try:
            payload = json.loads(Path(schedule_json).read_text(encoding="utf-8"))
            schedule_rows = payload.get("rows")
            if not isinstance(schedule_rows, list):
                raise ValueError("provider RNOFF schedule rows are missing")
            arrays, feed_summary = _provider_schedule_rows_to_solver_arrays(schedule_rows, solver=solver)
            consumed_count = int(feed_summary.get("consumed_schedule_row_count", 0) or 0)
            if consumed_count <= 0:
                return _blocked_runtime_result(
                    request,
                    reason=SCHEDULE_VALIDATION_FAILED_REASON,
                    detail="RNOFF provider schedule contains no gindx=1 positive-tfail feed rows",
                    provider_selected=True,
                    runtime_feed_enabled=True,
            )
            taichi_field_feed_enabled = (
                _truthy(env_source.get(RNOFF_GPU_FIELD_FEED_ENV)) or project_cuda_backend_stage1_enabled
            )
            source_staging_field_enabled = (
                _truthy(env_source.get(DFS_SOURCE_STAGING_FIELD_ENV)) or project_cuda_backend_stage1_enabled
            )
            source_staging_fast_consume_enabled = (
                _truthy(env_source.get(DFS_SOURCE_STAGING_FAST_CONSUME_ENV)) or project_cuda_backend_stage1_enabled
            )
            source_staging_kernel_enabled = _truthy(env_source.get(DFS_SOURCE_STAGING_KERNEL_ENV))
            source_staging_kernel_required_gates_active = (
                _truthy(env_source.get(RNOFF_TOPOINDEX_ENV))
                and _truthy(env_source.get(RNOFF_NATIVE_UNSFIN_FEED_ENV))
                and runtime_feed_flag_enabled(dict(env_source))
                and taichi_field_feed_enabled
                and source_staging_field_enabled
                and source_staging_fast_consume_enabled
            )
            if (
                taichi_field_feed_enabled
                or source_staging_field_enabled
                or source_staging_fast_consume_enabled
                or source_staging_kernel_enabled
            ):
                schedule_info = solver.configure_precomputed_failure_schedule(
                    tfail_s=arrays["tfail_s"],
                    gindx=arrays["gindx"],
                    fdepth_m=arrays["fdepth_m"],
                    taichi_field_feed_enabled=taichi_field_feed_enabled,
                    source_staging_field_enabled=source_staging_field_enabled,
                    source_staging_fast_consume_enabled=source_staging_fast_consume_enabled,
                    source_staging_kernel_enabled=source_staging_kernel_enabled,
                    source_staging_kernel_required_gates_active=source_staging_kernel_required_gates_active,
                )
            else:
                schedule_info = solver.configure_precomputed_failure_schedule(
                    tfail_s=arrays["tfail_s"],
                    gindx=arrays["gindx"],
                    fdepth_m=arrays["fdepth_m"],
                )
            dfs_solver = getattr(solver, "dfs_dynamic_wave", None)
            if dfs_solver is not None and hasattr(dfs_solver, "dfs_failure_source_variant"):
                dfs_solver.dfs_failure_source_variant = "precomputed_unsfin_schedule"
        except Exception as exc:
            return _blocked_runtime_result(
                request,
                reason=SCHEDULE_CONFIGURATION_FAILED_REASON,
                detail=repr(exc),
                provider_selected=True,
                runtime_feed_enabled=True,
            )
        field_fallback_reason = (
            schedule_info.get("taichi_schedule_buffer_fallback_reason")
            if bool(schedule_info.get("rnoff_gpu_field_feed_gate_enabled", False))
            else None
        )
        project_cuda_backend_stage1_active = (
            project_cuda_backend_stage1_enabled
            and bool(schedule_info.get("rnoff_gpu_field_feed_active", False))
            and bool(schedule_info.get("dfs_source_staging_field_active", False))
            and bool(schedule_info.get("dfs_source_staging_fast_consume_gate_enabled", False))
        )
        project_cuda_backend_stage1_components = (
            list(PROJECT_CUDA_BACKEND_STAGE1_COMPONENTS) if project_cuda_backend_stage1_enabled else []
        )
        changed_field_names = [
            "dfs_dynamic_wave.precomputed_failure_tfail",
            "dfs_dynamic_wave.precomputed_failure_gindx",
            "dfs_dynamic_wave.precomputed_failure_fdepth",
            "dfs_dynamic_wave.dfs_failure_source_variant",
        ]
        if bool(schedule_info.get("rnoff_gpu_field_feed_active", False)):
            changed_field_names.extend(
                [
                    "dfs_dynamic_wave.precomputed_failure_tfail_field",
                    "dfs_dynamic_wave.precomputed_failure_gindx_field",
                    "dfs_dynamic_wave.precomputed_failure_fdepth_field",
                ]
            )
        if bool(schedule_info.get("dfs_source_staging_field_active", False)):
            changed_field_names.extend(
                [
                    "dfs_dynamic_wave.precomputed_failure_committed_fire_mask_field",
                    "dfs_dynamic_wave.precomputed_failure_source_depth_staging_field",
                    "dfs_dynamic_wave.precomputed_failure_source_density_staging_field",
                ]
            )
        runtime_meta = {
            **dry_result.meta,
            "mode": MODE_RUNTIME_SMOKE,
            "status": "configured",
            "provider_available": True,
            "provider_selected": True,
            "dry_run_enabled": True,
            "runtime_feed_enabled": True,
            "schedule_generated": True,
            "schedule_validated": True,
            "schedule_configured_into_solver": True,
            "schedule_consumed_by_dfs": consumed_count > 0,
            "rnoff_dfs_runtime_feed_active": consumed_count > 0,
            "dfs_runtime_feed_blocked": False,
            "final_state_mutated": consumed_count > 0,
            "blocked_reason": None,
            "fallback_reason": field_fallback_reason,
            "consumed_count": consumed_count,
            "committed_fire_count": 0,
            "committed_fired_count": 0,
            "duplicate_fire_count": 0,
            "rejected_step_discard_count": 0,
            "gindx_zero_no_feed_count": int(feed_summary.get("gindx_zero_no_feed_count", 0) or 0),
            "dfs_source_staging_field_gate_enabled": bool(schedule_info.get("dfs_source_staging_field_gate_enabled", False)),
            "dfs_source_staging_field_active": bool(schedule_info.get("dfs_source_staging_field_active", False)),
            "source_staging_field_roundtrip_ok": schedule_info.get("source_staging_field_roundtrip_ok"),
            "source_staging_cpu_vs_taichi_match": schedule_info.get("source_staging_cpu_vs_taichi_match"),
            "dfs_source_staging_fast_consume_gate_enabled": bool(
                schedule_info.get("dfs_source_staging_fast_consume_gate_enabled", False)
            ),
            "dfs_source_staging_fast_consume_active": bool(
                schedule_info.get("dfs_source_staging_fast_consume_active", False)
            ),
            "parity_validation_mode": schedule_info.get("parity_validation_mode"),
            "per_stage_parity_download_disabled": bool(
                schedule_info.get("per_stage_parity_download_disabled", False)
            ),
            "dfs_source_staging_kernel_gate_enabled": bool(
                schedule_info.get("dfs_source_staging_kernel_gate_enabled", False)
            ),
            "dfs_source_staging_kernel_required_gates_active": bool(
                schedule_info.get("dfs_source_staging_kernel_required_gates_active", False)
            ),
            "dfs_source_staging_kernel_active": bool(schedule_info.get("dfs_source_staging_kernel_active", False)),
            "source_staging_kernel_vs_cpu_match": schedule_info.get("source_staging_kernel_vs_cpu_match"),
            "kernel_fallback_active": bool(schedule_info.get("kernel_fallback_active", False)),
            "kernel_fallback_reason": schedule_info.get("kernel_fallback_reason"),
            "kernel_candidate_stage_count": int(schedule_info.get("kernel_candidate_stage_count", 0) or 0),
            "kernel_h2d_bytes": int(schedule_info.get("kernel_h2d_bytes", 0) or 0),
            "kernel_d2h_bytes": int(schedule_info.get("kernel_d2h_bytes", 0) or 0),
            "dfs_source_staging_field_fallback_reason": schedule_info.get("dfs_source_staging_field_fallback_reason"),
            "project_cuda_backend_stage1_gate_enabled": project_cuda_backend_stage1_enabled,
            "project_cuda_backend_stage1_active": project_cuda_backend_stage1_active,
            "project_cuda_backend_stage1_components": project_cuda_backend_stage1_components,
            "project_cuda_backend_stage1_field_lifecycle": PROJECT_CUDA_BACKEND_STAGE1_FIELD_LIFECYCLE,
            "cuda_backend_stage1_active": project_cuda_backend_stage1_active,
            "cuda_backend_stage1_component_count": len(project_cuda_backend_stage1_components),
            "transfer_bytes_h2d": int(schedule_info.get("transfer_bytes_h2d", 0) or 0),
            "transfer_bytes_d2h": int(schedule_info.get("transfer_bytes_d2h", 0) or 0),
            "rnoff_gpu_field_feed_gate_enabled": bool(schedule_info.get("rnoff_gpu_field_feed_gate_enabled", False)),
            "rnoff_gpu_field_feed_active": bool(schedule_info.get("rnoff_gpu_field_feed_active", False)),
            "schedule_buffer_uploaded_to_taichi": bool(schedule_info.get("schedule_buffer_uploaded_to_taichi", False)),
            "taichi_schedule_buffer_roundtrip_ok": schedule_info.get("taichi_schedule_buffer_roundtrip_ok"),
            "taichi_schedule_buffer_fallback_reason": schedule_info.get("taichi_schedule_buffer_fallback_reason"),
            "changed_field_names": changed_field_names if consumed_count > 0 else [],
            "rnoff_runtime_feed_summary": feed_summary,
            "runtime_schedule_info": schedule_info,
            "solver_schedule_shape": list(arrays["gindx"].shape),
            "rnoff_provider_schedule_artifact": schedule_json,
        }
        runtime_manifest = {
            **(dry_result.manifest or {}),
            "provider": PROVIDER_NAME,
            "mode": MODE_RUNTIME_SMOKE,
            "source_provenance": SOURCE_PROVENANCE,
            "runtime_feed_enabled": True,
            "rnoff_dfs_runtime_feed_active": consumed_count > 0,
            "schedule_consumed_by_dfs": consumed_count > 0,
            "schedule_configured_into_solver": True,
            "schedule_validated": True,
            "dfs_runtime_feed_blocked": False,
            "final_state_mutated": consumed_count > 0,
            "gindx_zero_no_feed_count": int(feed_summary.get("gindx_zero_no_feed_count", 0) or 0),
            "committed_fire_count": 0,
            "rejected_step_discard_count": 0,
            "duplicate_fire_count": 0,
            "changed_field_names": runtime_meta["changed_field_names"],
            "dfs_source_staging_field_gate_enabled": runtime_meta["dfs_source_staging_field_gate_enabled"],
            "dfs_source_staging_field_active": runtime_meta["dfs_source_staging_field_active"],
            "source_staging_field_roundtrip_ok": runtime_meta["source_staging_field_roundtrip_ok"],
            "source_staging_cpu_vs_taichi_match": runtime_meta["source_staging_cpu_vs_taichi_match"],
            "dfs_source_staging_fast_consume_gate_enabled": runtime_meta[
                "dfs_source_staging_fast_consume_gate_enabled"
            ],
            "dfs_source_staging_fast_consume_active": runtime_meta["dfs_source_staging_fast_consume_active"],
            "parity_validation_mode": runtime_meta["parity_validation_mode"],
            "per_stage_parity_download_disabled": runtime_meta["per_stage_parity_download_disabled"],
            "dfs_source_staging_field_fallback_reason": runtime_meta["dfs_source_staging_field_fallback_reason"],
            "project_cuda_backend_stage1_gate_enabled": runtime_meta["project_cuda_backend_stage1_gate_enabled"],
            "project_cuda_backend_stage1_active": runtime_meta["project_cuda_backend_stage1_active"],
            "project_cuda_backend_stage1_components": runtime_meta["project_cuda_backend_stage1_components"],
            "project_cuda_backend_stage1_field_lifecycle": runtime_meta[
                "project_cuda_backend_stage1_field_lifecycle"
            ],
            "cuda_backend_stage1_active": runtime_meta["cuda_backend_stage1_active"],
            "cuda_backend_stage1_component_count": runtime_meta["cuda_backend_stage1_component_count"],
            "transfer_bytes_h2d": runtime_meta["transfer_bytes_h2d"],
            "transfer_bytes_d2h": runtime_meta["transfer_bytes_d2h"],
            "rnoff_gpu_field_feed_gate_enabled": runtime_meta["rnoff_gpu_field_feed_gate_enabled"],
            "rnoff_gpu_field_feed_active": runtime_meta["rnoff_gpu_field_feed_active"],
            "schedule_buffer_uploaded_to_taichi": runtime_meta["schedule_buffer_uploaded_to_taichi"],
            "taichi_schedule_buffer_roundtrip_ok": runtime_meta["taichi_schedule_buffer_roundtrip_ok"],
            "taichi_schedule_buffer_fallback_reason": runtime_meta["taichi_schedule_buffer_fallback_reason"],
            "fallback_reason": field_fallback_reason,
            "blocked_reason": None,
        }
        return NativeUnsfinRuntimeFeedResult(
            status="configured",
            provider_available=True,
            provider_selected=True,
            dry_run_enabled=True,
            runtime_feed_enabled=True,
            schedule_generated=True,
            schedule_validated=True,
            schedule_configured_into_solver=True,
            schedule_consumed_by_dfs=consumed_count > 0,
            blocked_reason=None,
            meta=runtime_meta,
            manifest=runtime_manifest,
            artifact_paths=dict(dry_result.artifact_paths),
        )

    artifact_dir = artifact_dir or (
        Path(env_source[PROVIDER_ARTIFACT_DIR_ENV]) if env_source.get(PROVIDER_ARTIFACT_DIR_ENV) else None
    )
    if artifact_dir is not None:
        try:
            ledger, manifest, paths = load_provider_dry_run_artifacts(artifact_dir)
        except Exception as exc:
            return _blocked_runtime_result(
                request,
                reason=GENERATION_FAILED_REASON,
                detail=repr(exc),
                provider_selected=True,
                runtime_feed_enabled=True,
            )
        meta = dict(ledger.meta)
        compatible, detail = _validate_loaded_artifact_runtime_compatibility(meta, request)
        if not compatible:
            return _blocked_runtime_result(
                request,
                reason=PROVIDER_ARTIFACT_PROVENANCE_MISMATCH_REASON,
                detail=detail,
                provider_selected=True,
                runtime_feed_enabled=True,
            )
        if bool(meta.get("rnoff_native_unsfin_feed_enabled")) or bool(
            (manifest or {}).get("rnoff_native_unsfin_feed_enabled")
        ):
            return _blocked_runtime_result(
                request,
                reason=RNOFF_RUNTIME_FEED_SCHEDULE_NOT_SOURCE_BACKED_REASON,
                detail=(
                    "loaded provider artifact contains RNOFF diagnostics, but generated schedules "
                    "are dry-run only and are not source-backed as a DFS runtime feed"
                ),
                provider_selected=True,
                runtime_feed_enabled=True,
            )
    else:
        dry_request = NativeUnsfinDryRunRequest(
            case_dir=request.case_dir,
            output_dir=request.output_dir,
            provider_selected=True,
            dry_run_enabled=True,
            runtime_feed_enabled=False,
            ledger_window_s=request.ledger_window_s,
            checkpoint_dir=request.checkpoint_dir,
            resume=request.resume,
            checkpoint_interval=request.checkpoint_interval,
            metadata_overrides=request.metadata_overrides,
        )
        dry_result = run_provider_dry_run(dry_request, generator=generator)
        if not dry_result.ok:
            return _blocked_runtime_result(
                request,
                reason=dry_result.blocked_reason or GENERATION_FAILED_REASON,
                detail=dry_result.meta.get("blocked_detail"),
                provider_selected=True,
                runtime_feed_enabled=True,
            )
        try:
            ledger, manifest, paths = load_provider_dry_run_artifacts(request.output_dir)
        except Exception as exc:
            return _blocked_runtime_result(
                request,
                reason=GENERATION_FAILED_REASON,
                detail=repr(exc),
                provider_selected=True,
                runtime_feed_enabled=True,
            )
        meta = dict(dry_result.meta)

    valid, reason = _validate_runtime_schedule(meta, ledger)
    if not valid:
        return _blocked_runtime_result(
            request,
            reason=SCHEDULE_VALIDATION_FAILED_REASON,
            detail=reason,
            provider_selected=True,
            runtime_feed_enabled=True,
        )

    try:
        arrays = _ledger_to_solver_arrays(ledger, solver=solver)
        schedule_info = solver.configure_precomputed_failure_schedule(
            tfail_s=arrays["tfail_s"],
            gindx=arrays["gindx"],
            fdepth_m=arrays["fdepth_m"],
        )
    except Exception as exc:
        return _blocked_runtime_result(
            request,
            reason=SCHEDULE_CONFIGURATION_FAILED_REASON,
            detail=repr(exc),
            provider_selected=True,
            runtime_feed_enabled=True,
        )

    tfail_positive = int(np.count_nonzero(np.isfinite(ledger.tfail_s) & (ledger.tfail_s > 0.0)))
    gindx_positive = int(np.count_nonzero(np.asarray(ledger.gindx) > 0))
    fdepth_positive = int(np.count_nonzero(np.isfinite(ledger.fdepth_m) & (ledger.fdepth_m > 0.0)))
    runtime_meta = {
        **meta,
        "mode": MODE_RUNTIME_SMOKE,
        "status": "configured",
        "provider_available": True,
        "provider_selected": True,
        "dry_run_enabled": True,
        "runtime_feed_enabled": True,
        "schedule_generated": True,
        "schedule_validated": True,
        "schedule_configured_into_solver": True,
        "schedule_consumed_by_dfs": False,
        "blocked_reason": None,
        "tfail_positive_count": tfail_positive,
        "gindx_positive_count": gindx_positive,
        "fdepth_positive_count": fdepth_positive,
        "consumed_count": 0,
        "committed_fired_count": 0,
        "duplicate_fire_count": 0,
        "rejected_step_discard_count": 0,
        "total_staged_depth_sum": 0.0,
        "total_staged_mass_sum": 0.0,
        "runtime_schedule_info": schedule_info,
        "solver_schedule_shape": list(arrays["gindx"].shape),
    }
    runtime_manifest = {
        **(manifest or {}),
        "provider": PROVIDER_NAME,
        "mode": MODE_RUNTIME_SMOKE,
        "source_provenance": SOURCE_PROVENANCE,
        "runtime_feed_enabled": True,
        "schedule_consumed_by_dfs": False,
        "schedule_configured_into_solver": True,
        "schedule_validated": True,
        "output_inferred": False,
        "blocked_reason": None,
    }
    return NativeUnsfinRuntimeFeedResult(
        status="configured",
        provider_available=True,
        provider_selected=True,
        dry_run_enabled=True,
        runtime_feed_enabled=True,
        schedule_generated=True,
        schedule_validated=True,
        schedule_configured_into_solver=True,
        schedule_consumed_by_dfs=False,
        blocked_reason=None,
        meta=runtime_meta,
        manifest=runtime_manifest,
        artifact_paths=paths,
    )


def default_generator(request: NativeUnsfinDryRunRequest) -> tuple[LedgerArrays, dict[str, Any]]:
    from tools.diagnostics.native_unsfin_analytic_cell import run_active_order_0_600

    ledger, _active_trace, _gate_trace, summary = run_active_order_0_600(
        request.case_dir,
        checkpoint_dir=request.checkpoint_dir,
        resume=request.resume,
        checkpoint_interval=request.checkpoint_interval,
        ledger_window_s=request.ledger_window_s,
    )
    return ledger, summary


def run_provider_dry_run(
    request: NativeUnsfinDryRunRequest,
    *,
    generator: GeneratorFn | None = None,
    rnoff_schedule_generator: RnoffScheduleGeneratorFn | None = None,
) -> NativeUnsfinProviderResult:
    if not request.provider_selected:
        return _blocked_result(request, reason=DISABLED_REASON)
    if not request.dry_run_enabled:
        return _blocked_result(request, reason=DRY_RUN_DISABLED_REASON)
    if request.runtime_feed_enabled:
        return _blocked_result(request, reason=RUNTIME_FEED_BLOCKED_REASON)
    if request.ledger_window_s <= 0.0:
        return _blocked_result(request, reason=INVALID_METADATA_REASON, detail="ledger_window_s must be positive")
    if not request.case_dir.exists():
        return _blocked_result(request, reason=MISSING_INPUT_REASON, detail=f"missing case_dir: {request.case_dir}")
    if request.resume and request.checkpoint_dir is None:
        return _blocked_result(request, reason=MISSING_INPUT_REASON, detail="resume requires checkpoint_dir")
    if request.resume and request.checkpoint_dir is not None and not request.checkpoint_dir.exists():
        return _blocked_result(request, reason=MISSING_INPUT_REASON, detail=f"missing checkpoint_dir: {request.checkpoint_dir}")
    rnoff_feed_meta: dict[str, Any] = {}
    if request.rnoff_native_unsfin_feed_enabled:
        feed_meta, reason, detail = _prepare_rnoff_provider_feed(request)
        if reason is not None:
            return _blocked_result(request, reason=reason, detail=detail)
        rnoff_feed_meta = feed_meta or {}
    if request.rnoff_provider_schedule_generation_enabled:
        if not request.rnoff_native_unsfin_feed_enabled:
            return _blocked_result(
                request,
                reason=RNOFF_CONTRACT_MISSING_REASON,
                detail="RNOFF schedule generation requires an accepted RNOFF provider feed contract",
            )
        q_rows_by_cell, cell_count, error = _rnoff_q_rows_by_cell(request)
        if error is not None:
            return _blocked_result(request, reason=RNOFF_CONTRACT_INVALID_REASON, detail=error)
        target_cells, error = _coerce_target_cells(
            request.rnoff_schedule_target_cells,
            cell_count=int(cell_count or 0),
        )
        if error is not None:
            return _blocked_result(request, reason=RNOFF_SCHEDULE_TARGETS_MISSING_REASON, detail=error)

    generator = generator or default_generator
    try:
        ledger, summary = generator(request)
    except Exception as exc:
        return _blocked_result(request, reason=GENERATION_FAILED_REASON, detail=repr(exc))

    meta = _base_meta(request)
    meta.update(
        {
            "status": "generated",
            "schedule_generated": True,
            "schedule_validated": False,
            "schedule_consumed_by_dfs": False,
            "active_count": int(len(ledger.gindx)),
            "completed_active_count": int(ledger.meta.get("completed_active_count", len(ledger.gindx))),
            "eligible_count": int(ledger.meta.get("processed_eligible_cells", ledger.meta.get("eligible_cells_in_evaluated_range", 0))),
            "performance_truncated": bool(ledger.meta.get("performance_truncated", False)),
            "tfail_positive_count": int(np.count_nonzero(np.isfinite(ledger.tfail_s) & (ledger.tfail_s > 0.0) & (ledger.tfail_s <= request.ledger_window_s))),
            "gindx_positive_count": int(np.count_nonzero(ledger.gindx > 0)),
            "fdepth_positive_count": int(np.count_nonzero(np.isfinite(ledger.fdepth_m) & (ledger.fdepth_m > 0.0))),
            "diagnostic_source_provenance": ledger.meta.get("source_provenance"),
            "diagnostic_config_hash": ledger.meta.get("config_hash"),
            "diagnostic_summary": {
                key: summary.get(key)
                for key in (
                    "last_processed_active_index",
                    "next_active_index",
                    "ts_carry",
                    "processed_eligible_cells",
                    "candidate_count_window",
                    "wall_seconds",
                )
                if key in summary
            },
        }
    )
    meta.update(rnoff_feed_meta)
    schedule_rows: list[dict[str, Any]] = []
    schedule_summary: dict[str, Any] | None = None
    if request.rnoff_provider_schedule_generation_enabled:
        try:
            schedule_generator = rnoff_schedule_generator or default_rnoff_schedule_generator
            schedule_rows, schedule_summary = schedule_generator(request, q_rows_by_cell or {})
        except Exception as exc:
            return _blocked_result(request, reason=RNOFF_SCHEDULE_DIAGNOSTIC_FAILED_REASON, detail=repr(exc))
        meta.update(
            {
                "schedule_generated_with_rnoff": True,
                "provider_schedule_generation_active": True,
                "dfs_runtime_feed_blocked": True,
                "final_state_mutated": False,
                "schedule_consumed_by_dfs": False,
                "rnoff_provider_schedule": schedule_summary,
            }
        )
    meta.update(request.metadata_overrides)
    valid, reason = validate_provider_metadata(meta)
    if not valid:
        return _blocked_result(request, reason=INVALID_METADATA_REASON, detail=reason)

    request.output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "gindx": request.output_dir / "provider_dry_run_gindx.npz",
        "tfail_s": request.output_dir / "provider_dry_run_tfail_s.npz",
        "fdepth_m": request.output_dir / "provider_dry_run_fdepth_m.npz",
        "meta": request.output_dir / "provider_dry_run_meta.json",
        "manifest": request.output_dir / "provider_dry_run_manifest.json",
        "summary": request.output_dir / "provider_dry_run_summary.json",
    }
    if request.rnoff_provider_schedule_generation_enabled:
        paths["rnoff_schedule"] = request.output_dir / "provider_rnoff_schedule_diagnostics.csv"
        paths["rnoff_schedule_summary"] = request.output_dir / "provider_rnoff_schedule_diagnostics.json"
    np.savez_compressed(paths["gindx"], gindx=ledger.gindx)
    np.savez_compressed(paths["tfail_s"], tfail_s=ledger.tfail_s)
    np.savez_compressed(paths["fdepth_m"], fdepth_m=ledger.fdepth_m)
    array_hashes = {
        "gindx": _artifact_entry(paths["gindx"]),
        "tfail_s": _artifact_entry(paths["tfail_s"]),
        "fdepth_m": _artifact_entry(paths["fdepth_m"]),
    }
    meta["hashes"] = array_hashes
    paths["meta"].write_text(json.dumps(meta, indent=2), encoding="utf-8")
    manifest = {
        "provider": PROVIDER_NAME,
        "mode": MODE_DRY_RUN,
        "source_provenance": SOURCE_PROVENANCE,
        "runtime_feed_enabled": False,
        "rnoff_native_unsfin_feed_enabled": bool(request.rnoff_native_unsfin_feed_enabled),
        "rnoff_contract_loaded": bool(meta.get("rnoff_contract_loaded", False)),
        "rik_period_loaded": bool(meta.get("rik_period_loaded", False)),
        "q_formula_validated": bool(meta.get("q_formula_validated", False)),
        "q_runtime_oracle_status": meta.get("q_runtime_oracle_status"),
        "native_unsfin_rnoff_feed_active": bool(meta.get("native_unsfin_rnoff_feed_active", False)),
        "schedule_generated_with_rnoff": bool(meta.get("schedule_generated_with_rnoff", False)),
        "provider_schedule_generation_active": bool(meta.get("provider_schedule_generation_active", False)),
        "dfs_runtime_feed_blocked": bool(meta.get("dfs_runtime_feed_blocked", False)),
        "final_state_mutated": bool(meta.get("final_state_mutated", False)),
        "fallback_reason": meta.get("fallback_reason"),
        "rnoff_provider_feed": meta.get("rnoff_provider_feed"),
        "rnoff_provider_schedule": meta.get("rnoff_provider_schedule"),
        "schedule_consumed_by_dfs": False,
        "output_inferred": False,
        "artifacts": {**array_hashes, "meta": _artifact_entry(paths["meta"])},
        "blocked_reason": None,
    }
    if request.rnoff_provider_schedule_generation_enabled:
        _write_dict_csv(paths["rnoff_schedule"], schedule_rows)
        paths["rnoff_schedule_summary"].write_text(
            json.dumps(
                {
                    "provider": PROVIDER_NAME,
                    "mode": "rnoff_schedule_generation_dry_run",
                    "final_state_mutated": False,
                    "schedule_consumed_by_dfs": False,
                    "dfs_runtime_feed_blocked": True,
                    "summary": schedule_summary,
                    "rows": schedule_rows,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        manifest["artifacts"]["rnoff_schedule"] = _artifact_entry(paths["rnoff_schedule"])
        manifest["artifacts"]["rnoff_schedule_summary"] = _artifact_entry(paths["rnoff_schedule_summary"])
    paths["manifest"].write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    paths["summary"].write_text(
        json.dumps({"meta": meta, "manifest": manifest, "diagnostic_summary": summary}, indent=2),
        encoding="utf-8",
    )

    return NativeUnsfinProviderResult(
        status="generated",
        provider_available=True,
        provider_selected=True,
        dry_run_enabled=True,
        runtime_feed_enabled=False,
        schedule_generated=True,
        schedule_validated=False,
        schedule_consumed_by_dfs=False,
        blocked_reason=None,
        meta=meta,
        manifest=manifest,
        artifact_paths={key: str(value) for key, value in paths.items()},
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dry-run native unsfin provider")
    parser.add_argument("--case-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--provider", default=PROVIDER_NAME)
    parser.add_argument("--enable-provider", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--runtime-feed-enabled", action="store_true")
    parser.add_argument("--ledger-window-s", type=float, default=DEFAULT_FULL_WINDOW_S)
    parser.add_argument("--checkpoint-dir", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--checkpoint-interval", type=int, default=5000)
    args = parser.parse_args(argv)
    if args.provider != PROVIDER_NAME:
        request = NativeUnsfinDryRunRequest(
            case_dir=args.case_dir,
            output_dir=args.output_dir,
            provider_selected=False,
            dry_run_enabled=args.dry_run,
            runtime_feed_enabled=args.runtime_feed_enabled,
            ledger_window_s=args.ledger_window_s,
            checkpoint_dir=args.checkpoint_dir,
            resume=args.resume,
            checkpoint_interval=args.checkpoint_interval,
        )
        result = _blocked_result(request, reason=INVALID_METADATA_REASON, detail=f"unknown provider: {args.provider}")
    else:
        request = NativeUnsfinDryRunRequest(
            case_dir=args.case_dir,
            output_dir=args.output_dir,
            provider_selected=args.enable_provider,
            dry_run_enabled=args.dry_run,
            runtime_feed_enabled=args.runtime_feed_enabled,
            ledger_window_s=args.ledger_window_s,
            checkpoint_dir=args.checkpoint_dir,
            resume=args.resume,
            checkpoint_interval=args.checkpoint_interval,
        )
        result = run_provider_dry_run(request)
    print(json.dumps({"status": result.status, "blocked_reason": result.blocked_reason, "meta": result.meta, "artifact_paths": result.artifact_paths}, indent=2))
    return 0 if result.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
