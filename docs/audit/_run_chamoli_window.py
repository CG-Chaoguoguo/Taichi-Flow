"""Run Chamoli on the production EDDASolver path and diff ASCII grids vs Fortran.

This keeps native EDDA-named writers (EDDA -> Taichi). It is not the npz
checkpoint runner used for BJ residual hunts.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from api.services import apply_native_runtime_inputs  # noqa: E402
from api.services import build_reference_runtime_metadata, parse_reference_config_file  # noqa: E402
from edda.backend.backend_manager import assert_live_cuda, live_backend_snapshot  # noqa: E402
from edda.solver.edda_solver import EDDASolver  # noqa: E402

# Same production experiment flags as tools/run_cuda_candidate_case.py.
# Do not import that module here: it currently fails unless edda.io.fortran_text_format exists.
DEFAULT_CUDA_FLAGS = {
    "EDDA_EXPERIMENT_GPU_ONLY_PRODUCTION_SMOKE": "1",
    "EDDA_EXPERIMENT_PROJECT_CUDA_BACKEND_STAGE1": "1",
    "EDDA_EXPERIMENT_PROJECT_CUDA_BACKEND_STAGE2": "1",
    "EDDA_EXPERIMENT_RNOFF_PERIOD_PRECOMPUTE": "1",
    "EDDA_EXPERIMENT_RNOFF_TOPOINDEX": "1",
    "EDDA_EXPERIMENT_RNOFF_TOPOINDEX_PERIOD_GPU_KERNEL": "1",
    "EDDA_EXPERIMENT_RNOFF_NATIVE_UNSFIN_FEED": "1",
    "EDDA_NATIVE_UNSFIN_RUNTIME_FEED": "1",
    "EDDA_EXPERIMENT_RNOFF_GPU_FIELD_FEED": "1",
    "EDDA_EXPERIMENT_DFS_SOURCE_STAGING_FIELD": "1",
    "EDDA_EXPERIMENT_DFS_SOURCE_STAGING_FAST_CONSUME": "1",
    "EDDA_EXPERIMENT_DFS_SOURCE_STAGING_KERNEL": "1",
    "EDDA_EXPERIMENT_DFS_EROSION_DEPOSITION_DIAGNOSTIC_KERNEL": "1",
    "EDDA_EXPERIMENT_DFS_EROSION_DEPOSITION_DEEP_STATE_DIAGNOSTIC_KERNEL": "1",
    "EDDA_EXPERIMENT_DFS_EROSION_DEPOSITION_MUTATE": "1",
    "EDDA_EXPERIMENT_DFS_ORIGINAL_PREDICTOR_RETRY_GATES": "1",
    "EDDA_EXPERIMENT_DFS_IFORT_INACTIVE_BARRIER_DEPTH_GATE_COMPAT": "0",
    "EDDA_EXPERIMENT_VALIDATE_PRECOMPUTED_UNSFIN_FAILURE_GRID_MATCH": "1",
    "TQDM_DISABLE": "1",
}

FAMILIES = (
    ("Flow_depth_EDDA", "Flow_depth_EDDA"),
    ("Flow_velocity_EDDA", "Flow_velocity_EDDA"),
    ("Max_flow_depth_EDDA", "Max_flow_depth_EDDA"),
    ("Max_flow_velocity_EDDA", "Max_flow_velocity_EDDA"),
    ("Erosion_depth_EDDA", "Erosion_depth_EDDA"),
    ("Deposit_depth_EDDA", "Deposit_depth_EDDA"),
    ("Total_depth_EDDA", "Total_depth_EDDA"),
    ("Volumetric_sediment_conceEDDA", "Volumetric_sediment_conceEDDA"),
    ("LS_ScarEDDA", "LS_ScarEDDA"),
    ("faildphEDDA", "faildphEDDA"),
    ("SFdepthEDDA", "SFdepthEDDA"),
    ("DFdepthEDDA", "DFdepthEDDA"),
    ("FFdepthEDDA", "FFdepthEDDA"),
    ("MaxSFdepthEDDA", "MaxSFdepthEDDA"),
    ("MaxDFdepthEDDA", "MaxDFdepthEDDA"),
    ("MaxFFdepthEDDA", "MaxFFdepthEDDA"),
)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def read_ascii_grid(path: Path) -> np.ndarray:
    rows: list[list[float]] = []
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            values: list[float] = []
            ok = True
            for part in stripped.replace(",", " ").split():
                try:
                    values.append(float(part))
                except ValueError:
                    ok = False
                    break
            if ok and values:
                rows.append(values)
    if not rows:
        raise ValueError(f"no numeric rows parsed from {path}")
    return np.asarray(rows, dtype=np.float64)


def align_arrays(actual: np.ndarray, reference: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    actual = np.asarray(actual, dtype=np.float64)
    reference = np.asarray(reference, dtype=np.float64)
    if actual.shape == reference.shape:
        return actual, reference
    if actual.T.shape == reference.shape:
        return actual.T, reference
    min0 = min(actual.shape[0], reference.shape[0])
    min1 = min(actual.shape[1], reference.shape[1])
    return actual[:min0, :min1], reference[:min0, :min1]


def find_grid(directory: Path, original_stem: str, checkpoint: float) -> Path | None:
    time_token = f"{checkpoint:.1f}"
    taichi_stem = original_stem.replace("EDDA", "Taichi")
    candidates = [
        directory / f"{taichi_stem}_{time_token}.txt",
        directory / f"{taichi_stem}_{time_token}.asc",
        directory / f"{original_stem}_{time_token}.txt",
        directory / f"{original_stem}_{time_token}.asc",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def compare_family(
    *,
    family: str,
    original_stem: str,
    checkpoint: float,
    actual_dir: Path,
    reference_dir: Path,
) -> dict[str, Any]:
    actual_path = find_grid(actual_dir, original_stem, checkpoint)
    reference_path = find_grid(reference_dir, original_stem, checkpoint)
    row: dict[str, Any] = {
        "family": family,
        "checkpoint": checkpoint,
        "actual_path": str(actual_path) if actual_path else None,
        "reference_path": str(reference_path) if reference_path else None,
    }
    if actual_path is None or reference_path is None:
        row["status"] = "missing"
        return row
    actual, reference = align_arrays(read_ascii_grid(actual_path), read_ascii_grid(reference_path))
    valid = np.isfinite(actual) & np.isfinite(reference) & (reference > -9990.0) & (actual > -9990.0)
    if not np.any(valid):
        row["status"] = "no_valid_cells"
        return row
    diff = actual[valid] - reference[valid]
    abs_diff = np.abs(diff)
    wet = (np.abs(actual) > 1.0e-12) | (np.abs(reference) > 1.0e-12)
    wet &= valid
    row.update(
        {
            "status": "pass" if int(np.count_nonzero(abs_diff > 1.0e-12)) == 0 else "residual",
            "compared_count": int(np.count_nonzero(valid)),
            "wet_cell_count": int(np.count_nonzero(wet)),
            "mismatch_count": int(np.count_nonzero(abs_diff > 1.0e-12)),
            "max_abs_error": float(np.max(abs_diff)),
            "rmse": float(np.sqrt(np.mean(np.square(diff)))),
        }
    )
    return row


def _volume_snapshot(solver: Any, t: float) -> dict[str, Any]:
    dfs = getattr(solver, "dfs_dynamic_wave", None)
    stepper = getattr(solver, "time_stepper", None)
    if dfs is None or stepper is None:
        return {"t": t}
    return {
        "t": t,
        "accepted_step_id": int(getattr(solver, "dfs_accepted_step_id", 0)),
        "rejected_steps": int(getattr(stepper, "rejected_steps", 0)),
        "step_count": int(getattr(stepper, "step_count", 0)),
        "dt_current": float(getattr(stepper, "dt_current", 0.0)),
        "fortran_tempdt": float(getattr(solver, "fortran_tempdt", 0.0)),
        "totalinflowvolume": float(dfs.totalinflowvolume[None]),
        "totaloutflowvolume": float(dfs.totaloutflowvolume[None]),
        "totalerosionvolume": float(dfs.totalerosionvolume[None]),
        "totaldepovolume": float(dfs.totaldepovolume[None]),
        "totalrivolume": float(dfs.totalrivolume[None]),
        "totalinfilvolume": float(dfs.totalinfilvolume[None]),
        "totalfsvolume": float(dfs.totalfsvolume[None]),
    }


def _summarize_dt_trace(records: list[dict[str, Any]]) -> dict[str, Any]:
    accepted = [row for row in records if row.get("event") == "accepted"]
    rejected = [row for row in records if row.get("event") == "rejected"]
    dts = [float(row.get("used_dt") or row.get("dt_attempt") or 0.0) for row in accepted]
    reasons: dict[str, int] = {}
    for row in rejected:
        name = str(((row.get("first_reject") or {}).get("first_reject_reason_name")) or "unknown")
        reasons[name] = reasons.get(name, 0) + 1
    return {
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "mean_accepted_dt": float(np.mean(dts)) if dts else None,
        "min_accepted_dt": float(np.min(dts)) if dts else None,
        "max_accepted_dt": float(np.max(dts)) if dts else None,
        "reject_reasons": reasons,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Chamoli production solver for a short window.")
    parser.add_argument("--edda-in", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--backend", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--t-end", type=float, default=45.0)
    parser.add_argument("--reference-results", required=True)
    parser.add_argument(
        "--enable-dt-probe",
        action="store_true",
        help="Export observational dt/reject/volume traces without changing numerics.",
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )

    edda_in = Path(args.edda_in).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    solver_output = output_dir / "solver_output"
    solver_output.mkdir(parents=True, exist_ok=True)

    old_env = {key: os.environ.get(key) for key in DEFAULT_CUDA_FLAGS}
    os.environ.update(DEFAULT_CUDA_FLAGS)
    started = time.time()
    manifest: dict[str, Any] = {
        "edda_in": str(edda_in),
        "output_dir": str(output_dir),
        "backend": args.backend,
        "t_end": float(args.t_end),
        "reference_results": str(Path(args.reference_results).resolve()),
        "started_at_epoch": started,
    }
    write_json(output_dir / "run_manifest.json", manifest)
    try:
        parsed = parse_reference_config_file(str(edda_in), str(edda_in.parent))
        config, effective_config, runtime_input_manifest, runtime_provenance = build_reference_runtime_metadata(
            parsed,
            output_dir / "_metadata",
        )
        config.compute.backend = str(args.backend)
        config.compute.use_double_precision = True
        config.time.t_end = float(args.t_end)
        config.output_dir = str(solver_output)
        if isinstance(effective_config.get("config"), dict):
            compute_cfg = dict(effective_config["config"].get("compute") or {})
            compute_cfg["backend"] = str(args.backend)
            compute_cfg["use_double_precision"] = True
            effective_config["config"]["compute"] = compute_cfg
        write_json(output_dir / "effective_config.json", effective_config)
        write_json(output_dir / "runtime_provenance.json", runtime_provenance)
        print(
            f"[chamoli-window] requested backend={args.backend} t_end={args.t_end}",
            flush=True,
        )

        solver = EDDASolver(config)
        print("[chamoli-window] initializing solver (Taichi + field alloc)", flush=True)
        solver.initialize()
        if str(args.backend) == "cuda":
            snapshot = assert_live_cuda()
        else:
            snapshot = live_backend_snapshot()
        manifest["live_backend"] = snapshot
        write_json(output_dir / "run_manifest.json", manifest)
        print(
            "[chamoli-window] live backend "
            f"arch={snapshot.get('live_arch')} gpu={snapshot.get('gpu_name')} "
            f"vram={snapshot.get('gpu_memory_used_MB')}MB "
            f"util={snapshot.get('gpu_utilization_percent')}%",
            flush=True,
        )
        print(
            "[chamoli-window] applying native unsfin ledger "
            "(CPU analytic roots; CUDA fields stay resident until DFS steps)",
            flush=True,
        )
        runtime_input_manifest = apply_native_runtime_inputs(solver, runtime_input_manifest)
        write_json(output_dir / "runtime_input_manifest.json", runtime_input_manifest)
        if str(args.backend) == "cuda":
            snapshot = assert_live_cuda()
            manifest["live_backend_after_unsfin"] = snapshot
            write_json(output_dir / "run_manifest.json", manifest)
            print("[chamoli-window] CUDA still live after unsfin; starting solver.run()", flush=True)
        triggerslide = next(
            (item for item in runtime_input_manifest.get("inputs", []) if item.get("family") == "triggerslide"),
            {},
        )
        manifest["triggerslide_loaded"] = bool(triggerslide.get("path"))
        manifest["dfs_manningbar_variant"] = config.hydrology.dfs_manningbar_variant
        manifest["dfs_dry_face_velocity_variant"] = config.hydrology.dfs_dry_face_velocity_variant
        manifest["dfs_artivis_variant"] = config.hydrology.dfs_artivis_variant
        manifest["dfs_absubar_variant"] = config.hydrology.dfs_absubar_variant
        volume_checkpoints: list[dict[str, Any]] = []
        if args.enable_dt_probe:
            solver.configure_step_lifecycle_trace(
                enabled=True,
                window_start=0.0,
                window_end=float(args.t_end),
                limit=200000,
            )

            def _on_output(t: float, _state: Any) -> None:
                volume_checkpoints.append(_volume_snapshot(solver, float(t)))

            solver.set_output_callback(_on_output)
        write_json(output_dir / "run_manifest.json", manifest)

        solver.run()
        if args.enable_dt_probe:
            records = solver.get_step_lifecycle_trace_records()
            write_json(output_dir / "dt_probe_trace.json", records[-5000:])
            write_json(
                output_dir / "dt_probe.json",
                {
                    "summary": _summarize_dt_trace(records),
                    "volume_checkpoints": volume_checkpoints,
                    "final_volume": _volume_snapshot(solver, float(solver.time_stepper.t_current)),
                    "fortran_oracle": {
                        "total_steps_t14400": 38190,
                        "mean_dt_s": 14400.0 / 38190.0,
                        "scaled_steps_at_t_end": int(round(38190.0 * float(args.t_end) / 14400.0)),
                    },
                },
            )
        elapsed = time.time() - started
        tout = float(getattr(config.time, "dt_output", 45.0) or 45.0)
        wanted = []
        checkpoint = tout
        while checkpoint <= float(args.t_end) + 1.0e-9:
            wanted.append(float(checkpoint))
            checkpoint += tout
        if float(args.t_end) not in wanted:
            wanted.append(float(args.t_end))
        checkpoint_summaries: dict[str, Any] = {}
        for checkpoint in wanted:
            families = [
                compare_family(
                    family=label,
                    original_stem=stem,
                    checkpoint=checkpoint,
                    actual_dir=solver_output,
                    reference_dir=Path(args.reference_results).resolve(),
                )
                for label, stem in FAMILIES
            ]
            summary = {
                "backend": args.backend,
                "t_end": float(args.t_end),
                "checkpoint": checkpoint,
                "elapsed_seconds": elapsed,
                "compared_count": sum(1 for row in families if row.get("status") in {"pass", "residual"}),
                "missing_count": sum(1 for row in families if row.get("status") == "missing"),
                "residual_count": sum(1 for row in families if row.get("status") == "residual"),
                "pass_count": sum(1 for row in families if row.get("status") == "pass"),
                "max_abs_error": max(
                    (float(row["max_abs_error"]) for row in families if "max_abs_error" in row),
                    default=float("nan"),
                ),
                "families": families,
            }
            write_json(output_dir / f"grid_diff_t{checkpoint:.1f}.json", summary)
            checkpoint_summaries[f"{checkpoint:.1f}"] = summary
        summary = checkpoint_summaries[f"{float(args.t_end):.1f}"]
        manifest.update(
            {
                "status": "complete",
                "elapsed_seconds": elapsed,
                "summary": summary,
                "checkpoint_summaries": checkpoint_summaries,
            }
        )
        write_json(output_dir / "run_manifest.json", manifest)
        print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
        return 0
    except Exception as exc:
        manifest.update({"status": "failed", "error": str(exc), "elapsed_seconds": time.time() - started})
        write_json(output_dir / "run_manifest.json", manifest)
        raise
    finally:
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
