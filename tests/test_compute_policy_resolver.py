from __future__ import annotations

from pathlib import Path

import pytest

from api.services.compute_gate_defaults import (
    compute_gate_merge_baseline,
    merge_scenario_compute_parameters,
    validate_compute_gate_values,
    ComputeGateValidationError,
)
from api.services.compute_policy_resolver import (
    ComputePolicyResolutionError,
    POLICY_KEY,
    VARIANT_PATH,
    FSSIMUL_PATH,
    apply_resolved_policy_to_parameters,
    annotate_failure_source_registry,
    resolve_compute_policy,
    should_attempt_native_unsfin_provider,
)
from api.services.reference_config_parser import (
    _detect_dfs_failure_source_variant,
    _normalize_fortran_active_source,
)


def test_auto_maps_chamoli_fssimul_false_to_disabled() -> None:
    resolution = resolve_compute_policy(
        {
            FSSIMUL_PATH: False,
            VARIANT_PATH: "precomputed_unsfin_schedule",
        }
    )
    assert resolution.requested == "auto"
    assert resolution.effective["mode"] == "disabled"


def test_explicit_disabled_preserves_counterfactual_warning() -> None:
    resolution = resolve_compute_policy(
        {FSSIMUL_PATH: True, VARIANT_PATH: "precomputed_unsfin_schedule"},
        global_gates={POLICY_KEY: "disabled"},
    )
    assert resolution.effective["mode"] == "disabled"
    assert any("Counterfactual" in warning for warning in resolution.warnings)
    assert resolution.effective["simulate_shallow_landslide"] is False
    assert resolution.effective["active_variant"] is None
    assert resolution.effective["configured_variant"] == "precomputed_unsfin_schedule"


def test_auto_maps_bj_to_precomputed() -> None:
    resolution = resolve_compute_policy(
        {
            FSSIMUL_PATH: True,
            VARIANT_PATH: "precomputed_unsfin_schedule",
        }
    )
    assert resolution.effective["mode"] == "precomputed"
    assert resolution.effective["active_variant"] == "precomputed_unsfin_schedule"


def test_explicit_precomputed_is_counterfactual_when_fssimul_false() -> None:
    resolution = resolve_compute_policy(
        {FSSIMUL_PATH: False, VARIANT_PATH: "precomputed_unsfin_schedule"},
        global_gates={POLICY_KEY: "precomputed"},
    )
    assert resolution.source == "global_override"
    assert resolution.effective["mode"] == "precomputed"
    assert any("Counterfactual" in item for item in resolution.warnings)


def test_live_requires_experimental_unlock_for_settings() -> None:
    with pytest.raises(ComputePolicyResolutionError) as exc:
        resolve_compute_policy(
            {FSSIMUL_PATH: False, VARIANT_PATH: "precomputed_unsfin_schedule"},
            global_gates={POLICY_KEY: "live"},
            source_mode="reference_config",
        )
    assert exc.value.code == "live_policy_locked"
    unlocked = resolve_compute_policy(
        {FSSIMUL_PATH: False, VARIANT_PATH: "precomputed_unsfin_schedule"},
        global_gates={
            POLICY_KEY: "live",
            "experimental.enable_live_doublelayer_in_dfs": True,
        },
    )
    assert unlocked.effective["mode"] == "live"
    assert unlocked.effective["active_variant"] == "live_doublelayer_in_dfs"


def test_direct_api_live_does_not_require_unlock() -> None:
    resolution = resolve_compute_policy(
        {FSSIMUL_PATH: True, VARIANT_PATH: "live_doublelayer_in_dfs"},
        global_gates={POLICY_KEY: "live"},
        source_mode="direct_api",
    )
    assert resolution.effective["mode"] == "live"
    assert resolution.source == "global_override"


def test_direct_api_auto_uses_compatibility_source() -> None:
    resolution = resolve_compute_policy(
        {FSSIMUL_PATH: True},
        source_mode="direct_api",
    )
    assert resolution.source == "direct_api_compatibility"
    assert resolution.effective["mode"] == "live"
    assert any("compatibility fallback" in warning for warning in resolution.warnings)


def test_strict_unknown_topology_blocks_when_fssimul_true() -> None:
    with pytest.raises(ComputePolicyResolutionError) as exc:
        resolve_compute_policy(
            {FSSIMUL_PATH: True},
            strict_reference=True,
        )
    assert exc.value.code == "failure_source_topology_unknown"


def test_scenario_snapshot_preserves_blocked_evidence_and_allows_explicit_override() -> None:
    from api.services.compute_gate_defaults import resolve_scenario_compute_snapshot

    baseline = {FSSIMUL_PATH: True}
    blocked = resolve_scenario_compute_snapshot(
        baseline,
        {},
        template_id="imported-unknown",
        template_metadata={
            "_compute_policy": {
                "topology_status": "unknown",
                "evidence": [{"active_statement": "call unsfin", "matched": False}],
            }
        },
    )
    assert blocked.status == "blocked"
    assert blocked.resolution["blocking_issue"]["code"] == "failure_source_topology_unknown"
    explicit = resolve_scenario_compute_snapshot(
        baseline,
        {},
        global_gates={POLICY_KEY: "disabled"},
        template_id="imported-unknown",
        template_metadata={"_compute_policy": {"topology_status": "unknown", "evidence": []}},
    )
    assert explicit.status == "resolved"
    assert explicit.resolution["effective"]["mode"] == "disabled"


