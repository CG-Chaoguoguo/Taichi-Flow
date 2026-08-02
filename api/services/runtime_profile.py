"""Typed runtime profiles for Taichi Flow service runs."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, MutableMapping, Optional


DEFAULT_RUNTIME_PROFILE = "cuda_production_default"


@dataclass(frozen=True)
class RuntimeProfile:
    """Evidence-gated runtime defaults applied before solver construction."""

    name: str
    class_name: str
    default_backend: str
    description: str
    promoted_defaults: List[str] = field(default_factory=list)
    default_off: List[str] = field(default_factory=list)
    diagnostic_only: List[str] = field(default_factory=list)
    blocked: List[str] = field(default_factory=list)
    environment: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["is_default"] = self.name == DEFAULT_RUNTIME_PROFILE
        return payload


RUNTIME_PROFILES: Dict[str, RuntimeProfile] = {
    "edda_taichi_cuda_candidate": RuntimeProfile(
        name="edda_taichi_cuda_candidate",
        class_name="parity",
        default_backend="cuda",
        description=(
            "EDDA-Taichi CUDA candidate parity profile. This mirrors the "
            "environment gates used by tools/run_cuda_candidate_case.py so "
            "frontend-driven Taichi Flow runs can be compared against the "
            "EDDA-Taichi backend harness without changing solver equations."
        ),
        promoted_defaults=[
            "taichi_cuda_backend",
            "service_layer_native_input_manifest",
            "runtime_metadata_bundle",
            "output_manifest_bundle",
            "native_schedule_feed",
            "predictor_mutation_chain",
            "h_cv_rho_mutation_chain",
        ],
        environment={
            "TQDM_DISABLE": "1",
            "TAICHI_FLOW_RUNTIME_PROFILE": "edda_taichi_cuda_candidate",
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
        },
    ),
    "cuda_production_default": RuntimeProfile(
        name="cuda_production_default",
        class_name="production",
        default_backend="cuda",
        description=(
            "Default Taichi Flow runtime. CUDA is selected by default; only "
            "evidence-gated production behavior is enabled. Candidate and "
            "diagnostic mutation chains remain inactive."
        ),
        promoted_defaults=[
            "taichi_cuda_backend",
            "service_layer_native_input_manifest",
            "runtime_metadata_bundle",
            "output_manifest_bundle",
        ],
        default_off=[
            "legacy_stormdrain_hook",
            "legacy_topoindex_routing_hook",
            "native_schedule_feed",
            "predictor_mutation_chain",
            "h_cv_rho_mutation_chain",
        ],
        diagnostic_only=[
            "source_chain_diagnostics",
            "backend_guard_replay",
            "candidate_kernel_diagnostics",
        ],
        blocked=[
            "natural_case_gpu_equivalence_claim",
            "unsupported_output_flag_control",
            "unverified_frontend_parameter_exposure",
        ],
        environment={
            "TQDM_DISABLE": "1",
            "TAICHI_FLOW_RUNTIME_PROFILE": "cuda_production_default",
        },
    ),
    "compat_default_off": RuntimeProfile(
        name="compat_default_off",
        class_name="compatibility",
        default_backend="cpu",
        description=(
            "Compatibility profile for regression and parser work. Optional "
            "legacy hooks stay off unless an internal test explicitly enables "
            "them."
        ),
        default_off=[
            "legacy_stormdrain_hook",
            "legacy_topoindex_routing_hook",
            "native_schedule_feed",
        ],
        environment={
            "TQDM_DISABLE": "1",
            "TAICHI_FLOW_RUNTIME_PROFILE": "compat_default_off",
        },
    ),
    "diagnostic_only": RuntimeProfile(
        name="diagnostic_only",
        class_name="diagnostic",
        default_backend="cpu",
        description="Diagnostic profile for audit scripts; not a production runtime.",
        diagnostic_only=["all_explicit_diagnostic_tools"],
        blocked=["production_run_claim"],
        environment={
            "TQDM_DISABLE": "1",
            "TAICHI_FLOW_RUNTIME_PROFILE": "diagnostic_only",
        },
    ),
    "blocked": RuntimeProfile(
        name="blocked",
        class_name="blocked",
        default_backend="cpu",
        description="Marker profile used to report unsupported runtime requests.",
        blocked=["all_runtime_execution"],
    ),
}


def resolve_runtime_profile(name: Optional[str]) -> RuntimeProfile:
    """Resolve a profile name, defaulting to the CUDA production profile."""
    requested = (name or DEFAULT_RUNTIME_PROFILE).strip()
    profile = RUNTIME_PROFILES.get(requested)
    if profile is None:
        raise ValueError(f"Unsupported runtime_profile: {requested}")
    if profile.name == "blocked":
        raise ValueError("runtime_profile 'blocked' cannot be used to start a run")
    return profile


def apply_profile_environment(
    profile: RuntimeProfile,
    environ: Optional[MutableMapping[str, str]] = None,
) -> Dict[str, Optional[str]]:
    """
    Apply profile environment values and return the previous values.

    This intentionally sets only Taichi Flow profile variables and neutral
    progress-bar behavior. It does not enable legacy experimental gates.
    """
    import os

    target = os.environ if environ is None else environ
    previous: Dict[str, Optional[str]] = {}
    for key, value in profile.environment.items():
        previous[key] = target.get(key)
        target[key] = value
    return previous


def restore_profile_environment(
    previous: Dict[str, Optional[str]],
    environ: Optional[MutableMapping[str, str]] = None,
) -> None:
    """Restore values captured by apply_profile_environment."""
    import os

    target = os.environ if environ is None else environ
    for key, value in previous.items():
        if value is None:
            target.pop(key, None)
        else:
            target[key] = value


def runtime_profiles_catalog() -> Dict[str, Any]:
    return {
        "default_profile": DEFAULT_RUNTIME_PROFILE,
        "profiles": {name: profile.to_dict() for name, profile in RUNTIME_PROFILES.items()},
    }
