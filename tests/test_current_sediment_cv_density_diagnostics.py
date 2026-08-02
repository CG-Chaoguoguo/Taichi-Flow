import csv
import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PHASE = REPO / "PROJECT_REPORTS" / "agent_runs" / "2026-04-29" / "phase_volumetric_sediment_cv_mass_extra_neighbor_response_repair"


def test_current_sediment_diagnostics_exist_for_both_cases():
    report = (PHASE / "current_sediment_cv_density_diagnostics_report.md").read_text(encoding="utf-8")
    assert "CURRENT_SEDIMENT_DIAGNOSTICS_READY" in report

    for case_key in ("20a", "50a"):
        csv_path = PHASE / f"current_sediment_cv_density_diagnostics_{case_key}_600s.csv"
        json_path = PHASE / f"current_sediment_cv_density_diagnostics_{case_key}_600s.json"
        assert csv_path.exists()
        assert json_path.exists()
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        assert payload["rows"]


def test_current_sediment_diagnostics_include_required_fields_and_event_cells():
    required = {
        "fh_output_600s",
        "Cv_output_600s",
        "Cv_fortran_writer_candidate_600s",
        "original_Cv_output_600s",
        "frho_from_Cv_output_600s",
        "fh_lt_0p005_writer_mask",
        "qmassnet",
        "qqmass",
        "frhoflux",
    }
    expected_cells = {"20a": {36761, 36762, 37023}, "50a": {36761, 36762, 36763, 37023}}
    for case_key, cells in expected_cells.items():
        with (PHASE / f"current_sediment_cv_density_diagnostics_{case_key}_600s.csv").open(encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            assert required <= set(reader.fieldnames or [])
            rows = list(reader)
        found = {int(float(row["cell_id"])) for row in rows if row.get("cell_id")}
        assert cells <= found
