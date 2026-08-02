from __future__ import annotations

import json

import numpy as np

from api.services.edda_input_mapper import collect_runtime_source_chain_diagnostics
from edda.solver.native_unsfin_provider import PROVIDER_ARTIFACT_DIR_ENV, RUNTIME_FEED_ENV
from tests.test_native_input_chain import _make_reference_case, _write_ascii_grid
from tests.test_native_runtime_consumption import _initialize_real_solver


def _make_precomputed_schedule_case(tmp_path, *, with_artifacts: bool = True):
    edda_in = _make_reference_case(tmp_path)
    (edda_in.parent / "dfs.F90").write_text(
        "\n".join(
            [
                "        !if (fssimul) then",
                "        !    if (tnow<60.) tnow=60.",
                "        !    call doublelayer(imx1,kper,tnow,tempfsh,tempfsrho,gindx,eroindx,u)",
                "        !end if",
                "        if (tnow<=tfail(i) .and. tnext>tfail(i)) then",
                "            tempfsh(i)=fsdepth(i)",
                "            tempfsrho(i)=(rhos-rhow)*cvstar+rhow",
                "        end if",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (edda_in.parent / "edda main program.F90").write_text(
        "if (fssimul) call unsfin(imx1,u(19),u(2),profil)\n",
        encoding="utf-8",
    )
    if with_artifacts:
        _write_ascii_grid(edda_in.parent / "precomputed_unsfin_gindx.txt", np.array([[1, 0], [0, 1]], dtype=np.float64))
        _write_ascii_grid(edda_in.parent / "precomputed_unsfin_tfail.txt", np.array([[0.5, 9999.0], [9999.0, 0.75]], dtype=np.float64))
        _write_ascii_grid(edda_in.parent / "precomputed_unsfin_fdepth.txt", np.array([[0.2, 0.0], [0.0, 0.4]], dtype=np.float64))
        (edda_in.parent / "precomputed_unsfin_meta.json").write_text(
            '{"shape_kind":"dem_yx_grid","provider":"original_instrumented_unsfin","dump_point":"after unsfin returns and before dfs enters"}\n',
            encoding="utf-8",
        )
    return edda_in


def _write_provider_dry_run_artifacts(base, *, gindx, tfail_s, fdepth_m, case_dir=None):
    base.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(base / "provider_dry_run_gindx.npz", gindx=np.asarray(gindx, dtype=np.int32))
    np.savez_compressed(base / "provider_dry_run_tfail_s.npz", tfail_s=np.asarray(tfail_s, dtype=np.float64))
    np.savez_compressed(base / "provider_dry_run_fdepth_m.npz", fdepth_m=np.asarray(fdepth_m, dtype=np.float64))
    meta = {
        "provider": "production_native_unsfin",
        "mode": "dry_run",
        "source_provenance": "production_native_unsfin",
        "output_inferred": False,
        "runtime_feed_enabled": False,
        "schedule_consumed_by_dfs": False,
        "final_state_mutated": False,
        "schedule_generated_with_rnoff": False,
        "active_order_mode": True,
        "per_cell_fitted_ts": False,
        "dfs_runtime_modified": False,
        "rootc_deltamiu_default_real": True,
        "full_window_s": 64800.0,
        "performance_truncated": False,
    }
    if case_dir is not None:
        meta["case_dir"] = str(case_dir)
    (base / "provider_dry_run_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (base / "provider_dry_run_manifest.json").write_text(
        json.dumps(
            {
                "provider": "production_native_unsfin",
                "mode": "dry_run",
                "source_provenance": "production_native_unsfin",
                "runtime_feed_enabled": False,
                "schedule_consumed_by_dfs": False,
                "output_inferred": False,
                "artifacts": {},
                **({"case_dir": str(case_dir)} if case_dir is not None else {}),
            }
        ),
        encoding="utf-8",
    )


def test_post_run_source_chain_diagnostics_are_persisted_to_manifest(tmp_path):
    edda_in = _make_precomputed_schedule_case(tmp_path)
    solver, runtime_input_manifest, _, _ = _initialize_real_solver(edda_in, tmp_path / "out_failure_artifacts")
    solver.fields.erodible_thickness.from_numpy(np.full((solver.fields.nx, solver.fields.ny), 10.0, dtype=np.float64))

    solver.dfs_dynamic_wave.set_current_time(0.0)
    step_info = solver.dfs_dynamic_wave.step(1.0)
    assert step_info["accepted"] is True

    diagnostics = collect_runtime_source_chain_diagnostics(solver, runtime_input_manifest)

    assert diagnostics["schedule_provider"] == "original_tfail_artifacts"
    assert diagnostics["schedule_loaded"] is True
    assert diagnostics["runtime_active"] is True
    assert diagnostics["runtime_equivalent_implemented"] is True
    assert diagnostics["scheduled_cell_count"] == 2
    assert diagnostics["consumed_count"] == 2
    assert diagnostics["fired_cell_count"] == 2
    assert diagnostics["committed_fired_count"] == 2
    assert diagnostics["candidate_fired_count"] == 0
    assert diagnostics["duplicate_fire_count"] == 0
    assert diagnostics["rejected_step_discard_count"] == 0
    assert diagnostics["last_staged_mass_sum"] > 0.0
    assert diagnostics["failure_source_flow_depth_sum"] > 0.0
    assert diagnostics["failure_source_mass_sum"] > 0.0
    assert "Cv_max" in diagnostics
    assert "Flow_depth_sum" in diagnostics

    registry = runtime_input_manifest["input_source_registry"]["dfs_failure_source_variant"]
    assert registry["post_run_source_chain_diagnostics"]["fired_cell_count"] == 2
    assert runtime_input_manifest["post_run_source_chain_diagnostics"]["failure_source_mass_sum"] > 0.0
    manifest = {entry["family"]: entry for entry in runtime_input_manifest["inputs"]}
    assert manifest["precomputed_unsfin_schedule"]["post_run_diagnostics"]["fired_cell_count"] == 2


def test_precomputed_schedule_branch_fails_closed_without_artifacts(tmp_path):
    edda_in = _make_precomputed_schedule_case(tmp_path, with_artifacts=False)
    _, runtime_input_manifest, _, _ = _initialize_real_solver(edda_in, tmp_path / "out_missing_failure_artifacts")

    registry = runtime_input_manifest["input_source_registry"]["dfs_failure_source_variant"]
    assert registry["schedule_loaded"] is False
    assert registry["runtime_active"] is False
    assert registry["runtime_equivalent_implemented"] is False
    assert registry["consumed_count"] == 0
    assert "loader status: missing_artifacts" in registry["blocked_reason"]

    manifest = {entry["family"]: entry for entry in runtime_input_manifest["inputs"]}
    assert manifest["precomputed_unsfin_schedule"]["consumed"] is False
    assert manifest["precomputed_unsfin_schedule"]["production_status"] == "blocked"
    assert manifest["precomputed_unsfin_schedule"]["default_substitution_used"] is False


def test_production_native_unsfin_runtime_feed_is_feature_gated_and_consumed(tmp_path, monkeypatch):
    edda_in = _make_precomputed_schedule_case(tmp_path, with_artifacts=False)
    artifact_dir = tmp_path / "provider_artifacts"
    _write_provider_dry_run_artifacts(
        artifact_dir,
        gindx=[1, 0, 0, 1],
        tfail_s=[0.5, np.nan, np.nan, 0.75],
        fdepth_m=[0.2, 0.0, 0.0, 0.4],
        case_dir=edda_in.parent,
    )
    monkeypatch.setenv(RUNTIME_FEED_ENV, "1")
    monkeypatch.setenv(PROVIDER_ARTIFACT_DIR_ENV, str(artifact_dir))

    solver, runtime_input_manifest, _, _ = _initialize_real_solver(
        edda_in,
        tmp_path / "out_native_provider_runtime_feed",
    )
    registry = runtime_input_manifest["input_source_registry"]["dfs_failure_source_variant"]

    assert registry["schedule_provider"] == "production_native_unsfin"
    assert registry["runtime_feed_enabled"] is True
    assert registry["schedule_generated"] is True
    assert registry["schedule_validated"] is True
    assert registry["schedule_configured_into_solver"] is True
    assert registry["schedule_consumed_by_dfs"] is False
    assert registry["source_provenance"] == "production_native_unsfin"
    assert registry["output_inferred"] is False
    assert registry["tfail_positive_count"] == 2
    assert registry["gindx_positive_count"] == 2
    assert registry["fdepth_positive_count"] == 2

    solver.fields.erodible_thickness.from_numpy(np.full((solver.fields.nx, solver.fields.ny), 10.0, dtype=np.float64))
    solver.dfs_dynamic_wave.set_current_time(0.0)
    step_info = solver.dfs_dynamic_wave.step(1.0)
    assert step_info["accepted"] is True

    diagnostics = collect_runtime_source_chain_diagnostics(solver, runtime_input_manifest)
    assert diagnostics["schedule_provider"] == "production_native_unsfin"
    assert diagnostics["schedule_loaded"] is True
    assert diagnostics["runtime_active"] is True
    assert diagnostics["consumed_count"] == 2
    assert diagnostics["committed_fired_count"] == 2
