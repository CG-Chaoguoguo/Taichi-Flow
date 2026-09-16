"""Ledger-only diagnostic for the original EDDA `unsfin` schedule path.

This module deliberately does not feed DFS runtime state. It can inventory the
validated original memory-dump oracle, emit a native diagnostic ledger, and
compare native/original ledgers. When the current code lacks a source-backed
native implementation of the original analytic `unsfin` algorithm, the native
ledger is emitted as blocked instead of fabricating schedule values.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


ORIGINAL_PROVENANCE = "original_unsfin_memory_dump"
NATIVE_PROVENANCE = "production_native_unsfin_ledger_only"
RUNTIME_PROVIDER_ENABLED = False
OUTPUT_INFERRED = False
DFS_RUNTIME_MODIFIED = False

BLOCKED_REASON = (
    "ORIGINAL_UNSFIN_ANALYTIC_DOUBLELAYER_TIME_SEARCH_NOT_IMPLEMENTED_IN_NATIVE_LEDGER"
)
BLOCKED_GAPS = [
    "roota/rootb/rootc eigen-series coefficient path is not ported into current native ledger code",
    "original doublelayer.F90 analytic time-convolution evaluation is not available as a ledger-only callable",
    "unsfin.F90 tnown/tincrement first-hit refinement loop is not implemented as native production code",
    "current DoubleLayerSoilModel advances live DFS/Richards state and is not equivalent to original pre-DFS analytic unsfin search",
]


@dataclass(frozen=True)
class LedgerArrays:
    gindx: np.ndarray
    tfail_s: np.ndarray
    fdepth_m: np.ndarray
    fsdepth_m: np.ndarray | None
    meta: dict[str, Any]


def file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _load_array(base: Path, stem: str) -> np.ndarray:
    npy = base / f"{stem}.npy"
    txt = base / f"{stem}.txt"
    if npy.exists():
        return np.load(npy)
    if txt.exists():
        return np.loadtxt(txt)
    raise FileNotFoundError(f"missing required oracle artifact: {stem}.npy or {stem}.txt in {base}")


def _artifact_entry(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "exists": path.exists(),
        "bytes": path.stat().st_size if path.exists() else 0,
        "sha256": file_sha256(path) if path.exists() else None,
    }


def load_original_oracle(oracle_dir: Path) -> LedgerArrays:
    oracle_dir = Path(oracle_dir)
    meta_path = oracle_dir / "precomputed_unsfin_meta.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"missing required oracle meta: {meta_path}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    provider = meta.get("source_provenance") or meta.get("provider")
    if provider == "original_instrumented_unsfin":
        provider = ORIGINAL_PROVENANCE
    if provider != ORIGINAL_PROVENANCE:
        raise ValueError(f"oracle provenance must be {ORIGINAL_PROVENANCE}, got {provider!r}")
    serialized = json.dumps(meta, sort_keys=True).lower()
    blocked_markers = ("faildph", "ls_scar", "flow_depth", "volumetric_sediment", "deposit_depth", "erosion_depth")
    if any(marker in serialized for marker in blocked_markers):
        raise ValueError("oracle metadata contains output-inference markers")

    gindx = np.asarray(_load_array(oracle_dir, "precomputed_unsfin_gindx"), dtype=np.int32)
    tfail = np.asarray(_load_array(oracle_dir, "precomputed_unsfin_tfail"), dtype=np.float64)
    fdepth = np.asarray(_load_array(oracle_dir, "precomputed_unsfin_fdepth"), dtype=np.float64)
    if gindx.shape != tfail.shape or gindx.shape != fdepth.shape:
        raise ValueError(
            f"oracle shape mismatch: gindx={gindx.shape}, tfail={tfail.shape}, fdepth={fdepth.shape}"
        )

    fsdepth = None
    fsdepth_npy = oracle_dir / "precomputed_unsfin_fsdepth.npy"
    fsdepth_txt = oracle_dir / "precomputed_unsfin_fsdepth.txt"
    if fsdepth_npy.exists() or fsdepth_txt.exists():
        fsdepth = np.asarray(
            np.load(fsdepth_npy) if fsdepth_npy.exists() else np.loadtxt(fsdepth_txt),
            dtype=np.float64,
        )
        if fsdepth.shape != gindx.shape:
            raise ValueError(f"oracle fsdepth shape {fsdepth.shape} does not match {gindx.shape}")

    meta = {
        **meta,
        "source_provenance": ORIGINAL_PROVENANCE,
        "output_inferred": False,
        "artifact_hashes": {
            "gindx_npy": _artifact_entry(oracle_dir / "precomputed_unsfin_gindx.npy"),
            "tfail_npy": _artifact_entry(oracle_dir / "precomputed_unsfin_tfail.npy"),
            "fdepth_npy": _artifact_entry(oracle_dir / "precomputed_unsfin_fdepth.npy"),
            "meta": _artifact_entry(meta_path),
        },
    }
    return LedgerArrays(gindx=gindx, tfail_s=tfail, fdepth_m=fdepth, fsdepth_m=fsdepth, meta=meta)


def build_native_blocked_ledger(shape: tuple[int, ...], *, source_root: Path | None = None) -> LedgerArrays:
    gindx = np.zeros(shape, dtype=np.int32)
    tfail = np.full(shape, np.nan, dtype=np.float64)
    fdepth = np.zeros(shape, dtype=np.float64)
    fsdepth = np.full(shape, np.nan, dtype=np.float64)
    meta = {
        "source_provenance": NATIVE_PROVENANCE,
        "runtime_provider_enabled": RUNTIME_PROVIDER_ENABLED,
        "output_inferred": OUTPUT_INFERRED,
        "dfs_runtime_modified": DFS_RUNTIME_MODIFIED,
        "parse_status": "blocked",
        "blocked_reason": BLOCKED_REASON,
        "blocked_gaps": BLOCKED_GAPS,
        "shape": list(shape),
        "source_root": str(source_root) if source_root is not None else None,
        "notes": (
            "This blocked ledger preserves the no-output-inference rule. It uses "
            "oracle shape only for comparison compatibility and does not copy or "
            "derive any schedule values from the oracle."
        ),
    }
    return LedgerArrays(gindx=gindx, tfail_s=tfail, fdepth_m=fdepth, fsdepth_m=fsdepth, meta=meta)


def count_window(tfail: np.ndarray, upper: float) -> int:
    values = np.asarray(tfail, dtype=np.float64)
    return int(np.count_nonzero(np.isfinite(values) & (values > 0.0) & (values <= upper)))


def compare_ledgers(native: LedgerArrays, original: LedgerArrays) -> dict[str, Any]:
    if native.gindx.shape != original.gindx.shape:
        raise ValueError(f"native/original shape mismatch: {native.gindx.shape} vs {original.gindx.shape}")

    orig_g = original.gindx > 0
    nat_g = native.gindx > 0
    tp = int(np.count_nonzero(orig_g & nat_g))
    fp = int(np.count_nonzero(~orig_g & nat_g))
    fn = int(np.count_nonzero(orig_g & ~nat_g))
    union = int(np.count_nonzero(orig_g | nat_g))

    orig_t_pos = np.isfinite(original.tfail_s) & (original.tfail_s > 0.0)
    nat_t_pos = np.isfinite(native.tfail_s) & (native.tfail_s > 0.0)
    tfail_overlap = orig_t_pos & nat_t_pos
    tfail_abs = np.abs(native.tfail_s[tfail_overlap] - original.tfail_s[tfail_overlap])

    fdepth_overlap = (original.fdepth_m > 0.0) & (native.fdepth_m > 0.0)
    fdepth_abs = np.abs(native.fdepth_m[fdepth_overlap] - original.fdepth_m[fdepth_overlap])
    fdepth_delta = native.fdepth_m[fdepth_overlap] - original.fdepth_m[fdepth_overlap]

    early_windows = [78.243000, 321.109500, 343.176600, 373.049000]
    early_window_metrics = []
    for center in early_windows:
        orig_abs_delta = np.abs(original.tfail_s[orig_t_pos] - center)
        nat_abs_delta = np.abs(native.tfail_s[nat_t_pos] - center)
        orig_count = int(np.count_nonzero(orig_t_pos & (np.abs(original.tfail_s - center) <= 1.0)))
        nat_count = int(np.count_nonzero(nat_t_pos & (np.abs(native.tfail_s - center) <= 1.0)))
        early_window_metrics.append(
            {
                "center_s": center,
                "tolerance_s": 1.0,
                "original_near_count": orig_count,
                "native_near_count": nat_count,
                "nearest_original_abs_delta_s": float(np.min(orig_abs_delta)) if orig_abs_delta.size else None,
                "nearest_native_abs_delta_s": float(np.min(nat_abs_delta)) if nat_abs_delta.size else None,
            }
        )

    return {
        "shape": list(original.gindx.shape),
        "native_parse_status": native.meta.get("parse_status", "ok"),
        "native_blocked_reason": native.meta.get("blocked_reason"),
        "gindx": {
            "positive_count_original": int(np.count_nonzero(orig_g)),
            "positive_count_native": int(np.count_nonzero(nat_g)),
            "true_positives": tp,
            "false_positives": fp,
            "false_negatives": fn,
            "precision": (tp / (tp + fp)) if (tp + fp) else None,
            "recall": (tp / (tp + fn)) if (tp + fn) else 0.0,
            "jaccard_iou": (tp / union) if union else None,
        },
        "tfail": {
            "finite_count_original": int(np.count_nonzero(np.isfinite(original.tfail_s))),
            "finite_count_native": int(np.count_nonzero(np.isfinite(native.tfail_s))),
            "positive_count_original": int(np.count_nonzero(orig_t_pos)),
            "positive_count_native": int(np.count_nonzero(nat_t_pos)),
            "positive_overlap_count": int(np.count_nonzero(tfail_overlap)),
            "mae_on_positive_overlap": float(np.mean(tfail_abs)) if tfail_abs.size else None,
            "rmse_on_positive_overlap": float(np.sqrt(np.mean(tfail_abs * tfail_abs))) if tfail_abs.size else None,
            "median_abs_error_on_positive_overlap": float(np.median(tfail_abs)) if tfail_abs.size else None,
            "max_abs_error_on_positive_overlap": float(np.max(tfail_abs)) if tfail_abs.size else None,
            "early_window_matches": early_window_metrics,
        },
        "fdepth": {
            "positive_count_original": int(np.count_nonzero(original.fdepth_m > 0.0)),
            "positive_count_native": int(np.count_nonzero(native.fdepth_m > 0.0)),
            "positive_overlap_count": int(np.count_nonzero(fdepth_overlap)),
            "mae_on_positive_overlap": float(np.mean(fdepth_abs)) if fdepth_abs.size else None,
            "rmse_on_positive_overlap": float(np.sqrt(np.mean(fdepth_abs * fdepth_abs))) if fdepth_abs.size else None,
            "sum_delta_on_positive_overlap": float(np.sum(fdepth_delta)) if fdepth_delta.size else None,
            "max_abs_error_on_positive_overlap": float(np.max(fdepth_abs)) if fdepth_abs.size else None,
        },
        "candidate_windows": {
            "0_600_s": {
                "original_positive_tfail_count": count_window(original.tfail_s, 600.0),
                "native_positive_tfail_count": count_window(native.tfail_s, 600.0),
            },
            "0_3600_s": {
                "original_positive_tfail_count": count_window(original.tfail_s, 3600.0),
                "native_positive_tfail_count": count_window(native.tfail_s, 3600.0),
            },
            "0_10800_s": {
                "original_positive_tfail_count": count_window(original.tfail_s, 10800.0),
                "native_positive_tfail_count": count_window(native.tfail_s, 10800.0),
            },
            "0_64800_s": {
                "original_positive_tfail_count": count_window(original.tfail_s, 64800.0),
                "native_positive_tfail_count": count_window(native.tfail_s, 64800.0),
            },
        },
        "classification": (
            "LEDGER_COMPARISON_BLOCKED_NATIVE_LEDGER_NOT_GENERATED"
            if native.meta.get("parse_status") == "blocked"
            else "NATIVE_LEDGER_NO_MEANINGFUL_OVERLAP"
        ),
    }


def write_hotspots(path: Path, native: LedgerArrays, original: LedgerArrays, limit: int = 200) -> None:
    orig_positive_tfail = np.flatnonzero(np.isfinite(original.tfail_s) & (original.tfail_s > 0.0))
    order = orig_positive_tfail[np.argsort(original.tfail_s[orig_positive_tfail])]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "raw_vector_index_zero_based",
                "raw_cell_id_one_based",
                "original_gindx",
                "native_gindx",
                "original_tfail_s",
                "native_tfail_s",
                "original_fdepth_m",
                "native_fdepth_m",
                "mismatch_class",
            ],
        )
        writer.writeheader()
        for idx in order[:limit]:
            writer.writerow(
                {
                    "raw_vector_index_zero_based": int(idx),
                    "raw_cell_id_one_based": int(idx) + 1,
                    "original_gindx": int(original.gindx[idx]),
                    "native_gindx": int(native.gindx[idx]),
                    "original_tfail_s": float(original.tfail_s[idx]),
                    "native_tfail_s": None
                    if not np.isfinite(native.tfail_s[idx])
                    else float(native.tfail_s[idx]),
                    "original_fdepth_m": float(original.fdepth_m[idx]),
                    "native_fdepth_m": float(native.fdepth_m[idx]),
                    "mismatch_class": "ORIGINAL_POSITIVE_TFAIL_NATIVE_BLOCKED_OR_MISSING",
                }
            )


def write_ledger_arrays(output_dir: Path, ledger: LedgerArrays) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "native_unsfin_gindx": output_dir / "native_unsfin_gindx.npy",
        "native_unsfin_tfail_s": output_dir / "native_unsfin_tfail_s.npy",
        "native_unsfin_fdepth_m": output_dir / "native_unsfin_fdepth_m.npy",
        "native_unsfin_fsdepth_m": output_dir / "native_unsfin_fsdepth_m.npy",
        "native_unsfin_meta": output_dir / "native_unsfin_ledger_meta.json",
    }
    np.save(paths["native_unsfin_gindx"], ledger.gindx)
    np.save(paths["native_unsfin_tfail_s"], ledger.tfail_s)
    np.save(paths["native_unsfin_fdepth_m"], ledger.fdepth_m)
    if ledger.fsdepth_m is not None:
        np.save(paths["native_unsfin_fsdepth_m"], ledger.fsdepth_m)
    paths["native_unsfin_meta"].write_text(json.dumps(ledger.meta, indent=2), encoding="utf-8")
    return {key: str(value) for key, value in paths.items()}


def write_phase_outputs(phase_dir: Path, oracle_dir: Path, source_root: Path | None = None) -> dict[str, Any]:
    original = load_original_oracle(oracle_dir)
    native = build_native_blocked_ledger(original.gindx.shape, source_root=source_root)

    generator_dir = phase_dir / "04_native_unsfin_ledger_generator"
    comparison_dir = phase_dir / "05_ledger_comparison"
    gap_dir = phase_dir / "06_gap_attribution"
    paths = write_ledger_arrays(generator_dir, native)

    metrics = compare_ledgers(native, original)
    comparison_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = comparison_dir / "native_vs_original_ledger_metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    write_hotspots(comparison_dir / "native_vs_original_ledger_hotspots.csv", native, original)

    gap = {
        "decision": "GAP_ATTRIBUTED_NEEDS_CURRENT_FIELD_IMPLEMENTATION",
        "primary_gap": BLOCKED_REASON,
        "categories": [
            "TFIRST_SEARCH_LOOP_MISMATCH",
            "TINCREMENT_REFINEMENT_MISMATCH",
            "DOUBLELAYER_FS_MISMATCH",
            "FDEPTH_CAPTURE_MISMATCH",
            "CURRENT_FIELD_MISSING",
        ],
        "patchable_now": False,
        "runtime_patch_forbidden_this_phase": True,
        "next_trace": "Instrument original unsfin/doublelayer for q, rka/rkb, pt, desatt, fs, fmn, gindx at first-hit windows, or port analytic roota/rootb/rootc/doublelayer as ledger-only code.",
        "evidence": {
            "native_blocked_reason": BLOCKED_REASON,
            "native_runtime_provider_enabled": RUNTIME_PROVIDER_ENABLED,
            "output_inferred": OUTPUT_INFERRED,
            "dfs_runtime_modified": DFS_RUNTIME_MODIFIED,
        },
    }
    gap_dir.mkdir(parents=True, exist_ok=True)
    gap_path = gap_dir / "gap_attribution.json"
    gap_path.write_text(json.dumps(gap, indent=2), encoding="utf-8")

    return {
        "oracle": original.meta,
        "native": native.meta,
        "native_paths": paths,
        "metrics_path": str(metrics_path),
        "gap_path": str(gap_path),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase-dir", required=True, type=Path)
    parser.add_argument("--oracle-dir", required=True, type=Path)
    parser.add_argument("--source-root", type=Path, default=None)
    args = parser.parse_args(argv)

    summary = write_phase_outputs(args.phase_dir, args.oracle_dir, args.source_root)
    summary_path = args.phase_dir / "04_native_unsfin_ledger_generator" / "native_unsfin_ledger_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({"status": "ok", "summary_path": str(summary_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
