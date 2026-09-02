"""BJ short-window regression: default face-flux must stay both_thin_weighted."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from api.services import apply_native_runtime_inputs  # noqa: E402
from api.services import build_reference_runtime_metadata, parse_reference_config_file  # noqa: E402
from edda.solver.edda_solver import EDDASolver  # noqa: E402

# Same production CUDA experiment flags as Chamoli window runner.
DEFAULT_CUDA_FLAGS = {
    "EDDA_EXPERIMENT_GPU_ONLY_PRODUCTION_SMOKE": "1",
    "EDDA_EXPERIMENT_PROJECT_CUDA_BACKEND_STAGE1": "1",
    "EDDA_EXPERIMENT_PROJECT_CUDA_BACKEND_STAGE2": "1",
    "TQDM_DISABLE": "1",
}

BJ = Path(r"C:\Users\Administrator\Desktop\EDDA_test_project\BJ_HXL_Text(1)\BJ_HXL_Text")
OUT = REPO_ROOT / "artifacts" / "bj_cpu_t2_faceflux_guard"


def main() -> int:
    if not (BJ / "edda_in.txt").exists():
        print(json.dumps({"status": "skipped", "reason": "BJ case missing"}))
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    solver_output = OUT / "solver_output"
    solver_output.mkdir(parents=True, exist_ok=True)
    started = time.time()
    os.environ.update(DEFAULT_CUDA_FLAGS)
    parsed = parse_reference_config_file(str(BJ / "edda_in.txt"), str(BJ))
    assert parsed.dfs_face_flux_variant == "both_thin_weighted", parsed.dfs_face_flux_variant
    assert parsed.dfs_manningbar_variant == "exponential_cv", parsed.dfs_manningbar_variant
    assert parsed.dfs_dry_face_velocity_variant == "keep_velocity_bj", parsed.dfs_dry_face_velocity_variant
    assert parsed.dfs_artivis_variant == "depth_ratio_bj", parsed.dfs_artivis_variant
    assert parsed.dfs_absubar_variant == "max_component_bj", parsed.dfs_absubar_variant
    config, effective, manifest, provenance = build_reference_runtime_metadata(parsed, OUT / "_metadata")
    config.compute.backend = "cuda"
    config.compute.use_double_precision = True
    config.time.t_end = 2.0
    config.time.dt_output = 2.0
    config.output_dir = str(solver_output)
    solver = EDDASolver(config)
    solver.initialize()
    manifest = apply_native_runtime_inputs(solver, manifest)
    assert solver.dfs_dynamic_wave.dfs_face_flux_variant == "both_thin_weighted"
    assert solver.dfs_dynamic_wave.dfs_manningbar_variant == "exponential_cv"
    assert solver.dfs_dynamic_wave.dfs_dry_face_velocity_variant == "keep_velocity_bj"
    assert solver.dfs_dynamic_wave.dfs_artivis_variant == "depth_ratio_bj"
    assert solver.dfs_dynamic_wave.dfs_absubar_variant == "max_component_bj"
    solver.run()
    payload = {
        "status": "complete",
        "elapsed_seconds": time.time() - started,
        "dfs_face_flux_variant": config.hydrology.dfs_face_flux_variant,
        "dfs_manningbar_variant": config.hydrology.dfs_manningbar_variant,
        "dfs_dry_face_velocity_variant": config.hydrology.dfs_dry_face_velocity_variant,
        "dfs_artivis_variant": config.hydrology.dfs_artivis_variant,
        "dfs_absubar_variant": config.hydrology.dfs_absubar_variant,
        "backend": "cuda",
        "t_end": 2.0,
    }
    (OUT / "run_manifest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
