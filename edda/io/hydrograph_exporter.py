"""Original-EDDA-style monitored-cell hydrograph output helpers."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence


FLOAT_RE = re.compile(r"[-+]?(?:\d+\.\d*|\d+|\.\d+)(?:[eEdD][-+]?\d+)?")
MAX_LINE_RE = re.compile(
    r"HYDROGRAPH ELEMENT:\s*(?P<cell>\d+)\s*IS:\s*(?P<q>[-+0-9.EeDd]+)"
    r"\s*CM/s AT TIME:\s*(?P<time>[-+0-9.EeDd]+)"
)


@dataclass
class HydrographMonitorSample:
    """One checkpoint sample for an original EDDA monitored cell."""

    cell_id: int
    time_hours: float
    discharge_cms: float
    cv: float


@dataclass
class HydrographAccumulator:
    """Small in-memory accumulator for HYDROGRAPH_* monitored-cell output."""

    cell_ids: Sequence[int]
    samples_by_cell: Dict[int, List[HydrographMonitorSample]] = field(init=False)
    max_discharge: Dict[int, float] = field(init=False)
    max_time_hours: Dict[int, float] = field(init=False)

    def __post_init__(self) -> None:
        normalized = [int(cell_id) for cell_id in self.cell_ids]
        self.cell_ids = normalized
        self.samples_by_cell = {cell_id: [] for cell_id in normalized}
        self.max_discharge = {cell_id: 0.0 for cell_id in normalized}
        self.max_time_hours = {cell_id: 0.0 for cell_id in normalized}

    def record_sample(
        self,
        *,
        cell_id: int,
        time_hours: float,
        discharge_cms: float,
        cv: float,
    ) -> None:
        cell_id = int(cell_id)
        if cell_id not in self.samples_by_cell:
            raise KeyError(f"Hydrograph cell {cell_id} is not configured.")
        discharge = float(discharge_cms)
        sample = HydrographMonitorSample(
            cell_id=cell_id,
            time_hours=float(time_hours),
            discharge_cms=discharge,
            cv=float(cv),
        )
        self.samples_by_cell[cell_id].append(sample)
        if discharge > self.max_discharge[cell_id]:
            self.max_discharge[cell_id] = discharge
            self.max_time_hours[cell_id] = float(time_hours)

    def record_checkpoint(
        self,
        *,
        time_hours: float,
        values: Dict[int, Dict[str, float]],
    ) -> None:
        for cell_id in self.cell_ids:
            value = values.get(int(cell_id), {})
            self.record_sample(
                cell_id=int(cell_id),
                time_hours=float(time_hours),
                discharge_cms=float(value.get("discharge_cms", 0.0)),
                cv=float(value.get("cv", 0.0)),
            )


def _numeric_tokens(line: str) -> List[float]:
    return [float(token.replace("D", "E").replace("d", "e")) for token in FLOAT_RE.findall(line)]


def parse_hydrograph_cell_file(path: str | Path) -> Dict[str, Any]:
    """Parse original hydrograph.txt: heading, count, then monitored cell ids."""
    sidecar = Path(path)
    if not sidecar.exists():
        raise FileNotFoundError(f"hydrograph.txt not found: {sidecar}")

    lines = [line.strip() for line in sidecar.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip()]
    numeric: List[int] = []
    for line in lines:
        for value in _numeric_tokens(line):
            numeric.append(int(value))

    declared = int(numeric[0]) if numeric else 0
    cell_ids = [int(value) for value in numeric[1 : 1 + max(declared, 0)]]
    return {
        "path": str(sidecar),
        "nonempty_line_count": len(lines),
        "declared_cell_count": max(declared, 0),
        "parsed_cell_count": len(cell_ids),
        "cell_ids": cell_ids,
        "extra_numeric_tokens": max(0, len(numeric) - 1 - len(cell_ids)),
    }


def write_hydrograph_file(
    output_path: str | Path,
    *,
    cell_ids: Sequence[int],
    samples_by_cell: Dict[int, Sequence[HydrographMonitorSample | Dict[str, float]]],
    max_discharge: Optional[Dict[int, float]] = None,
    max_time_hours: Optional[Dict[int, float]] = None,
) -> Path:
    """Write original-compatible HYDROGRAPH_<suffix>.txt text output."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    max_discharge = max_discharge or {}
    max_time_hours = max_time_hours or {}

    with output.open("w", encoding="utf-8", newline="\n") as handle:
        for raw_cell_id in cell_ids:
            cell_id = int(raw_cell_id)
            handle.write(
                f"THE MAX Q AT HYDROGRAPH ELEMENT: {cell_id:6d}IS: "
                f"{float(max_discharge.get(cell_id, 0.0)):6.2f} CM/s AT TIME: "
                f"{float(max_time_hours.get(cell_id, 0.0)):6.2f}\n"
            )
        for raw_cell_id in cell_ids:
            cell_id = int(raw_cell_id)
            handle.write("ELEMENT       TIME (HRS)     DISCHARGE (CMS)CV\n")
            samples = samples_by_cell.get(cell_id, [])
            for index, raw_sample in enumerate(samples):
                if isinstance(raw_sample, HydrographMonitorSample):
                    time_hours = raw_sample.time_hours
                    discharge = raw_sample.discharge_cms
                    cv = raw_sample.cv
                else:
                    time_hours = float(raw_sample["time_hours"])
                    discharge = float(raw_sample["discharge_cms"])
                    cv = float(raw_sample["cv"])
                if index == 0:
                    handle.write(f"{cell_id:6d}{time_hours:14.2f}{discharge:17.2f}{cv:13.4f}\n")
                else:
                    handle.write(f"{'':6}{time_hours:14.2f}{discharge:17.2f}{cv:13.4f}\n")
    return output


