from __future__ import annotations

import json

import numpy as np

from edda.solver.native_unsfin_provider import (
    DISABLED_REASON,
    GENERATION_FAILED_REASON,
    INVALID_METADATA_REASON,
    MISSING_INPUT_REASON,
    PROVIDER_NAME,
    RNOFF_CONTRACT_INVALID_REASON,
    RNOFF_CONTRACT_MISSING_REASON,
    RNOFF_NATIVE_UNSFIN_FEED_ENV,
    RNOFF_Q_ORACLE_NOT_ACCEPTED_REASON,
    RNOFF_RUNTIME_FEED_SCHEDULE_NOT_SOURCE_BACKED_REASON,
    RNOFF_SCHEDULE_TARGETS_MISSING_REASON,
    RNOFF_TOPOINDEX_ENV,
    RUNTIME_FEED_ENV,
    RUNTIME_FEED_FLAG_DISABLED_REASON,
    RUNTIME_FEED_BLOCKED_REASON,
    PROVIDER_ARTIFACT_PROVENANCE_MISMATCH_REASON,
    NativeUnsfinDryRunRequest,
    _skip_event_type,
    configure_provider_runtime_feed,
    rnoff_native_unsfin_feed_flag_enabled,
    run_provider_dry_run,
)
from tests.test_native_input_chain import _write_ascii_grid
from tools.diagnostics.native_unsfin_ledger_diagnostic import LedgerArrays


def _fake_generator(_request: NativeUnsfinDryRunRequest):
    ledger = LedgerArrays(
        gindx=np.array([1, 0, 1, 1], dtype=np.int32),
        tfail_s=np.array([10.0, np.nan, 600.0, 70000.0], dtype=np.float64),
        fdepth_m=np.array([3.0, 0.0, 3.0, 3.0], dtype=np.float64),
        fsdepth_m=None,
        meta={
            "source_provenance": "production_native_unsfin_ledger_only",
            "completed_active_count": 4,
            "processed_eligible_cells": 3,
            "performance_truncated": False,
            "config_hash": "fake-config",
        },
    )
    return ledger, {
        "last_processed_active_index": 4,
        "next_active_index": 5,
        "ts_carry": 60.0,
        "processed_eligible_cells": 3,
        "candidate_count_window": 2,
        "wall_seconds": 0.01,
    }


def _fake_rnoff_schedule_generator(request: NativeUnsfinDryRunRequest, q_rows_by_cell):
    rows = []
    for cell_id in request.rnoff_schedule_target_cells or []:
        q_rows = list(q_rows_by_cell.get(int(cell_id), []))
        if int(cell_id) == 2:
            rows.append(
                {
                    "case": "unit",
                    "one_based_cell_id": int(cell_id),
                    "period": 0,
                    "q_period_count": 0,
                    "q_after_cap": np.nan,
                    "tfail": 0.0,
                    "gindx": 0,
                    "fdepth": 0.0,
                    "branch": "SkippedSlopeGate",
                    "event_type": "SkippedSlopeGate",
                }
            )
            continue
        last_q = q_rows[-1]
        rows.append(
            {
                "case": "unit",
                "one_based_cell_id": int(cell_id),
                "period": int(last_q["period"]),
                "q_period_count": len(q_rows),
                "q_after_cap": float(last_q["q_after_cap"]),
                "tfail": 10.0,
                "gindx": 1,
                "fdepth": 3.0,
                "branch": "tfail_assigned",
                "event_type": "TFailAssignment",
            }
        )
    return rows, {
        "schedule_diagnostic_row_count": len(rows),
        "event_type_counts": {"TFailAssignment": 1, "SkippedSlopeGate": 1},
        "tfail_positive_count": 1,
        "tfail_negative_count": 0,
        "skip_or_no_failure_count": 1,
        "q_period_rows_used": 1,
    }


