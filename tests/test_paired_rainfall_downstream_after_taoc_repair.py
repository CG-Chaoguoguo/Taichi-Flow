from __future__ import annotations

import json
from pathlib import Path


PHASE_DIR = Path(
    r"C:\Users\Administrator\EDDA-Taichi\PROJECT_REPORTS\agent_runs\2026-04-27\phase_taoc_fortran_formula_repair_and_erosion_gate_validation"
)


def test_after_taoc_diagnostic_report_is_self_consistent_if_present():
    report_dir = PHASE_DIR / "paired_erosion_gate_diagnostic"
    paths = [
        report_dir / "current_downstream_internal_20a_600s_after_taoc.json",
        report_dir / "current_downstream_internal_50a_600s_after_taoc.json",
    ]
    if not all(path.exists() for path in paths):
        return

    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        taoc_stats = payload["stats"].get("taoc", payload["stats"]["taoc_fortran"])
        assert payload["stats"]["taoc_fortran"]["max"] == taoc_stats["max"]
        assert payload["count_tau_gt_taoc_fortran"] == payload["count_tao_gt_taoc"]
        assert payload["count_erosion_gate_temp"] == payload["count_all_erosion_gates_true_fortran"]
        assert payload["count_all_erosion_gates_true_old"] == 0
        assert payload["stats"]["Flow_depth"]["sum"] is not None
        assert payload["stats"]["Erosion_depth"]["sum"] is not None