def parse_hydrograph_output(path: str | Path) -> Dict[str, Any]:
    """Parse HYDROGRAPH_* text output for oracle/current comparisons."""
    output = Path(path)
    if not output.exists():
        raise FileNotFoundError(f"Hydrograph output not found: {output}")
    rows: List[Dict[str, Any]] = []
    current_cell: Optional[int] = None
    header: Optional[str] = None

    for line in output.read_text(encoding="utf-8", errors="ignore").splitlines():
        raw = line.rstrip("\n")
        stripped = raw.strip()
        if not stripped:
            continue
        max_match = MAX_LINE_RE.search(stripped)
        if max_match:
            current_cell = int(max_match.group("cell"))
            rows.append(
                {
                    "record_type": "max",
                    "cell_id": current_cell,
                    "time_hrs": float(max_match.group("time").replace("D", "E").replace("d", "e")),
                    "discharge": float(max_match.group("q").replace("D", "E").replace("d", "e")),
                    "cv": None,
                    "raw": raw,
                }
            )
            continue
        if stripped.upper().startswith("ELEMENT"):
            header = stripped
            continue

        tokens = _numeric_tokens(stripped)
        if len(tokens) == 4:
            current_cell = int(tokens[0])
            time_hours, discharge, cv = tokens[1], tokens[2], tokens[3]
        elif len(tokens) == 3 and current_cell is not None:
            time_hours, discharge, cv = tokens
        else:
            continue
        rows.append(
            {
                "record_type": "sample",
                "cell_id": int(current_cell),
                "time_hrs": float(time_hours),
                "discharge": float(discharge),
                "cv": float(cv),
                "raw": raw,
            }
        )

    samples = [row for row in rows if row["record_type"] == "sample"]
    return {
        "file": str(output),
        "header": header,
        "rows": rows,
        "row_count": len(rows),
        "sample_count": len(samples),
        "monitored_cells": sorted({int(row["cell_id"]) for row in rows}),
        "time_stamps_hours": [float(row["time_hrs"]) for row in samples],
    }