def _fake_rnoff_schedule_generator_with_nofailure(request: NativeUnsfinDryRunRequest, q_rows_by_cell):
    rows, _summary = _fake_rnoff_schedule_generator(request, q_rows_by_cell)
    for row in rows:
        if row["one_based_cell_id"] == 2:
            row.update(
                {
                    "tfail": 0.0,
                    "gindx": 0,
                    "fdepth": 999.0,
                    "branch": "exit_no_failure_after_tsimul",
                    "event_type": "NoFailureInSearch",
                }
            )
    return rows, {
        "schedule_diagnostic_row_count": len(rows),
        "event_type_counts": {
            "TFailAssignment": sum(1 for row in rows if row["event_type"] == "TFailAssignment"),
            "NoFailureInSearch": sum(1 for row in rows if row["event_type"] == "NoFailureInSearch"),
        },
        "tfail_positive_count": 1,
        "tfail_negative_count": 0,
        "skip_or_no_failure_count": 1,
        "q_period_rows_used": 1,
    }


def test_skip_event_type_preserves_case_local_ltstar_upper_gate_reason():
    assert _skip_event_type("ltstar_gt_15") == "SkippedLtstarGate"


class _FakeFields:
    nx = 2
    ny = 2


class _FakeConfig:
    def __init__(self, dem_file):
        self.dem_file = str(dem_file)


class _FakeSolver:
    def __init__(self, dem_file, output_dir):
        self.fields = _FakeFields()
        self.config = _FakeConfig(dem_file)
        self.output_dir = output_dir
        self.configured = None

    def configure_precomputed_failure_schedule(self, *, tfail_s, gindx, fdepth_m):
        self.configured = {
            "tfail_s": np.asarray(tfail_s),
            "gindx": np.asarray(gindx),
            "fdepth_m": np.asarray(fdepth_m),
        }
        return {
            "configured": True,
            "scheduled_cell_count": int(np.count_nonzero(np.isfinite(tfail_s) & (np.asarray(tfail_s) > 0.0))),
        }


def _runtime_request(tmp_path):
    return NativeUnsfinDryRunRequest(
        case_dir=tmp_path,
        output_dir=tmp_path / "provider_runtime",
        provider_selected=True,
        dry_run_enabled=True,
        ledger_window_s=64800.0,
    )


def _minimal_rnoff_contract():
    return {
        "sidecar_shape_validated": True,
        "runtime_mutation": False,
        "imax": 2,
        "periods": [
            {
                "period_index": 1,
                "cell_count": 2,
                "rik_period": {"1": 1.0, "2": 0.2},
            }
        ],
    }


def test_provider_is_disabled_by_default(tmp_path):
    request = NativeUnsfinDryRunRequest(case_dir=tmp_path, output_dir=tmp_path / "out")

    result = run_provider_dry_run(request, generator=_fake_generator)

    assert result.status == "blocked"
    assert result.blocked_reason == DISABLED_REASON
    assert result.schedule_generated is False
    assert result.schedule_consumed_by_dfs is False
    assert not (tmp_path / "out").exists()


def test_rnoff_native_unsfin_feed_flag_requires_both_gates():
    assert rnoff_native_unsfin_feed_flag_enabled({}) is False
    assert rnoff_native_unsfin_feed_flag_enabled({RNOFF_TOPOINDEX_ENV: "1"}) is False
    assert rnoff_native_unsfin_feed_flag_enabled({RNOFF_NATIVE_UNSFIN_FEED_ENV: "1"}) is False
    assert (
        rnoff_native_unsfin_feed_flag_enabled(
            {
                RNOFF_TOPOINDEX_ENV: "1",
                RNOFF_NATIVE_UNSFIN_FEED_ENV: "1",
            }
        )
        is True
    )


def test_provider_refuses_runtime_feed_even_when_selected(tmp_path):
    request = NativeUnsfinDryRunRequest(
        case_dir=tmp_path,
        output_dir=tmp_path / "out",
        provider_selected=True,
        dry_run_enabled=True,
        runtime_feed_enabled=True,
    )

    result = run_provider_dry_run(request, generator=_fake_generator)

    assert result.status == "blocked"
    assert result.blocked_reason == RUNTIME_FEED_BLOCKED_REASON
    assert result.schedule_consumed_by_dfs is False


def test_provider_missing_case_dir_fails_closed(tmp_path):
    request = NativeUnsfinDryRunRequest(
        case_dir=tmp_path / "missing",
        output_dir=tmp_path / "out",
        provider_selected=True,
        dry_run_enabled=True,
    )

    result = run_provider_dry_run(request, generator=_fake_generator)

    assert result.status == "blocked"
    assert result.blocked_reason == MISSING_INPUT_REASON
    assert result.manifest is None


