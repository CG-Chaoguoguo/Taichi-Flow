from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from decimal import Decimal

import pytest

from tools.fix3.acceptance import compare_run
from tools.fix3.grid_compare import GridComparisonError, compare_ascii_grids


def _write_asc(path: Path, *, rows: int = 2, cols: int = 2, nodata: float = -9999.0, body: str = "1 2\n3 4\n") -> None:
    path.write_text(
        "\n".join(
            [
                f"ncols {cols}",
                f"nrows {rows}",
                "xllcorner 0",
                "yllcorner 0",
                "cellsize 30",
                f"NODATA_value {nodata}",
                body.rstrip(),
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_strict_comparator_rejects_georeference_mismatch(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.asc"
    reference = tmp_path / "reference.asc"
    _write_asc(candidate)
    _write_asc(reference)
    reference.write_text(reference.read_text(encoding="utf-8").replace("cellsize 30", "cellsize 31"), encoding="utf-8")

    with pytest.raises(GridComparisonError, match="cellsize"):
        compare_ascii_grids(candidate, reference, metric="erosion_depth")


def test_strict_comparator_rejects_nodata_mask_mismatch(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.asc"
    reference = tmp_path / "reference.asc"
    _write_asc(candidate, body="1 -9999\n3 4\n")
    _write_asc(reference, body="1 2\n3 4\n")

    with pytest.raises(GridComparisonError, match="NoData mask"):
        compare_ascii_grids(candidate, reference, metric="erosion_depth")


def test_strict_comparator_reports_not_determinable_for_zero_reference_denominator(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.asc"
    reference = tmp_path / "reference.asc"
    _write_asc(candidate, body="0 0\n0 0\n")
    _write_asc(reference, body="0 0\n0 0\n")

    report = compare_ascii_grids(candidate, reference, metric="flow_velocity")

    assert report["ratio"] is None
    assert report["ratio_status"] == "not_determinable_zero_reference"


def test_strict_comparator_never_crops_extra_values(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.asc"
    reference = tmp_path / "reference.asc"
    _write_asc(candidate, body="1 2\n3 4 5\n")
    _write_asc(reference)

    with pytest.raises(GridComparisonError, match="exactly 4"):
        compare_ascii_grids(candidate, reference, metric="erosion_depth")


def test_strict_comparator_parse_cache_is_versioned_by_grid_content(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.asc"
    reference = tmp_path / "reference.asc"
    cache_dir = tmp_path / "parse-cache"
    _write_asc(candidate)
    _write_asc(reference)

    first = compare_ascii_grids(candidate, reference, metric="erosion_depth", cache_dir=cache_dir)

    assert first["grid_parse_cache_schema"] == "fix3-grid-parse-cache-v1"
    # Identical bytes share one parsed-array cache entry even across paths.
    assert len(list(cache_dir.glob("*.npz"))) == 1

    _write_asc(candidate, body="2 3\n4 5\n")
    second = compare_ascii_grids(candidate, reference, metric="erosion_depth", cache_dir=cache_dir)

    assert second["candidate"]["sha256"] != second["reference"]["sha256"]
    assert len(list(cache_dir.glob("*.npz"))) == 2


def _write_acceptance_grid(path: Path) -> None:
    _write_asc(path, body="1 2\n3 4\n")


def _populate_complete_acceptance_run(candidate: Path, reference: Path) -> None:
    candidate.mkdir()
    reference.mkdir()
    families = ["Erosion_depth", "Flow_velocity", *[f"Family_{index}" for index in range(14)]]
    for family in families:
        for time_s in (45.0, 90.0):
            _write_acceptance_grid(candidate / f"{family}_Taichi_{time_s:.1f}.txt")
            _write_acceptance_grid(reference / f"{family}_EDDA_{time_s:.1f}.asc")


def _write_frame_manifest(output: Path, *, actual_times: dict[str, str] | None = None) -> Path:
    actual_times = actual_times or {}
    events = []
    result_files = []
    for index, path in enumerate(sorted(output.glob("*"), key=lambda item: item.name)):
        if path.suffix not in {".txt", ".asc"}:
            continue
        time_s = actual_times.get(path.name, path.stem.rsplit("_", 1)[1])
        writer = "taichi_edda_text" if path.suffix == ".txt" else "original_edda_text"
        events.append(
            {
                "event_index": index,
                "time_s": time_s,
                "writer": writer,
                "relative_paths": [path.name],
            }
        )
        result_files.append(
            {
                "relative_path": path.name,
                "sha256": sha256(path.read_bytes()).hexdigest(),
                "writer": writer,
                "frame_event_writer": writer,
                "frame_event_index": index,
                "frame_time_s": time_s,
            }
        )
    sidecar = output / "output_frame_events.json"
    sidecar.write_text(
        json.dumps({"schema_version": "fix3-output-frame-events-v1", "events": events}),
        encoding="utf-8",
    )
    manifest = output / "output_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "output-manifest-v2",
                "frame_event_evidence": {"status": "present"},
                "metadata_files": [
                    {
                        "relative_path": "output_frame_events.json",
                        "sha256": sha256(sidecar.read_bytes()).hexdigest(),
                    }
                ],
                "result_files": result_files,
            }
        ),
        encoding="utf-8",
    )
    return manifest


def test_acceptance_requires_all_families_and_applies_hard_gate(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    reference = tmp_path / "reference"
    _populate_complete_acceptance_run(candidate, reference)

    result = compare_run(
        candidate,
        reference,
        end_time_s=Decimal("90"),
        output_interval_s=Decimal("45"),
    )

    assert result["verdict"]["pass"] is True
    assert result["summary"]["compared_frame_count"] == 32
    assert result["hard_gate"]["pass"] is True
    assert result["verdict"]["final_acceptance_pass"] is False
    assert result["verdict"]["evidence_qualified"] is False


def test_matching_output_grids_cannot_override_canonical_dem_even_on_cache_hit(tmp_path: Path) -> None:
    candidate, reference = tmp_path / "candidate", tmp_path / "reference"
    _populate_complete_acceptance_run(candidate, reference)
    canonical = tmp_path / "dem.asc"
    _write_acceptance_grid(canonical)
    kwargs = dict(end_time_s=Decimal("90"), output_interval_s=Decimal("45"),
                  canonical_dem=canonical, metrics_cache_dir=tmp_path / "metrics")
    assert compare_run(candidate, reference, **kwargs)["verdict"]["pass"] is True
    canonical.write_text(canonical.read_text().replace("xllcorner 0", "xllcorner 30"))
    result = compare_run(candidate, reference, **kwargs)
    assert result["verdict"]["pass"] is False
    assert result["summary"]["invalid_frame_count"] == 32


def test_unexpected_candidate_time_is_not_silently_discarded(tmp_path: Path) -> None:
    candidate, reference = tmp_path / "candidate", tmp_path / "reference"
    _populate_complete_acceptance_run(candidate, reference)
    _write_acceptance_grid(candidate / "Erosion_depth_Taichi_89.9.txt")
    result = compare_run(candidate, reference, end_time_s=Decimal("90"), output_interval_s=Decimal("45"))
    assert result["verdict"]["pass"] is False
    assert any("unexpected" in error for error in result["inventory"]["errors"])


def test_acceptance_metrics_cache_is_separate_from_parse_cache(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    reference = tmp_path / "reference"
    _populate_complete_acceptance_run(candidate, reference)
    parse_cache = tmp_path / "parse-cache"
    metrics_cache = tmp_path / "metrics-cache"

    first = compare_run(
        candidate,
        reference,
        end_time_s=Decimal("90"),
        output_interval_s=Decimal("45"),
        parse_cache_dir=parse_cache,
        metrics_cache_dir=metrics_cache,
    )
    second = compare_run(
        candidate,
        reference,
        end_time_s=Decimal("90"),
        output_interval_s=Decimal("45"),
        parse_cache_dir=parse_cache,
        metrics_cache_dir=metrics_cache,
    )

    assert first["cache"]["metrics_schema"] == "fix3-grid-metrics-cache-v1"
    assert first["cache"]["metrics_misses"] > 0
    assert second["cache"]["metrics_hits"] == 32
    assert second["cache"]["metrics_misses"] == 0


def test_formal_acceptance_uses_hashed_writer_events_instead_of_rounded_filename(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    reference = tmp_path / "reference"
    _populate_complete_acceptance_run(candidate, reference)
    candidate_manifest = _write_frame_manifest(
        candidate,
        actual_times={"Flow_velocity_Taichi_90.0.txt": "89.99999999999999"},
    )
    reference_manifest = _write_frame_manifest(reference)

    result = compare_run(
        candidate,
        reference,
        end_time_s=Decimal("90"),
        output_interval_s=Decimal("45"),
        candidate_manifest=candidate_manifest,
        reference_manifest=reference_manifest,
        require_frame_events=True,
        candidate_evidence_class="taichi_stage_baseline",
        reference_evidence_class="original_binary",
    )

    assert result["verdict"]["pass"] is False
    assert "Flow_velocity@90.0s" in result["inventory"]["missing_candidate"]
    assert result["evidence"]["candidate"]["class"] == "taichi_stage_baseline"
    assert result["evidence"]["reference"]["class"] == "original_binary"


def test_acceptance_fails_closed_when_one_expected_frame_is_missing(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    reference = tmp_path / "reference"
    _populate_complete_acceptance_run(candidate, reference)
    (candidate / "Family_3_Taichi_90.0.txt").unlink()

    result = compare_run(
        candidate,
        reference,
        end_time_s=Decimal("90"),
        output_interval_s=Decimal("45"),
    )

    assert result["verdict"]["pass"] is False
    assert result["inventory"]["missing_candidate"] == ["Family_3@90.0s"]
