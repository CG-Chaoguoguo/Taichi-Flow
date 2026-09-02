"""Regression coverage for content-addressed reference-case input binding."""

from pathlib import Path

from api.services.runtime_session import prepare_runtime_from_payload
from tests.test_native_input_chain import _make_reference_case


def test_reference_runtime_rebinds_uploaded_native_files_before_activation(tmp_path):
    source_config = _make_reference_case(tmp_path / "source")
    source_case = source_config.parent
    upload_dir = tmp_path / "uploaded"
    upload_dir.mkdir()
    uploaded_config = upload_dir / "edda_in.txt"
    uploaded_config.write_text(
        source_config.read_text(encoding="utf-8").replace(
            "10, 10, 100, 2, 0.001, 9.8e3, 7200, 1",
            "10, 10, 100, 2, 0.001, 9.8e3, 7200, 2",
        ).replace(
            "Simulate shallow landslide? Enter T (.true.) or F (.false.)\nT",
            "Simulate shallow landslide? Enter T (.true.) or F (.false.)\nF",
        ),
        encoding="utf-8",
    )
    project_root = tmp_path / "empty-project-root"
    project_root.mkdir()
    tutorial = source_case / "Data" / "tutorial"

    prepared = prepare_runtime_from_payload(
        app_output_dir=tmp_path / "outputs",
        output_dir=str(tmp_path / "outputs" / "run"),
        dem_file=str(tutorial / "bcdem.asc"),
        soil_zones_file=str(tutorial / "bczone.asc"),
        case_config_file=str(uploaded_config),
        case_base_dir=str(project_root),
        case_input_files={
            "slofil": str(tutorial / "bcslope.asc"),
            "zfil": str(tutorial / "bcltstar.asc"),
            "outflow.txt": str(source_case / "outflow.txt"),
            "inflow.txt": str(source_case / "inflow.txt"),
        },
        runtime_profile_name="cuda_production_default",
    )

    inputs = {entry["family"]: entry for entry in prepared.runtime_input_manifest["inputs"]}
    assert Path(prepared.config.dem_file) == tutorial / "bcdem.asc"
    assert prepared.config.spatial_zones is not None
    assert Path(prepared.config.spatial_zones.zone_file) == tutorial / "bczone.asc"

    assert Path(inputs["zonfil"]["path"]) == tutorial / "bczone.asc"
    assert inputs["zonfil"]["exists_on_disk"] is True
    assert Path(inputs["outflow.txt"]["path"]) == source_case / "outflow.txt"
    assert inputs["outflow.txt"]["original_branch_active"] is True
    assert inputs["outflow.txt"]["current_backend_branch_active"] is True
    assert inputs["outflow.txt"]["structure_summary"]["cell_ids"] == [1]
    assert Path(inputs["inflow.txt"]["path"]) == source_case / "inflow.txt"
    assert inputs["inflow.txt"]["structure_summary"]["declared_cell_count"] == 1
