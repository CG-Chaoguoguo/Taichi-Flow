"""
Configuration management for EDDA simulation.
"""
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from pathlib import Path
import yaml
from pydantic import BaseModel, Field


class HydrologyParams(BaseModel):
    """Hydrology parameters for Green-Ampt infiltration model."""
    K_sat: float = Field(1e-5, description="Saturated hydraulic conductivity (m/s)")
    theta_s: float = Field(0.45, description="Saturated water content")
    theta_i: float = Field(0.20, description="Initial water content")
    psi_f: float = Field(0.10, description="Wetting front suction head (m)")
    depthwt_initial: float = Field(1.0, description="Original EDDA default initial water-table depth when depfil is unavailable (m)")
    rizero_initial: float = Field(0.0, description="Original EDDA default initial infiltration-rate grid value when rizerofil is unavailable (m/s)")
    use_background_flux_offset: bool = Field(False, description="Original EDDA bkgrof flag for adding steady background infiltration when transient infiltration is zero")
    use_transient_green_ampt_in_dfs: bool = Field(
        False,
        description=(
            "Experimental research switch: stage DFS infiltration with the exact "
            "Green-Ampt average-rate algorithm from infr.F90 instead of the "
            "literal ir=min(Ks,inflx) path in the provided dfs.F90 source."
        ),
    )
    dfs_infiltration_variant: str = Field(
        "tol_clipped_fhw",
        description=(
            "Native-input DFS infiltration staging variant. "
            "`tol_clipped_fhw` matches the provided EntireBanzigou-style "
            "`fhw=fh*(1-cv/cvstar)+rain*dt+tempinflowh; if (fhw<tol) fhw=0; inflx=fhw/dt` "
            "path. `direct_rain_plus_storage` matches the NO.5/NO.8/Test31-style "
            "`fhw=fh*(1-cv/cvstar); inflx=rain+(tempinflowh+fhw)/dt` path."
        ),
    )
    dfs_face_flux_variant: str = Field(
        "both_thin_weighted",
        description=(
            "Native-input DFS face-flux / wet-dry gating variant. "
            "`both_thin_weighted` (BJ/NO.5 default) uses the both-thin gate with "
            "`cellareacal`-weighted `hbar/cvbar/frhobar`. "
            "`arithmetic_mean_chamoli` keeps the both-thin gate and weighted `hbar`, "
            "but uses area-mean `cvbar` without depth and arithmetic `frhobar`. "
            "`asymmetric_head_guard` matches EntireBanzigou-style asymmetric thin-front "
            "gating with arithmetic `hbar/cvbar/frhobar`."
        ),
    )
    dfs_failure_source_variant: str = Field(
        "live_doublelayer_in_dfs",
        description=(
            "Native-input DFS failure-source staging variant. "
            "`live_doublelayer_in_dfs` matches the path where DFS advances the "
            "double-layer model every accepted step. "
            "`precomputed_unsfin_schedule` matches paired NO.5-style cases where "
            "`unsfin` precomputes `gindx/tfail/fdepth` before DFS and the DFS "
            "loop does not call `doublelayer` directly."
        ),
    )
    inflow_denominator_variant: str = Field(
        "CELLAREA",
        description=(
            "Source-detected original EDDA inflow.txt staging denominator. "
            "`CELLAREA`/`CELLAREACAL` stage discharge over a cell-area denominator; "
            "`CELSIZ_DIRECTIONAL_VELOCITY` matches bundled sources that divide by "
            "`celsiz * fv(i,4)` after assigning the traced directional velocity."
        ),
    )
    inflow_denominator_direction: Optional[int] = Field(
        None,
        description="For CELSIZ_DIRECTIONAL_VELOCITY, the original Fortran fv direction used in the denominator.",
    )
    inflow_denominator_fv_value: Optional[float] = Field(
        None,
        description="For CELSIZ_DIRECTIONAL_VELOCITY, the source-assigned fv value used in the denominator.",
    )
    dfs_manningbar_variant: str = Field(
        "exponential_cv",
        description=(
            "Native-input DFS Manning-bar variant. "
            "`exponential_cv` matches BJ_HXL `manningbar=manning*manningb*exp(manningm*cv)` "
            "when `cv>cvtol`. `debrisflowmanning_cvtol` matches Chamoli `dfs.F90:417-421` "
            "`manningbar=debrisflowmanning` in the erosion-rate branch, with a no-op "
            "face-flux `cvbar>cvtol` assignment."
        ),
    )
    dfs_dry_face_velocity_variant: str = Field(
        "keep_velocity_bj",
        description=(
            "Native-input DFS dry-face predicted-velocity variant. "
            "`keep_velocity_bj` keeps `fvpredi=dv+fv` even when the upstream cell is dry "
            "(BJ production default). `zero_dry_face_chamoli` matches Chamoli "
            "`dfs.F90:736-737`, zeroing `fvpredi` when the upstream cell is thinner "
            "than `tol` before the sign-reversal branch."
        ),
    )
    dfs_artivis_variant: str = Field(
        "depth_ratio_bj",
        description=(
            "Native-input DFS artificial-viscosity weight variant. "
            "`depth_ratio_bj` uses `0.02*|Δh|/(h_i+h_nq)` on every direction (BJ). "
            "`velocity_ratio_chamoli` uses `0.02*|Δv|/(|v_nq|+|v_i|+1)` and divides "
            "the diagonal `artivis` term by `√2` (Chamoli `dfs.F90:730-732`)."
        ),
    )
    dfs_absubar_variant: str = Field(
        "max_component_bj",
        description=(
            "Native-input DFS erosion/deposition velocity-magnitude (`absubar`) variant. "
            "`max_component_bj` takes `max(vorth,vcomp)` from half-velocity `fvpredi2` (BJ). "
            "`signed_mean_chamoli` reconstructs a signed Cartesian speed from raw `fv` "
            "with literal `0.707` diagonals (Chamoli `dfs.F90:209-212`)."
        ),
    )
    use_fortran_absubar_velocity_state: bool = Field(
        True,
        description=(
            "Feature-gated DFS erosion/deposition velocity-magnitude source. "
            "When true, `absubar` uses the paired-case Fortran lifecycle where "
            "`fvpredi` is reset before the source branch and "
            "`fvpredi2=0.5*(fv+fvpredi)` therefore evaluates from half of the "
            "accepted directional velocity."
        ),
    )
    use_tol_subtracted_inflx_in_dfs: bool = Field(
        False,
        description=(
            "Experimental research switch: stage DFS infiltration with "
            "inflx=max((fhw-tol)/dt,0) before ir=min(Ks,inflx). This follows the "
            "commented alternate branch present in the supplied dfs.F90 and is "
            "useful for diagnosing thin-front sensitivity around tol=0.01 m."
        ),
    )


