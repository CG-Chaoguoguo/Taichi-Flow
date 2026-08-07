from __future__ import annotations

import json
from pathlib import Path


PHASE_DIR = Path(
    r"C:\Users\Administrator\EDDA-Taichi\PROJECT_REPORTS\agent_runs\2026-04-27\phase_gate_timing_original_internal_artifact_repair"
)


def test_output_parity_phase_paired_run_status_is_auditable():
    status_path = PHASE_DIR / "paired_current_run_status.json"
    assert status_path.exists()

    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["status"] in {"running", "completed", "failed"}

    if status["status"] == "completed":
        assert (PHASE_DIR / "_current_runs" / "20a_cuda").exists()
        assert (PHASE_DIR / "_current_runs" / "50a_cuda").exists()
        for name in (
            "paired_rainfall_response_report.md",
            "delta_of_delta_matrix.md",
            "acceptance_gate_update.md",
        ):
            assert (PHASE_DIR / name).exists(), name
    else:
        assert (PHASE_DIR / "_current_runs").exists()