def test_provider_existing_but_incomplete_case_fails_closed(tmp_path):
    case_dir = tmp_path / "empty_case"
    case_dir.mkdir()
    request = NativeUnsfinDryRunRequest(
        case_dir=case_dir,
        output_dir=tmp_path / "out",
        provider_selected=True,
        dry_run_enabled=True,
    )

    result = run_provider_dry_run(request)

    assert result.status == "blocked"
    assert result.blocked_reason == GENERATION_FAILED_REASON
    assert result.schedule_generated is False
    assert result.schedule_consumed_by_dfs is False


def test_provider_rejects_output_inferred_metadata(tmp_path):
    request = NativeUnsfinDryRunRequest(
        case_dir=tmp_path,
        output_dir=tmp_path / "out",
        provider_selected=True,
        dry_run_enabled=True,
        metadata_overrides={"output_inferred": True},
    )

    result = run_provider_dry_run(request, generator=_fake_generator)

    assert result.status == "blocked"
    assert result.blocked_reason == INVALID_METADATA_REASON
    assert result.schedule_generated is False
    assert not (tmp_path / "out").exists()


def test_provider_dry_run_writes_arrays_manifest_and_never_consumes_dfs(tmp_path):
    output_dir = tmp_path / "provider"
    request = NativeUnsfinDryRunRequest(
        case_dir=tmp_path,
        output_dir=output_dir,
        provider_selected=True,
        dry_run_enabled=True,
        ledger_window_s=64800.0,
    )

    result = run_provider_dry_run(request, generator=_fake_generator)

    assert result.ok
    assert result.meta["provider"] == PROVIDER_NAME
    assert result.meta["source_provenance"] == "production_native_unsfin"
    assert result.meta["runtime_feed_enabled"] is False
    assert result.meta["schedule_consumed_by_dfs"] is False
    assert result.meta["native_unsfin_rnoff_feed_active"] is False
    assert result.meta["schedule_generated_with_rnoff"] is False
    assert result.meta["final_state_mutated"] is False
    assert result.meta["output_inferred"] is False
    assert result.meta["active_order_mode"] is True
    assert result.meta["per_cell_fitted_ts"] is False
    assert result.meta["tfail_positive_count"] == 2
    assert result.meta["gindx_positive_count"] == 3
    assert result.meta["fdepth_positive_count"] == 3

    manifest = json.loads((output_dir / "provider_dry_run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["provider"] == PROVIDER_NAME
    assert manifest["runtime_feed_enabled"] is False
    assert manifest["schedule_consumed_by_dfs"] is False
    assert manifest["native_unsfin_rnoff_feed_active"] is False
    assert manifest["schedule_generated_with_rnoff"] is False
    assert manifest["final_state_mutated"] is False
    assert manifest["output_inferred"] is False
    assert manifest["artifacts"]["gindx"]["sha256"]
    assert manifest["artifacts"]["tfail_s"]["sha256"]
    assert manifest["artifacts"]["fdepth_m"]["sha256"]

    assert np.load(output_dir / "provider_dry_run_gindx.npz")["gindx"].tolist() == [1, 0, 1, 1]
    assert np.load(output_dir / "provider_dry_run_tfail_s.npz")["tfail_s"][0] == 10.0


def test_rnoff_native_unsfin_feed_missing_contract_fails_closed(tmp_path):
    request = NativeUnsfinDryRunRequest(
        case_dir=tmp_path,
        output_dir=tmp_path / "out",
        provider_selected=True,
        dry_run_enabled=True,
        rnoff_native_unsfin_feed_enabled=True,
        rnoff_q_runtime_oracle_status="Q_RUNTIME_MATCHES_FORMULA_REPLAY",
    )

    result = run_provider_dry_run(request, generator=_fake_generator)

    assert result.status == "blocked"
    assert result.blocked_reason == RNOFF_CONTRACT_MISSING_REASON
    assert result.meta["rnoff_contract_loaded"] is False
    assert result.meta["fallback_reason"] == RNOFF_CONTRACT_MISSING_REASON


def test_rnoff_native_unsfin_feed_rejects_unaccepted_q_oracle(tmp_path):
    request = NativeUnsfinDryRunRequest(
        case_dir=tmp_path,
        output_dir=tmp_path / "out",
        provider_selected=True,
        dry_run_enabled=True,
        rnoff_native_unsfin_feed_enabled=True,
        rnoff_contract=_minimal_rnoff_contract(),
        rnoff_contract_kst={1: 1.0e-6, 2: 1.0e-6},
        rnoff_contract_rikzero={1: 0.001, 2: 0.001},
        rnoff_q_runtime_oracle_status="PENDING",
    )

    result = run_provider_dry_run(request, generator=_fake_generator)

    assert result.status == "blocked"
    assert result.blocked_reason == RNOFF_Q_ORACLE_NOT_ACCEPTED_REASON
    assert result.schedule_generated is False


def test_rnoff_native_unsfin_feed_rejects_malformed_contract(tmp_path):
    malformed_contract = {
        "sidecar_shape_validated": True,
        "runtime_mutation": False,
        "imax": 2,
        "periods": [],
    }
    request = NativeUnsfinDryRunRequest(
        case_dir=tmp_path,
        output_dir=tmp_path / "out",
        provider_selected=True,
        dry_run_enabled=True,
        rnoff_native_unsfin_feed_enabled=True,
        rnoff_contract=malformed_contract,
        rnoff_contract_kst={1: 1.0e-6, 2: 1.0e-6},
        rnoff_contract_rikzero={1: 0.001, 2: 0.001},
        rnoff_q_runtime_oracle_status="Q_RUNTIME_MATCHES_FORMULA_REPLAY",
    )

    result = run_provider_dry_run(request, generator=_fake_generator)

    assert result.status == "blocked"
    assert result.blocked_reason == RNOFF_CONTRACT_INVALID_REASON
    assert result.schedule_generated is False


def test_rnoff_native_unsfin_feed_computes_q_diagnostics_from_rik(tmp_path):
    output_dir = tmp_path / "provider"
    request = NativeUnsfinDryRunRequest(
        case_dir=tmp_path,
        output_dir=output_dir,
        provider_selected=True,
        dry_run_enabled=True,
        rnoff_native_unsfin_feed_enabled=True,
        rnoff_contract=_minimal_rnoff_contract(),
        rnoff_contract_kst={1: 1.0e-6, 2: 1.0e-6},
        rnoff_contract_rikzero={1: 0.001, 2: 0.001},
        rnoff_q_runtime_oracle_status="Q_RUNTIME_MATCHES_FORMULA_REPLAY",
    )

    result = run_provider_dry_run(request, generator=_fake_generator)

    assert result.ok
    assert result.meta["rnoff_contract_loaded"] is True
    assert result.meta["rik_period_loaded"] is True
    assert result.meta["q_formula_validated"] is True
    assert result.meta["native_unsfin_rnoff_feed_active"] is True
    assert result.meta["schedule_generated_with_rnoff"] is False
    assert result.meta["final_state_mutated"] is False
    diagnostics = result.meta["rnoff_provider_feed"]
    assert diagnostics["semantic_payload"] == "rik_period"
    assert diagnostics["q_payload_role"] == "diagnostic_check_only"
    assert diagnostics["q_diagnostic_row_count"] == 2
    assert diagnostics["cap_applied_count"] == 1
    sample_rows = diagnostics["q_diagnostic_sample_rows"]
    assert sample_rows[0]["one_based_cell_id"] == 1
    assert sample_rows[0]["q_after_cap"] == 1.0e-6
    assert sample_rows[0]["cap_applied"] is True
    assert sample_rows[1]["one_based_cell_id"] == 2
    assert sample_rows[1]["q_after_cap"] == 2.01e-7
    assert sample_rows[1]["cap_applied"] is False

    manifest = json.loads((output_dir / "provider_dry_run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["rnoff_contract_loaded"] is True
    assert manifest["rik_period_loaded"] is True
    assert manifest["q_formula_validated"] is True
    assert manifest["native_unsfin_rnoff_feed_active"] is True
    assert manifest["schedule_generated_with_rnoff"] is False
    assert manifest["final_state_mutated"] is False
    assert manifest["q_runtime_oracle_status"] == "Q_RUNTIME_MATCHES_FORMULA_REPLAY"
    assert manifest["rnoff_provider_feed"]["q_diagnostic_row_count"] == 2


def test_rnoff_provider_schedule_generation_requires_target_cells(tmp_path):
    request = NativeUnsfinDryRunRequest(
        case_dir=tmp_path,
        output_dir=tmp_path / "provider",
        provider_selected=True,
        dry_run_enabled=True,
        rnoff_native_unsfin_feed_enabled=True,
        rnoff_contract=_minimal_rnoff_contract(),
        rnoff_contract_kst={1: 1.0e-6, 2: 1.0e-6},
        rnoff_contract_rikzero={1: 0.001, 2: 0.001},
        rnoff_q_runtime_oracle_status="Q_RUNTIME_MATCHES_FORMULA_REPLAY",
        rnoff_provider_schedule_generation_enabled=True,
    )

    result = run_provider_dry_run(request, generator=_fake_generator)

    assert result.status == "blocked"
    assert result.blocked_reason == RNOFF_SCHEDULE_TARGETS_MISSING_REASON
    assert result.meta["final_state_mutated"] is False


def test_rnoff_provider_schedule_generation_dry_run_writes_diagnostics_without_dfs_feed(tmp_path):
    output_dir = tmp_path / "provider"
    request = NativeUnsfinDryRunRequest(
        case_dir=tmp_path,
        output_dir=output_dir,
        provider_selected=True,
        dry_run_enabled=True,
        rnoff_native_unsfin_feed_enabled=True,
        rnoff_contract=_minimal_rnoff_contract(),
        rnoff_contract_kst={1: 1.0e-6, 2: 1.0e-6},
        rnoff_contract_rikzero={1: 0.001, 2: 0.001},
        rnoff_q_runtime_oracle_status="Q_RUNTIME_MATCHES_FORMULA_REPLAY",
        rnoff_provider_schedule_generation_enabled=True,
        rnoff_schedule_target_cells=[1, 2],
    )

    result = run_provider_dry_run(
        request,
        generator=_fake_generator,
        rnoff_schedule_generator=_fake_rnoff_schedule_generator,
    )

    assert result.ok
    assert result.meta["rnoff_contract_loaded"] is True
    assert result.meta["rik_period_loaded"] is True
    assert result.meta["q_formula_validated"] is True
    assert result.meta["native_unsfin_rnoff_feed_active"] is True
    assert result.meta["schedule_generated_with_rnoff"] is True
    assert result.meta["provider_schedule_generation_active"] is True
    assert result.meta["dfs_runtime_feed_blocked"] is True
    assert result.meta["schedule_consumed_by_dfs"] is False
    assert result.meta["final_state_mutated"] is False
    assert result.meta["rnoff_provider_schedule"]["schedule_diagnostic_row_count"] == 2

    manifest = json.loads((output_dir / "provider_dry_run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["schedule_generated_with_rnoff"] is True
    assert manifest["provider_schedule_generation_active"] is True
    assert manifest["dfs_runtime_feed_blocked"] is True
    assert manifest["schedule_consumed_by_dfs"] is False
    assert manifest["final_state_mutated"] is False
    assert manifest["rnoff_provider_schedule"]["event_type_counts"]["TFailAssignment"] == 1
    assert manifest["rnoff_provider_schedule"]["event_type_counts"]["SkippedSlopeGate"] == 1
    assert (output_dir / "provider_rnoff_schedule_diagnostics.csv").exists()
    assert (output_dir / "provider_rnoff_schedule_diagnostics.json").exists()


def test_rnoff_runtime_feed_request_blocks_until_schedule_generation_is_source_backed(tmp_path):
    dem_file = tmp_path / "dem.asc"
    _write_ascii_grid(dem_file, np.array([[10.0, 11.0], [12.0, 13.0]], dtype=np.float64))
    solver = _FakeSolver(dem_file, tmp_path / "out")
    request = NativeUnsfinDryRunRequest(
        case_dir=tmp_path,
        output_dir=tmp_path / "provider_runtime",
        provider_selected=True,
        dry_run_enabled=True,
        rnoff_native_unsfin_feed_enabled=True,
        rnoff_contract=_minimal_rnoff_contract(),
        rnoff_contract_kst={1: 1.0e-6, 2: 1.0e-6},
        rnoff_contract_rikzero={1: 0.001, 2: 0.001},
        rnoff_q_runtime_oracle_status="Q_RUNTIME_MATCHES_FORMULA_REPLAY",
    )

    result = configure_provider_runtime_feed(
        solver,
        request,
        env={
            RUNTIME_FEED_ENV: "1",
            RNOFF_TOPOINDEX_ENV: "1",
            RNOFF_NATIVE_UNSFIN_FEED_ENV: "1",
        },
        generator=_fake_generator,
    )

    assert result.status == "blocked"
    assert result.blocked_reason == RNOFF_RUNTIME_FEED_SCHEDULE_NOT_SOURCE_BACKED_REASON
    assert result.meta["runtime_feed_enabled"] is True
    assert result.meta["rnoff_native_unsfin_feed_enabled"] is True
    assert result.meta["schedule_generated_with_rnoff"] is False
    assert result.meta["final_state_mutated"] is False
    assert result.schedule_configured_into_solver is False
    assert solver.configured is None


def test_rnoff_runtime_feed_configures_source_backed_provider_schedule_under_all_gates(tmp_path):
    dem_file = tmp_path / "dem.asc"
    _write_ascii_grid(dem_file, np.array([[10.0, 11.0], [12.0, 13.0]], dtype=np.float64))
    solver = _FakeSolver(dem_file, tmp_path / "out")
    request = NativeUnsfinDryRunRequest(
        case_dir=tmp_path,
        output_dir=tmp_path / "provider_runtime",
        provider_selected=True,
        dry_run_enabled=True,
        rnoff_native_unsfin_feed_enabled=True,
        rnoff_contract=_minimal_rnoff_contract(),
        rnoff_contract_kst={1: 1.0e-6, 2: 1.0e-6},
        rnoff_contract_rikzero={1: 0.001, 2: 0.001},
        rnoff_q_runtime_oracle_status="Q_RUNTIME_MATCHES_FORMULA_REPLAY",
        rnoff_provider_schedule_generation_enabled=True,
        rnoff_schedule_target_cells=[1, 2],
    )

    result = configure_provider_runtime_feed(
        solver,
        request,
        env={
            RUNTIME_FEED_ENV: "1",
            RNOFF_TOPOINDEX_ENV: "1",
            RNOFF_NATIVE_UNSFIN_FEED_ENV: "1",
        },
        generator=_fake_generator,
        rnoff_schedule_generator=_fake_rnoff_schedule_generator_with_nofailure,
    )

    assert result.ok
    assert result.schedule_consumed_by_dfs is True
    assert result.meta["rnoff_dfs_runtime_feed_active"] is True
    assert result.meta["final_state_mutated"] is True
    assert result.meta["gindx_zero_no_feed_count"] == 1
    assert result.meta["rnoff_runtime_feed_summary"]["consumed_schedule_row_count"] == 1
    np.testing.assert_array_equal(solver.configured["gindx"], np.array([[1, 0], [0, 0]], dtype=np.int32))
    np.testing.assert_allclose(solver.configured["tfail_s"], np.array([[10.0, 0.0], [0.0, 0.0]]))
    np.testing.assert_allclose(solver.configured["fdepth_m"], np.array([[3.0, 0.0], [0.0, 0.0]]))


def test_rnoff_runtime_feed_artifact_blocks_before_solver_configuration(tmp_path):
    output_dir = tmp_path / "provider"
    dry_request = NativeUnsfinDryRunRequest(
        case_dir=tmp_path,
        output_dir=output_dir,
        provider_selected=True,
        dry_run_enabled=True,
        rnoff_native_unsfin_feed_enabled=True,
        rnoff_contract=_minimal_rnoff_contract(),
        rnoff_contract_kst={1: 1.0e-6, 2: 1.0e-6},
        rnoff_contract_rikzero={1: 0.001, 2: 0.001},
        rnoff_q_runtime_oracle_status="Q_RUNTIME_MATCHES_FORMULA_REPLAY",
    )
    dry_result = run_provider_dry_run(dry_request, generator=_fake_generator)
    assert dry_result.ok

    dem_file = tmp_path / "dem.asc"
    _write_ascii_grid(dem_file, np.array([[10.0, 11.0], [12.0, 13.0]], dtype=np.float64))
    solver = _FakeSolver(dem_file, tmp_path / "out")

    result = configure_provider_runtime_feed(
        solver,
        _runtime_request(tmp_path),
        env={RUNTIME_FEED_ENV: "1"},
        artifact_dir=output_dir,
        generator=_fake_generator,
    )

    assert result.status == "blocked"
    assert result.blocked_reason == RNOFF_RUNTIME_FEED_SCHEDULE_NOT_SOURCE_BACKED_REASON
    assert result.schedule_configured_into_solver is False
    assert solver.configured is None


def test_runtime_feed_rejects_provider_artifact_from_different_case_dir(tmp_path):
    artifact_case = tmp_path / "artifact_case"
    runtime_case = tmp_path / "runtime_case"
    artifact_case.mkdir()
    runtime_case.mkdir()
    output_dir = tmp_path / "provider"
    dry_request = NativeUnsfinDryRunRequest(
        case_dir=artifact_case,
        output_dir=output_dir,
        provider_selected=True,
        dry_run_enabled=True,
    )
    dry_result = run_provider_dry_run(dry_request, generator=_fake_generator)
    assert dry_result.ok

    dem_file = runtime_case / "dem.asc"
    _write_ascii_grid(dem_file, np.array([[10.0, 11.0], [12.0, 13.0]], dtype=np.float64))
    solver = _FakeSolver(dem_file, tmp_path / "out")

    result = configure_provider_runtime_feed(
        solver,
        _runtime_request(runtime_case),
        env={RUNTIME_FEED_ENV: "1"},
        artifact_dir=output_dir,
        generator=_fake_generator,
    )

    assert result.status == "blocked"
    assert result.blocked_reason == PROVIDER_ARTIFACT_PROVENANCE_MISMATCH_REASON
    assert result.schedule_configured_into_solver is False
    assert solver.configured is None


def test_runtime_feed_flag_off_fails_closed_without_configuring_solver(tmp_path):
    dem_file = tmp_path / "dem.asc"
    _write_ascii_grid(dem_file, np.array([[10.0, 11.0], [12.0, 13.0]], dtype=np.float64))
    solver = _FakeSolver(dem_file, tmp_path / "out")

    result = configure_provider_runtime_feed(
        solver,
        _runtime_request(tmp_path),
        env={},
        generator=_fake_generator,
    )

    assert result.status == "blocked"
    assert result.blocked_reason == RUNTIME_FEED_FLAG_DISABLED_REASON
    assert result.schedule_configured_into_solver is False
    assert solver.configured is None


def test_runtime_feed_flag_on_validates_maps_and_configures_solver(tmp_path):
    dem_file = tmp_path / "dem.asc"
    _write_ascii_grid(dem_file, np.array([[10.0, 11.0], [12.0, 13.0]], dtype=np.float64))
    solver = _FakeSolver(dem_file, tmp_path / "out")

    result = configure_provider_runtime_feed(
        solver,
        _runtime_request(tmp_path),
        env={RUNTIME_FEED_ENV: "1"},
        generator=_fake_generator,
    )

    assert result.ok
    assert result.meta["provider"] == PROVIDER_NAME
    assert result.meta["runtime_feed_enabled"] is True
    assert result.meta["schedule_validated"] is True
    assert result.meta["schedule_configured_into_solver"] is True
    assert result.meta["schedule_consumed_by_dfs"] is False
    assert result.meta["tfail_positive_count"] == 3
    np.testing.assert_array_equal(solver.configured["gindx"], np.array([[1, 1], [0, 1]], dtype=np.int32))
    np.testing.assert_allclose(solver.configured["tfail_s"], np.array([[10.0, 600.0], [np.nan, 70000.0]]))
    np.testing.assert_allclose(solver.configured["fdepth_m"], np.array([[3.0, 3.0], [0.0, 3.0]]))


def test_runtime_feed_rejects_invalid_provider_metadata_before_solver_configuration(tmp_path):
    dem_file = tmp_path / "dem.asc"
    _write_ascii_grid(dem_file, np.array([[10.0, 11.0], [12.0, 13.0]], dtype=np.float64))
    solver = _FakeSolver(dem_file, tmp_path / "out")
    request = NativeUnsfinDryRunRequest(
        case_dir=tmp_path,
        output_dir=tmp_path / "provider_runtime",
        provider_selected=True,
        dry_run_enabled=True,
        metadata_overrides={"output_inferred": True},
    )

    result = configure_provider_runtime_feed(
        solver,
        request,
        env={RUNTIME_FEED_ENV: "1"},
        generator=_fake_generator,
    )

    assert result.status == "blocked"
    assert result.blocked_reason == INVALID_METADATA_REASON
    assert result.schedule_configured_into_solver is False
    assert solver.configured is None
