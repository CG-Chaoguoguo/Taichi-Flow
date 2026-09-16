"""Fail-closed FIX3 run acceptance and evidence rendering.

The tool deliberately treats a missing, mismatched, or unparseable grid as an
acceptance failure.  It never transposes, crops, interpolates, or silently
chooses a nearby time frame.  It can compare a short independent run against a
master original-output directory without pretending the latter should contain
only the short run's frames.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import re
from decimal import Decimal, InvalidOperation
import sys
from typing import Any, Iterable

# Support both ``python -m tools.fix3.acceptance`` and the evidence-pack
# command recorded in reports as ``python tools/fix3/acceptance.py``.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.fix3.grid_compare import (
    AsciiGrid,
    GRID_PARSE_CACHE_SCHEMA,
    GridComparisonError,
    _ensure_same_grid,
    _nse,
    compare_ascii_grids,
    read_ascii_grid_strict,
)


class AcceptanceError(ValueError):
    """Raised for an invalid run inventory or command-line contract."""


_CANDIDATE_RE = re.compile(
    r"^(?P<family>.+?)(?:_Taichi_|Taichi_)(?P<time>\d+(?:\.\d+)?)\.txt$",
    re.IGNORECASE,
)
_REFERENCE_RE = re.compile(
    r"^(?P<family>.+?)(?:_EDDA_|EDDA_)(?P<time>\d+(?:\.\d+)?)\.asc$",
    re.IGNORECASE,
)
_HARD_METRIC_FAMILIES = {
    "Erosion_depth": "erosion_depth",
    "Flow_velocity": "flow_velocity",
}
METRICS_CACHE_SCHEMA = "fix3-grid-metrics-cache-v1"


@dataclass(frozen=True, order=True)
class OutputKey:
    family: str
    time_s: Decimal

    @property
    def time_text(self) -> str:
        # Do not round a physical event time back to the one-decimal filename
        # convention. A writer event at 89.999... must remain distinguishable
        # from the requested 90.0 s frame.
        text = format(self.time_s, "f")
        return f"{text}.0" if "." not in text else text

    @property
    def label(self) -> str:
        return f"{self.family}@{self.time_text}s"


def _source_sha256() -> str:
    return sha256(Path(__file__).read_bytes()).hexdigest()


class _MetricsCache:
    """Persist completed grid metrics separately from parsed-grid cache files."""

    def __init__(self, root: str | Path | None):
        self.root = Path(root) if root is not None else None
        self.hits = 0
        self.misses = 0

    def _key(self, candidate_path: Path, reference_path: Path, metric: str) -> str:
        candidate_hash = sha256(candidate_path.read_bytes()).hexdigest()
        reference_hash = sha256(reference_path.read_bytes()).hexdigest()
        material = "\0".join((METRICS_CACHE_SCHEMA, metric, candidate_hash, reference_hash))
        return sha256(material.encode("utf-8")).hexdigest()

    def get(self, candidate_path: Path, reference_path: Path, metric: str) -> dict[str, Any] | None:
        if self.root is None:
            return None
        key = self._key(candidate_path, reference_path, metric)
        path = self.root / f"{METRICS_CACHE_SCHEMA}-{key}.json"
        if not path.is_file():
            self.misses += 1
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("schema_version") != METRICS_CACHE_SCHEMA or payload.get("metric") != metric:
                self.misses += 1
                return None
            result = payload.get("result")
            if not isinstance(result, dict):
                self.misses += 1
                return None
        except (OSError, json.JSONDecodeError):
            self.misses += 1
            return None
        self.hits += 1
        # Paths identify the current evidence, even when identical content was
        # first measured under a different run directory.
        result = dict(result)
        result["candidate"] = {**dict(result.get("candidate") or {}), "path": str(candidate_path)}
        result["reference"] = {**dict(result.get("reference") or {}), "path": str(reference_path)}
        return result

    def put(self, candidate_path: Path, reference_path: Path, metric: str, result: dict[str, Any]) -> None:
        if self.root is None:
            return
        key = self._key(candidate_path, reference_path, metric)
        target = self.root / f"{METRICS_CACHE_SCHEMA}-{key}.json"
        temporary = target.with_name(f"{target.name}.tmp")
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            temporary.write_text(
                json.dumps(
                    {"schema_version": METRICS_CACHE_SCHEMA, "metric": metric, "result": result},
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            temporary.replace(target)
        except OSError:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _parse_decimal_time(raw: str, *, path: Path) -> Decimal:
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise AcceptanceError(f"{path}: invalid output time {raw!r}.") from exc
    if not value.is_finite() or value < 0:
        raise AcceptanceError(f"{path}: output time must be a finite non-negative decimal.")
    return value


def _safe_manifest_relative_path(raw: Any, *, manifest_path: Path) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise AcceptanceError(f"{manifest_path}: result manifest path must be a non-empty string.")
    normalized = raw.replace("\\", "/")
    path = Path(normalized)
    if path.is_absolute() or ".." in path.parts:
        raise AcceptanceError(f"{manifest_path}: result manifest path escapes the output directory: {raw!r}.")
    return path.as_posix()


def _load_frame_manifest(
    manifest_path: str | Path | None,
    output_dir: str | Path,
    *,
    side: str,
    required: bool,
) -> tuple[dict[Path, dict[str, Any]], list[str], dict[str, Any]]:
    """Return physical output-event provenance indexed by real output path.

    A filename has only presentation precision. Formal acceptance therefore
    consumes the solver-generated manifest and verifies its recorded hash
    before using a frame's physical time.
    """
    evidence: dict[str, Any] = {"side": side, "path": None, "status": "not_requested", "errors": []}
    if manifest_path is None:
        if required:
            evidence.update(status="missing", errors=[f"{side} frame manifest is required for formal acceptance."])
        return {}, list(evidence["errors"]), evidence
    source = Path(manifest_path)
    evidence["path"] = str(source)
    if not source.is_file():
        evidence.update(status="missing", errors=[f"{side} frame manifest does not exist: {source}"])
        return {}, list(evidence["errors"]), evidence
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        evidence.update(status="invalid", errors=[f"{side} frame manifest is unreadable: {exc}"])
        return {}, list(evidence["errors"]), evidence
    if not isinstance(payload, dict):
        evidence.update(status="invalid", errors=[f"{side} frame manifest must be an object"])
        return {}, list(evidence["errors"]), evidence

    event_evidence = payload.get("frame_event_evidence")
    if not isinstance(event_evidence, dict) or event_evidence.get("status") != "present":
        evidence.update(
            status="invalid",
            errors=[f"{side} manifest lacks complete solver-recorded frame-event evidence."],
        )
        return {}, list(evidence["errors"]), evidence
    root = Path(output_dir).resolve()
    events_path = root / "output_frame_events.json"
    metadata_files = payload.get("metadata_files")
    metadata_entry = next(
        (
            item
            for item in metadata_files
            if isinstance(item, dict) and item.get("relative_path") == "output_frame_events.json"
        ),
        None,
    ) if isinstance(metadata_files, list) else None
    if not events_path.is_file() or not isinstance(metadata_entry, dict):
        evidence.update(status="invalid", errors=[f"{side} manifest does not hash its output frame event sidecar."])
        return {}, list(evidence["errors"]), evidence
    sidecar_hash = sha256(events_path.read_bytes()).hexdigest()
    if sidecar_hash != metadata_entry.get("sha256"):
        evidence.update(status="invalid", errors=[f"{side} output frame event sidecar content hash does not match manifest."])
        return {}, list(evidence["errors"]), evidence
    try:
        event_payload = json.loads(events_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        evidence.update(status="invalid", errors=[f"{side} output frame event sidecar is unreadable: {exc}"])
        return {}, list(evidence["errors"]), evidence
    if not isinstance(event_payload, dict) or event_payload.get("schema_version") != "fix3-output-frame-events-v1":
        evidence.update(status="invalid", errors=[f"{side} output frame event sidecar has an unexpected schema."])
        return {}, list(evidence["errors"]), evidence
    raw_events = event_payload.get("events")
    if not isinstance(raw_events, list):
        evidence.update(status="invalid", errors=[f"{side} output frame event sidecar has no events list."])
        return {}, list(evidence["errors"]), evidence
    event_records: dict[str, dict[str, Any]] = {}
    event_errors: list[str] = []
    for position, event in enumerate(raw_events):
        if not isinstance(event, dict):
            event_errors.append(f"{side} output frame event {position} is not an object.")
            continue
        try:
            event_time = _parse_decimal_time(str(event.get("time_s")), path=events_path)
        except AcceptanceError as exc:
            event_errors.append(str(exc))
            continue
        paths = event.get("relative_paths")
        if not isinstance(paths, list):
            event_errors.append(f"{events_path}: event {position} has no relative_paths list.")
            continue
        for raw_path in paths:
            try:
                relative = _safe_manifest_relative_path(raw_path, manifest_path=events_path)
            except AcceptanceError as exc:
                event_errors.append(str(exc))
                continue
            if relative in event_records:
                event_errors.append(f"{events_path}: duplicate event path {relative}.")
                continue
            event_records[relative] = {"time_s": event_time, "writer": event.get("writer")}
    if event_errors:
        evidence.update(status="invalid", errors=event_errors)
        return {}, event_errors, evidence
    entries = payload.get("result_files")
    if not isinstance(entries, list):
        evidence.update(status="invalid", errors=[f"{side} frame manifest has no result_files list."])
        return {}, list(evidence["errors"]), evidence

    indexed: dict[Path, dict[str, Any]] = {}
    errors: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("frame_time_s") is None:
            continue
        try:
            relative = _safe_manifest_relative_path(entry.get("relative_path"), manifest_path=source)
            time_s = _parse_decimal_time(str(entry["frame_time_s"]), path=source)
        except AcceptanceError as exc:
            errors.append(str(exc))
            continue
        event_record = event_records.get(relative)
        if event_record is None or event_record["time_s"] != time_s:
            errors.append(f"{source}: {relative} frame time is not backed by the hashed event sidecar.")
            continue
        declared_writer = entry.get("frame_event_writer") or entry.get("writer")
        if event_record.get("writer") and declared_writer and event_record["writer"] != declared_writer:
            errors.append(f"{source}: {relative} writer identity conflicts with its event sidecar.")
            continue
        actual_path = (root / relative).resolve()
        try:
            actual_path.relative_to(root)
        except ValueError:
            errors.append(f"{source}: declared frame path escapes the supplied {side} output directory: {relative}.")
            continue
        expected_hash = entry.get("sha256")
        if not isinstance(expected_hash, str) or len(expected_hash) != 64:
            errors.append(f"{source}: {relative} has no valid content hash in the frame manifest.")
            continue
        if not actual_path.is_file():
            errors.append(f"{source}: declared frame file is missing: {relative}.")
            continue
        actual_hash = sha256(actual_path.read_bytes()).hexdigest()
        if actual_hash != expected_hash:
            errors.append(f"{source}: content hash mismatch for {relative}.")
            continue
        if actual_path in indexed:
            errors.append(f"{source}: duplicate manifest entry for {relative}.")
            continue
        indexed[actual_path] = {
            "time_s": time_s,
            "writer": entry.get("writer"),
            "frame_event_index": entry.get("frame_event_index"),
        }
    evidence.update(status="present" if not errors else "invalid", frame_count=len(indexed), errors=errors)
    return (indexed if not errors else {}), errors, evidence


def _discover_grids(
    directory: str | Path,
    *,
    candidate: bool,
    frame_manifest: dict[Path, dict[str, Any]] | None = None,
    require_frame_events: bool = False,
) -> tuple[dict[OutputKey, Path], list[str]]:
    root = Path(directory)
    if not root.is_dir():
        raise AcceptanceError(f"output directory does not exist: {root}")
    pattern = _CANDIDATE_RE if candidate else _REFERENCE_RE
    extension = "*.txt" if candidate else "*.asc"
    found: dict[OutputKey, Path] = {}
    ignored: list[str] = []
    for path in sorted(root.glob(extension), key=lambda item: item.name.lower()):
        match = pattern.match(path.name)
        if match is None:
            ignored.append(path.name)
            continue
        manifest_entry = (frame_manifest or {}).get(path.resolve())
        if require_frame_events and manifest_entry is None:
            raise AcceptanceError(f"{path}: grid is not bound to a verified physical output event.")
        key = OutputKey(
            family=match.group("family"),
            time_s=(
                manifest_entry["time_s"]
                if manifest_entry is not None
                else _parse_decimal_time(match.group("time"), path=path)
            ),
        )
        previous = found.get(key)
        if previous is not None:
            raise AcceptanceError(f"duplicate output frame {key.label}: {previous.name}, {path.name}")
        found[key] = path
    return found, ignored


def expected_output_times(*, end_time_s: Decimal, interval_s: Decimal) -> list[Decimal]:
    if end_time_s <= 0 or interval_s <= 0:
        raise AcceptanceError("end time and output interval must both be positive.")
    remainder = end_time_s % interval_s
    if remainder != 0:
        raise AcceptanceError(
            f"end time {end_time_s} is not an integral number of output intervals {interval_s}."
        )
    return [interval_s * index for index in range(1, int(end_time_s / interval_s) + 1)]


def _generic_grid_metrics(
    candidate_path: Path,
    reference_path: Path,
    *,
    parse_cache_dir: str | Path | None = None,
) -> dict[str, Any]:
    candidate = read_ascii_grid_strict(candidate_path, cache_dir=parse_cache_dir)
    reference = read_ascii_grid_strict(reference_path, cache_dir=parse_cache_dir)
    _ensure_same_grid(candidate, reference)
    valid = candidate.data != candidate.nodata
    candidate_values = candidate.data[valid]
    reference_values = reference.data[valid]
    return {
        "candidate": {"path": str(candidate.path), "sha256": candidate.sha256},
        "reference": {"path": str(reference.path), "sha256": reference.sha256},
        "shape": [candidate.nrows, candidate.ncols],
        "georeference": candidate.georeference,
        "nodata": candidate.nodata,
        "valid_cell_count": int(valid.sum()),
        "nse": _nse(candidate_values, reference_values),
        "rmse": float(((candidate_values - reference_values) ** 2).mean() ** 0.5),
    }


def _frame_result(
    key: OutputKey,
    candidate_path: Path,
    reference_path: Path,
    *,
    parse_cache_dir: str | Path | None = None,
    metrics_cache: _MetricsCache | None = None,
    canonical_grid: AsciiGrid | None = None,
) -> dict[str, Any]:
    metric = _HARD_METRIC_FAMILIES.get(key.family)
    try:
        # Validate against the independently frozen DEM even on a metric-cache
        # hit: two equally shifted output grids must never validate each other.
        if canonical_grid is not None:
            for path in (candidate_path, reference_path):
                _ensure_same_grid(read_ascii_grid_strict(path, cache_dir=parse_cache_dir), canonical_grid)
        cache_metric = metric or "generic_grid_metrics"
        result = metrics_cache.get(candidate_path, reference_path, cache_metric) if metrics_cache else None
        cache_status = "hit" if result is not None else "not_configured"
        if result is None:
            cache_status = "miss" if metrics_cache and metrics_cache.root is not None else "not_configured"
            if metric is not None:
                result = compare_ascii_grids(
                    candidate_path,
                    reference_path,
                    metric=metric,
                    cache_dir=parse_cache_dir,
                )
            else:
                result = _generic_grid_metrics(candidate_path, reference_path, parse_cache_dir=parse_cache_dir)
            if metrics_cache:
                metrics_cache.put(candidate_path, reference_path, cache_metric, result)
        return {
            "family": key.family,
            "time_s": float(key.time_s),
            "time_s_exact": format(key.time_s, "f"),
            "status": "compared",
            "metric": metric,
            "metrics_cache": cache_status,
            **result,
        }
    except (GridComparisonError, OSError, UnicodeError, ValueError) as exc:
        return {
            "family": key.family,
            "time_s": float(key.time_s),
            "time_s_exact": format(key.time_s, "f"),
            "status": "invalid",
            "metric": metric,
            "candidate": {"path": str(candidate_path)},
            "reference": {"path": str(reference_path)},
            "error": str(exc),
        }


def _hard_gate(frame: dict[str, Any]) -> dict[str, Any]:
    nse = frame.get("nse")
    ratio = frame.get("ratio")
    return {
        "family": frame["family"],
        "nse": nse,
        "nse_threshold": 0.90,
        "nse_pass": isinstance(nse, (int, float)) and nse >= 0.90,
        "ratio": ratio,
        "ratio_range": [0.90, 1.10],
        "ratio_pass": isinstance(ratio, (int, float)) and 0.90 <= ratio <= 1.10,
        "ratio_status": frame.get("ratio_status"),
    }


def compare_run(
    candidate_dir: str | Path,
    reference_dir: str | Path,
    *,
    end_time_s: Decimal,
    output_interval_s: Decimal,
    expected_family_count: int = 16,
    parse_cache_dir: str | Path | None = None,
    metrics_cache_dir: str | Path | None = None,
    candidate_manifest: str | Path | None = None,
    reference_manifest: str | Path | None = None,
    require_frame_events: bool = False,
    candidate_evidence_class: str = "unknown",
    reference_evidence_class: str = "unknown",
    canonical_dem: str | Path | None = None,
) -> dict[str, Any]:
    """Compare every expected frame in one run and return a traceable verdict."""
    if expected_family_count <= 0:
        raise AcceptanceError("expected family count must be positive.")
    expected_times = expected_output_times(end_time_s=end_time_s, interval_s=output_interval_s)
    metrics_cache = _MetricsCache(metrics_cache_dir)
    candidate_frame_manifest, candidate_manifest_errors, candidate_manifest_evidence = _load_frame_manifest(
        candidate_manifest,
        candidate_dir,
        side="candidate",
        required=require_frame_events,
    )
    reference_frame_manifest, reference_manifest_errors, reference_manifest_evidence = _load_frame_manifest(
        reference_manifest,
        reference_dir,
        side="reference",
        required=require_frame_events,
    )
    inventory_errors: list[str] = [*candidate_manifest_errors, *reference_manifest_errors]
    canonical_grid = None
    if canonical_dem is not None:
        try:
            canonical_grid = read_ascii_grid_strict(canonical_dem, cache_dir=parse_cache_dir)
            _ensure_same_grid(canonical_grid, canonical_grid)
        except (GridComparisonError, OSError, UnicodeError, ValueError) as exc:
            inventory_errors.append(f"invalid canonical DEM: {exc}")
    try:
        candidate, candidate_ignored = _discover_grids(
            candidate_dir,
            candidate=True,
            frame_manifest=candidate_frame_manifest,
            require_frame_events=require_frame_events,
        )
    except AcceptanceError as exc:
        candidate, candidate_ignored = {}, []
        inventory_errors.append(str(exc))
    try:
        reference, reference_ignored = _discover_grids(
            reference_dir,
            candidate=False,
            frame_manifest=reference_frame_manifest,
            require_frame_events=require_frame_events,
        )
    except AcceptanceError as exc:
        reference, reference_ignored = {}, []
        inventory_errors.append(str(exc))

    expected_time_set = set(expected_times)
    candidate_families = {key.family for key in candidate if key.time_s in expected_time_set}
    reference_families = {key.family for key in reference if key.time_s in expected_time_set}
    all_families = sorted(candidate_families | reference_families)
    family_count_ok = len(all_families) == expected_family_count
    expected_keys = {OutputKey(family, time_s) for family in all_families for time_s in expected_times}
    candidate_keys = {key for key in candidate if key.time_s in expected_time_set}
    reference_keys = {key for key in reference if key.time_s in expected_time_set}

    missing_candidate = sorted(expected_keys - candidate_keys)
    missing_reference = sorted(expected_keys - reference_keys)
    unexpected_candidate = sorted(set(candidate) - expected_keys)
    unexpected_reference = sorted(reference_keys - expected_keys)
    family_mismatch = sorted(candidate_families ^ reference_families)
    if not family_count_ok:
        inventory_errors.append(
            f"expected {expected_family_count} grid families at the selected run times; found {len(all_families)}."
        )
    if family_mismatch:
        inventory_errors.append(f"candidate/reference family mismatch: {', '.join(family_mismatch)}.")
    if missing_candidate:
        inventory_errors.append(f"candidate is missing {len(missing_candidate)} required frame(s).")
    if missing_reference:
        inventory_errors.append(f"reference is missing {len(missing_reference)} required frame(s).")
    if unexpected_candidate:
        inventory_errors.append(f"candidate has {len(unexpected_candidate)} unexpected selected-time frame(s).")
    if unexpected_reference:
        inventory_errors.append(f"reference has {len(unexpected_reference)} unexpected selected-time frame(s).")

    comparable_keys = sorted(expected_keys & candidate_keys & reference_keys)
    frames = [
        _frame_result(
            key,
            candidate[key],
            reference[key],
            parse_cache_dir=parse_cache_dir,
            metrics_cache=metrics_cache,
            canonical_grid=canonical_grid,
        )
        for key in comparable_keys
    ]
    invalid_frames = [frame for frame in frames if frame["status"] != "compared"]
    final_time = Decimal(end_time_s)
    final_hard_frames = [
        frame
        for frame in frames
        if Decimal(str(frame["time_s_exact"])) == final_time and frame["family"] in _HARD_METRIC_FAMILIES
    ]
    hard_gates = [_hard_gate(frame) for frame in final_hard_frames]
    hard_gate_by_family = {gate["family"]: gate for gate in hard_gates}
    missing_hard = sorted(set(_HARD_METRIC_FAMILIES) - set(hard_gate_by_family))
    hard_pass = not missing_hard and all(gate["nse_pass"] and gate["ratio_pass"] for gate in hard_gates)

    time_averaged_rmse: dict[str, float] = {}
    grouped_rmse: dict[str, list[float]] = defaultdict(list)
    for frame in frames:
        if frame["status"] == "compared" and isinstance(frame.get("rmse"), (int, float)):
            grouped_rmse[frame["family"]].append(float(frame["rmse"]))
    for family, values in sorted(grouped_rmse.items()):
        time_averaged_rmse[family] = sum(values) / len(values)

    return {
        "schema_version": "fix3-acceptance-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "comparator": {"path": str(Path(__file__)), "sha256": _source_sha256()},
        "cache": {
            "grid_parse_schema": GRID_PARSE_CACHE_SCHEMA if parse_cache_dir is not None else None,
            "grid_parse_dir": str(Path(parse_cache_dir)) if parse_cache_dir is not None else None,
            "metrics_schema": METRICS_CACHE_SCHEMA if metrics_cache_dir is not None else None,
            "metrics_dir": str(Path(metrics_cache_dir)) if metrics_cache_dir is not None else None,
            "metrics_hits": metrics_cache.hits,
            "metrics_misses": metrics_cache.misses,
        },
        "evidence": {
            "canonical_dem": (
                {"path": str(canonical_grid.path), "sha256": canonical_grid.sha256}
                if canonical_grid is not None else None
            ),
            "require_frame_events": require_frame_events,
            "candidate": {"class": candidate_evidence_class, **candidate_manifest_evidence},
            "reference": {"class": reference_evidence_class, **reference_manifest_evidence},
        },
        "run": {
            "candidate_dir": str(Path(candidate_dir)),
            "reference_dir": str(Path(reference_dir)),
            "end_time_s": float(end_time_s),
            "output_interval_s": float(output_interval_s),
            "expected_family_count": expected_family_count,
            "expected_frame_count": expected_family_count * len(expected_times),
            "expected_times_s": [float(value) for value in expected_times],
            "expected_times_exact_s": [format(value, "f") for value in expected_times],
        },
        "inventory": {
            "candidate_family_count": len(candidate_families),
            "reference_family_count": len(reference_families),
            "families": all_families,
            "candidate_ignored_non_grid_files": candidate_ignored,
            "reference_ignored_non_grid_files": reference_ignored,
            "reference_frames_outside_run_window": len([key for key in reference if key.time_s not in expected_time_set]),
            "errors": inventory_errors,
            "missing_candidate": [key.label for key in missing_candidate],
            "missing_reference": [key.label for key in missing_reference],
        },
        "frames": frames,
        "summary": {
            "compared_frame_count": len(frames),
            "invalid_frame_count": len(invalid_frames),
            "time_averaged_rmse": time_averaged_rmse,
        },
        "hard_gate": {
            "at_time_s": float(final_time),
            "required_families": sorted(_HARD_METRIC_FAMILIES),
            "missing_families": missing_hard,
            "metrics": hard_gates,
            "pass": hard_pass,
        },
        "verdict": {
            "scope": "single_run_numerical_comparison",
            "final_acceptance_pass": False,
            "evidence_qualified": (
                canonical_grid is not None
                and require_frame_events
                and candidate_manifest_evidence.get("status") == "present"
                and reference_manifest_evidence.get("status") == "present"
                and reference_evidence_class == "original_binary"
                and final_time in (Decimal("900"), Decimal("14400"))
            ),
            "pass": not inventory_errors and not invalid_frames and hard_pass,
            "reason": (
                "all required frames were compared strictly and both final hard metrics passed"
                if not inventory_errors and not invalid_frames and hard_pass
                else "one or more inventory, parse/comparison, or final hard-gate conditions failed"
            ),
        },
    }


def _render_markdown(result: dict[str, Any]) -> str:
    verdict = "PASS" if result["verdict"]["pass"] else "NOT PASSED"
    run = result["run"]
    lines = [
        "# FIX3 single-run numerical comparison",
        "",
        f"Numerical comparison: **{verdict}**. This is not final FIX3 acceptance.",
        f"Evidence qualified: {result['verdict']['evidence_qualified']}.",
        "",
        f"- Candidate: `{run['candidate_dir']}`",
        f"- Reference: `{run['reference_dir']}`",
        f"- Run end: {run['end_time_s']:.1f} s; output interval: {run['output_interval_s']:.1f} s",
        f"- Strictly compared frames: {result['summary']['compared_frame_count']} / {run['expected_frame_count']}",
        "",
        "| Final hard metric | NSE | Ratio | Result |",
        "| --- | ---: | ---: | --- |",
    ]
    for gate in result["hard_gate"]["metrics"]:
        nse = "not determinable" if gate["nse"] is None else f"{gate['nse']:.8f}"
        ratio = "not determinable" if gate["ratio"] is None else f"{gate['ratio']:.8f}"
        outcome = "pass" if gate["nse_pass"] and gate["ratio_pass"] else "fail"
        lines.append(f"| {gate['family']} | {nse} | {ratio} | {outcome} |")
    if result["inventory"]["errors"]:
        lines.extend(["", "## Inventory failures", ""])
        lines.extend(f"- {item}" for item in result["inventory"]["errors"])
    invalid = [frame for frame in result["frames"] if frame["status"] != "compared"]
    if invalid:
        lines.extend(["", "## Strict comparison failures", ""])
        lines.extend(f"- {frame['family']} at {frame['time_s']} s: {frame['error']}" for frame in invalid)
    return "\n".join(lines) + "\n"


def _render_html(markdown: str) -> str:
    # The JSON is the machine-readable authority; HTML is an intentionally
    # simple, safe evidence viewer that cannot reinterpret numeric results.
    return """<!doctype html>
