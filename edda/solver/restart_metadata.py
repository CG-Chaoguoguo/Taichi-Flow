"""Explicit, pickle-free DFS host-state contract for restart checkpoints.

Taichi field discovery cannot capture Python scalars or NumPy schedule state.
This module owns that serialization boundary; it does not change physics or UI.
The same frozen inputs/configuration are still required for continuation.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

import numpy as np

VERSION = 1
PREFIX = "dfs_host__"
SCALARS = {
    "legacy_previous_face_cvbar_scalar": float,
    "slide1": int,
    "isslidetriggered": int,
    "triggerslide_enabled": bool,
    "last_accepted_outflow_dt": float,
    "current_time": float,
}
SCHEDULE_ARRAYS = (
    "precomputed_failure_tfail", "precomputed_failure_gindx",
    "precomputed_failure_fdepth", "precomputed_failure_fired",
)
POLICY_KEYS = {
    "taichi_field_feed_enabled": "rnoff_gpu_field_feed_gate_enabled",
    "source_staging_field_enabled": "dfs_source_staging_field_gate_enabled",
    "source_staging_fast_consume_enabled": "dfs_source_staging_fast_consume_gate_enabled",
    "source_staging_kernel_enabled": "dfs_source_staging_kernel_gate_enabled",
    "source_staging_kernel_required_gates_active": "dfs_source_staging_kernel_required_gates_active",
}


def configuration_digest(config: Any) -> str:
    """Bind numerical configuration, excluding the destination and stop window.

    This identifies configured values, not file contents. Runtime input hashes
    remain the responsibility of the workbench's immutable input revision.
    Backend/precision remain bound; changing them is an explicit experiment,
    not a transparent restart.
    """
    value = config.to_dict()
    value.pop("output_dir", None)
    value.pop("save_intermediate", None)
    value["time"].pop("t_end", None)
    value["time"].pop("dt_output", None)
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def export_dfs_host_state(dfs: Any) -> dict[str, np.ndarray]:
    """Serialize persistent state at an attempt boundary, without pickle."""
    if dfs._ci_candidate is not None or dfs._precomputed_failure_candidate_cell_count:
        raise ValueError("Checkpoint requires a completed attempt, not a staged candidate")
    arrays = {
        PREFIX + "version": np.asarray(VERSION, dtype=np.int64),
        PREFIX + "config_sha256": np.asarray(configuration_digest(dfs.config)),
    }
    for name, cast in SCALARS.items():
        value = cast(getattr(dfs, name))
        if not np.isfinite(value):
            raise ValueError(f"Non-finite checkpoint host state: {name}")
        arrays[PREFIX + name] = np.asarray(value)
    present = [getattr(dfs, name) is not None for name in SCHEDULE_ARRAYS]
    if any(present) and not all(present):
        raise ValueError("Incomplete precomputed failure schedule in checkpoint source")
    arrays[PREFIX + "has_schedule"] = np.asarray(all(present), dtype=np.int8)
    if all(present):
        for name in SCHEDULE_ARRAYS:
            arrays[PREFIX + name] = np.asarray(getattr(dfs, name)).copy()
        policy = {key: bool(dfs.precomputed_failure_schedule_info.get(info_key, False))
                  for key, info_key in POLICY_KEYS.items()}
        arrays[PREFIX + "schedule_policy"] = np.asarray(json.dumps(policy, sort_keys=True))
    return arrays


def _scalar(checkpoint: Mapping[str, Any], name: str) -> Any:
    key = PREFIX + name
    if key not in checkpoint:
        raise ValueError(f"Incomplete DFS checkpoint: missing {key}")
    value = np.asarray(checkpoint[key])
    if value.shape != ():
        raise ValueError(f"DFS checkpoint scalar {key} has shape {value.shape}")
    return value.item()


def validate_dfs_host_state(dfs: Any, checkpoint: Mapping[str, Any]) -> dict[str, Any]:
    """Read and validate all host metadata BEFORE mutating any live field."""
    if PREFIX + "version" not in checkpoint:
        raise ValueError(
            "Incomplete legacy DFS checkpoint: retry cv, face cvbar and trigger "
            "state are not guaranteed. Regenerate with the audited solver; "
            "an old checkpoint cannot establish trajectory parity."
        )
    if _scalar(checkpoint, "version") != VERSION:
        raise ValueError("Unsupported DFS checkpoint host-state version")
    if _scalar(checkpoint, "config_sha256") != configuration_digest(dfs.config):
        raise ValueError("DFS checkpoint numerical configuration does not match the initialized solver")
    state: dict[str, Any] = {}
    for name, cast in SCALARS.items():
        raw = _scalar(checkpoint, name)
        if not isinstance(raw, (bool, int, float)) or not np.isfinite(raw):
            raise ValueError(f"Invalid DFS checkpoint host scalar {name}")
        if cast in (int, bool) and raw not in (0, 1):
            raise ValueError(f"Invalid DFS checkpoint flag {name}: {raw}")
        state[name] = cast(raw)
    if state["last_accepted_outflow_dt"] < 0:
        raise ValueError("Negative accepted outflow timestep in DFS checkpoint")
    for name in ("source_cv_carry", "source_cv_carry_valid"):
        key = "dfs__" + name
        if key not in checkpoint or np.asarray(checkpoint[key]).shape != (dfs.fields.nx, dfs.fields.ny):
            raise ValueError(f"Missing or incompatible DFS retry state: {key}")
    has_schedule = _scalar(checkpoint, "has_schedule")
    if has_schedule not in (0, 1):
        raise ValueError("Invalid DFS checkpoint schedule-presence flag")
    state["has_schedule"] = bool(has_schedule)
    if has_schedule:
        shape = (dfs.fields.nx, dfs.fields.ny)
        for name in SCHEDULE_ARRAYS:
            key = PREFIX + name
            if key not in checkpoint:
                raise ValueError(f"Incomplete DFS checkpoint schedule: {name}")
            array = np.asarray(checkpoint[key])
            if array.shape != shape or array.dtype.kind not in "bifu" or not np.all(np.isfinite(array)):
                raise ValueError(f"Invalid DFS checkpoint schedule array: {name}")
            if name.endswith(("gindx", "fired")) and not np.all(np.isin(array, (0, 1))):
                raise ValueError(f"Invalid DFS checkpoint schedule mask: {name}")
            if name.endswith("fdepth") and np.any(array < 0):
                raise ValueError("Negative failure depth in DFS checkpoint")
            state[name] = array.copy()
        policy = json.loads(_scalar(checkpoint, "schedule_policy"))
        if not isinstance(policy, dict) or set(policy) != set(POLICY_KEYS) or any(
                type(value) is not bool for value in policy.values()):
            raise ValueError("Invalid DFS checkpoint schedule policy")
        state["schedule_policy"] = policy
    elif dfs.precomputed_failure_fired is not None:
        raise ValueError("DFS checkpoint has no schedule but initialized solver has one")
    return state


def restore_dfs_host_state(dfs: Any, state: Mapping[str, Any]) -> None:
    """Allocate optional schedule fields before the caller restores Ti arrays."""
    if state["has_schedule"]:
        dfs.configure_precomputed_failure_schedule(
            tfail_s=state["precomputed_failure_tfail"],
            gindx=state["precomputed_failure_gindx"],
            fdepth_m=state["precomputed_failure_fdepth"],
            **state["schedule_policy"],
        )
        dfs.precomputed_failure_fired = state["precomputed_failure_fired"].astype(bool, copy=True)
        fired = int(np.count_nonzero(dfs.precomputed_failure_fired))
        dfs.precomputed_failure_schedule_info.update(fired_cell_count=fired, committed_fired_count=fired)
        if dfs.precomputed_failure_committed_fire_mask_field is not None:
            dfs.precomputed_failure_committed_fire_mask_field.from_numpy(
                dfs.precomputed_failure_fired.astype(np.int32)
            )
        dfs._discard_precomputed_failure_candidate()
    for name in SCALARS:
        setattr(dfs, name, state[name])
    # Cached host markers must be re-read from the restored Ti scalar fields.
    dfs._persistent_source_state_seeded = False
    dfs._rholimit_seeded = False
    dfs._legacy_previous_face_cvbar_origin = None