def _read_reference_line_value(lines: Sequence[str], prompt: str) -> Optional[str]:
    prompt_lower = prompt.lower()
    for idx, line in enumerate(lines):
        if line.strip().lower().startswith(prompt_lower):
            for next_line in lines[idx + 1 :]:
                value = next_line.strip()
                if value:
                    return value
    return None


def parse_reference_hydrosave_controls(case_dir: str | Path) -> Dict[str, Any]:
    """Read the small edda_in controls needed by the hydrograph dry-run writer."""
    case_path = Path(case_dir)
    edda_in = case_path / "edda_in.txt"
    if not edda_in.exists():
        raise FileNotFoundError(f"edda_in.txt not found: {edda_in}")
    lines = edda_in.read_text(encoding="utf-8", errors="ignore").splitlines()
    suffix = _read_reference_line_value(lines, "Identification code to be added to names of output files")
    hydrosave_token = _read_reference_line_value(lines, "Save hydrograph of specified cells?")
    dt_line = _read_reference_line_value(lines, "dtmin(s)   dtmax(s)")
    values = _numeric_tokens(dt_line or "")
    if len(values) < 6:
        raise ValueError("Could not parse simul/tout from edda_in.txt dt control line.")
    return {
        "case_dir": str(case_path),
        "edda_in": str(edda_in),
        "suffix": (suffix or "EDDA").strip(),
        "hydrosave": str(hydrosave_token or "").strip().lower().startswith(("t", ".t")),
        "simul_s": float(values[4]),
        "tout_s": float(values[5]),
    }


def checkpoint_times_seconds(simul_s: float, tout_s: float) -> List[float]:
    if simul_s < 0.0 or tout_s <= 0.0:
        raise ValueError("simul_s must be non-negative and tout_s must be positive.")
    times = [0.0]
    t = float(tout_s)
    # Original EDDA records the initial row plus each tout checkpoint.
    while t <= float(simul_s) + 1.0e-9:
        times.append(float(t))
        t += float(tout_s)
    if times[-1] < float(simul_s) - 1.0e-9:
        times.append(float(simul_s))
    return times


