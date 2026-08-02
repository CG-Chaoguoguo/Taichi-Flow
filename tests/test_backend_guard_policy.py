import numpy as np

from edda.utils.backend_guard_policy import (
    BACKEND_COMPARISON_CONTEXT,
    CPU_REFERENCE_VS_KERNEL_CONTEXT,
    DEFAULT_POLICY_NAME,
    QMASSNET_POLICY_NAME,
    compare_guarded_arrays,
    resolve_guard_tolerance,
    summarize_guarded_comparisons,
)


def test_qmassnet_cpu_cuda_backend_policy_passes_known_drift():
    left = np.array([0.04], dtype=np.float64)
    right = np.array([0.04000000041166004], dtype=np.float64)

    result = compare_guarded_arrays(
        left,
        right,
        field_name="qmassnet_fortran",
        comparison_context=BACKEND_COMPARISON_CONTEXT,
        left_backend="cpu",
        right_backend="cuda",
    )

    assert result["policy_applied"] is True
    assert result["policy_name"] == QMASSNET_POLICY_NAME
    assert result["rtol"] == 1.0e-8
    assert result["atol"] == 1.0e-10
    assert result["tolerance_pass"] is True
    assert result["fail_count"] == 0
    assert result["exact_hash_match"] is False
    assert result["left_sha256"] != result["right_sha256"]


def test_same_qmassnet_drift_fails_default_policy():
    left = np.array([0.04], dtype=np.float64)
    right = np.array([0.04000000041166004], dtype=np.float64)

    result = compare_guarded_arrays(
        left,
        right,
        field_name="qmassnet_fortran",
        comparison_context="unknown_context",
        left_backend="cpu",
        right_backend="cuda",
    )

    assert result["policy_applied"] is False
    assert result["policy_name"] == DEFAULT_POLICY_NAME
    assert result["rtol"] == 1.0e-9
    assert result["atol"] == 1.0e-12
    assert result["tolerance_pass"] is False
    assert result["fail_count"] == 1


def test_qmassnet_cpu_reference_vs_kernel_context_stays_strict():
    tolerance = resolve_guard_tolerance(
        field_name="qmassnet_fortran",
        comparison_context=CPU_REFERENCE_VS_KERNEL_CONTEXT,
        left_backend="cpu",
        right_backend="cuda",
    )

    assert tolerance.policy_applied is False
    assert tolerance.policy_name == DEFAULT_POLICY_NAME
    assert tolerance.rtol == 1.0e-9
    assert tolerance.atol == 1.0e-12


def test_non_qmassnet_field_uses_default_policy_for_cpu_cuda_backend_pair():
    left = np.array([1.0], dtype=np.float64)
    right = np.array([1.00000001], dtype=np.float64)

    result = compare_guarded_arrays(
        left,
        right,
        field_name="h",
        comparison_context=BACKEND_COMPARISON_CONTEXT,
        left_backend="cpu",
        right_backend="cuda",
    )

    assert result["policy_applied"] is False
    assert result["policy_name"] == DEFAULT_POLICY_NAME
    assert result["tolerance_pass"] is False
    assert result["fail_count"] == 1


def test_downstream_default_field_failure_still_fails_gate_summary():
    qmassnet = compare_guarded_arrays(
        np.array([0.04], dtype=np.float64),
        np.array([0.04000000041166004], dtype=np.float64),
        field_name="qmassnet_fortran",
        comparison_context=BACKEND_COMPARISON_CONTEXT,
        left_backend="cpu",
        right_backend="cuda",
    )
    h = compare_guarded_arrays(
        np.array([1.0], dtype=np.float64),
        np.array([1.00000001], dtype=np.float64),
        field_name="h",
        comparison_context=BACKEND_COMPARISON_CONTEXT,
        left_backend="cpu",
        right_backend="cuda",
    )

    summary = summarize_guarded_comparisons({"qmassnet_fortran": qmassnet, "h": h})

    assert summary["all_tolerance_pass"] is False
    assert summary["tolerance_fail_count_total"] == 1
    assert summary["policy_applied_fields"] == ["qmassnet_fortran"]
    assert summary["failed_fields"] == ["h"]
