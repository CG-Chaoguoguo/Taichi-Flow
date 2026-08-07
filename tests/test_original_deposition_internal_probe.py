import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PHASE = REPO / "PROJECT_REPORTS" / "agent_runs" / "2026-04-29" / "phase_deposition_internal_artifact_and_flow_response_repair"
PATCH = REPO / "tests" / "_fortran_toolchain_sandbox" / "patches" / "instrument_original_deposition_internal_probe.patch"


def test_original_deposition_internal_probe_records_status_and_patch_contract():
    report = (PHASE / "original_deposition_internal_probe_report.md").read_text(encoding="utf-8")
    status = json.loads((PHASE / "original_deposition_internal_probe_status.json").read_text(encoding="utf-8"))

    assert PATCH.exists()
    assert status["status"] in {
        "ORIGINAL_DEPOSITION_INTERNAL_ARTIFACT_BLOCKED_WITH_TRACE",
        "ORIGINAL_DEPOSITION_INTERNAL_ARTIFACT_PARTIAL",
    }
    assert status["status"] in report
    assert "No original `EDDA.exe` or original `results/` directory was overwritten" in report
