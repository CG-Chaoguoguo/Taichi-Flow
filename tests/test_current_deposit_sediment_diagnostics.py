import csv
import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PHASE = REPO / "PROJECT_REPORTS" / "agent_runs" / "2026-04-29" / "phase_deposit_sediment_internal_extra_neighbor_repair_with_comparison_reports"


def test_current_deposit_sediment_diagnostics_exist():
    report = (PHASE / "current_deposit_sediment_diagnostics_report.md").read_text(encoding="utf-8")
    assert "CURRENT_DEPOSIT_SEDIMENT_DIAGNOSTICS_READY" in report

    for case_key in ("20a", "50a"):
        csv_path = PHASE / f"current_deposit_sediment_diagnostics_{case_key}_600s.csv"
        json_path = PHASE / f"current_deposit_sediment_diagnostics_{case_key}_600s.json"
        assert csv_path.exists()
        assert json_path.exists()
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        assert payload["rows"]


def test_current_deposit_sediment_diagnostics_include_required_cell_sets():
    expected_cells = {"20a": {36761, 36762, 37023}, "50a": {36761, 36762, 36763, 37023}}
    required = {
        "Deposit_depth_exported",
        "original_Deposit_depth",
        "Deposit_depth_gap",
        "Volumetric_sediment_exported",
        "Erosion_depth_exported",
        "extra_neighbor_flag",
    }
    for case_key, cells in expected_cells.items():
        with (PHASE / f"current_deposit_sediment_diagnostics_{case_key}_600s.csv").open(encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            assert required <= set(reader.fieldnames or [])
            rows = list(reader)
        found = {int(float(row["cell_id"])) for row in rows if row.get("cell_id")}
        assert cells <= found