<html lang=\"en\"><meta charset=\"utf-8\"><title>FIX3 numerical acceptance</title>
<style>body{font:15px/1.5 system-ui,sans-serif;max-width:1100px;margin:32px auto;padding:0 20px;color:#172033}pre{white-space:pre-wrap;background:#f5f7fb;border:1px solid #d9e0ee;padding:20px;border-radius:8px}</style>
<body><pre>""" + escape(markdown) + "</pre></body></html>\n"


def _write_evidence(path: str | Path | None, content: str) -> None:
    if path is None:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8", newline="\n")


def _main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Strict FIX3 full-run acceptance")
    parser.add_argument("candidate_dir")
    parser.add_argument("reference_dir")
    parser.add_argument("--end-time-s", required=True, type=Decimal)
    parser.add_argument("--output-interval-s", required=True, type=Decimal)
    parser.add_argument("--expected-family-count", type=int, default=16)
    parser.add_argument("--parse-cache-dir")
    parser.add_argument("--metrics-cache-dir")
    parser.add_argument("--candidate-manifest")
    parser.add_argument("--reference-manifest")
    parser.add_argument("--require-frame-events", action="store_true")
    parser.add_argument("--candidate-evidence-class", default="unknown")
    parser.add_argument("--reference-evidence-class", default="unknown")
    parser.add_argument("--canonical-dem")
    parser.add_argument("--json-out")
    parser.add_argument("--markdown-out")
    parser.add_argument("--html-out")
    args = parser.parse_args(list(argv) if argv is not None else None)
    result = compare_run(
        args.candidate_dir,
        args.reference_dir,
        end_time_s=args.end_time_s,
        output_interval_s=args.output_interval_s,
        expected_family_count=args.expected_family_count,
        parse_cache_dir=args.parse_cache_dir,
        metrics_cache_dir=args.metrics_cache_dir,
        candidate_manifest=args.candidate_manifest,
        reference_manifest=args.reference_manifest,
        require_frame_events=args.require_frame_events,
        candidate_evidence_class=args.candidate_evidence_class,
        reference_evidence_class=args.reference_evidence_class,
        canonical_dem=args.canonical_dem,
    )
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    markdown = _render_markdown(result)
    _write_evidence(args.json_out, payload)
    _write_evidence(args.markdown_out, markdown)
    _write_evidence(args.html_out, _render_html(markdown))
    print(payload)
    return 0 if result["verdict"]["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())
