"""Diagnostic loader and dry-run calculator for original RNOFF TopoIndex sidecars.

This module intentionally does not mutate solver runtime state.  It reproduces
the original ``rnoff.F90`` runoff-routing sidecar branch for diagnostics and
oracle comparisons.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import math
import os
import re
from typing import Dict, Iterable, List, Mapping, Sequence


NUMBER_RE = re.compile(r"[-+]?(?:\d+\.\d*|\d+|\.\d+)(?:[eEdD][-+]?\d+)?")
RNOFF_TOPOINDEX_RUNTIME_FLAG = "EDDA_EXPERIMENT_RNOFF_TOPOINDEX"
GPU_ONLY_PRODUCTION_SMOKE_ENV = "EDDA_EXPERIMENT_GPU_ONLY_PRODUCTION_SMOKE"


class TopoIndexSidecarError(ValueError):
    """Raised when TopoIndex sidecar inputs cannot be interpreted safely."""


@dataclass(frozen=True)
class TopoIndexSidecars:
    """One-based TopoIndex sidecar arrays matching original RNOFF semantics."""

    imax: int
    nxt: List[int]
    indx: List[int]
    dsctr: List[int]
    dsc: List[int]
    wf: List[float]
    metadata: Dict[str, object]


@dataclass(frozen=True)
class RnoffDryRunResult:
    """Dry-run output for the original RNOFF sidecar branch."""

    sidecar_branch_active: bool
    cells: List[Dict[str, float | int]]
    sidecar_mappings: List[Dict[str, float | int]]
    trace: List[Dict[str, float | int | str]]
    totals: Dict[str, float]


@dataclass(frozen=True)
class RnoffPrecomputeContract:
    """Source-aligned pre-DFS period precompute manifest for RNOFF/TopoIndex."""

    manifest: Dict[str, object]


def _numeric_tokens(line: str) -> List[float]:
    return [float(token.replace("D", "E").replace("d", "e")) for token in NUMBER_RE.findall(line)]


def _read_numeric_tokens(path: Path) -> List[float]:
    tokens: List[float] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        tokens.extend(_numeric_tokens(line))
    return tokens


def _file_sha256(path: str | Path | None) -> str | None:
    if not path:
        return None
    candidate = Path(path)
    if not candidate.is_file():
        return None
    digest = hashlib.sha256()
    with candidate.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_file(path: str | Path, family: str) -> Path:
    candidate = Path(path)
    if not candidate.exists():
        raise FileNotFoundError(f"{family} sidecar file not found: {candidate}")
    if not candidate.is_file():
        raise TopoIndexSidecarError(f"{family} sidecar path is not a file: {candidate}")
    return candidate


def _read_ascii_int_grid(path: str | Path, *, imax: int, nodata: int = -9999) -> Dict[str, object]:
    grid = _require_file(path, "nxtfil")
    lines = [line.strip() for line in grid.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip()]
    if len(lines) < 7:
        raise TopoIndexSidecarError(f"nxtfil grid is missing header/data rows: {grid}")

    header: Dict[str, float] = {}
    for line in lines[:6]:
        parts = line.split()
        if len(parts) < 2:
            raise TopoIndexSidecarError(f"Invalid ASCII grid header line in {grid}: {line!r}")
        key = parts[0].lower()
        value = _numeric_tokens(" ".join(parts[1:]))
        if not value:
            raise TopoIndexSidecarError(f"Invalid ASCII grid header value in {grid}: {line!r}")
        header[key] = value[0]

    try:
        ncols = int(header["ncols"])
        nrows = int(header["nrows"])
    except KeyError as exc:
        raise TopoIndexSidecarError(f"nxtfil grid missing required header: {exc.args[0]}") from exc
    nodata_value = int(header.get("nodata_value", nodata))
    rows = lines[6:]
    if len(rows) != nrows:
        raise TopoIndexSidecarError(f"nxtfil expected {nrows} data rows, found {len(rows)}")

    active_values: List[int] = [0]
    for row in rows:
        values = [int(value) for value in _numeric_tokens(row)]
        if len(values) != ncols:
            raise TopoIndexSidecarError(f"nxtfil row expected {ncols} values, found {len(values)}: {row!r}")
        for value in values:
            if value != nodata_value:
                active_values.append(int(value))
    if len(active_values) - 1 != imax:
        raise TopoIndexSidecarError(f"nxtfil active-cell count {len(active_values)-1} does not match imax {imax}")
    for cell_id, target in enumerate(active_values[1:], start=1):
        if target < 1 or target > imax:
            raise TopoIndexSidecarError(f"nxtfil target for cell {cell_id} is out of range: {target}")
    return {"values": active_values, "header": header, "path": str(grid)}


def _read_indx(path: str | Path, *, imax: int) -> List[int]:
    sidecar = _require_file(path, "ndxfil")
    values = [int(value) for value in _read_numeric_tokens(sidecar)]
    if len(values) < imax * 2:
        raise TopoIndexSidecarError(f"ndxfil expected at least {imax} row pairs, found {len(values)//2}")
    indx = [0] * (imax + 1)
    seen_positions = set()
    for offset in range(0, imax * 2, 2):
        position = int(values[offset])
        cell_id = int(values[offset + 1])
        if position < 1 or position > imax:
            raise TopoIndexSidecarError(f"ndxfil position out of range: {position}")
        if cell_id < 1 or cell_id > imax:
            raise TopoIndexSidecarError(f"ndxfil cell id out of range at position {position}: {cell_id}")
        if position in seen_positions:
            raise TopoIndexSidecarError(f"ndxfil duplicate position: {position}")
        indx[position] = cell_id
        seen_positions.add(position)
    missing = [idx for idx in range(1, imax + 1) if indx[idx] == 0]
    if missing:
        raise TopoIndexSidecarError(f"ndxfil missing positions: {missing}")
    return indx


def _read_sawtooth_int(path: str | Path, *, imax: int, marker: int = -9999) -> tuple[List[int], List[int]]:
    sidecar = _require_file(path, "dscfil")
    tokens = [int(value) for value in _read_numeric_tokens(sidecar)]
    entries = [0]
    dsctr = [0] * (imax + 2)
    idx = 0
    while idx < len(tokens):
        value = tokens[idx]
        if value == marker:
            idx += 1
            if idx >= len(tokens):
                raise TopoIndexSidecarError("dscfil marker is missing following row id")
            row_id = tokens[idx]
            if row_id < 1 or row_id > imax + 1:
                raise TopoIndexSidecarError(f"dscfil row marker out of range: {row_id}")
            dsctr[row_id] = len(entries)
        else:
            if value < 1 or value > imax:
                raise TopoIndexSidecarError(f"dscfil receptor cell out of range: {value}")
            entries.append(value)
        idx += 1
    if dsctr[imax + 1] == 0:
        dsctr[imax + 1] = len(entries)
    for row_id in range(1, imax + 2):
        if dsctr[row_id] == 0:
            raise TopoIndexSidecarError(f"dscfil missing sawtooth pointer for row {row_id}")
    return entries, dsctr


def _read_sawtooth_float(
    path: str | Path,
    *,
    imax: int,
    expected_dsctr: Sequence[int],
    marker: float = -9999.0,
) -> List[float]:
    sidecar = _require_file(path, "wffil")
    tokens = _read_numeric_tokens(sidecar)
    entries = [0.0]
    dsctr = [0] * (imax + 2)
    idx = 0
    while idx < len(tokens):
        value = float(tokens[idx])
        if value == marker:
            idx += 1
            if idx >= len(tokens):
                raise TopoIndexSidecarError("wffil marker is missing following row id")
            row_id = int(tokens[idx])
            if row_id < 1 or row_id > imax + 1:
                raise TopoIndexSidecarError(f"wffil row marker out of range: {row_id}")
            dsctr[row_id] = len(entries)
        else:
            if not math.isfinite(value):
                raise TopoIndexSidecarError(f"wffil contains non-finite weight: {value}")
            entries.append(value)
        idx += 1
    if dsctr[imax + 1] == 0:
        dsctr[imax + 1] = len(entries)
    if list(expected_dsctr) != dsctr:
        raise TopoIndexSidecarError(f"wffil sawtooth pointers do not match dscfil: {dsctr} != {list(expected_dsctr)}")
    if len(entries) != expected_dsctr[imax + 1]:
        raise TopoIndexSidecarError("wffil entry count does not match dscfil entry count")
    return entries


def load_topoindex_sidecars(
    *,
    nxtfil: str | Path,
    ndxfil: str | Path,
    dscfil: str | Path,
    wffil: str | Path,
    imax: int,
    nodata: int = -9999,
    marker: int = -9999,
) -> TopoIndexSidecars:
    """Load original RNOFF TopoIndex sidecars into one-based arrays."""
    if imax < 1:
        raise TopoIndexSidecarError(f"imax must be positive, got {imax}")
    nxt_grid = _read_ascii_int_grid(nxtfil, imax=imax, nodata=nodata)
    indx = _read_indx(ndxfil, imax=imax)
    dsc, dsctr = _read_sawtooth_int(dscfil, imax=imax, marker=marker)
    wf = _read_sawtooth_float(wffil, imax=imax, expected_dsctr=dsctr, marker=float(marker))
    return TopoIndexSidecars(
        imax=imax,
        nxt=list(nxt_grid["values"]),
        indx=indx,
        dsctr=dsctr,
        dsc=dsc,
        wf=wf,
        metadata={
            "sidecar_branch_active": True,
            "nxtfil": str(Path(nxtfil)),
            "ndxfil": str(Path(ndxfil)),
            "dscfil": str(Path(dscfil)),
            "wffil": str(Path(wffil)),
            "nxt_header": nxt_grid["header"],
            "one_based_indexing": True,
            "mapping_count": len(dsc) - 1,
        },
    )


def _one_based_values(values: Mapping[int, float] | Sequence[float], *, imax: int, name: str) -> List[float]:
    result = [0.0] * (imax + 1)
    if isinstance(values, Mapping):
        for key, value in values.items():
            cell_id = int(key)
            if cell_id < 1 or cell_id > imax:
                raise TopoIndexSidecarError(f"{name} cell id out of range: {cell_id}")
            result[cell_id] = float(value)
        return result
    if len(values) == imax + 1:
        return [float(value) for value in values]
    if len(values) == imax:
        for idx, value in enumerate(values, start=1):
            result[idx] = float(value)
        return result
    raise TopoIndexSidecarError(f"{name} must have length imax or imax+1, got {len(values)}")


def _direct_fallback(rideb: float, kst: float) -> Dict[str, float]:
    if kst <= 0.0:
        raise TopoIndexSidecarError(f"kst must be positive, got {kst}")
    if kst < rideb:
        return {"ir": kst, "rik": 1.0, "ro": rideb - kst}
    return {"ir": rideb, "rik": rideb / kst, "ro": 0.0}


def _direct_fallback_cells(
    *,
    imax: int,
    rideb: Mapping[int, float] | Sequence[float],
    kst: Mapping[int, float] | Sequence[float],
    depth: Mapping[int, float] | Sequence[float] | None = None,
    rizero: Mapping[int, float] | Sequence[float] | None = None,
) -> List[Dict[str, float | int]]:
    rideb_values = _one_based_values(rideb, imax=imax, name="rideb")
    kst_values = _one_based_values(kst, imax=imax, name="kst")
    depth_values = _one_based_values(depth or {}, imax=imax, name="depth")
    rizero_values = _one_based_values(rizero or {}, imax=imax, name="rizero")
    cells: List[Dict[str, float | int]] = []
    for cell_id in range(1, imax + 1):
        direct = _direct_fallback(rideb_values[cell_id], kst_values[cell_id])
        cells.append(
            {
                "cell_id": cell_id,
                "rideb": rideb_values[cell_id],
                "kst": kst_values[cell_id],
                "depth": depth_values[cell_id],
                "rizero": rizero_values[cell_id],
                "ir": direct["ir"],
                "rik": direct["rik"],
                "ro": direct["ro"],
                "ir_direct_fallback": direct["ir"],
                "rik_direct_fallback": direct["rik"],
                "ro_direct_fallback": direct["ro"],
                "delta_rik_vs_direct": 0.0,
                "delta_ro_vs_direct": 0.0,
            }
        )
    return cells


def rnoff_topoindex_runtime_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Return whether the experimental RNOFF TopoIndex runtime path is enabled."""
    values = os.environ if environ is None else environ
    return (
        str(values.get(RNOFF_TOPOINDEX_RUNTIME_FLAG, "")).strip() == "1"
        or str(values.get(GPU_ONLY_PRODUCTION_SMOKE_ENV, "")).strip() == "1"
    )