class SoilParams(BaseModel):
    """Soil parameters for slope stability analysis."""
    c: float = Field(5000.0, description="Cohesion (Pa)")
    phi: float = Field(30.0, description="Internal friction angle (degrees)")
    gamma_s: float = Field(20000.0, description="Soil unit weight (N/m³)")
    gamma_w: float = Field(9800.0, description="Water unit weight (N/m³)")
    depth: float = Field(2.0, description="Soil depth (m)")
    double_layer: Optional["DoubleLayerSoilParams"] = Field(None, description="Double-layer soil model parameters (optional)")


class TopLayerParams(BaseModel):
    """Parameters for the top soil layer in double-layer model."""
    c: float = Field(5000.0, description="Cohesion (Pa)")
    phi: float = Field(30.0, description="Internal friction angle (degrees)")
    phib: float = Field(15.0, description="Basal friction angle (degrees)")
    gamma_s: float = Field(20000.0, description="Soil unit weight (N/m³)")
    K_sat: float = Field(1e-5, description="Saturated hydraulic conductivity (m/s)")
    theta_sat: float = Field(0.45, description="Saturated water content")
    theta_res: float = Field(0.05, description="Residual water content")
    theta_ini: float = Field(0.20, description="Initial water content")
    alpha: float = Field(2.0, description="Van Genuchten parameter alpha (1/m)")
    diffusivity: float = Field(1e-6, description="Soil water diffusivity (m²/s)")