def test_scenario_snapshot_does_not_canonicalize_missing_fssimul_to_disabled() -> None:
    from api.services.compute_gate_defaults import resolve_scenario_compute_snapshot

    snapshot = resolve_scenario_compute_snapshot(
        {FSSIMUL_PATH: False, VARIANT_PATH: "precomputed_unsfin_schedule"},
        {},
        template_id="imported-missing-fssimul",
        template_metadata={
            "_compute_policy": {
                "original_fssimul": None,
                "topology": "precomputed_unsfin_schedule",
                "topology_status": "recognized",
            }
        },
    )
    assert snapshot.status == "blocked"
    assert snapshot.resolution["blocking_issue"]["code"] == "failure_source_control_unknown"


def test_bj_template_id_without_provenance_does_not_hide_unknown_topology() -> None:
    with pytest.raises(ComputePolicyResolutionError) as exc:
        resolve_compute_policy(
            {FSSIMUL_PATH: True},
            template_id="pt-bj-hxl-v3",
            strict_reference=True,
        )
    assert exc.value.code == "failure_source_topology_unknown"


def test_numeric_variants_auto_vs_override() -> None:
    resolution = resolve_compute_policy(
        {"hydrology.dfs_face_flux_variant": "arithmetic_mean_chamoli"},
        global_gates={"hydrology.dfs_face_flux_variant": "both_thin_weighted"},
    )
    assert resolution.numeric_variants["hydrology.dfs_face_flux_variant"]["source"] == "global_override"
    auto = resolve_compute_policy({"hydrology.dfs_face_flux_variant": "arithmetic_mean_chamoli"})
    assert auto.numeric_variants["hydrology.dfs_face_flux_variant"]["source"] == "case_baseline"


def test_disabled_registry_is_control_off_not_provider_failure() -> None:
    resolution = resolve_compute_policy({FSSIMUL_PATH: False, VARIANT_PATH: "precomputed_unsfin_schedule"})
    annotated = annotate_failure_source_registry({"blocked_reason": "old"}, resolution)
    assert annotated["runtime_active"] is False
    assert annotated["skip_reason"] == "control_off"
    assert annotated["blocked_reason"] is None
    assert should_attempt_native_unsfin_provider(resolution) is False
    assert should_attempt_native_unsfin_provider(resolution, force_native_provider_generation=True) is False


def test_apply_policy_sets_fssimul_atomically() -> None:
    merged = apply_resolved_policy_to_parameters(
        {FSSIMUL_PATH: True, VARIANT_PATH: "precomputed_unsfin_schedule"},
        resolve_compute_policy({FSSIMUL_PATH: False, VARIANT_PATH: "precomputed_unsfin_schedule"}),
    )
    assert merged[FSSIMUL_PATH] is False


def test_empty_settings_do_not_overwrite_case_variants() -> None:
    baseline = {
        "hydrology.dfs_face_flux_variant": "arithmetic_mean_chamoli",
        FSSIMUL_PATH: False,
        VARIANT_PATH: "precomputed_unsfin_schedule",
    }
    merged, resolution = merge_scenario_compute_parameters(baseline, {}, {})
    assert merged["hydrology.dfs_face_flux_variant"] == "arithmetic_mean_chamoli"
    assert merged[FSSIMUL_PATH] is False
    assert resolution["effective"]["mode"] == "disabled"
    assert "hydrology.dfs_face_flux_variant" not in compute_gate_merge_baseline()


def test_validate_strips_auto_and_locks_live() -> None:
    cleaned = validate_compute_gate_values({POLICY_KEY: "auto", "hydrology.dfs_face_flux_variant": "both_thin_weighted"})
    assert POLICY_KEY not in cleaned
    with pytest.raises(ComputeGateValidationError):
        validate_compute_gate_values({POLICY_KEY: "live"})
    with pytest.raises(ComputeGateValidationError):
        validate_compute_gate_values({POLICY_KEY: "live", "experimental.enable_live_doublelayer_in_dfs": False})
    allowed = validate_compute_gate_values(
        {POLICY_KEY: "live", "experimental.enable_live_doublelayer_in_dfs": True}
    )
    assert allowed[POLICY_KEY] == "live"


def test_fortran_normalization_ignores_comments_and_joins_continuations() -> None:
    text = (
        "!    call doublelayer(imx1,kper,tnow,tempfsh,tempfsrho,gindx,eroindx,u)\n"
        "      call unsfin &\n"
        "     &(imx1)\n"
    )
    compact = _normalize_fortran_active_source(text)
    assert "calldoublelayer(imx1,kper,tnow,tempfsh" not in compact
    assert "callunsfin(imx1)" in compact