def write_zero_flow_hydrograph_for_case(
    case_dir: str | Path,
    output_dir: str | Path,
    *,
    output_filename: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Write a monitored-cell hydrograph dry-run using source-backed control fields.

    The dry-run is intentionally limited to zero-flow oracle cases: it exercises
    hydrosave parsing, hydrograph.txt cell selection, checkpoint timing, and the
    HYDROGRAPH_* text writer without changing DFS equations or inflow forcing.
    """
    controls = parse_reference_hydrosave_controls(case_dir)
    if not controls["hydrosave"]:
        return {**controls, "written": False, "reason": "hydrosave is false"}

    case_path = Path(case_dir)
    sidecar = case_path / "hydrograph.txt"
    parsed_sidecar = parse_hydrograph_cell_file(sidecar)
    if not parsed_sidecar["cell_ids"]:
        raise ValueError(f"hydrosave is true but no monitored cells were parsed from {sidecar}")

    accumulator = HydrographAccumulator(parsed_sidecar["cell_ids"])
    for time_s in checkpoint_times_seconds(controls["simul_s"], controls["tout_s"]):
        accumulator.record_checkpoint(
            time_hours=float(time_s) / 3600.0,
            values={cell_id: {"discharge_cms": 0.0, "cv": 0.0} for cell_id in parsed_sidecar["cell_ids"]},
        )

    filename = output_filename or f"HYDROGRAPH_{controls['suffix']}.txt"
    output_path = Path(output_dir) / filename
    write_hydrograph_file(
        output_path,
        cell_ids=parsed_sidecar["cell_ids"],
        samples_by_cell=accumulator.samples_by_cell,
        max_discharge=accumulator.max_discharge,
        max_time_hours=accumulator.max_time_hours,
    )
    return {
        **controls,
        "written": True,
        "hydrograph_sidecar": parsed_sidecar,
        "output_file": str(output_path),
        "parsed_output": parse_hydrograph_output(output_path),
    }


def compare_hydrograph_outputs(
    original_path: str | Path,
    current_path: str | Path,
    *,
    tolerance: float = 1.0e-12,
) -> Dict[str, Any]:
    original = parse_hydrograph_output(original_path)
    current = parse_hydrograph_output(current_path)
    original_max_rows = [row for row in original["rows"] if row["record_type"] == "max"]
    current_max_rows = [row for row in current["rows"] if row["record_type"] == "max"]
    original_samples = [row for row in original["rows"] if row["record_type"] == "sample"]
    current_samples = [row for row in current["rows"] if row["record_type"] == "sample"]
    max_diffs: List[Dict[str, Any]] = []
    for idx in range(max(len(original_max_rows), len(current_max_rows))):
        if idx >= len(original_max_rows) or idx >= len(current_max_rows):
            max_diffs.append({"row_index": idx, "status": "missing_or_extra_max_row"})
            continue
        o = original_max_rows[idx]
        c = current_max_rows[idx]
        max_diffs.append(
            {
                "row_index": idx,
                "original_cell_id": o["cell_id"],
                "current_cell_id": c["cell_id"],
                "time_delta": float(c["time_hrs"] - o["time_hrs"]),
                "discharge_delta": float(c["discharge"] - o["discharge"]),
            }
        )
    diffs: List[Dict[str, Any]] = []
    for idx in range(max(len(original_samples), len(current_samples))):
        if idx >= len(original_samples) or idx >= len(current_samples):
            diffs.append({"row_index": idx, "status": "missing_or_extra_row"})
            continue
        o = original_samples[idx]
        c = current_samples[idx]
        diffs.append(
            {
                "row_index": idx,
                "original_cell_id": o["cell_id"],
                "current_cell_id": c["cell_id"],
                "time_delta": float(c["time_hrs"] - o["time_hrs"]),
                "discharge_delta": float(c["discharge"] - o["discharge"]),
                "cv_delta": float(c["cv"] - o["cv"]),
            }
        )
    max_abs_discharge = max((abs(row.get("discharge_delta", 0.0)) for row in diffs), default=0.0)
    max_abs_cv = max((abs(row.get("cv_delta", 0.0)) for row in diffs), default=0.0)
    max_abs_time = max((abs(row.get("time_delta", 0.0)) for row in diffs), default=0.0)
    max_line_abs_discharge = max((abs(row.get("discharge_delta", 0.0)) for row in max_diffs), default=0.0)
    max_line_abs_time = max((abs(row.get("time_delta", 0.0)) for row in max_diffs), default=0.0)
    max_line_count_match = len(original_max_rows) == len(current_max_rows)
    cells_match = original["monitored_cells"] == current["monitored_cells"]
    row_count_match = original["sample_count"] == current["sample_count"]
    return {
        "original": original,
        "current": current,
        "max_diffs": max_diffs,
        "diffs": diffs,
        "cells_match": cells_match,
        "row_count_match": row_count_match,
        "max_line_count_match": max_line_count_match,
        "max_abs_time_delta": max_abs_time,
        "max_abs_discharge_delta": max_abs_discharge,
        "max_abs_cv_delta": max_abs_cv,
        "max_line_abs_time_delta": max_line_abs_time,
        "max_line_abs_discharge_delta": max_line_abs_discharge,
        "matches": (
            cells_match
            and row_count_match
            and max_line_count_match
            and max_abs_time <= tolerance
            and max_abs_discharge <= tolerance
            and max_abs_cv <= tolerance
            and max_line_abs_time <= tolerance
            and max_line_abs_discharge <= tolerance
        ),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Write a source-backed zero-flow HYDROGRAPH_* dry-run.")
    parser.add_argument("--case-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--output-filename")
    parser.add_argument("--manifest")
    args = parser.parse_args(argv)

    manifest = write_zero_flow_hydrograph_for_case(
        args.case_dir,
        args.output_dir,
        output_filename=args.output_filename,
    )
    if args.manifest:
        manifest_path = Path(args.manifest)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    else:
        print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