class BottomLayerParams(BaseModel):
    """Parameters for the bottom soil layer in double-layer model."""
    c: float = Field(8000.0, description="Cohesion (Pa)")
    phi: float = Field(35.0, description="Internal friction angle (degrees)")
    phib: float = Field(20.0, description="Basal friction angle (degrees)")
    gamma_s: float = Field(21000.0, description="Soil unit weight (N/m³)")
    K_sat: float = Field(5e-6, description="Saturated hydraulic conductivity (m/s)")
    theta_sat: float = Field(0.40, description="Saturated water content")
    theta_res: float = Field(0.05, description="Residual water content")
    theta_ini: float = Field(0.18, description="Initial water content")
    alpha: float = Field(1.5, description="Van Genuchten parameter alpha (1/m)")
    diffusivity: float = Field(5e-7, description="Soil water diffusivity (m²/s)")


class DoubleLayerSoilParams(BaseModel):
    """Configuration for double-layer soil model with Richards equation."""
    enabled: bool = Field(False, description="Enable double-layer soil model")
    nzst: int = Field(26, description="Number of sublayers in top layer")
    nzsb: int = Field(26, description="Number of sublayers in bottom layer")
    top_layer: TopLayerParams = Field(default_factory=TopLayerParams, description="Top layer parameters")
    bottom_layer: BottomLayerParams = Field(default_factory=BottomLayerParams, description="Bottom layer parameters")
    ltstar: float = Field(1.0, description="Top layer thickness (m)")
    lbstar: float = Field(1.0, description="Bottom layer thickness (m)")
    zmin: float = Field(0.01, description="Minimum layer thickness (m)")
    uww: float = Field(
        0.0,
        description=(
            "Original EDDA water unit weight parameter uww (N/m³). "
            "Current double-layer runtime consumes this config field directly."
        ),
    )
    min_slope_angle_deg: float = Field(5.0, description="Minimum slope angle threshold in degrees for the double-layer stability model")
    nudzt: List[float] = Field(
        default_factory=lambda: [0.01] * 26,
        description="Sublayer thickness distribution for top layer (m)"
    )
    nudzb: List[float] = Field(
        default_factory=lambda: [0.01] * 26,
        description="Sublayer thickness distribution for bottom layer (m)"
    )


class RheologyParams(BaseModel):
    """Rheology parameters for flow modeling."""
    # Manning formula parameters (clear water, Cv < 0.2)
    n_manning: float = Field(0.03, description="Manning roughness coefficient")

    # Quadratic model parameters (debris flow, Cv >= 0.2)
    alpha1: float = Field(0.0765, description="Quadratic model parameter α1")
    beta1: float = Field(10.11, description="Quadratic model parameter β1")
    alpha2: float = Field(0.0538, description="Quadratic model parameter α2")
    beta2: float = Field(17.48, description="Quadratic model parameter β2")

    # Density parameters
    rho_water: float = Field(1000.0, description="Water density (kg/m³)")
    rho_sediment: float = Field(2650.0, description="Sediment density (kg/m³)")

    # Concentration thresholds
    Cv_threshold: float = Field(0.2, description="Concentration threshold for flow type")
    Cv_max: float = Field(0.65, description="Maximum volumetric concentration")
    limitfr: float = Field(1.0, description="Froude number limit used for adaptive Manning update")
    manningb: float = Field(0.0538, description="Original EDDA debris-Manning multiplier coefficient")
    manningm: float = Field(6.0896, description="Original EDDA debris-Manning exponent coefficient")
    kresis: float = Field(8.0, description="Original EDDA viscous resistance coefficient")
    cs: float = Field(0.9, description="Original EDDA channel suspension coefficient")
    shallown: float = Field(0.2, description="Original EDDA shallow-flow Manning coefficient for wfs path")
    debrisflowmanning: Optional[float] = Field(
        None,
        description="Chamoli-variant debris-flow Manning coefficient used when cv>cvtol in dfs.F90 erosion staging",
    )
    cvglacier: Optional[float] = Field(
        None,
        description="Original EDDA cvglacier; parsed for provenance. Chamoli dfs.F90 rhoero assignment is commented out.",
    )
    cvlandslide: Optional[float] = Field(
        None,
        description="Original EDDA cvlandslide used as triggerslide mixture concentration in dfs.F90:561",
    )


