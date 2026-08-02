from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def test_erosion_writer_parity_remains_active():
    solver_text = (REPO / "edda" / "solver" / "edda_solver.py").read_text(encoding="utf-8")

    assert "_build_fortran_erosion_depth_output" in solver_text
    assert "eleori-ele" in solver_text
    assert "0.001" in solver_text
    assert "gindx == 1" in solver_text