def _sidecar_file_presence(
    *,
    nxtfil: str | Path | None,
    ndxfil: str | Path | None,
    dscfil: str | Path | None,
    wffil: str | Path | None,
) -> Dict[str, bool]:
    return {
        "nxtfil": bool(nxtfil) and Path(nxtfil).is_file(),
        "ndxfil": bool(ndxfil) and Path(ndxfil).is_file(),
        "dscfil": bool(dscfil) and Path(dscfil).is_file(),
        "wffil": bool(wffil) and Path(wffil).is_file(),
    }


def _cell_values(cells: Sequence[Mapping[str, float | int]], field: str) -> Dict[str, float]:
    return {str(int(row["cell_id"])): float(row[field]) for row in cells}


def _changed_runtime_fields(
    before: Sequence[Mapping[str, float | int]],
    after: Sequence[Mapping[str, float | int]],
    *,
    tolerance: float = 0.0,
) -> List[str]:
    changed: List[str] = []
    for field in ("ir", "rik", "ro"):
        before_by_cell = _cell_values(before, field)
        after_by_cell = _cell_values(after, field)
        if any(abs(after_by_cell[cell] - before_by_cell[cell]) > tolerance for cell in before_by_cell):
            changed.append(field)
    return changed


def _normalize_period_inputs(
    values: Mapping[int, Mapping[int, float] | Sequence[float]] | Sequence[Mapping[int, float] | Sequence[float]],
    *,
    imax: int,
    name: str,
) -> List[List[float]]:
    if isinstance(values, Mapping):
        ordered = [values[key] for key in sorted(values)]
    else:
        ordered = list(values)
    if not ordered:
        raise TopoIndexSidecarError(f"{name} must include at least one rainfall period")
    return [_one_based_values(period, imax=imax, name=f"{name}[{period_index}]") for period_index, period in enumerate(ordered, start=1)]