class ErosionParams(BaseModel):
    """Erosion and deposition parameters."""
    tau_c: float = Field(10.0, description="Critical shear stress for erosion (Pa)")
    ctao: float = Field(10.0, description="Original EDDA ctao top-layer erosion threshold term (Pa)")
    k_erosion: float = Field(1e-5, description="Erosion coefficient (m/s/Pa)")
    v_critical: float = Field(0.5, description="Critical velocity for deposition (m/s)")
    k_deposition: float = Field(0.1, description="Deposition coefficient")
    d50: float = Field(0.001, description="Median particle diameter used by original EDDA deposition law (m)")
    coedepo: float = Field(0.1, description="Original EDDA deposition coefficient")


class ZoneParams(BaseModel):
    """Parameters for a single spatial zone."""
    zone_id: int = Field(..., description="Zone identifier")

    # Hydrology parameters
    K_sat: float = Field(1e-5, description="Saturated hydraulic conductivity (m/s)")
    theta_s: float = Field(0.45, description="Saturated water content")
    theta_i: float = Field(0.20, description="Initial water content")
    psi_f: float = Field(0.10, description="Wetting front suction head (m)")

    # Soil parameters
    c: float = Field(5000.0, description="Cohesion (Pa)")
    phi: float = Field(30.0, description="Internal friction angle (degrees)")
    gamma_s: float = Field(20000.0, description="Soil unit weight (N/m³)")
    gamma_w: float = Field(9800.0, description="Water unit weight (N/m³)")
    depth: float = Field(2.0, description="Soil depth (m)")

    # Rheology parameters
    n_manning: float = Field(0.03, description="Manning roughness coefficient")
    alpha1: float = Field(0.0765, description="Quadratic model parameter α1")
    beta1: float = Field(10.11, description="Quadratic model parameter β1")
    alpha2: float = Field(0.0538, description="Quadratic model parameter α2")
    beta2: float = Field(17.48, description="Quadratic model parameter β2")

    # Double-layer soil parameters (per zone)
    alpha_top: float = Field(2.0, description="Van Genuchten alpha for top layer (1/m)")
    alpha_bottom: float = Field(1.5, description="Van Genuchten alpha for bottom layer (1/m)")
    K_sat_top: float = Field(1e-5, description="Saturated hydraulic conductivity for top layer (m/s)")
    K_sat_bottom: float = Field(5e-6, description="Saturated hydraulic conductivity for bottom layer (m/s)")
    theta_sat_top: float = Field(0.45, description="Saturated water content for top layer")
    theta_sat_bottom: float = Field(0.40, description="Saturated water content for bottom layer")
    theta_res_top: float = Field(0.05, description="Residual water content for top layer")
    theta_res_bottom: float = Field(0.05, description="Residual water content for bottom layer")
    phib: float = Field(15.0, description="Unsaturated shear strength angle (degrees)")
    kero: float = Field(1e-5, description="Erosion coefficient (m/s/Pa)")
    ctao: float = Field(10.0, description="Original EDDA ctao top-layer erosion threshold term (Pa)")
    cvero: Optional[float] = Field(
        None,
        description="Zone bed volumetric concentration for erosion density (Chamoli cvero). Absent on BJ; rhoero falls back to cvstar.",
    )
    c_bottom: float = Field(8000.0, description="Bottom-layer cohesion (Pa); parsed for provenance, unused by original double-layer FS")
    phi_bottom: float = Field(35.0, description="Bottom-layer internal friction angle (degrees); parsed for provenance, unused by original double-layer FS")
    phib_bottom: float = Field(20.0, description="Bottom-layer basal friction angle (degrees); parsed for provenance, unused by original double-layer FS")
    gamma_s_bottom: float = Field(21000.0, description="Bottom-layer unit weight (N/m³); parsed for provenance, unused by original double-layer FS")
    ltstar: float = Field(1.0, description="Top layer thickness (m)")
    lbstar: float = Field(1.0, description="Bottom layer thickness (m)")


class SpatialZoneConfig(BaseModel):
    """Configuration for spatial zone system."""
    enabled: bool = Field(False, description="Enable spatial zone system for heterogeneous parameters")
    zone_file: Optional[str] = Field(None, description="Path to zone raster file (GeoTIFF or ASCII)")
    num_zones: int = Field(1, description="Number of zones")
    zones: Dict[int, ZoneParams] = Field(default_factory=dict, description="Zone parameters by zone ID")


