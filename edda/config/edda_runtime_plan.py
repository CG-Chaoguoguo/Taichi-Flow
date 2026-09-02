"""Immutable runtime view of original EDDA run and output controls.

The parser/API models remain serialization-friendly, while the solver receives
one frozen plan.  A control-free direct API request deliberately stays in the
legacy compatibility path; any request carrying EDDA controls is strict.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from edda.config.sim_config import SimulationConfig


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class EddaRuntimeControlPlan:
    registry_version: str
    source_mode: str
    strict: bool
    run_controls: Mapping[str, Any]
    output_controls: Mapping[str, Any]
    extension_controls: Mapping[str, Any]

    def run_enabled(self, key: str, *, compatibility_default: bool = True) -> bool:
        if key in self.run_controls:
            return bool(self.run_controls[key])
        if self.strict:
            raise KeyError(f"Missing strict EDDA run control: {key}")
        return bool(compatibility_default)

    def output_enabled(self, key: str, *, compatibility_default: bool = True) -> bool:
        if key in self.output_controls:
            return bool(self.output_controls[key])
        if self.strict:
            raise KeyError(f"Missing strict EDDA output control: {key}")
        return bool(compatibility_default)

    def output_value(self, key: str, *, compatibility_default: Any = None) -> Any:
        if key in self.output_controls:
            return self.output_controls[key]
        if self.strict:
            raise KeyError(f"Missing strict EDDA output control: {key}")
        return compatibility_default

    def extension_enabled(self, key: str, *, compatibility_default: bool = False) -> bool:
        if key in self.extension_controls:
            return bool(self.extension_controls[key])
        return bool(compatibility_default)

    def to_dict(self) -> dict[str, Any]:
        def thaw(value: Any) -> Any:
            if isinstance(value, Mapping):
                return {key: thaw(item) for key, item in value.items()}
            if isinstance(value, tuple):
                return [thaw(item) for item in value]
            return value

        return {
            "registry_version": self.registry_version,
            "source_mode": self.source_mode,
            "strict": self.strict,
            "run_controls": thaw(self.run_controls),
            "output_controls": thaw(self.output_controls),
            "extension_controls": thaw(self.extension_controls),
        }


def build_runtime_control_plan(config: SimulationConfig) -> EddaRuntimeControlPlan:
    edda = config.edda
    run_controls = dict(edda.run_controls or {})
    output_controls = dict(edda.output_controls or {})
    extension_controls = dict(edda.extension_controls or {})
    declared_source_mode = str(
        getattr(getattr(config, "native_inputs", None), "source_mode", "") or ""
    )
    has_controls = bool(run_controls or output_controls or extension_controls)
    strict = declared_source_mode == "reference_config" or has_controls
    source_mode = (
        declared_source_mode
        if declared_source_mode
        else "edda_controls"
        if has_controls
        else "direct_api_compatibility"
    )
    return EddaRuntimeControlPlan(
        registry_version=str(edda.registry_version),
        source_mode=source_mode,
        strict=strict,
        run_controls=_freeze(run_controls),
        output_controls=_freeze(output_controls),
        extension_controls=_freeze(extension_controls),
    )