def _sidecar_provenance(
    *,
    nxtfil: str | Path | None,
    ndxfil: str | Path | None,
    dscfil: str | Path | None,
    wffil: str | Path | None,
) -> Dict[str, object]:
    paths = {
        "nxtfil": str(Path(nxtfil)) if nxtfil else None,
        "ndxfil": str(Path(ndxfil)) if ndxfil else None,
        "dscfil": str(Path(dscfil)) if dscfil else None,
        "wffil": str(Path(wffil)) if wffil else None,
    }
    return {
        "paths": paths,
        "sha256": {
            name: _file_sha256(path)
            for name, path in {
                "nxtfil": nxtfil,
                "ndxfil": ndxfil,
                "dscfil": dscfil,
                "wffil": wffil,
            }.items()
        },
    }


def _runtime_manifest_base(
    *,
    enabled: bool,
    sidecar_presence: Mapping[str, bool],
    direct_cells: List[Dict[str, float | int]],
) -> Dict[str, object]:
    return {
        "rnoff_topoindex_available": all(sidecar_presence.values()),
        "rnoff_topoindex_selected": enabled,
        "rnoff_topoindex_runtime_enabled": enabled,
        "rnoff_topoindex_branch_active": False,
        "sidecar_files_present": dict(sidecar_presence),
        "sidecar_shape_validated": False,
        "nxt_count": 0,
        "indx_count": 0,
        "dsc_count": 0,
        "wf_count": 0,
        "ro_before": _cell_values(direct_cells, "ro"),
        "ro_after": _cell_values(direct_cells, "ro"),
        "rik_before": _cell_values(direct_cells, "rik"),
        "rik_after": _cell_values(direct_cells, "rik"),
        "ir_before": _cell_values(direct_cells, "ir"),
        "ir_after": _cell_values(direct_cells, "ir"),
        "changed_field_names": [],
        "blocked_reason": None,
        "fail_closed": False,
        "default_off_verified": not enabled,
        "cells": direct_cells,
        "sidecar_mappings": [],
        "trace": [],
        "totals": {
            "sum_ro": sum(float(row["ro"]) for row in direct_cells),
            "sum_rik": sum(float(row["rik"]) for row in direct_cells),
            "sum_rideb": sum(float(row["rideb"]) for row in direct_cells),
        },
    }


