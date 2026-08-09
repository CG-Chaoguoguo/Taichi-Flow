"""Canonical, versioned registry for the 45 switches in original EDDA 1.5.

The registry is the only ordered definition of the core ``edda_in.txt``
switch contract.  Parsers, API catalogues, runtime ledgers and the frontend
consume this module instead of maintaining independent flag lists.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from types import MappingProxyType
from typing import Any, Dict, Iterable, Mapping, Tuple


REGISTRY_VERSION = "1.0.0"
ALLOWED_STATUSES = frozenset(
    {
        "production_consumed",
        "config_fallback_consumed",
        "parsed_only",
        "mapped_only",
        "metadata_only",
        "partial",
        "unsupported",
        "blocked",
    }
)

COMMON_AUDIT = "artifact-id:2026-08-07_edda_switch_backend_parity"


@dataclass(frozen=True)
class EddaSwitchSpec:
    key: str
    source_index: int
    group: str
    value_type: str
    allowed_values: Tuple[Any, ...]
    original_variable: str
    fortran_read_location: str
    fortran_runtime_consumer: str
    activation_condition: str
    taichi_parser_field: str
    taichi_config_path: str
    taichi_runtime_consumer: str
    real_case_activation_evidence: str
    test_or_audit_artifact: str
    consumption_stage: str
    dependencies: Tuple[str, ...]
    affected_output_families: Tuple[str, ...]
    frontend_policy: str
    status: str
    status_reason: str
    original_semantics: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EddaSwitchValue:
    key: str
    source_index: int
    raw_value: Any
    effective_value: Any
    source: str

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["raw_value"] = _thaw_value(self.raw_value)
        payload["effective_value"] = _thaw_value(self.effective_value)
        return payload


@dataclass(frozen=True)
class EddaSwitchSnapshot:
    registry_version: str
    entries: Tuple[EddaSwitchValue, ...]

    @property
    def values(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {entry.key: _thaw_value(entry.effective_value) for entry in self.entries}
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "registry_version": self.registry_version,
            "entries": [entry.to_dict() for entry in self.entries],
            "values": dict(self.values),
        }


def _freeze_value(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, dict):
        return tuple((key, _freeze_value(item)) for key, item in value.items())
    return value


def _thaw_value(value: Any) -> Any:
    if isinstance(value, tuple):
        if value and all(isinstance(item, tuple) and len(item) == 2 for item in value):
            return {key: _thaw_value(item) for key, item in value}
        return [_thaw_value(item) for item in value]
    return value


def _frontend_policy(status: str) -> str:
    return "editable" if status in {"production_consumed", "config_fallback_consumed"} else "read_only"


def _spec(
    index: int,
    key: str,
    *,
    group: str,
    original_variable: str,
    read_line: str,
    original_consumer: str,
    activation: str,
    runtime_consumer: str,
    evidence: str,
    stage: str,
    status: str,
    reason: str,
    original_semantics: str,
    outputs: Iterable[str] = (),
    dependencies: Iterable[str] = (),
    value_type: str = "boolean",
    allowed_values: Iterable[Any] = (False, True),
) -> EddaSwitchSpec:
    config_group = "output_controls" if group in {"legacy_output", "process_output"} else "run_controls"
    return EddaSwitchSpec(
        key=key,
        source_index=index,
        group=group,
        value_type=value_type,
        allowed_values=tuple(allowed_values),
        original_variable=original_variable,
        fortran_read_location=f"trini.f90:{read_line}",
        fortran_runtime_consumer=original_consumer,
        activation_condition=activation,
        taichi_parser_field=f"flags.{key}",
        taichi_config_path=f"edda.{config_group}.{key}",
        taichi_runtime_consumer=runtime_consumer,
        real_case_activation_evidence=f"edda_in.txt:{evidence}",
        test_or_audit_artifact=COMMON_AUDIT,
        consumption_stage=stage,
        dependencies=tuple(dependencies),
        affected_output_families=tuple(outputs),
        frontend_policy=_frontend_policy(status),
        status=status,
        status_reason=reason,
        original_semantics=original_semantics,
    )


EDDA_SWITCH_REGISTRY: Tuple[EddaSwitchSpec, ...] = (
    # Original legacy output/list controls, edda_in.txt lines 133-160.
    _spec(1, "save_runoff_grids", group="legacy_output", original_variable="rodoc", read_line="238", original_consumer="rnoff.F90 runoff-period writer", activation="rodoc is true during RNOFF preprocessing", runtime_consumer="RNOFF production output gate not yet closed", evidence="133-134 value F", stage="preprocess_output", status="unsupported", reason="Original runoff-grid writer is not implemented as a production result family.", original_semantics="active_output_gate", outputs=("runoff_*",)),
    _spec(2, "save_fs_min_legacy", group="legacy_output", original_variable="outp(3)", read_line="243", original_consumer="No active consumer located in the exact BJ_HXL source beyond read/log", activation="Pending paired original counterfactual", runtime_consumer="parser snapshot only", evidence="135-136 value T", stage="metadata", status="parsed_only", reason="Source-read-only candidate pending the required original counterfactual run.", original_semantics="no_op_candidate", outputs=("fs_min_legacy_*",)),
    _spec(3, "save_fs_depth_at_min", group="legacy_output", original_variable="outp(4)", read_line="247", original_consumer="No active consumer located in the exact BJ_HXL source beyond read/log", activation="Pending paired original counterfactual", runtime_consumer="parser snapshot only", evidence="137-138 value T", stage="metadata", status="parsed_only", reason="Source-read-only candidate pending counterfactual verification.", original_semantics="no_op_candidate", outputs=("depth_at_fs_min_*",)),
    _spec(4, "save_fs_pore_pressure_at_min", group="legacy_output", original_variable="outp(5)", read_line="252", original_consumer="No active consumer located in the exact BJ_HXL source beyond read/log", activation="Pending paired original counterfactual", runtime_consumer="parser snapshot only", evidence="139-140 value F", stage="metadata", status="parsed_only", reason="Source-read-only candidate pending counterfactual verification.", original_semantics="no_op_candidate", outputs=("p_at_fs_min_*",)),
    _spec(5, "save_infiltration_rate", group="legacy_output", original_variable="outp(6)", read_line="257", original_consumer="rnoff.F90 gates CTinfilratPer/TRinfilratPer", activation="outp(6) is true during RNOFF", runtime_consumer="experimental RNOFF provider only", evidence="141-142 value F", stage="preprocess_output", status="partial", reason="Original active gate is traced but production RNOFF output parity is not closed.", original_semantics="active_output_gate", outputs=("actual_infiltration_rate_*",)),
    _spec(6, "save_basal_flux", group="legacy_output", original_variable="outp(7)", read_line="262", original_consumer="No active consumer located in the exact BJ_HXL source beyond read/log", activation="Pending paired original counterfactual", runtime_consumer="parser snapshot only", evidence="143-144 value F", stage="metadata", status="parsed_only", reason="Source-read-only candidate pending counterfactual verification.", original_semantics="no_op_candidate", outputs=("basal_flux_*",)),
    _spec(7, "save_deposit_distribution", group="legacy_output", original_variable="depositsave", read_line="268", original_consumer="No active consumer located in exact BJ_HXL runtime source", activation="Pending paired original counterfactual", runtime_consumer="parser snapshot only", evidence="145-146 value T", stage="metadata", status="parsed_only", reason="Legacy deposit-distribution flag is not yet tied to a source-backed writer.", original_semantics="no_op_candidate", outputs=("deposit_distribution_*",)),
    _spec(8, "save_pf", group="legacy_output", original_variable="pfsave", read_line="275", original_consumer="No active consumer located in exact BJ_HXL runtime source", activation="Pending paired original counterfactual", runtime_consumer="parser snapshot only", evidence="147-148 value F", stage="metadata", status="parsed_only", reason="Probability-of-failure writer is absent and original activity remains to be disproved by paired run.", original_semantics="no_op_candidate", outputs=("pf_at_fs_min_*",)),
    _spec(9, "save_road_risk", group="legacy_output", original_variable="risksave", read_line="281", original_consumer="No active consumer located in exact BJ_HXL runtime source", activation="Pending paired original counterfactual", runtime_consumer="parser snapshot only", evidence="149-150 value F", stage="metadata", status="parsed_only", reason="Road-risk branch is source-read-only in the visible case source.", original_semantics="no_op_candidate", outputs=("road_risk_*",)),
    _spec(10, "save_road_warning", group="legacy_output", original_variable="warninglevelsave", read_line="288", original_consumer="No active consumer located in exact BJ_HXL runtime source", activation="Pending paired original counterfactual", runtime_consumer="parser snapshot only", evidence="151-152 value F", stage="metadata", status="parsed_only", reason="Road-warning branch is source-read-only in the visible case source.", original_semantics="no_op_candidate", outputs=("road_warning_*",)),
    _spec(11, "save_detached_trace", group="legacy_output", original_variable="tracesave", read_line="294", original_consumer="No active consumer located in exact BJ_HXL runtime source", activation="Pending paired original counterfactual", runtime_consumer="parser snapshot only", evidence="153-154 value F", stage="metadata", status="parsed_only", reason="Detached-trace branch is source-read-only in the visible case source.", original_semantics="no_op_candidate", outputs=("detached_trace_*",)),
    _spec(12, "pressure_head_fs_listing_flag", group="legacy_output", original_variable="flag", read_line="301", original_consumer="unsfin.F90:48-55 listing-header gate", activation="flag equals -2 or -1", runtime_consumer="reference listing metadata only", evidence="155-156 value -1", stage="preprocess_output", status="partial", reason="The original header gate is traced; full listing output parity is not implemented.", original_semantics="active_listing_gate", outputs=("list_z_p_fs_*",), value_type="integer", allowed_values=(-2, -1, 0)),
    _spec(13, "slope_failure_output_count", group="legacy_output", original_variable="nout", read_line="307", original_consumer="No post-initialization consumer of nout/ksav located in exact source", activation="Pending paired original counterfactual", runtime_consumer="parser snapshot only", evidence="157-158 value 1", stage="metadata", status="parsed_only", reason="Schedule count is allocated/read but no active runtime consumer is visible.", original_semantics="no_op_candidate", value_type="integer", allowed_values=()),
    _spec(14, "slope_failure_output_times_s", group="legacy_output", original_variable="tsav(:)", read_line="315", original_consumer="No post-initialization consumer of tsav located in exact source", activation="Pending paired original counterfactual", runtime_consumer="parser snapshot only", evidence="159-160 value [3600]", stage="metadata", status="parsed_only", reason="Schedule values are read/clamped but no active runtime consumer is visible.", original_semantics="no_op_candidate", value_type="number_array", allowed_values=()),

    # User controls, edda_in.txt lines 161-174.
    _spec(15, "skip_other_timesteps", group="run_control", original_variable="lskip", read_line="325", original_consumer="No active consumer located beyond read/log", activation="Pending paired original counterfactual", runtime_consumer="parser snapshot only", evidence="161-162 value F", stage="metadata", status="parsed_only", reason="Original source-read-only candidate; no Taichi behavior is invented.", original_semantics="no_op_candidate"),
    _spec(16, "use_analytic_fillable_porosity", group="run_control", original_variable="lany", read_line="331", original_consumer="No active consumer located beyond read/log", activation="Pending paired original counterfactual", runtime_consumer="parser snapshot only", evidence="163-164 value T", stage="metadata", status="parsed_only", reason="Original source-read-only candidate; no Taichi behavior is invented.", original_semantics="no_op_candidate"),
    _spec(17, "estimate_positive_pressure_head", group="run_control", original_variable="llus", read_line="337", original_consumer="No active consumer located beyond read/log", activation="Pending paired original counterfactual", runtime_consumer="parser snapshot only", evidence="165-166 value T", stage="metadata", status="parsed_only", reason="Original source-read-only candidate; no Taichi behavior is invented.", original_semantics="no_op_candidate"),
    _spec(18, "use_psi0_negative_inverse_alpha", group="run_control", original_variable="lps0", read_line="343", original_consumer="No active consumer located beyond read/log", activation="Pending paired original counterfactual", runtime_consumer="parser snapshot only", evidence="167-168 value F", stage="metadata", status="parsed_only", reason="Original source-read-only candidate; no Taichi behavior is invented.", original_semantics="no_op_candidate"),
    _spec(19, "log_mass_balance_results", group="run_control", original_variable="outp(8)", read_line="349", original_consumer="No active consumer located beyond read/log", activation="Pending paired original counterfactual", runtime_consumer="structured audit metadata only", evidence="169-170 value T", stage="metadata", status="metadata_only", reason="Taichi emits audit metadata, not an invented EDDALog behavior; original no-op status still needs paired confirmation.", original_semantics="no_op_candidate"),
    _spec(20, "flow_direction_mode", group="run_control", original_variable="flowdir", read_line="355", original_consumer="No active consumer located beyond read/log; flodir is called independently", activation="Pending paired original counterfactual", runtime_consumer="parser snapshot only", evidence="171-172 value slope", stage="metadata", status="parsed_only", reason="Current connectivity cannot expose a mode switch without an original active consumer.", original_semantics="no_op_candidate", value_type="enum", allowed_values=("gener", "slope", "hydro")),
    _spec(21, "background_flux_offset", group="run_control", original_variable="bkgrof", read_line="362", original_consumer="unsfin.F90:108 and RNOFF infiltration contract", activation="bkgrof is true during UNSFIN/RNOFF infiltration", runtime_consumer="immutable runtime plan -> DFS/native UNSFIN provider; direct compatibility falls back to SimulationConfig.hydrology", evidence="173-174 value T", stage="preprocess_and_timestep", status="production_consumed", reason="Original active source trace and current runtime consumer are both present.", original_semantics="active_run_control"),

    # Process controls, edda_in.txt lines 182-203.
    _spec(22, "use_full_dynamic_wave", group="run_control", original_variable="fulldyna", read_line="395", original_consumer="No active branch consumer located in exact BJ_HXL source", activation="Pending paired original counterfactual", runtime_consumer="fixed DFS metadata only", evidence="182-183 value T", stage="metadata", status="parsed_only", reason="Exact source reads/logs the value but does not switch equations; no diffusive-wave behavior is invented.", original_semantics="no_op_candidate"),
    _spec(23, "simulate_rainfall", group="run_control", original_variable="rainsimul", read_line="402", original_consumer="dfs.F90:231 and wfs.F90:113 rainfall staging", activation="rainsimul is true", runtime_consumer="immutable runtime plan -> EDDASolver rainfall update and DFS rainfall source staging", evidence="184-185 value T", stage="forcing_staging", status="production_consumed", reason="The DFS true/off branches consume the frozen control and preserve source order; unsupported WFS is admitted separately.", original_semantics="active_run_control"),
    _spec(24, "simulate_infiltration", group="run_control", original_variable="infilsimul", read_line="409", original_consumer="main/DFS infiltration and double-layer staging", activation="infilsimul is true", runtime_consumer="immutable runtime plan -> DFS Green-Ampt or zero-infiltration mass staging", evidence="186-187 value T", stage="forcing_staging", status="production_consumed", reason="The false branch fixes ir=0 while retaining rainfall/inflow mass; the active branch keeps the existing accepted-step infiltration path.", original_semantics="active_run_control"),
    _spec(25, "simulate_inflow_hydrograph", group="run_control", original_variable="inflowsimul", read_line="416", original_consumer="main:438; dfs.F90:253; wfs.F90:135", activation="inflowsimul is true and inflow.txt exists", runtime_consumer="native inflow sidecar loader and DFS staging", evidence="188-189 value F", stage="forcing_staging", status="partial", reason="Supported DFS forcing exists; branch/reporting parity remains incomplete.", original_semantics="active_run_control"),
    _spec(26, "simulate_outflow_cell", group="run_control", original_variable="outflowsimul", read_line="423", original_consumer="main:440; dfs.F90:140 and accepted-step outflow branch", activation="outflowsimul is true and outflow.txt exists", runtime_consumer="dedicated dfs_outflow_mask -> accepted predictor sample/clear -> outer observer", evidence="190-191 value T", stage="accepted_step", status="production_consumed", reason="The sidecar is isolated from generic boundaries; pre-clear samples commit only after step acceptance and drive OUTNQ.", original_semantics="active_run_control", outputs=("OUTNQ_*",)),
    _spec(27, "simulate_shallow_landslide", group="run_control", original_variable="fssimul", read_line="430", original_consumer="main:488 UNSFIN and failure-source merge", activation="fssimul is true", runtime_consumer="immutable plan gates DFS failure staging; dynamic preflight requires an active UNSFIN schedule", evidence="192-193 value T", stage="preprocess_and_forcing", status="partial", reason="The off branch is closed, but the exact BJ active branch remains fail-closed until a validated UNSFIN schedule is configured.", original_semantics="active_run_control", outputs=("LS_Scar_*", "faildph_*")),
    _spec(28, "simulate_debris_flow", group="run_control", original_variable="debrissimul", read_line="437", original_consumer="main:527 selects DFS else WFS", activation="true selects DFS; false selects WFS", runtime_consumer="strict true selects DFS; strict false is rejected before initialization because WFS is unavailable", evidence="194-195 value T", stage="solver_selection", status="partial", reason="The active BJ DFS selection is explicit; the original WFS branch remains unsupported and fail-closed.", original_semantics="active_branch_selector"),
    _spec(29, "simulate_erosion", group="run_control", original_variable="erosionsimul", read_line="444", original_consumer="dfs.F90:392 and output gate :1393", activation="erosionsimul is true", runtime_consumer="immutable plan gates DFS erosion rate/candidate staging and the compound writer", evidence="196-197 value T", stage="forcing_staging", status="production_consumed", reason="The independent DFS off branch zeros erosion rates/candidates and the output family consumes the same control.", original_semantics="active_run_control", outputs=("Erosion_depth_*",)),
    _spec(30, "simulate_water_and_solid_separately", group="run_control", original_variable="sepdepositionsimul", read_line="451", original_consumer="dfs.F90:469 and deposition/total output gates", activation="sepdepositionsimul is true", runtime_consumer="immutable plan gates separate deposition rate/candidate staging and compound writers", evidence="198-199 value T", stage="forcing_staging", status="production_consumed", reason="The independent DFS off branch zeros separate-deposition candidates; deposition and total writers consume the same gate.", original_semantics="active_run_control", outputs=("Deposit_depth_*", "Total_depth_*")),
    _spec(31, "simulate_drainage_flow", group="run_control", original_variable="dwsimul", read_line="459", original_consumer="main:344/504; dfs.F90:1060/1186; dwflow.f90", activation="dwsimul is true and drainage topology exists", runtime_consumer="default-off experimental stormdrain hook", evidence="200-201 value F", stage="accepted_step", status="partial", reason="Source-backed hook exists but is not a default production branch.", original_semantics="active_run_control", outputs=("dw_nodal_flow.txt", "dw_conduit_flow.txt")),
    _spec(32, "simulate_barrier", group="run_control", original_variable="barriersimul", read_line="466", original_consumer="main:292 barrier load; UNSFIN skip and DFS face/barrier flux", activation="barriersimul is true and flexible/rigid assets exist", runtime_consumer="no complete parser-to-runtime barrier chain", evidence="202-203 value F", stage="pre_connectivity_and_flux", status="unsupported", reason="Barrier assets and runtime semantics are not yet wired end to end.", original_semantics="active_run_control"),

    # Whole-process output controls, edda_in.txt lines 204-229.
    _spec(33, "save_fs_min_grid", group="process_output", original_variable="fsminsave", read_line="473", original_consumer="dfs.F90:1309/1327 writes LS_Scar and faildph", activation="fsminsave is true", runtime_consumer="strict periodic writer gate using configured failure gindx/fdepth when available", evidence="204-205 value T", stage="periodic_output", status="partial", reason="The writer gate is closed, but exact BJ gindx/fdepth production evidence depends on the still-blocked UNSFIN schedule.", original_semantics="active_output_gate", outputs=("LS_Scar_*", "faildph_*"), dependencies=("simulate_shallow_landslide",)),
    _spec(34, "save_flow_depth", group="process_output", original_variable="flowdepthsave", read_line="480", original_consumer="DFS/WFS periodic Flow_depth writer", activation="flowdepthsave is true", runtime_consumer="strict periodic EDDA text writer gate independent of generic GeoTIFF output", evidence="206-207 value T", stage="periodic_output", status="production_consumed", reason="The family consumes its own frozen control and committed flow depth at each output boundary.", original_semantics="active_output_gate", outputs=("Flow_depth_*",)),
    _spec(35, "save_max_flow_depth", group="process_output", original_variable="maxflowdepthsave", read_line="487", original_consumer="DFS/WFS accepted-step maxfh and periodic writer", activation="maxflowdepthsave is true", runtime_consumer="accepted-step max_flow_depth field -> strict periodic writer", evidence="208-209 value T", stage="accepted_step_and_output", status="production_consumed", reason="The writer reads the monotonic accepted-step maximum and consumes the independent output control.", original_semantics="active_output_gate", outputs=("Max_flow_depth_*",)),
    _spec(36, "save_flow_velocity", group="process_output", original_variable="fvsave", read_line="494", original_consumer="DFS/WFS periodic scalar writer: 0.5*sum(abs(fv(1:4)))", activation="fvsave is true", runtime_consumer="strict periodic scalar EDDA velocity writer from the first four directional faces", evidence="210-211 value T", stage="periodic_output", status="production_consumed", reason="The scalar original writer formula and independent family gate are both consumed.", original_semantics="active_output_gate", outputs=("Flow_velocity_*",)),
    _spec(37, "save_max_flow_velocity", group="process_output", original_variable="maxfvsave", read_line="501", original_consumer="DFS/WFS accepted-step maxfv and periodic writer", activation="maxfvsave is true", runtime_consumer="accepted-step max_flow_velocity field -> strict periodic writer", evidence="212-213 value T", stage="accepted_step_and_output", status="production_consumed", reason="The writer reads the monotonic accepted-step maximum and consumes the independent output control.", original_semantics="active_output_gate", outputs=("Max_flow_velocity_*",)),
    _spec(38, "save_erosion_depth", group="process_output", original_variable="erodepthsave", read_line="508", original_consumer="dfs.F90:1393 requires erosionsimul and erodepthsave", activation="simulate_erosion and save_erosion_depth are true", runtime_consumer="compound immutable run/output gate -> original bed-delta writer", evidence="214-215 value T", stage="periodic_output", status="production_consumed", reason="The family requires both controls and writes the thresholded original-bed minus committed-bed depth.", original_semantics="active_output_gate", outputs=("Erosion_depth_*",), dependencies=("simulate_erosion",)),
    _spec(39, "save_deposition_depth", group="process_output", original_variable="debdepodepthsave", read_line="515", original_consumer="dfs.F90:1409 requires sepdepositionsimul and debdepodepthsave", activation="separate deposition and save flag are true", runtime_consumer="compound immutable run/output gate -> positive committed-bed delta writer", evidence="216-217 value T", stage="periodic_output", status="production_consumed", reason="The family requires both controls and writes max(ele-eleori,0) rather than bookkeeping deposition.", original_semantics="active_output_gate", outputs=("Deposit_depth_*",), dependencies=("simulate_water_and_solid_separately",)),
    _spec(40, "save_total_depth", group="process_output", original_variable="totaldepthsave", read_line="522", original_consumer="dfs.F90:1435 uses fh+ele-eleori under separate-deposition gate", activation="separate deposition and totaldepthsave are true", runtime_consumer="compound immutable run/output gate -> fh+ele-eleori writer", evidence="218-219 value T", stage="periodic_output", status="production_consumed", reason="The original total-depth formula and both required controls are consumed at the periodic writer.", original_semantics="active_output_gate", outputs=("Total_depth_*",), dependencies=("simulate_water_and_solid_separately",)),
    _spec(41, "save_max_solid_depth", group="process_output", original_variable="maxsoliddepthsave", read_line="529", original_consumer="dfs.F90:1422 writes accepted-step maxsd with <=0.005 zeroing", activation="maxsoliddepthsave is true", runtime_consumer="accepted-step max_solid_depth field -> strict writer with <=0.005 zeroing", evidence="220-221 value T", stage="accepted_step_and_output", status="production_consumed", reason="The monotonic accepted h*Cv maximum, original threshold, and independent output gate are all consumed.", original_semantics="active_output_gate", outputs=("Maxsoliddepth_*",)),
    _spec(42, "save_volumetric_sediment_concentration", group="process_output", original_variable="cvsave", read_line="536", original_consumer="DFS periodic Cv writer", activation="cvsave is true", runtime_consumer="strict periodic writer with original fh<0.005 shallow-depth zeroing", evidence="222-223 value T", stage="periodic_output", status="production_consumed", reason="The committed concentration, original shallow-depth mask, and independent family gate are consumed.", original_semantics="active_output_gate", outputs=("Volumetric_sediment_concentration_*",)),
    _spec(43, "save_outflow_process", group="process_output", original_variable="outflowsave", read_line="543", original_consumer="dfs.F90:1482 and wfs.F90:907 call soutf at end", activation="outflowsave is true", runtime_consumer="accepted pre-clear outflow samples -> gated end-of-run three-column OUTNQ writer", evidence="224-225 value F", stage="end_of_run_output", status="production_consumed", reason="The false gate creates no file; the true gate writes original ELEMENT/TIME/DISCHARGE columns from accepted pre-clear samples.", original_semantics="active_output_gate", outputs=("OUTNQ_*",), dependencies=("simulate_outflow_cell",)),
    _spec(44, "save_drainage_nodal_flow", group="process_output", original_variable="dwnodesave", read_line="549", original_consumer="dwflow.f90:635 writes dw_nodal_flow.txt", activation="dwsimul and dwnodesave are true", runtime_consumer="experimental stormdrain diagnostics only", evidence="226-227 value F", stage="accepted_step_output", status="partial", reason="Production drainage node writer is not closed.", original_semantics="active_output_gate", outputs=("dw_nodal_flow.txt",), dependencies=("simulate_drainage_flow",)),
    _spec(45, "save_drainage_conduit_flow", group="process_output", original_variable="dwconduitsave", read_line="555", original_consumer="dwflow.f90:644 writes dw_conduit_flow.txt", activation="dwsimul and dwconduitsave are true", runtime_consumer="experimental stormdrain diagnostics only", evidence="228-229 value F", stage="accepted_step_output", status="partial", reason="Production drainage conduit writer is not closed.", original_semantics="active_output_gate", outputs=("dw_conduit_flow.txt",), dependencies=("simulate_drainage_flow",)),
)


def _validate_registry(registry: Tuple[EddaSwitchSpec, ...]) -> None:
    if len(registry) != 45:
        raise RuntimeError(f"EDDA core switch registry must contain 45 entries, got {len(registry)}")
    keys = tuple(spec.key for spec in registry)
    if len(set(keys)) != len(keys):
        raise RuntimeError("EDDA core switch registry contains duplicate keys")
    if tuple(spec.source_index for spec in registry) != tuple(range(1, 46)):
        raise RuntimeError("EDDA core switch registry source_index values must be exactly 1..45")
    for spec in registry:
        if spec.status not in ALLOWED_STATUSES:
            raise RuntimeError(f"Invalid switch status for {spec.key}: {spec.status}")
        unknown = set(spec.dependencies) - set(keys)
        if unknown:
            raise RuntimeError(f"Unknown dependencies for {spec.key}: {sorted(unknown)}")

    visiting: set[str] = set()
    visited: set[str] = set()
    dependency_map = {spec.key: spec.dependencies for spec in registry}

    def visit(key: str) -> None:
        if key in visiting:
            raise RuntimeError(f"Cycle detected in EDDA switch dependencies at {key}")
        if key in visited:
            return
        visiting.add(key)
        for dependency in dependency_map[key]:
            visit(dependency)
        visiting.remove(key)
        visited.add(key)

    for key in keys:
        visit(key)


_validate_registry(EDDA_SWITCH_REGISTRY)
EDDA_SWITCH_KEYS: Tuple[str, ...] = tuple(spec.key for spec in EDDA_SWITCH_REGISTRY)
EDDA_SWITCH_BY_KEY: Mapping[str, EddaSwitchSpec] = MappingProxyType(
    {spec.key: spec for spec in EDDA_SWITCH_REGISTRY}
)


def build_switch_snapshot(
    values: Mapping[str, Any],
    *,
    source: str,
) -> EddaSwitchSnapshot:
    """Freeze effective values in the exact original source order."""
    entries = tuple(
        EddaSwitchValue(
            key=spec.key,
            source_index=spec.source_index,
            raw_value=_freeze_value(values.get(spec.key)),
            effective_value=_freeze_value(values.get(spec.key)),
            source=source,
        )
        for spec in EDDA_SWITCH_REGISTRY
    )
    return EddaSwitchSnapshot(registry_version=REGISTRY_VERSION, entries=entries)


def registry_payload() -> Dict[str, Any]:
    return {
        "registry_version": REGISTRY_VERSION,
        "entry_count": len(EDDA_SWITCH_REGISTRY),
        "entries": [spec.to_dict() for spec in EDDA_SWITCH_REGISTRY],
    }


def snapshot_config_payload(
    snapshot: EddaSwitchSnapshot,
    *,
    extension_controls: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Map one immutable snapshot into the deep SimulationConfig contract."""
    values = snapshot.values
    return {
        "registry_version": snapshot.registry_version,
        "run_controls": {
            spec.key: values[spec.key]
            for spec in EDDA_SWITCH_REGISTRY
            if spec.group == "run_control"
        },
        "output_controls": {
            spec.key: values[spec.key]
            for spec in EDDA_SWITCH_REGISTRY
            if spec.group in {"legacy_output", "process_output"}
        },
        "extension_controls": dict(extension_controls or {}),
    }
