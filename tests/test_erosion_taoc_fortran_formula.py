from __future__ import annotations

import math

import numpy as np

from api.services.edda_input_mapper import build_reference_runtime_metadata
from api.services.reference_config_parser import parse_reference_config_file
from tests.test_native_input_chain import _make_reference_case
from tests.test_native_runtime_consumption import _initialize_real_solver


def _make_ctao_case(tmp_path, ctao: float = 12.5):
    edda_in = _make_reference_case(tmp_path)
    text = edda_in.read_text(encoding="utf-8")
    text = text.replace(
        "4000 0 28 0 14 0 20500 2e-6 2e-5 0.43 0.04 0.18 0.38 0.09 1.8 2e-6",
        f"4000 0 28 0 14 0 20500 2e-6 2e-5 0.43 0.04 0.18 0.38 0.09 1.8 2e-6 {ctao}",
    )
    edda_in.write_text(text, encoding="utf-8")
    return edda_in


def test_native_parser_and_mapper_preserve_top_layer_ctao(tmp_path):
    edda_in = _make_ctao_case(tmp_path, ctao=12.5)

    parsed = parse_reference_config_file(str(edda_in))
    config, _, _, _ = build_reference_runtime_metadata(parsed, tmp_path / "out")

    assert parsed.zones[1].top.ctao == 12.5
    assert config.erosion.ctao == 12.5
    assert config.erosion.tau_c == 12.5
    assert config.spatial_zones.zones[1].ctao == 12.5


def test_fortran_style_taoc_uses_ctao_cv_h_slope_and_phi(tmp_path):
    edda_in = _make_ctao_case(tmp_path, ctao=15.0)
    solver, _, _, _ = _initialize_real_solver(edda_in, tmp_path / "out_taoc_formula")
    dfs = solver.dfs_dynamic_wave
    shape = (solver.fields.nx, solver.fields.ny)

    h = np.full(shape, 0.4, dtype=np.float64)
    cv = np.full(shape, 0.25, dtype=np.float64)
    fhpredi1 = np.full(shape, 0.5, dtype=np.float64)
    frhopredi1 = np.full(
        shape,
        solver.config.rheology.rho_water
        + cv[0, 0] * (solver.config.rheology.rho_sediment - solver.config.rheology.rho_water),
        dtype=np.float64,
    )
    phi = np.full(shape, 24.0, dtype=np.float64)
    slope = np.full(shape, 0.2, dtype=np.float64)
    ctao = np.full(shape, 15.0, dtype=np.float64)
    old_c = np.full(shape, 4000.0, dtype=np.float64)
    cvlimit = np.full(shape, 0.65, dtype=np.float64)
    rholimit = np.full(
        shape,
        solver.config.rheology.rho_water
        + cvlimit[0, 0] * (solver.config.rheology.rho_sediment - solver.config.rheology.rho_water),
        dtype=np.float64,
    )

    solver.fields.h.from_numpy(h)
    solver.fields.Cv.from_numpy(cv)
    solver.fields.fhpredi1.from_numpy(fhpredi1)
    solver.fields.frhopredi1.from_numpy(frhopredi1)
    solver.fields.phi_field.from_numpy(phi)
    solver.fields.slope_angle.from_numpy(slope)
    solver.fields.tanslo_fortran.from_numpy(np.tan(slope))
    solver.fields.ctao_field.from_numpy(ctao)
    solver.fields.c_field.from_numpy(old_c)
    solver.fields.cvlimit_temp.from_numpy(cvlimit)
    solver.fields.rholimit_temp.from_numpy(rholimit)

    dfs._compute_source_rates(
        1.0,
        solver.config.rheology.rho_water,
        solver.config.rheology.rho_sediment,
        solver.config.rheology.Cv_max,
    )

    expected = (
        15.0
        + (1.0 - solver.config.rheology.cs)
        * 0.25
        * (solver.config.rheology.rho_sediment - solver.config.rheology.rho_water)
        * dfs.g
        * 0.4
        * math.cos(0.2) ** 2
        * math.tan(math.radians(24.0))
    )
    taoc = solver.fields.taoc_temp.to_numpy()
    taoc_fortran = solver.fields.taoc_fortran_temp.to_numpy()
    taoc_old = solver.fields.taoc_old_temp.to_numpy()

    np.testing.assert_allclose(taoc, np.full(shape, expected), rtol=1.0e-6, atol=1.0e-6)
    np.testing.assert_allclose(taoc_fortran, taoc, rtol=1.0e-12, atol=1.0e-12)
    assert float(np.min(taoc_old)) > expected
