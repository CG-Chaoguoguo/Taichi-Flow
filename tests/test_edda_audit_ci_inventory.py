"""CI inventory must fail for missing, duplicated or mixed-revision evidence."""
from copy import deepcopy

import pytest

from scripts.edda_audit_ci import partition, validate_manifests


def _complete():
    all_ids = [f"tests/test_a.py::test_{i}" for i in range(8)]
    return [{"index": i, "count": 4, "source_sha": "same-commit",
             "all_nodeids": all_ids, "selected_nodeids": partition(all_ids, i, 4),
             "completed_nodeids": partition(all_ids, i, 4), "exit_code": 0,
             "outcomes": {n: "passed" for n in partition(all_ids, i, 4)}} for i in range(4)]


def test_complete_inventory_covers_all_nodes_exactly_once():
    summary = validate_manifests(_complete(), 4)
    assert summary["collected"] == summary["executed"] == summary["passed"] == 8


@pytest.mark.parametrize("defect", ["missing_shard", "early_stop", "duplicate", "mixed_sha", "failure", "changed_collection"])
def test_inventory_rejects_incomplete_or_misbound_evidence(defect):
    manifests = deepcopy(_complete())
    if defect == "missing_shard":
        manifests.pop()
    elif defect == "early_stop":
        manifests[0]["completed_nodeids"].pop()
    elif defect == "duplicate":
        manifests[0]["completed_nodeids"].append(manifests[0]["completed_nodeids"][0])
    elif defect == "mixed_sha":
        manifests[1]["source_sha"] = "another-commit"
    elif defect == "failure":
        manifests[0]["exit_code"] = 1
    elif defect == "changed_collection":
        manifests[1]["all_nodeids"] = manifests[1]["all_nodeids"][:-1]
    with pytest.raises(ValueError):
        validate_manifests(manifests, 4)


def test_empty_or_duplicate_collection_cannot_pass():
    with pytest.raises(ValueError):
        partition([], 0, 4)
    with pytest.raises(ValueError):
        partition(["same", "same"], 0, 1)
