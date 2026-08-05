import type { CaseConfigInterface } from "../types";

const FLAG_LABELS: Record<string, string> = {
  simulate_rainfall: "模拟降雨",
  simulate_infiltration: "模拟入渗",
  simulate_inflow_hydrograph: "模拟入流过程",
  simulate_outflow_cell: "模拟出流单元",
  simulate_shallow_landslide: "模拟浅层滑坡",
  simulate_debris_flow: "模拟泥石流",
  simulate_erosion: "模拟侵蚀",
  simulate_water_and_solid_separately: "水沙分离",
  simulate_water_solid_separately: "水沙分离",
  simulate_drainage_flow: "模拟排水",
  simulate_barrier: "模拟拦挡",
  use_full_dynamic_wave: "全动态波方程",
  use_analytic_fillable_porosity: "解析可填充孔隙度",
  estimate_positive_pressure_head: "估计正压水头",
  use_psi0_negative_inverse_alpha: "psi0=-1/alpha",
  log_mass_balance_results: "记录质量守恒",
  background_flux_offset: "背景入渗偏移",
  flow_direction_mode: "流向模式",
};

function formatFlag(value: unknown): string {
  if (typeof value === "boolean") return value ? "是" : "否";
  if (value == null) return "—";
  return String(value);
}

export function EddaFlagsSection({ caseConfig }: { caseConfig: CaseConfigInterface | null }) {
  const flags = caseConfig?.audit?.flags || {};
  const entries = Object.entries(flags);
  if (!entries.length) {
    return (
      <section className="tf-card tf-card-flush tf-config-section">
        <div className="tf-body tf-group-header tf-font-semibold">模拟开关</div>
        <div className="tf-card-body-sm tf-caption tf-text-tertiary">暂无开关信息（需先上传并解析 edda_in）。</div>
      </section>
    );
  }

  return (
    <section className="tf-card tf-card-flush tf-config-section" data-testid="edda-flags-section">
      <div className="tf-body tf-group-header tf-font-semibold">模拟开关（只读）</div>
      <div className="tf-card-body-sm">
        <div className="tf-flag-grid">
          {entries.map(([key, value]) => (
            <div key={key} className="tf-flag-item">
              <span className="tf-caption tf-text-secondary">{FLAG_LABELS[key] || key}</span>
              <span className="tf-mono">{formatFlag(value)}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
