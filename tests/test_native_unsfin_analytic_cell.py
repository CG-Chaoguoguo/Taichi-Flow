import math

import tools.diagnostics.native_unsfin_analytic_cell as analytic
from tools.diagnostics.native_unsfin_analytic_cell import (
    ActiveContext,
    CellFieldPack,
    Coefficients,
    DoublelayerState,
    RootResult,
    ZoneParams,
    evaluate_doublelayer_top,
    evaluate_inidoublelayer,
    native_tfirst_search_cell,
    parse_edda_in,
    roota,
    rootb,
    rootc,
    unsfin_coefficients,
)


def _write_ascii_grid(path, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [" ".join(str(value) for value in row) for row in values]
    path.write_text(
        "\n".join(
            [
                f"ncols {len(values[0])}",
                f"nrows {len(values)}",
                "xllcorner 0",
                "yllcorner 0",
                "cellsize 1",
                "NODATA_value -9999",
                *rows,
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_case_grids(case_dir, *, zones):
    data_dir = case_dir / "Data" / "tutorial"
    _write_ascii_grid(data_dir / "slope.asc", [[20 for _ in zones]])
    _write_ascii_grid(data_dir / "zones.asc", [zones])
    _write_ascii_grid(data_dir / "glacier.asc", [[3.0 for _ in zones]])
    _write_ascii_grid(data_dir / "rizero.asc", [[1.0e-9 for _ in zones]])


def _edda_in_text(zone_blocks: str, *, zone_count: int = 1) -> str:
    return f"""EDDA: integrated simulation of debris flow erosion, deposition and property changes
EDDA_1.5
imax, row, col, nwf, tx, nmax,flow-direction numbering scheme (ESRI=1, TopoIndex=2)
2, 1, 2, 400000, 1, 10, 1
nzsb, nzst, mmax, nper, zmin, uww, t(rainfall), zones
10, 10, 100, 2, 0.001, 9.8e3, 7200, {zone_count}
ltstar, lbstar, zmax, depth, rizero, Min_Slope_Angle (degrees)
-1, 4, 7, 7, 1.0e-9, 0.1
nojunction, nooutfall, noconduits
0, 0, 0
nsection
0
{zone_blocks}
cri(1), cri(2), ..., cri(nper)
1.0e-6 2.0e-6
capt(1), capt(2), ..., capt(n), capt(n+1)
0 3600 7200
File name of slope angle grid (slofil)
Data\\tutorial\\slope.asc
File name of dem file grid (demfil)
Data\\tutorial\\dem.asc
File name of property zone grid (zonfil)
Data\\tutorial\\zones.asc
File name of depth grid (zfil)
Data\\tutorial\\glacier.asc
File name of initial infiltration rate grid (rizerofil)
Data\\tutorial\\rizero.asc
"""


def _zone_block(zone_id: int, label: str, top_kst: float) -> str:
    return f"""zone, {zone_id} {label}
cohesion,sdcohesion,phi, sdphi,phib, sdphib,uws, diffus, K-sat, Theta-sat,Theta-res,Theta-ini,porosity, psi, Alpha (bottom layer)
2.0e+07, 5.3e3, 52, 5.10, 24, 3.69, 2.65e+04, 2.3e-5, 2.0e-7, 0.2, 0.07, 0.1155, 0.35, 5.1e-2, 0.7
cohesion,sdcohesion,phi, sdphi,phib, sdphib,uws, diffus, K-sat, Theta-sat,Theta-res,Theta-ini,porosity, psi, Alpha, kero, ctao, cvero (top layer)
2.0e+04, 1.0e3, 16, 5.10, 24, 3.69, 2.00e+04, 2.3e-5, {top_kst}, 0.5, 0.27, 0.1155, 0.35, 5.1e-2, 0.7, 1.8e-6, 10, 0.55"""


def test_parse_edda_in_preserves_single_zone_copied_layout(tmp_path):
    case_dir = tmp_path / "single_zone"
    case_dir.mkdir()
    _write_case_grids(case_dir, zones=[1, 1])
    (case_dir / "edda_in.txt").write_text(
        _edda_in_text(_zone_block(1, "(Vegetated land)", 1.0e-6), zone_count=1),
        encoding="utf-8",
    )

    config = parse_edda_in(case_dir)
    context = analytic.build_active_context(case_dir)
    pack = analytic.make_field_pack_for_cell(context, 1)

    assert config["paths"]["zone"] == "Data\\tutorial\\zones.asc"
    assert sorted(config["zones"]) == [1]
    assert pack.zone_id == 1
    assert pack.zone.kst == 1.0e-6


def test_parse_edda_in_handles_multizone_test31_labels(tmp_path):
    case_dir = tmp_path / "test31_style"
    case_dir.mkdir()
    _write_case_grids(case_dir, zones=[2, 3])
    zone_blocks = "\n".join(
        [
            _zone_block(1, "Bedrock(non-erodible)", 4.0e-6),
            _zone_block(2, "Channel_upper", 8.0e-6),
            _zone_block(3, "Channel_lower", 8.0e-6),
        ]
    )
    (case_dir / "edda_in.txt").write_text(_edda_in_text(zone_blocks, zone_count=3), encoding="utf-8")

    config = parse_edda_in(case_dir)
    context = analytic.build_active_context(case_dir)
    upper = analytic.make_field_pack_for_cell(context, 1)
    lower = analytic.make_field_pack_for_cell(context, 2)

    assert config["paths"]["zone"] == "Data\\tutorial\\zones.asc"
    assert config["paths"]["zone"] != "zone, 3 Channel_lower"
    assert sorted(config["zones"]) == [1, 2, 3]
    assert upper.zone_id == 2
    assert lower.zone_id == 3
    assert upper.zone.kst == 8.0e-6
    assert lower.zone.kst == 8.0e-6


def test_eligibility_uses_source_backed_unsfin_ltstar_gate(tmp_path):
    case_dir = tmp_path / "test31_gate"
    case_dir.mkdir()
    _write_case_grids(case_dir, zones=[2, 3])
    _write_ascii_grid(case_dir / "Data" / "tutorial" / "glacier.asc", [[15.0, 10.0]])
    zone_blocks = "\n".join(
        [
            _zone_block(1, "Bedrock(non-erodible)", 4.0e-6),
            _zone_block(2, "Channel_upper", 8.0e-6),
            _zone_block(3, "Channel_lower", 8.0e-6),
        ]
    )
    (case_dir / "edda_in.txt").write_text(_edda_in_text(zone_blocks, zone_count=3), encoding="utf-8")
    (case_dir / "unsfin.F90").write_text("      if (ltstar(i)>15) cycle\n", encoding="utf-8")

    config = parse_edda_in(case_dir)
    context = analytic.build_active_context(case_dir)

    assert config["ltstar_upper_gate"] == 15.0
    assert analytic.eligibility_for_cell(context, 1) == (True, None)
    assert analytic.eligibility_for_cell(context, 2) == (True, None)


def test_eligibility_keeps_default_ltstar_gate_without_unsfin_source(tmp_path):
    case_dir = tmp_path / "default_gate"
    case_dir.mkdir()
    _write_case_grids(case_dir, zones=[1])
    _write_ascii_grid(case_dir / "Data" / "tutorial" / "glacier.asc", [[15.0]])
    (case_dir / "edda_in.txt").write_text(
        _edda_in_text(_zone_block(1, "(Vegetated land)", 1.0e-6), zone_count=1),
        encoding="utf-8",
    )

    config = parse_edda_in(case_dir)
    context = analytic.build_active_context(case_dir)

    assert config["ltstar_upper_gate"] == 5.0
    assert analytic.eligibility_for_cell(context, 1) == (False, "ltstar_gt_5")


def test_parse_edda_in_missing_property_zone_label_fails_closed(tmp_path):
    case_dir = tmp_path / "bad_case"
    case_dir.mkdir()
    _write_case_grids(case_dir, zones=[1])
    text = _edda_in_text(_zone_block(1, "(Vegetated land)", 1.0e-6), zone_count=1)
    text = text.replace("File name of property zone grid (zonfil)\nData\\tutorial\\zones.asc\n", "")
    (case_dir / "edda_in.txt").write_text(text, encoding="utf-8")

    try:
        parse_edda_in(case_dir)
    except ValueError as exc:
        assert "property zone grid|zonfil" in str(exc)
    else:
        raise AssertionError("Expected missing property zone label to fail closed")


def test_parse_edda_in_zone_count_mismatch_fails_closed(tmp_path):
    case_dir = tmp_path / "bad_zone_count"
    case_dir.mkdir()
    _write_case_grids(case_dir, zones=[1, 2])
    zone_blocks = "\n".join(
        [
            _zone_block(1, "Bedrock(non-erodible)", 4.0e-6),
            _zone_block(2, "Channel_upper", 8.0e-6),
        ]
    )
    (case_dir / "edda_in.txt").write_text(_edda_in_text(zone_blocks, zone_count=3), encoding="utf-8")

    try:
        parse_edda_in(case_dir)
    except ValueError as exc:
        assert "Parsed 2 zone blocks, expected 3" in str(exc)
    else:
        raise AssertionError("Expected missing zone block to fail closed")


def test_root_components_match_original_cell_21846_trace_values():
    beta = 1.0e-2
    lt = 8.6939658047138590e-1
    lb = 1.1591954406285143
    kst = 9.9999999999999995e-7
    ksb = 1.0e-8

    roots_a = roota(10, beta, lt, lb, kst, ksb)
    roots_b = rootb(10, beta, lt, lb, kst, ksb)
    roots_c = rootc(10, beta, lt, lb, kst, ksb)

    assert len(roots_a.lambdas) == 10
    assert len(roots_b.lambdas) == 0
    assert len(roots_c.lambdas) == 2
    assert abs(roots_a.lambdas[0] - 5.6658813915254953) < 1.0e-9
    assert abs(roots_a.mius[0] - 0.27114962553606609) < 1.0e-9
    assert abs(roots_c.lambdas[0] - 3.1572420685326734) < 1.0e-9
    assert abs(roots_c.mius[0] - 0.38447135810990557) < 1.0e-9


def test_rootc_uses_original_default_real_deltamiu_semantic():
    roots_c = rootc(
        10,
        beta=1.0e-2,
        lt=0.8937509580496752,
        lb=1.1916679440662334,
        kst=1.0e-6,
        ksb=1.0e-8,
    )

    assert analytic.FORTRAN_ROOTC_DELTAMIU_DEFAULT_REAL != 0.01
    assert len(roots_c.lambdas) == 2
    assert abs(roots_c.lambdas[0] - 3.0752170723485186) < 1.0e-12
    assert abs(roots_c.mius[0] - 0.3910631657154149) < 1.0e-12
    assert abs(roots_c.lambdas[1] - 1.0699026139986674) < 1.0e-12
    assert abs(roots_c.mius[1] - 0.48585294479460367) < 1.0e-12


def test_doublelayer_cell_21846_trace_reaches_fdepth_gindx_event():
    zone = ZoneParams(
        cb=1.0e5,
        ct=1.0e4,
        phib=math.radians(39.0),
        phit=math.radians(24.0),
        phibb=math.radians(24.6),
        phibt=math.radians(24.6),
        uwsb=2.1e4,
        uwst=2.1e4,
        ksb=1.0e-8,
        kst=1.0e-6,
        thsatb=0.4,
        thsatt=0.4,
        thresib=0.25,
        thresit=0.25,
        alphab=0.8,
        alphat=0.8,
    )
    pack = CellFieldPack(
        cell=21846,
        row=215,
        col=151,
        slope_rad=0.9249545158539896,
        zone_id=1,
        ltstar=3.0,
        lbstar=4.0,
        zmin=0.001,
        nzst=10,
        nzsb=10,
        uww=9.8e3,
        q=[
            1.0e-6,
            1.0e-6,
            1.0e-6,
            1.0e-6,
            1.0e-6,
            1.0e-6,
            1.0e-6,
            1.0e-6,
            1.0e-6,
            1.0e-6,
            5.01e-7,
            6.12111e-7,
            5.56556e-7,
            2.51e-7,
            1.67667e-7,
            1.12111e-7,
            5.65556e-8,
            5.65556e-8,
        ],
        capt=[float(value) for value in range(0, 64801, 3600)],
        beta=1.0e-2,
        lt=8.6939658047138590e-1,
        lb=1.1591954406285143,
        rikzero=1.0e-3,
        zone=zone,
    )
    roots_a = roota(10, pack.beta, pack.lt, pack.lb, zone.kst, zone.ksb)
    roots_b = rootb(10, pack.beta, pack.lt, pack.lb, zone.kst, zone.ksb)
    roots_c = rootc(10, pack.beta, pack.lt, pack.lb, zone.kst, zone.ksb)
    coeffs = unsfin_coefficients(
        roots_a,
        roots_b,
        roots_c,
        beta=pack.beta,
        lt=pack.lt,
        lb=pack.lb,
        kst=zone.kst,
        ksb=zone.ksb,
    )

    initial = evaluate_inidoublelayer(pack, roots_a, roots_b, roots_c, coeffs, tt=60.0)
    _rows, final = evaluate_doublelayer_top(
        pack,
        roots_a,
        roots_b,
        roots_c,
        coeffs,
        initial,
        tt=373.0,
        initial_state=DoublelayerState(fdepth=3.0, fsmin=1.0000023528399553),
    )

    assert final["fdepth"] == 3.0
    assert final["gindx"] == 1
    assert final["fsmin"] < 1.0


def test_tfirst_cell_21846_reproduces_original_first_hit():
    zone = ZoneParams(
        cb=1.0e5,
        ct=1.0e4,
        phib=math.radians(39.0),
        phit=math.radians(24.0),
        phibb=math.radians(24.6),
        phibt=math.radians(24.6),
        uwsb=2.1e4,
        uwst=2.1e4,
        ksb=1.0e-8,
        kst=1.0e-6,
        thsatb=0.4,
        thsatt=0.4,
        thresib=0.25,
        thresit=0.25,
        alphab=0.8,
        alphat=0.8,
    )
    pack = CellFieldPack(
        cell=21846,
        row=215,
        col=151,
        slope_rad=0.9249545158539896,
        zone_id=1,
        ltstar=3.0,
        lbstar=4.0,
        zmin=0.001,
        nzst=10,
        nzsb=10,
        uww=9.8e3,
        q=[
            1.0e-6,
            1.0e-6,
            1.0e-6,
            1.0e-6,
            1.0e-6,
            1.0e-6,
            1.0e-6,
            1.0e-6,
            1.0e-6,
            1.0e-6,
            5.01e-7,
            6.12111e-7,
            5.56556e-7,
            2.51e-7,
            1.67667e-7,
            1.12111e-7,
            5.65556e-8,
            5.65556e-8,
        ],
        capt=[float(value) for value in range(0, 64801, 3600)],
        beta=1.0e-2,
        lt=8.6939658047138590e-1,
        lb=1.1591954406285143,
        rikzero=1.0e-3,
        zone=zone,
    )
    roots_a = roota(10, pack.beta, pack.lt, pack.lb, zone.kst, zone.ksb)
    roots_b = rootb(10, pack.beta, pack.lt, pack.lb, zone.kst, zone.ksb)
    roots_c = rootc(10, pack.beta, pack.lt, pack.lb, zone.kst, zone.ksb)
    coeffs = unsfin_coefficients(
        roots_a,
        roots_b,
        roots_c,
        beta=pack.beta,
        lt=pack.lt,
        lb=pack.lb,
        kst=zone.kst,
        ksb=zone.ksb,
    )

    _trace, summary = native_tfirst_search_cell(
        pack,
        roots_a,
        roots_b,
        roots_c,
        coeffs,
        initial_ts=60.0,
    )

    assert summary["tfail"] == 373.0
    assert summary["fdepth"] == 3.0
    assert summary["gindx"] == 1
    assert summary["refinement_count"] == 4


def test_field_pack_uses_original_default_real_dg2rad_semantic():
    zone = ZoneParams(
        cb=1.0e5,
        ct=1.0e4,
        phib=0.0,
        phit=0.0,
        phibb=0.0,
        phibt=0.0,
        uwsb=2.1e4,
        uwst=2.1e4,
        ksb=1.0e-8,
        kst=1.0e-6,
        thsatb=0.4,
        thsatt=0.4,
        thresib=0.25,
        thresit=0.25,
        alphab=0.8,
        alphat=0.8,
    )
    context = ActiveContext(
        config={
            "zone": zone,
            "cltstar": -1.0,
            "clbstar": 4.0,
            "zmin": 0.001,
            "nzst": 10,
            "nzsb": 10,
            "uww": 9.8e3,
            "crizero": 1.0e-9,
            "cri": [1.0e-6],
            "capt": [0.0, 3600.0],
            "dg2rad": analytic.FORTRAN_MAIN_DG2RAD,
        },
        slope_values_deg=[52.20644],
        zone_values=[1.0],
        ltstar_values=[3.0],
        active_mapping=[(356, 97)],
        shape=(688, 417),
    )

    pack = analytic.make_field_pack_for_cell(context, 1)

    assert analytic.FORTRAN_MAIN_PI_DEFAULT_REAL != math.pi
    assert pack.slope_rad == 52.20644 * analytic.FORTRAN_MAIN_DG2RAD
    assert abs(pack.lt - 0.9013108008635095) < 1.0e-15
    assert abs(pack.lb - 1.2017477344846792) < 1.0e-15


def test_active_order_checkpoint_resume_matches_uninterrupted_prefix(tmp_path, monkeypatch):
    context = ActiveContext(
        config={},
        slope_values_deg=[10.0] * 5,
        zone_values=[1.0] * 5,
        ltstar_values=[3.0] * 5,
        active_mapping=[(idx, 1) for idx in range(1, 6)],
        shape=(5, 1),
    )
    zone = ZoneParams(
        cb=1.0,
        ct=1.0,
        phib=0.1,
        phit=0.1,
        phibb=0.1,
        phibt=0.1,
        uwsb=1.0,
        uwst=1.0,
        ksb=1.0,
        kst=1.0,
        thsatb=0.4,
        thsatt=0.4,
        thresib=0.1,
        thresit=0.1,
        alphab=1.0,
        alphat=1.0,
    )

    def fake_pack(_context, cell):
        return CellFieldPack(
            cell=cell,
            row=cell,
            col=1,
            slope_rad=0.2,
            zone_id=1,
            ltstar=3.0,
            lbstar=4.0,
            zmin=0.001,
            nzst=1,
            nzsb=1,
            uww=1.0,
            q=[1.0],
            capt=[0.0, 600.0],
            beta=1.0,
            lt=1.0,
            lb=1.0,
            rikzero=0.0,
            zone=zone,
        )

    def fake_tfirst(pack, *_args, initial_ts, **_kwargs):
        tfail = 100.0 + pack.cell if pack.cell in {2, 4} else None
        return [], {
            "tfail": tfail,
            "fdepth": 3.0 if tfail is not None else 0.0,
            "gindx": 1 if tfail is not None else 0,
            "fsmin": 0.9 if tfail is not None else 10.0,
            "initial_ts": initial_ts,
            "final_ts": initial_ts + pack.cell,
            "exit_reason": "tfail_assigned" if tfail is not None else "exit_no_failure_after_tsimul",
            "iterations": 1,
            "refinement_count": 0,
        }

    monkeypatch.setattr(analytic, "build_active_context", lambda _case_dir: context)
    monkeypatch.setattr(analytic, "eligibility_for_cell", lambda _context, _cell: (True, None))
    monkeypatch.setattr(analytic, "make_field_pack_for_cell", fake_pack)
    monkeypatch.setattr(analytic, "roota", lambda *_args: RootResult([], []))
    monkeypatch.setattr(analytic, "rootb", lambda *_args: RootResult([], []))
    monkeypatch.setattr(analytic, "rootc", lambda *_args: RootResult([], []))
    monkeypatch.setattr(analytic, "unsfin_coefficients", lambda *_args, **_kwargs: Coefficients([], [], []))
    monkeypatch.setattr(analytic, "native_tfirst_search_cell", fake_tfirst)

    direct, _trace, _gate, direct_summary = analytic.run_active_order_0_600(tmp_path, max_active_index=5)
    checkpoint_dir = tmp_path / "checkpoint"
    analytic.run_active_order_0_600(
        tmp_path,
        max_active_index=3,
        checkpoint_dir=checkpoint_dir,
        checkpoint_interval=2,
    )
    resumed, _trace, _gate, resumed_summary = analytic.run_active_order_0_600(
        tmp_path,
        max_active_index=5,
        checkpoint_dir=checkpoint_dir,
        resume=True,
        checkpoint_interval=2,
    )

    assert direct.gindx.tolist() == resumed.gindx.tolist()
    assert direct.fdepth_m.tolist() == resumed.fdepth_m.tolist()
    assert direct_summary["candidates_0_600"] == resumed_summary["candidates_0_600"]
    assert math.isnan(direct.tfail_s[0]) and math.isnan(resumed.tfail_s[0])
    assert direct.tfail_s[1] == resumed.tfail_s[1] == 102.0
    assert direct.tfail_s[3] == resumed.tfail_s[3] == 104.0
    assert direct_summary["ts_carry"] == resumed_summary["ts_carry"] == 75.0