def run_rnoff_topoindex_runtime_consumer(
    *,
    nxtfil: str | Path | None,
    ndxfil: str | Path | None,
    dscfil: str | Path | None,
    wffil: str | Path | None,
    imax: int,
    rideb: Mapping[int, float] | Sequence[float],
    kst: Mapping[int, float] | Sequence[float],
    depth: Mapping[int, float] | Sequence[float] | None = None,
    rizero: Mapping[int, float] | Sequence[float] | None = None,
    environ: Mapping[str, str] | None = None,
) -> Dict[str, object]:
    """Run the default-off RNOFF TopoIndex runtime smoke path.

    The helper is intentionally gated by ``EDDA_EXPERIMENT_RNOFF_TOPOINDEX=1``.
    When the flag is unset or zero-like, it returns direct fallback state and
    does not load or apply sidecars.  When enabled, malformed or incomplete
    sidecars fail closed by returning the direct fallback state plus a blocked
    reason instead of mutating runtime values.
    """
    enabled = rnoff_topoindex_runtime_enabled(environ)
    sidecar_presence = _sidecar_file_presence(nxtfil=nxtfil, ndxfil=ndxfil, dscfil=dscfil, wffil=wffil)
    direct_cells = _direct_fallback_cells(imax=imax, rideb=rideb, kst=kst, depth=depth, rizero=rizero)
    manifest = _runtime_manifest_base(enabled=enabled, sidecar_presence=sidecar_presence, direct_cells=direct_cells)

    if not enabled:
        return manifest

    missing = [name for name, present in sidecar_presence.items() if not present]
    if missing:
        manifest["blocked_reason"] = f"missing required TopoIndex sidecar files: {', '.join(missing)}"
        manifest["fail_closed"] = True
        return manifest

    try:
        sidecars = load_topoindex_sidecars(
            nxtfil=nxtfil or "",
            ndxfil=ndxfil or "",
            dscfil=dscfil or "",
            wffil=wffil or "",
            imax=imax,
        )
        result = run_rnoff_topoindex_dry_run(
            sidecars,
            rideb=rideb,
            kst=kst,
            depth=depth,
            rizero=rizero,
        )
    except Exception as exc:  # The runtime gate must fail closed on malformed sidecars.
        manifest["blocked_reason"] = str(exc)
        manifest["fail_closed"] = True
        return manifest

    after_cells = result.cells
    manifest.update(
        {
            "rnoff_topoindex_branch_active": result.sidecar_branch_active,
            "sidecar_shape_validated": True,
            "nxt_count": sidecars.imax,
            "indx_count": sidecars.imax,
            "dsc_count": len(sidecars.dsc) - 1,
            "wf_count": len(sidecars.wf) - 1,
            "ro_after": _cell_values(after_cells, "ro"),
            "rik_after": _cell_values(after_cells, "rik"),
            "ir_after": _cell_values(after_cells, "ir"),
            "changed_field_names": _changed_runtime_fields(direct_cells, after_cells),
            "cells": after_cells,
            "sidecar_mappings": result.sidecar_mappings,
            "trace": result.trace,
            "totals": result.totals,
        }
    )
    return manifest


