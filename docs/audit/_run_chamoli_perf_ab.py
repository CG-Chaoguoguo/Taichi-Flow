"""Same-code Chamoli CUDA A/B window: OPT vs emulated pre-opt I/O/hot-path flags.

Does not check out old git.  Baseline emulation uses current kernels with:
  async_output=off, observe_stride=1, EDDA_CAPTURE_DEPO_VELOCITY=1,
  EDDA_SYNC_LEGACY_DIRECTIONAL_VELOCITY=1.
OPT uses current defaults: async on, stride 20, those env flags off.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import logging
import os
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_WINDOW_PATH = Path(__file__).resolve().with_name("_run_chamoli_window.py")
_WINDOW_SPEC = importlib.util.spec_from_file_location("chamoli_window_helpers", _WINDOW_PATH)
if _WINDOW_SPEC is None or _WINDOW_SPEC.loader is None:
    raise RuntimeError(f"Unable to load Chamoli window helpers from {_WINDOW_PATH}")
_WINDOW = importlib.util.module_from_spec(_WINDOW_SPEC)
_WINDOW_SPEC.loader.exec_module(_WINDOW)

DEFAULT_CUDA_FLAGS = _WINDOW.DEFAULT_CUDA_FLAGS
FAMILIES = _WINDOW.FAMILIES
apply_native_runtime_inputs = _WINDOW.apply_native_runtime_inputs
build_reference_runtime_metadata = _WINDOW.build_reference_runtime_metadata
compare_family = _WINDOW.compare_family
parse_reference_config_file = _WINDOW.parse_reference_config_file
write_json = _WINDOW.write_json

from edda.backend.backend_manager import assert_live_cuda, live_backend_snapshot  # noqa: E402
from edda.solver.edda_solver import EDDASolver  # noqa: E402


def _nvidia_sample() -> dict[str, Any]:
    raw = subprocess.check_output(
        [
            "nvidia-smi",
            "--query-gpu=utilization.gpu,utilization.memory,memory.used,memory.total",
            "--format=csv,noheader,nounits",
        ],
        text=True,
        timeout=8,
    ).strip()
    gpu, memu, used, total = [part.strip() for part in raw.split(",")]
    return {
        "gpu_util": float(gpu),
        "mem_util": float(memu),
        "mem_used_mb": float(used),
        "mem_total_mb": float(total),
    }


def _dir_bytes(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                pass
    return total


class GpuSampler:
    def __init__(self, csv_path: Path, output_dir: Path, interval_s: float = 1.0) -> None:
        self.csv_path = csv_path
        self.output_dir = output_dir
        self.interval_s = interval_s
        self.rows: list[dict[str, Any]] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="nvidia-smi-sampler", daemon=True)

    def start(self) -> None:
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        self.t0 = time.time()
        self._thread.start()

    def stop(self) -> list[dict[str, Any]]:
        self._stop.set()
        self._thread.join(timeout=5)
        if self.rows:
            with self.csv_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(self.rows[0].keys()))
                writer.writeheader()
                writer.writerows(self.rows)
        return self.rows

    def _run(self) -> None:
        while not self._stop.is_set():
            row: dict[str, Any] = {"wall_s": round(time.time() - self.t0, 3)}
            try:
                row.update(_nvidia_sample())
            except Exception as exc:  # noqa: BLE001
                row.update(
                    {
                        "gpu_util": None,
                        "mem_util": None,
                        "mem_used_mb": None,
                        "mem_total_mb": None,
                        "error": str(exc),
                    }
                )
            row["out_bytes"] = _dir_bytes(self.output_dir)
            self.rows.append(row)
            self._stop.wait(self.interval_s)


def _summarize_gpu(rows: list[dict[str, Any]]) -> dict[str, Any]:
    vals = [float(row["gpu_util"]) for row in rows if row.get("gpu_util") is not None]
    mems = [float(row["mem_used_mb"]) for row in rows if row.get("mem_used_mb") is not None]
    if not vals:
        return {"n": 0}
    ordered = sorted(vals)
    p90_idx = min(len(ordered) - 1, int(round(0.90 * (len(ordered) - 1))))
    return {
        "n": len(vals),
        "min": min(vals),
        "mean": statistics.fmean(vals),
        "median": statistics.median(vals),
        "p90": ordered[p90_idx],
        "max": max(vals),
        "vram_mean_mb": statistics.fmean(mems) if mems else None,
        "vram_max_mb": max(mems) if mems else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Chamoli same-code OPT vs baseline-emulation CUDA window.")
    parser.add_argument("--edda-in", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--reference-results", required=True)
    parser.add_argument("--backend", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--t-end", type=float, default=180.0)
    parser.add_argument("--emulate-baseline", action="store_true")
    parser.add_argument("--async-output", dest="async_output", action="store_true")
    parser.add_argument("--no-async-output", dest="async_output", action="store_false")
    parser.add_argument("--observe-stride", type=int, default=None)
    parser.add_argument("--gpu-interval-s", type=float, default=1.0)
    parser.set_defaults(async_output=None)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )

    emulate = bool(args.emulate_baseline)
    async_output = False if emulate else (True if args.async_output is None else bool(args.async_output))
    observe_stride = 1 if emulate else (20 if args.observe_stride is None else int(args.observe_stride))

    extra_env = dict(DEFAULT_CUDA_FLAGS)
    if emulate:
        extra_env["EDDA_CAPTURE_DEPO_VELOCITY"] = "1"
        extra_env["EDDA_SYNC_LEGACY_DIRECTIONAL_VELOCITY"] = "1"
    else:
        extra_env.setdefault("EDDA_CAPTURE_DEPO_VELOCITY", "0")
        extra_env.setdefault("EDDA_SYNC_LEGACY_DIRECTIONAL_VELOCITY", "0")

    edda_in = Path(args.edda_in).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    solver_output = output_dir / "solver_output"
    solver_output.mkdir(parents=True, exist_ok=True)

    old_env = {key: os.environ.get(key) for key in extra_env}
    os.environ.update(extra_env)
    started = time.time()
    mode = "baseline_emulation" if emulate else "opt"
    manifest: dict[str, Any] = {
        "mode": mode,
        "edda_in": str(edda_in),
        "output_dir": str(output_dir),
        "backend": args.backend,
        "t_end": float(args.t_end),
        "async_output": async_output,
        "numerical_observe_stride": observe_stride,
        "emulate_baseline": emulate,
        "capture_depo_velocity": extra_env.get("EDDA_CAPTURE_DEPO_VELOCITY"),
        "sync_legacy_directional_velocity": extra_env.get("EDDA_SYNC_LEGACY_DIRECTIONAL_VELOCITY"),
        "started_at_epoch": started,
    }
    write_json(output_dir / "run_manifest.json", manifest)
    sampler = GpuSampler(output_dir / "gpu_samples.csv", solver_output, interval_s=float(args.gpu_interval_s))
    try:
        parsed = parse_reference_config_file(str(edda_in), str(edda_in.parent))
        config, effective_config, runtime_input_manifest, runtime_provenance = build_reference_runtime_metadata(
            parsed,
            output_dir / "_metadata",
        )
        config.compute.backend = str(args.backend)
        config.compute.use_double_precision = True
        config.compute.async_output = async_output
        config.compute.numerical_observe_stride = observe_stride
        config.compute.write_geotiff_frames = True
        config.time.t_end = float(args.t_end)
        config.output_dir = str(solver_output)
        write_json(output_dir / "effective_config.json", effective_config)
        write_json(output_dir / "runtime_provenance.json", runtime_provenance)

        solver = EDDASolver(config)
        print(f"[chamoli-ab] mode={mode} t_end={args.t_end} async={async_output} stride={observe_stride}", flush=True)
        solver.initialize()
        snapshot = assert_live_cuda() if args.backend == "cuda" else live_backend_snapshot()
        manifest["live_backend"] = snapshot
        runtime_input_manifest = apply_native_runtime_inputs(solver, runtime_input_manifest)
        write_json(output_dir / "runtime_input_manifest.json", runtime_input_manifest)
        sampler.start()
        print("[chamoli-ab] solver.run()", flush=True)
        solver.run()
        elapsed = time.time() - started
        gpu_rows = sampler.stop()
        gpu_summary = _summarize_gpu(gpu_rows)

        tout = float(getattr(config.time, "dt_output", 45.0) or 45.0)
        wanted: list[float] = []
        checkpoint = tout
        while checkpoint <= float(args.t_end) + 1.0e-9:
            wanted.append(float(checkpoint))
            checkpoint += tout
        if float(args.t_end) not in wanted:
            wanted.append(float(args.t_end))
        checkpoint_summaries: dict[str, Any] = {}
        reference = Path(args.reference_results).resolve()
        for checkpoint in wanted:
            families = [
                compare_family(
                    family=label,
                    original_stem=stem,
                    checkpoint=checkpoint,
                    actual_dir=solver_output,
                    reference_dir=reference,
                )
                for label, stem in FAMILIES
            ]
            summary = {
                "mode": mode,
                "checkpoint": checkpoint,
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

        manifest.update(
            {
                "status": "complete",
                "elapsed_seconds": elapsed,
                "gpu_summary": gpu_summary,
                "out_bytes": _dir_bytes(solver_output),
                "checkpoint_summaries": checkpoint_summaries,
            }
        )
        write_json(output_dir / "run_manifest.json", manifest)
        write_json(output_dir / "gpu_summary.json", gpu_summary)
        print(
            json.dumps(
                {
                    "mode": mode,
                    "elapsed_seconds": elapsed,
                    "gpu_summary": gpu_summary,
                    "out_bytes": manifest["out_bytes"],
                },
                indent=2,
                ensure_ascii=False,
            ),
            flush=True,
        )
        return 0
    except Exception as exc:
        try:
            sampler.stop()
        except Exception:
            pass
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
