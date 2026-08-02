from __future__ import annotations

from api.services.edda_input_mapper import _annotate_manifest_with_input_source_registry
from api.services.runtime_audit import _source_registry_parameter_entry


def test_inactive_inflow_source_does_not_claim_effective_runtime_activation():
    runtime_input_manifest = {
        "inputs": [
            {
                "family": "inflow.txt",
                "path": "C:\\fake\\inflow.txt",
            }
        ]
    }
    registry = {
        "inflow_source": {
            "family": "inflow.txt",
            "state": "file_backed",
            "selected_source": "inflow_txt",
            "path": "C:\\fake\\inflow.txt",
            "exists_on_disk": True,
            "required_by_flag": False,
            "runtime_active": False,
        }
    }

    _annotate_manifest_with_input_source_registry(runtime_input_manifest, registry)
    inflow_entry = runtime_input_manifest["inputs"][0]
    assert inflow_entry["effective_runtime_source_active"] is False

    audit_entry = _source_registry_parameter_entry(
        "inflow_source",
        registry["inflow_source"],
        consumed=False,
    )
    assert audit_entry["evidence"]["effective_runtime_source_active"] is False