def build_rnoff_pre_dfs_period_precompute_contract(
    *,
    nxtfil: str | Path | None,
    ndxfil: str | Path | None,
    dscfil: str | Path | None,
    wffil: str | Path | None,
    imax: int,
    rideb_periods: Mapping[int, Mapping[int, float] | Sequence[float]]
    | Sequence[Mapping[int, float] | Sequence[float]],
    kst: Mapping[int, float] | Sequence[float],
    depth: Mapping[int, float] | Sequence[float] | None = None,
    rizero: Mapping[int, float] | Sequence[float] | None = None,
    environ: Mapping[str, str] | None = None,
    diagnostic_request: bool = False,
    case_path: str | Path | None = None,
    provenance_note: str | None = None,
) -> RnoffPrecomputeContract:
    """Build a source-aligned pre-DFS RNOFF period precompute manifest.

    This function is intentionally non-mutating. It reuses the validated
    sidecar loader and single-period dry-run calculator to describe original
    EDDA's period-level ``rnoff -> optional unsfin -> dfs`` boundary. It does
    not write Taichi fields, does not alter the current DFS-internal bridge
    hook, and does not route ``rik`` into native ``unsfin`` runtime state.
    """
    enabled = rnoff_topoindex_runtime_enabled(environ)
    contract_requested = bool(enabled or diagnostic_request)
    sidecar_presence = _sidecar_file_presence(nxtfil=nxtfil, ndxfil=ndxfil, dscfil=dscfil, wffil=wffil)
    base_manifest: Dict[str, object] = {
        "contract_name": "SOURCE_ALIGNED_PRE_DFS_PRECOMPUTE_CONTRACT",
        "source_order": ["flodir", "steady", "rnoff", "optional_unsfin", "dfs"],
        "current_bridge_name": "CURRENT_DFS_INTERNAL_BRIDGE_HOOK",
        "current_bridge_retained": True,
        "runtime_mutation": False,
        "dfs_runtime_mutation": False,
        "native_unsfin_runtime_feed": False,
        "rik_unsfin_input_candidate": True,
        "rik_unsfin_runtime_integrated": False,
        "requires_unsfin_q_oracle_before_runtime_feed": True,
        "rnoff_topoindex_runtime_enabled": enabled,
        "diagnostic_request": bool(diagnostic_request),
        "contract_generation_enabled": contract_requested,
        "default_off_verified": not enabled,
        "case_path": str(Path(case_path)) if case_path is not None else None,
        "provenance_note": provenance_note,
        "imax": int(imax),
        "sidecar_files_present": dict(sidecar_presence),
        "sidecar_provenance": _sidecar_provenance(nxtfil=nxtfil, ndxfil=ndxfil, dscfil=dscfil, wffil=wffil),
        "sidecar_shape_validated": False,
        "one_based_indexing": True,
        "period_count": 0,
        "periods": [],
        "blocked_reason": None,
        "fail_closed": False,
        "claims": {
            "source_aligned_pre_dfs_contract": True,
            "changes_dfs_predictors": False,
            "changes_dfs_connectivity": False,
            "changes_rnoff_formulas": False,
            "gpu_production_equivalence": False,
            "natural_case_parity": False,
        },
    }

    if not contract_requested:
        base_manifest["blocked_reason"] = "contract generation not requested; flag unset and diagnostic_request false"
        return RnoffPrecomputeContract(manifest=base_manifest)

    missing = [name for name, present in sidecar_presence.items() if not present]
    if missing:
        base_manifest["blocked_reason"] = f"missing required TopoIndex sidecar files: {', '.join(missing)}"
        base_manifest["fail_closed"] = True
        return RnoffPrecomputeContract(manifest=base_manifest)

    try:
        sidecars = load_topoindex_sidecars(
            nxtfil=nxtfil or "",
            ndxfil=ndxfil or "",
            dscfil=dscfil or "",
            wffil=wffil or "",
            imax=imax,
        )
        rideb_values_by_period = _normalize_period_inputs(rideb_periods, imax=imax, name="rideb_periods")
        periods: List[Dict[str, object]] = []
        for period_index, rideb_values in enumerate(rideb_values_by_period, start=1):
            result = run_rnoff_topoindex_dry_run(
                sidecars,
                rideb=rideb_values,
                kst=kst,
                depth=depth,
                rizero=rizero,
            )
            periods.append(
                {
                    "period_index": period_index,
                    "sidecar_branch_active": result.sidecar_branch_active,
                    "cell_count": imax,
                    "ro_period": _cell_values(result.cells, "ro"),
                    "ir_period": _cell_values(result.cells, "ir"),
                    "rik_period": _cell_values(result.cells, "rik"),
                    "cells": result.cells,
                    "sidecar_mappings": result.sidecar_mappings,
                    "totals": result.totals,
                }
            )
    except Exception as exc:
        base_manifest["blocked_reason"] = str(exc)
        base_manifest["fail_closed"] = True
        return RnoffPrecomputeContract(manifest=base_manifest)

    base_manifest.update(
        {
            "sidecar_shape_validated": True,
            "nxt_count": sidecars.imax,
            "indx_count": sidecars.imax,
            "dsc_count": len(sidecars.dsc) - 1,
            "wf_count": len(sidecars.wf) - 1,
            "sidecar_metadata": sidecars.metadata,
            "period_count": len(periods),
            "periods": periods,
        }
    )
    return RnoffPrecomputeContract(manifest=base_manifest)