# Rebuild model to resolve forward references
SoilParams.model_rebuild()


class TimeParams(BaseModel):
    """Time stepping parameters."""
    t_start: float = Field(0.0, description="Start time (s)")
    t_end: float = Field(3600.0, description="End time (s)")
    dt_initial: float = Field(0.1, description="Initial time step (s)")
    dt_min: float = Field(1e-4, description="Minimum time step (s)")
    dt_max: float = Field(1.0, description="Maximum time step (s)")
    dt_output: float = Field(60.0, description="Output interval (s)")
    CFL: float = Field(0.5, description="CFL number for stability")
    dt_increase: float = Field(0.0, description="Original EDDA successful-step dt increment dti (s)")
    dt_decrease: float = Field(0.0, description="Original EDDA rejected-step dt decrement dtd (s)")
    toldh: float = Field(0.1, description="Original EDDA absolute depth-change limiter toldh (m)")
    toldhp: float = Field(0.05, description="Original EDDA relative depth-change limiter toldhp")
    wavemax: float = Field(0.25, description="Original EDDA full dynamic-wave stability coefficient wavemax")


class ComputeParams(BaseModel):
    """Computational parameters."""
    backend: str = Field("cuda", description="Taichi backend: cuda, cpu, vulkan, auto")
    use_double_precision: bool = Field(False, description="Use double precision")
    use_tanslodir_carry_quirk: bool = Field(
        False,
        description=(
            "Experimental research switch: reproduce the supplied dfs.F90 "
            "tanslodir(maxdirection) carry-over semantics across missing "
            "neighbors, cells, and accepted steps."
        ),
    )
    chunk_size: Optional[int] = Field(None, description="Chunk size for large grids")
    num_threads: Optional[int] = Field(None, description="Number of CPU threads")


class RainfallConfig(BaseModel):
    """Rainfall input configuration."""
    mode: str = Field("single_file", description="Rainfall input mode: single_file, spatial_tif_series, csv")
    file: Optional[str] = Field(None, description="Single rainfall file path (CSV or TXT)")
    directory: Optional[str] = Field(None, description="Directory containing spatial rainfall GeoTIFF files")
    file_pattern: str = Field("*.tif", description="Glob pattern for rainfall files in directory")
    time_step_hours: float = Field(1.0, description="Time step between consecutive rainfall files (hours)")
    interval_bounds_s: Optional[List[float]] = Field(
        None,
        description=(
            "Optional EDDA `capt` interval boundaries in seconds for spatial "
            "rainfall series. When provided, these boundaries take precedence "
            "over uniform time_step_hours."
        ),
    )


class BoundaryConditionConfig(BaseModel):
    """Boundary condition configuration."""
    mode: str = Field("auto", description="Boundary detection mode: auto, file, manual")
    default_type: str = Field("outflow", description="Default boundary type: outflow, wall, periodic")
    boundary_file: Optional[str] = Field(None, description="Path to boundary mask file (.shp or .tif)")
    include_nodata: bool = Field(True, description="Include NoData cells as boundaries")
    manual_cells: Optional[list] = Field(None, description="List of manually selected boundary cells [(i,j), ...]")


class NativeInputFileConfig(BaseModel):
    """Formal descriptor for one original/native input family."""
    family: str = Field(..., description="Original EDDA file/input family key")
    path: Optional[str] = Field(None, description="Resolved production path for this input family")
    provenance: str = Field("api_payload", description="Origin of the value: api_payload, reference_config, generated_from_reference_config, helper_fallback")
    status: str = Field("recognized", description="Current backend status for this input family")
    runtime_stage: str = Field("none", description="Expected runtime stage that consumes this input family")
    notes: Optional[str] = Field(None, description="Audit note about support level or semantic limits")
    blocked_reason: Optional[str] = Field(None, description="Machine-readable reason why this family is blocked or only partially aligned")
    activation_condition: Optional[str] = Field(None, description="Condition under which this family becomes active in the current backend")
    status_basis: Optional[str] = Field(None, description="Evidence summary explaining why the current status was assigned")
    original_branch_active: Optional[bool] = Field(None, description="Whether the original EDDA run flag activates this sidecar/input family")
    current_backend_branch_active: Optional[bool] = Field(None, description="Whether the current backend should consume this sidecar/input family at runtime")


