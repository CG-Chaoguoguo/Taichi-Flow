import csv
import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PHASE = REPO / "PROJECT_REPORTS" / "agent_runs" / "2026-04-29" / "phase_deposition_internal_artifact_and_flow_response_repair"


def test_current_deposition_internal_diagnostics_are_present():
    report = (PHASE / "current_deposition_internal_diagnostics_report.md").read_text(encoding="utf-8")

    assert "CURRENT_DEPOSITION_INTERNAL_DIAGNOSTICS_READY" in report
    for case_key in ("20a", "50a"):
        csv_path = PHASE / f"current_deposition_internal_{case_key}_600s.csv"
        json_path = PHASE / f"current_deposition_internal_{case_key}_600s.json"
        assert csv_path.exists()
        assert json_path.exists()
        assert json.loads(json_path.read_text(encoding="utf-8"))["rows"]


def test_current_deposition_internal_diagnostics_include_required_fields():
    required = {
        "fh",
        "Cv",
        "frho",
        "frhopredi1",
        "frhopredi2",
        "deporate",
        "rhodepo",
        "fvdepo",
        "tempdebdepothick",
        "Deposit_depth_exported",
        "Erosion_depth_exported",
        "Volumetric_sediment_exported",
        "qmassnet",
        "frhoflux",
        "extra_neighbor_flag",
    }
    with (PHASE / "current_deposition_internal_20a_600s.csv").open(encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert required <= set(reader.fieldnames or [])