def test_fortran_normalization_ignores_fixed_form_comment_columns() -> None:
    text = (
        "C      call unsfin(imx1)\n"
        "*      call doublelayer(imx1,kper,tnow,tempfsh,tempfsrho,gindx,eroindx,u)\n"
        "D      call unsfin(imx1)\n"
        "      call unsfin(imx1)\n"
    )
    compact = _normalize_fortran_active_source(text)
    assert compact.count("callunsfin(imx1)") == 1
    assert "calldoublelayer" not in compact


def test_fortran_normalization_joins_fixed_form_column_six_continuation() -> None:
    text = "      call unsfin\n     1(imx1)\n"
    compact = _normalize_fortran_active_source(text)
    assert "callunsfin(imx1)" in compact


def test_precomputed_requires_active_unsfin_producer(tmp_path: Path) -> None:
    (tmp_path / "dfs.F90").write_text(
        "      if (tnow<=tfail(i) .and. tnext>tfail(i)) then\n"
        "        tempfsh(i)=fsdepth(i)\n"
        "        tempfsrho(i)=(rhos-rhow)*cvstar+rhow\n",
        encoding="utf-8",
    )
    variant, _source, _basis, evidence, status = _detect_dfs_failure_source_variant(tmp_path)
    assert status == "unknown"
    assert variant == ""
    assert any(item["active_statement"] == "call unsfin" and item["matched"] is False for item in evidence)


def test_synthetic_live_and_conflict_signatures(tmp_path: Path) -> None:
    (tmp_path / "dfs.F90").write_text(
        "      call doublelayer(imx1,kper,tnow,tempfsh,tempfsrho,gindx,eroindx,u)\n"
        "      if (tnow<=tfail(i) .and. tnext>tfail(i)) then\n"
        "        tempfsh(i)=fsdepth(i)\n"
        "        tempfsrho(i)=(rhos-rhow)*cvstar+rhow\n",
        encoding="utf-8",
    )
    (tmp_path / "edda main program.F90").write_text("      call unsfin\n", encoding="utf-8")
    variant, _source, _basis, evidence, status = _detect_dfs_failure_source_variant(tmp_path)
    assert status == "conflict"
    assert variant == ""
    assert evidence

    live_dir = tmp_path / "live"
    live_dir.mkdir()
    (live_dir / "dfs.F90").write_text(
        "      CALL DoubleLayer(imx1,kper,tnow,tempfsh,tempfsrho,gindx,eroindx,u)\n",
        encoding="utf-8",
    )
    variant, _source, _basis, _evidence, status = _detect_dfs_failure_source_variant(live_dir)
    assert status == "recognized"
    assert variant == "live_doublelayer_in_dfs"


@pytest.mark.skipif(
    not Path(r"C:\Users\Administrator\Desktop\EDDA_test_project\Chamoli-EDDA file\Chamoli-EDDA file\edda_in.txt").exists(),
    reason="Chamoli reference case is not on disk",
)
def test_real_chamoli_topology_is_precomputed_but_auto_disabled() -> None:
    from api.services.parameter_templates import normalized_parameter_values
    from api.services.reference_config_parser import parse_reference_config_file

    chamoli = Path(r"C:\Users\Administrator\Desktop\EDDA_test_project\Chamoli-EDDA file\Chamoli-EDDA file")
    parsed = parse_reference_config_file(str(chamoli / "edda_in.txt"), str(chamoli))
    assert parsed.dfs_failure_source_variant == "precomputed_unsfin_schedule"
    assert parsed.flags["simulate_shallow_landslide"] is False
    values = normalized_parameter_values(parsed)
    assert values[VARIANT_PATH] == "precomputed_unsfin_schedule"
    resolution = resolve_compute_policy(values)
    assert resolution.effective["mode"] == "disabled"


@pytest.mark.skipif(
    not Path(r"C:\Users\Administrator\Desktop\EDDA_test_project\BJ_HXL_Text(1)\BJ_HXL_Text\edda_in.txt").exists(),
    reason="BJ_HXL reference case is not on disk",
)
def test_real_bj_auto_is_precomputed() -> None:
    from api.services.parameter_templates import normalized_parameter_values
    from api.services.reference_config_parser import parse_reference_config_file

    bj = Path(r"C:\Users\Administrator\Desktop\EDDA_test_project\BJ_HXL_Text(1)\BJ_HXL_Text")
    parsed = parse_reference_config_file(str(bj / "edda_in.txt"), str(bj))
    assert parsed.dfs_failure_source_variant == "precomputed_unsfin_schedule"
    assert parsed.flags["simulate_shallow_landslide"] is True
    values = normalized_parameter_values(parsed)
    resolution = resolve_compute_policy(values)
    assert resolution.effective["mode"] == "precomputed"
