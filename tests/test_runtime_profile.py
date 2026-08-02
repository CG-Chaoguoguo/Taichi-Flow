from api.services.runtime_profile import (
    DEFAULT_RUNTIME_PROFILE,
    RUNTIME_PROFILES,
    apply_profile_environment,
    resolve_runtime_profile,
    restore_profile_environment,
)
from edda.config.sim_config import ComputeParams


def test_cuda_production_default_profile_is_the_default():
    profile = resolve_runtime_profile(None)

    assert profile.name == DEFAULT_RUNTIME_PROFILE
    assert profile.default_backend == "cuda"
    assert "taichi_cuda_backend" in profile.promoted_defaults
    assert "natural_case_gpu_equivalence_claim" in profile.blocked
    assert "legacy_topoindex_routing_hook" in profile.default_off


def test_compute_params_default_to_cuda():
    assert ComputeParams().backend == "cuda"


def test_profile_environment_uses_taichi_flow_namespace_only():
    env = {"TAICHI_FLOW_RUNTIME_PROFILE": "old"}

    previous = apply_profile_environment(RUNTIME_PROFILES["cuda_production_default"], env)

    assert env["TAICHI_FLOW_RUNTIME_PROFILE"] == "cuda_production_default"
    assert env["TQDM_DISABLE"] == "1"
    assert all(not key.startswith("EDDA_") for key in env)

    restore_profile_environment(previous, env)
    assert env["TAICHI_FLOW_RUNTIME_PROFILE"] == "old"
    assert "TQDM_DISABLE" not in env