class NativeInputConfig(BaseModel):
    """Formal production/native input-chain configuration for S1 provenance."""
    enabled: bool = Field(False, description="Enable native/reference input-chain metadata")
    source_mode: str = Field("api_payload", description="Input source mode: api_payload or reference_config")
    reference_config_file: Optional[str] = Field(None, description="Path to original EDDA `edda_in.txt` if used")
    reference_base_dir: Optional[str] = Field(None, description="Base directory used to resolve relative native file paths")
    parser_version: Optional[str] = Field(None, description="Reference parser version identifier for audit")
    files: Dict[str, NativeInputFileConfig] = Field(default_factory=dict, description="Resolved native input families and their production status")


class EddaControlsConfig(BaseModel):
    """Frozen effective EDDA switch controls carried into one Simulation Run."""

    registry_version: str = Field("1.0.0", description="Canonical EDDA switch registry version")
    run_controls: Dict[str, Any] = Field(default_factory=dict, description="User and process controls keyed by canonical switch name")
    output_controls: Dict[str, Any] = Field(default_factory=dict, description="Legacy and whole-process output controls keyed by canonical switch name")
    extension_controls: Dict[str, Any] = Field(default_factory=dict, description="Version-specific non-core controls such as later hydrosave extensions")


class SimulationConfig(BaseModel):
    """Complete simulation configuration."""
    # Input files
    dem_file: str = Field(..., description="DEM file path (GeoTIFF or ASCII)")
    rainfall_file: Optional[str] = Field(None, description="Single rainfall file (backward compatible)")
    soil_zones_file: Optional[str] = Field(None, description="Soil zones raster file")

    # Rainfall configuration (new, supports spatial tif series)
    rainfall: Optional[RainfallConfig] = Field(None, description="Rainfall input configuration")

    # Output settings
    output_dir: str = Field("./output", description="Output directory")
    output_format: str = Field("geotiff", description="Output format: geotiff, netcdf, ascii")
    save_intermediate: bool = Field(True, description="Save intermediate results")

    # Physical parameters
    hydrology: HydrologyParams = Field(default_factory=HydrologyParams)
    soil: SoilParams = Field(default_factory=SoilParams)
    rheology: RheologyParams = Field(default_factory=RheologyParams)
    erosion: ErosionParams = Field(default_factory=ErosionParams)

    # Time parameters
    time: TimeParams = Field(default_factory=TimeParams)

    # Compute parameters
    compute: ComputeParams = Field(default_factory=ComputeParams)

    # Boundary conditions
    boundary_conditions: Optional[BoundaryConditionConfig] = Field(None, description="Boundary condition configuration")

    # Spatial zone system
    spatial_zones: Optional[SpatialZoneConfig] = Field(None, description="Spatial zone configuration for heterogeneous parameters")

    # Native/reference input-chain metadata
    native_inputs: Optional[NativeInputConfig] = Field(None, description="Formal S1 native input-chain descriptors and provenance")

    # Original EDDA run/output controls
    edda: EddaControlsConfig = Field(default_factory=EddaControlsConfig)

    @classmethod
    def from_yaml(cls, yaml_file: str) -> "SimulationConfig":
        """Load configuration from YAML file."""
        with open(yaml_file, 'r') as f:
            data = yaml.safe_load(f)
        return cls(**data)

    def to_yaml(self, yaml_file: str):
        """Save configuration to YAML file."""
        with open(yaml_file, 'w') as f:
            yaml.dump(self.model_dump(), f, default_flow_style=False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SimulationConfig":
        """Create configuration from dictionary."""
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return self.model_dump()


# Example configuration template
def create_example_config(output_file: str = "config_example.yaml"):
    """Create an example configuration file."""
    config = SimulationConfig(
        dem_file="examples/data/dem.tif",
        rainfall_file="examples/data/rainfall.csv",
        output_dir="./output",
    )
    config.to_yaml(output_file)
    print(f"Example configuration saved to {output_file}")


if __name__ == "__main__":
    # Create example configuration
    create_example_config()