def run_rnoff_topoindex_dry_run(
    sidecars: TopoIndexSidecars,
    *,
    rideb: Mapping[int, float] | Sequence[float],
    kst: Mapping[int, float] | Sequence[float],
    depth: Mapping[int, float] | Sequence[float] | None = None,
    rizero: Mapping[int, float] | Sequence[float] | None = None,
    initial_ro: Mapping[int, float] | Sequence[float] | None = None,
) -> RnoffDryRunResult:
    """Compute original ``rnoff`` sidecar branch for one rainfall period."""
    imax = sidecars.imax
    rideb_values = _one_based_values(rideb, imax=imax, name="rideb")
    kst_values = _one_based_values(kst, imax=imax, name="kst")
    depth_values = _one_based_values(depth or {}, imax=imax, name="depth")
    rizero_values = _one_based_values(rizero or {}, imax=imax, name="rizero")
    ro = _one_based_values(initial_ro or {}, imax=imax, name="initial_ro")
    ir = [0.0] * (imax + 1)
    rik = [0.0] * (imax + 1)
    trace: List[Dict[str, float | int | str]] = []

    for cell_id in range(1, imax + 1):
        ir[cell_id] = kst_values[cell_id]
        ro[cell_id] = 0.0

    for order_index in range(1, imax + 1):
        cell_id = sidecars.indx[order_index]
        next_cell = sidecars.nxt[cell_id]
        inflx = ro[cell_id] + rideb_values[cell_id]
        kst_value = kst_values[cell_id]
        trace.append(
            {
                "stage": "CELL_START",
                "order_index": order_index,
                "cell_id": cell_id,
                "target_cell": next_cell,
                "inflx": inflx,
                "ro_before": ro[cell_id],
                "rik_before": rik[cell_id],
            }
        )
        if depth_values[cell_id] == 0.0 and rizero_values[cell_id] < 0.0:
            ir[cell_id] = 0.0
            rik[cell_id] = 0.0
            rnof = inflx - rizero_values[cell_id]
            ro[cell_id] = rnof
            _distribute_runoff(sidecars, ro, rik, rideb_values, kst_values, cell_id, order_index, next_cell, inflx, rnof, trace)
        elif kst_value < inflx:
            rik[cell_id] = 1.0
            rnof = inflx - kst_value
            ro[cell_id] = rnof
            _distribute_runoff(sidecars, ro, rik, rideb_values, kst_values, cell_id, order_index, next_cell, inflx, rnof, trace)
        else:
            ir[cell_id] = inflx
            rik[cell_id] = inflx / kst_value
            rnof = 0.0
            ro[cell_id] = rnof
            ro[next_cell] += rnof
        trace.append(
            {
                "stage": "CELL_END",
                "order_index": order_index,
                "cell_id": cell_id,
                "target_cell": next_cell,
                "rnof": rnof,
                "ro_after": ro[cell_id],
                "rik_after": rik[cell_id],
            }
        )

    cells: List[Dict[str, float | int]] = []
    for cell_id in range(1, imax + 1):
        direct = _direct_fallback(rideb_values[cell_id], kst_values[cell_id])
        cells.append(
            {
                "cell_id": cell_id,
                "nxt": sidecars.nxt[cell_id],
                "indx_cell_id": sidecars.indx[cell_id],
                "dsctr_start": sidecars.dsctr[cell_id],
                "dsctr_end": sidecars.dsctr[cell_id + 1] - 1,
                "rideb": rideb_values[cell_id],
                "kst": kst_values[cell_id],
                "depth": depth_values[cell_id],
                "rizero": rizero_values[cell_id],
                "ir": ir[cell_id],
                "rik": rik[cell_id],
                "ro": ro[cell_id],
                "ir_direct_fallback": direct["ir"],
                "rik_direct_fallback": direct["rik"],
                "ro_direct_fallback": direct["ro"],
                "delta_rik_vs_direct": rik[cell_id] - direct["rik"],
                "delta_ro_vs_direct": ro[cell_id] - direct["ro"],
            }
        )

    mappings = [
        {"cell_id": cell_id, "entry_index": entry, "dsc": sidecars.dsc[entry], "wf": sidecars.wf[entry]}
        for cell_id in range(1, imax + 1)
        for entry in range(sidecars.dsctr[cell_id], sidecars.dsctr[cell_id + 1])
    ]
    return RnoffDryRunResult(
        sidecar_branch_active=True,
        cells=cells,
        sidecar_mappings=mappings,
        trace=trace,
        totals={
            "sum_ro": sum(float(row["ro"]) for row in cells),
            "sum_rik": sum(float(row["rik"]) for row in cells),
            "sum_rideb": sum(float(row["rideb"]) for row in cells),
        },
    )


