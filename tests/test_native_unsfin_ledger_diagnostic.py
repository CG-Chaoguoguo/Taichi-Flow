from __future__ import annotations

import json

import numpy as np

from tools.diagnostics.native_unsfin_ledger_diagnostic import (
    NATIVE_PROVENANCE,
    build_native_blocked_ledger,
    compare_ledgers,
    load_original_oracle,
)


def test_native_unsfin_blocked_ledger_does_not_copy_oracle_values():
    native = build_native_blocked_ledger((3,))

    assert native.meta["source_provenance"] == NATIVE_PROVENANCE
    assert native.meta["runtime_provider_enabled"] is False
    assert native.meta["output_inferred"] is False
    assert native.meta["dfs_runtime_modified"] is False
    assert native.meta["parse_status"] == "blocked"
    assert np.count_nonzero(native.gindx) == 0
    assert np.count_nonzero(np.isfinite(native.tfail_s)) == 0
    assert np.count_nonzero(native.fdepth_m) == 0


def test_native_unsfin_comparison_reports_blocked_no_overlap():
    original = build_native_blocked_ledger((4,))
    original = original.__class__(
        gindx=np.array([1, 1, 0, 1], dtype=np.int32),
        tfail_s=np.array([10.0, 600.0, -9999.0, 700.0], dtype=np.float64),
        fdepth_m=np.array([3.0, 3.0, 0.0, 3.0], dtype=np.float64),
        fsdepth_m=None,
        meta={"source_provenance": "original_unsfin_memory_dump"},
    )
    native = build_native_blocked_ledger((4,))

    metrics = compare_ledgers(native, original)

    assert metrics["native_parse_status"] == "blocked"
    assert metrics["gindx"]["positive_count_original"] == 3
    assert metrics["gindx"]["positive_count_native"] == 0
    assert metrics["gindx"]["false_negatives"] == 3
    assert metrics["gindx"]["recall"] == 0.0
    assert metrics["tfail"]["positive_count_original"] == 3
    assert metrics["tfail"]["positive_overlap_count"] == 0
    assert metrics["candidate_windows"]["0_600_s"]["original_positive_tfail_count"] == 2
    assert metrics["candidate_windows"]["0_600_s"]["native_positive_tfail_count"] == 0


def test_original_unsfin_oracle_loader_rejects_output_inferred_meta(tmp_path):
    np.save(tmp_path / "precomputed_unsfin_gindx.npy", np.array([1], dtype=np.int32))
    np.save(tmp_path / "precomputed_unsfin_tfail.npy", np.array([1.0], dtype=np.float64))
    np.save(tmp_path / "precomputed_unsfin_fdepth.npy", np.array([3.0], dtype=np.float64))
    (tmp_path / "precomputed_unsfin_meta.json").write_text(
        json.dumps(
            {
                "provider": "original_instrumented_unsfin",
                "shape_kind": "active_cell_vector",
                "notes": "derived from faildph",
            }
        ),
        encoding="utf-8",
    )

    try:
        load_original_oracle(tmp_path)
    except ValueError as exc:
        assert "output-inference" in str(exc)
    else:
        raise AssertionError("expected output-inference metadata to be rejected")
