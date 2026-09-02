"""One-shot exporter for the Chamoli vs 45-switch capability matrix."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from api.services.edda_switch_registry import EDDA_SWITCH_REGISTRY, REGISTRY_VERSION
from api.services.parameter_catalog import (
    EDITABLE_PARAMETERS,
    READONLY_DISPLAY_PARAMETERS,
    build_static_parameter_catalog,
)
from api.services.reference_config_parser import parse_reference_config_file
from api.services.runmode_capabilities import RUNMODE_CAPABILITIES

CHAMOLI = Path(r"C:\Users\Administrator\Desktop\EDDA_test_project\Chamoli-EDDA file\Chamoli-EDDA file")
BJ_HXL = Path(r"C:\Users\Administrator\Desktop\EDDA_test_project\BJ_HXL_Text(1)\BJ_HXL_Text")
OUT = Path(__file__).with_name("chamoli_capability_matrix.json")

CHAMOLI_ACTIVE_PROCESS = {
    "simulate_rainfall": False,
    "simulate_infiltration": False,
    "simulate_inflow_hydrograph": True,
    "simulate_outflow_cell": True,
    "simulate_shallow_landslide": False,
    "simulate_debris_flow": True,
    "simulate_erosion": True,
    "simulate_water_and_solid_separately": True,
    "simulate_drainage_flow": False,
    "simulate_barrier": False,
}

CHAMOLI_ABSENT_SWITCHES = {
    "save_max_solid_depth": (
        "Chamoli trini.f90 has no maxsoliddepthsave read; input jumps from "
        "totaldepthsave to cvsave. Not a 46th registry entry — the 45-switch "
        "BJ_HXL contract keeps the key with parsed value null."
    ),
}


def _file_rows(parsed) -> list[dict]:
    rows = []
    for family, ref in parsed.file_inputs.items():
        rows.append(
            {
                "family": family,
                "raw_paths": list(ref.raw_paths),
                "resolved_paths": list(ref.resolved_paths),
                "exists_on_disk": list(ref.exists),
                "production_status": ref.production_status,
                "original_branch_active": ref.original_branch_active,
                "current_backend_branch_active": ref.current_backend_branch_active,
                "activation_condition": ref.activation_condition,
                "notes": ref.notes,
            }
        )
    return rows


def main() -> None:
    chamoli = parse_reference_config_file(str(CHAMOLI / "edda_in.txt"), str(CHAMOLI))
    bj = parse_reference_config_file(str(BJ_HXL / "edda_in.txt"), str(BJ_HXL))
    catalog = build_static_parameter_catalog()
    catalog_by_key = {entry["key"]: entry for entry in catalog["parameters"]}
    aux_by_key = {entry["key"]: entry for entry in RUNMODE_CAPABILITIES}

    tutorial = CHAMOLI / "Data" / "tutorial"
    present_rasters = sorted(p.name for p in tutorial.glob("*.asc")) if tutorial.exists() else []
    missing_declared = []
    for family, ref in chamoli.file_inputs.items():
        for path, exists in zip(ref.resolved_paths, ref.exists):
            if not exists:
                missing_declared.append({"family": family, "path": path})

    switches = []
    for spec in EDDA_SWITCH_REGISTRY:
        chamoli_value = chamoli.flags.get(spec.key)
        bj_value = bj.flags.get(spec.key)
        catalog_entry = catalog_by_key.get(f"edda.run_controls.{spec.key}") or catalog_by_key.get(
            f"edda.output_controls.{spec.key}"
        )
        frontend = None
        if catalog_entry:
            frontend = {
                "catalog_key": catalog_entry["key"],
                "editable": catalog_entry.get("editable"),
                "frontend_policy": catalog_entry.get("frontend_policy"),
                "label_zh": catalog_entry.get("label_zh"),
                "group": catalog_entry.get("group"),
            }
        switches.append(
            {
                "source_index": spec.source_index,
                "key": spec.key,
                "original_variable": spec.original_variable,
                "group": spec.group,
                "chamoli_parsed_value": chamoli_value,
                "bj_hxl_parsed_value": bj_value,
                "chamoli_active_in_this_case": CHAMOLI_ACTIVE_PROCESS.get(spec.key),
                "chamoli_variant_note": CHAMOLI_ABSENT_SWITCHES.get(spec.key),
                "backend_status": spec.status,
                "frontend_policy": spec.frontend_policy,
                "consumption_stage": spec.consumption_stage,
                "original_semantics": spec.original_semantics,
                "status_reason": spec.status_reason,
                "taichi_runtime_consumer": spec.taichi_runtime_consumer,
                "frontend_catalog": frontend,
            }
        )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "oracle_policy": "rerun Fortran Debug\\EDDA.exe; do not reuse pre-rerun results",
        "registry_version": REGISTRY_VERSION,
        "entry_count": len(EDDA_SWITCH_REGISTRY),
        "cases": {
            "chamoli": {
                "edda_in": str(CHAMOLI / "edda_in.txt"),
                "fortran_exe": str(CHAMOLI / "Debug" / "EDDA.exe"),
                "grid": {"imax": 41069, "nrow": 748, "ncol": 715},
                "time": {"simul_s": chamoli.simul, "tout_s": chamoli.tout},
                "sediment_line": {
                    "shape": "d50 cvstar cvglacier cvlandslide coedepo cs",
                    "d50": chamoli.d50,
                    "cvstar": chamoli.cvstar,
                    "cvglacier": chamoli.cvglacier,
                    "cvlandslide": chamoli.cvlandslide,
                    "coedepo": chamoli.coedepo,
                    "cs": chamoli.cs,
                },
                "manningbar_variant": chamoli.dfs_manningbar_variant,
                "face_flux_variant": chamoli.dfs_face_flux_variant,
                "dry_face_velocity_variant": chamoli.dfs_dry_face_velocity_variant,
                "artivis_variant": chamoli.dfs_artivis_variant,
                "absubar_variant": chamoli.dfs_absubar_variant,
                "debrisflowmanning": chamoli.debrisflowmanning,
                "extension_flags": chamoli.extension_flags,
                "present_tutorial_rasters": present_rasters,
                "declared_missing_files": missing_declared,
            },
            "bj_hxl": {
                "edda_in": str(BJ_HXL / "edda_in.txt"),
                "sediment_line": {
                    "shape": "d50 cvstar coedepo cs",
                    "d50": bj.d50,
                    "cvstar": bj.cvstar,
                    "coedepo": bj.coedepo,
                    "cs": bj.cs,
                },
                "manningbar_variant": bj.dfs_manningbar_variant,
                "face_flux_variant": bj.dfs_face_flux_variant,
                "dry_face_velocity_variant": bj.dfs_dry_face_velocity_variant,
                "artivis_variant": bj.dfs_artivis_variant,
                "absubar_variant": bj.dfs_absubar_variant,
            },
        },
        "compute": {
            "production_path": "Taichi kernels on CUDA (cuda_production_default)",
            "cpu_reference": "same kernels with ti.cpu for对照; not a separate Fortran rewrite",
            "not_raw_cuda_c": True,
        },
        "switches_45": switches,
        "input_families": _file_rows(chamoli),
        "auxiliary_capabilities": [aux_by_key[k] for k in (
            "native_inputs.triggerslide",
            "sidecar.inflow.txt",
            "sidecar.outflow.txt",
            "rheology.debrisflowmanning",
            "rheology.cvlandslide",
            "rheology.cvglacier",
            "extension_flags.simulate_buildings",
        ) if k in aux_by_key],
        "frontend_exposure": {
            "inspector_binding_fields": [
                "dem.primary",
                "zones.primary",
                "slope.primary",
                "thickness.primary",
                "trigger.primary",
                "inflow.primary",
                "outflow.primary",
            ],
            "editable_parameter_keys": sorted(EDITABLE_PARAMETERS),
            "readonly_display_parameter_keys": sorted(READONLY_DISPLAY_PARAMETERS),
            "buildingsimul_registry_policy": "extension_flags only; not a 46th core switch",
        },
        "remaining_gaps": [
            "buildingsimul ARF/WRF is parsed only; Chamoli dfs.F90:58 is not wired",
            "save_max_solid_depth is absent from Chamoli Fortran; Taichi treats null as off",
            "WFS remains fail-closed when debrissimul=F",
            "UNSFIN/LS_Scar active branch remains fail-closed (Chamoli fssimul=F so not in this case)",
            "zone-row porosity is parsed but not a production field",
            "Numerical Chamoli CUDA vs Fortran is not claimed as parity; t=900 absubar Flow_depth max-abs 35.02 m RMSE 0.821, erosion volume ratio 1.72 at t=900 (t=45 ratio 1.001)",
        ],
    }
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
