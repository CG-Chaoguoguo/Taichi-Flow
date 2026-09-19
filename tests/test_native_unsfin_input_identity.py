"""Input identity regressions; never remap a material row by active count alone."""
from pathlib import Path

import numpy as np
import pytest

from edda.solver.native_unsfin import analytic_cell as analytic


def _grid(path, values, *, x=0, y=0, cellsize=30, center=False, bom=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    values = np.asarray(values)
    origin = f"xllcenter {x + cellsize / 2}\nyllcenter {y + cellsize / 2}" if center else f"xllcorner {x}\nyllcorner {y}"
    text = f"ncols {values.shape[1]}\nnrows {values.shape[0]}\n{origin}\ncellsize {cellsize}\nNODATA_value -9999\n"
    text += "\n".join(" ".join(map(str, row)) for row in values) + "\n"
    path.write_text(text, encoding="utf-8-sig" if bom else "utf-8")


def _case(tmp_path, monkeypatch, *, style="/", slope=None, zone=None, ltstar=None, x=0):
    paths = {}
    for name, values in [("slope", [[10, 20], [30, 40]] if slope is None else slope),
                         ("zone", [[1, 1], [2, 2]] if zone is None else zone),
                         ("ltstar", [[2, 2], [3, 3]] if ltstar is None else ltstar)]:
        relative = f"Data with spaces/{name}.asc"
        _grid(tmp_path / relative, values, x=x if name == "zone" else 0)
        paths[name] = relative.replace("/", style)
    monkeypatch.setattr(analytic, "parse_edda_in", lambda _: {"paths": paths})
    return paths


@pytest.mark.parametrize("style", ["/", "\\"])
def test_native_context_resolves_legacy_paths_without_changing_provenance(tmp_path, monkeypatch, style):
    paths = _case(tmp_path, monkeypatch, style=style)
    context = analytic.build_active_context(tmp_path)
    assert context.config["paths"] == paths
    assert context.active_mapping == [(1, 1), (1, 2), (2, 1), (2, 2)]
    assert context.zone_values == [1.0, 1.0, 2.0, 2.0]
    assert context.shape == (2, 2)


@pytest.mark.parametrize("builder", [analytic.build_active_context, lambda path: analytic.build_cell_field_packs(path, {})])
@pytest.mark.parametrize("defect", ["mask", "origin", "fractional_zone", "nonfinite", "shape"])
def test_native_inputs_fail_closed_in_both_consumers(tmp_path, monkeypatch, builder, defect):
    kwargs = {}
    if defect == "mask":
        kwargs = {"slope": [[10, -9999], [30, 40]], "zone": [[-9999, 1], [2, 2]], "ltstar": [[2, -9999], [3, 3]]}
    elif defect == "origin":
        kwargs = {"x": 30}
    elif defect == "fractional_zone":
        kwargs = {"zone": [[1.5, 1], [2, 2]]}
    elif defect == "nonfinite":
        kwargs = {"ltstar": [[2, np.nan], [3, 3]]}
    elif defect == "shape":
        kwargs = {"zone": [[1, 1, 2, 2]]}
    _case(tmp_path, monkeypatch, **kwargs)
    with pytest.raises(ValueError):
        builder(tmp_path)


def test_reader_validates_declared_shape_and_preserves_one_based_active_order(tmp_path):
    path = tmp_path / "grid.asc"
    _grid(path, [[1, -9999], [2, 3]])
    values, mapping, _ = analytic.read_ascii_active_values(path)
    assert values == [1., 2., 3.]
    assert mapping == [(1, 1), (2, 1), (2, 2)]
    path.write_text(path.read_text().replace("nrows 2", "nrows 3"))
    with pytest.raises(ValueError):
        analytic.read_ascii_active_values(path)


def test_equivalent_center_origin_and_utf8_bom_are_not_misregistered(tmp_path, monkeypatch):
    paths = _case(tmp_path, monkeypatch)
    _grid(tmp_path / paths["zone"], [[1, 1], [2, 2]], center=True, bom=True)
    assert analytic.build_active_context(tmp_path).zone_values == [1., 1., 2., 2.]


def test_equivalent_decimal_center_and_corner_origins_are_not_misregistered(tmp_path, monkeypatch):
    paths = _case(tmp_path, monkeypatch)
    for family, values in (("slope", [[10, 20], [30, 40]]), ("zone", [[1, 1], [2, 2]]), ("ltstar", [[2, 2], [3, 3]])):
        _grid(
            tmp_path / paths[family],
            values,
            x=0.1,
            y=0.1,
            cellsize=0.1,
            center=family == "zone",
        )
    assert analytic.build_active_context(tmp_path).zone_values == [1., 1., 2., 2.]


@pytest.mark.parametrize("raw", ["", "  ", "C:relative.asc", r"\root-relative.asc", r"\\server\share\grid.asc", "/root-relative.asc", "/data/slope.asc"])
def test_ambiguous_paths_never_become_silent_relative_paths(tmp_path, raw):
    from edda.solver.native_unsfin.input_grid import resolve_native_input_path
    # Host-absolute POSIX /abs paths are not Windows root-relative; they must
    # fail as missing files, not as a silent join onto case_dir.
    expected = FileNotFoundError if raw.startswith("/") and Path(raw).is_absolute() else ValueError
    with pytest.raises(expected):
        resolve_native_input_path(tmp_path, raw)


def test_native_absolute_quoted_missing_and_foreign_drive_paths(tmp_path):
    import os
    from edda.solver.native_unsfin.input_grid import resolve_native_input_path
    path = tmp_path / "grid with spaces.asc"
    _grid(path, [[1]])
    assert resolve_native_input_path(tmp_path, f'"{path}"') == path
    with pytest.raises(FileNotFoundError):
        resolve_native_input_path(tmp_path, "missing.asc")
    if os.name != "nt":
        with pytest.raises(ValueError, match="Foreign Windows drive"):
            resolve_native_input_path(tmp_path, r"Z:\data\grid.asc")
