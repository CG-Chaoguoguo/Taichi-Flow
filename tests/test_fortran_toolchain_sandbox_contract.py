from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
SANDBOX = REPO_ROOT / "tests" / "_fortran_toolchain_sandbox"


def _load_validator_module():
    validator_path = SANDBOX / "scripts" / "validate_precomputed_unsfin_artifacts.py"
    spec = importlib.util.spec_from_file_location("validate_precomputed_unsfin_artifacts", validator_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_ascii_grid(path: Path, values: np.ndarray, nodata: float = -9999.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(f"ncols {values.shape[1]}\n")
        handle.write(f"nrows {values.shape[0]}\n")
        handle.write("xllcorner 0\n")
        handle.write("yllcorner 0\n")
        handle.write("cellsize 1\n")
        handle.write(f"NODATA_value {nodata}\n")
        for row in values:
            handle.write(" ".join(str(v) for v in row) + "\n")


def _write_precomputed_artifacts(case_dir: Path, tfail: np.ndarray) -> None:
    _write_ascii_grid(case_dir / "precomputed_unsfin_gindx.txt", np.array([[1, 0], [0, 1]], dtype=np.float64))
    _write_ascii_grid(case_dir / "precomputed_unsfin_tfail.txt", tfail)
    _write_ascii_grid(case_dir / "precomputed_unsfin_fdepth.txt", np.array([[0.2, 0.0], [0.0, 0.4]], dtype=np.float64))
    (case_dir / "precomputed_unsfin_meta.json").write_text(
        json.dumps({"provider": "synthetic_test"}),
        encoding="utf-8",
    )


def test_fortran_toolchain_sandbox_structure_and_gitignore_contract():
    assert (SANDBOX / "README.md").exists()
    assert (SANDBOX / ".gitignore").exists()
    for dirname in ("scripts", "patches", "fixtures", "generated", "logs", "toolchain", "work"):
        assert (SANDBOX / dirname).is_dir()

    for script_name in (
        "probe_fortran_toolchain.ps1",
        "install_msys2_gfortran.ps1",
        "setup_intel_oneapi_probe.ps1",
        "build_instrumented_edda.ps1",
        "run_instrumented_original_cases.ps1",
        "validate_precomputed_unsfin_artifacts.py",
    ):
        assert (SANDBOX / "scripts" / script_name).exists()

    assert (SANDBOX / "patches" / "instrument_tfail_dump.patch").exists()

    gitignore = (SANDBOX / ".gitignore").read_text(encoding="utf-8")
    for pattern in ("/generated/*", "/logs/*", "/toolchain/*", "/work/*", "*.exe", "*.obj", "*.mod", "*.pdb"):
        assert pattern in gitignore


def test_precomputed_unsfin_validator_accepts_synthetic_artifacts(tmp_path):
    validator = _load_validator_module()
    case_a = tmp_path / "20a"
    case_b = tmp_path / "50a"
    output_dir = tmp_path / "generated"
    _write_precomputed_artifacts(case_a, np.array([[100.0, 9999.0], [9999.0, 700.0]], dtype=np.float64))
    _write_precomputed_artifacts(case_b, np.array([[120.0, 9999.0], [9999.0, 720.0]], dtype=np.float64))

    report = validator.build_validation_report(case_a, case_b)
    assert report["case_a"]["summary"]["parse_status"] == "ok"
    assert report["case_a"]["summary"]["scheduled_cell_count"] == 2
    assert report["paired_diff"]["status"] == "ok"
    assert report["paired_diff"]["tfail_diff"]["nonzero_count"] == 2

    json_path, md_path = validator.write_reports(report, output_dir)
    assert json_path.exists()
    assert md_path.exists()
    assert "Original Tfail Artifact Validation" in md_path.read_text(encoding="utf-8")