def _distribute_runoff(
    sidecars: TopoIndexSidecars,
    ro: List[float],
    rik: List[float],
    rideb: List[float],
    kst: List[float],
    cell_id: int,
    order_index: int,
    next_cell: int,
    inflx: float,
    rnof: float,
    trace: List[Dict[str, float | int | str]],
) -> None:
    for entry in range(sidecars.dsctr[cell_id], sidecars.dsctr[cell_id + 1]):
        target = sidecars.dsc[entry]
        weight = sidecars.wf[entry]
        role = "CONTRIB_SELF" if target == cell_id else "CONTRIB"
        if target == cell_id:
            ro[target] += rnof * (weight - 1.0)
        else:
            ro[target] += rnof * weight
        trace.append(
            {
                "stage": role,
                "order_index": order_index,
                "cell_id": cell_id,
                "target_cell": target,
                "nxt": next_cell,
                "dsc": target,
                "wf": weight,
                "rideb": rideb[cell_id],
                "inflx": inflx,
                "kst": kst[cell_id],
                "ro_target_after": ro[target],
                "rik_cell": rik[cell_id],
                "rnof": rnof,
            }
        )


def result_to_manifest(result: RnoffDryRunResult) -> Dict[str, object]:
    """Return a JSON-serializable dry-run manifest."""
    return {
        "sidecar_branch_active": result.sidecar_branch_active,
        "cells": result.cells,
        "sidecar_mappings": result.sidecar_mappings,
        "trace": result.trace,
        "totals": result.totals,
    }


def precompute_contract_to_manifest(contract: RnoffPrecomputeContract) -> Dict[str, object]:
    """Return a JSON-serializable pre-DFS RNOFF period contract manifest."""
    return dict(contract.manifest)
