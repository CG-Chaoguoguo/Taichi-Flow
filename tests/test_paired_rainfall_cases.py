from __future__ import annotations

import json
from pathlib import Path


PHASE_DIR = Path(
    r"C:\Users\Administrator\EDDA-Taichi\PROJECT_REPORTS\agent_runs\2026-05-03\phase_full_case_scientific_closure_after_erosion_repairs"
)


def test_paired_cases_are_rainfall_only_different():
    diff = json.loads((PHASE_DIR / "paired_case_input_diff.json").read_text(encoding="utf-8"))
    assert diff["pair"]["non_rainfall_differences"] == []
    assert diff["pair"]["same_parameter_except_rainfall_inflow_claim_holds"] is True


def test_paired_current_cuda_runs_exist():
    for case in ("20a_cuda", "50a_cuda"):
        run_summary = json.loads((PHASE_DIR / "_current_runs" / case / "run_summary.json").read_text(encoding="utf-8"))
        assert run_summary["resolved_backend"] == "cuda"
        assert run_summary["result_file_count"] >= 13
        for name in (
            "result_0000_depth.tif",
            "result_0000_concentration.tif",
            "final_deposition.tif",
            "final_erosion.tif",
            "OUTNQ_EDDA_TAICHI.txt",
        ):
            assert (PHASE_DIR / "_current_runs" / case / name).exists(), name


def test_paired_runtime_input_sources_match_expected_semantics():
    for case in ("20a_cuda", "50a_cuda"):
        manifest = json.loads((PHASE_DIR / "_current_runs" / case / "runtime_input_manifest.json").read_text(encoding="utf-8"))
        registry = manifest["input_source_registry"]
        assert registry["dfs_infiltration_variant"]["selected_source"] == "direct_rain_plus_storage"
        assert registry["dfs_face_flux_variant"]["selected_source"] == "both_thin_weighted"
        assert registry["dfs_failure_source_variant"]["selected_source"] == "precomputed_unsfin_schedule"
        assert registry["dfs_failure_source_variant"]["schedule_provider"] == "original_tfail_artifacts"
        assert registry["dfs_failure_source_variant"]["schedule_loaded"] is True
        assert registry["dfs_failure_source_variant"]["runtime_equivalent_implemented"] is True
        assert registry["dfs_failure_source_variant"]["runtime_active"] is True
        assert registry["dfs_failure_source_variant"]["consumed_count"] > 0
        assert registry["outflow_point_source"]["selected_source"] == "outflow_txt"
        assert registry["water_table_source"]["selected_source"] == "config_depth"
        assert registry["initial_infiltration_source"]["selected_source"] == "config_rizero"
        assert registry["manning_source"]["selected_source"] == "global_manning"
        assert registry["rainfall_source"]["selected_source"] == "uniform_cri"
