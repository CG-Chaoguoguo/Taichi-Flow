import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useTaichiFlowStore } from "../../stores/taichiFlowStore";
import type { ComputePolicyResolution, QueueItem, Scenario } from "../../types";
import { RunModule } from "./RunModule";

const scenario: Scenario = {
  scenario_id: "scenario-run",
  project_id: "project-run",
  name: "运行方案",
  input_revision_id: "rev-1",
  parameter_template_id: "pt-bj-hxl-v3",
  parameter_baseline: {},
  parameter_patch: {},
  effective_parameters: {},
  input_bindings: [],
  status: "ready",
  progress: 0,
  latest_simulation_id: null,
  result_family_count: 0,
  file_count: 0,
  created_at: "2026-08-09T00:00:00Z",
  updated_at: "2026-08-09T00:00:00Z",
};

const secondScenario: Scenario = {
  ...scenario,
  scenario_id: "scenario-run-2",
  name: "另一个运行方案",
};

const disabledResolution: ComputePolicyResolution = {
  status: "resolved",
  source: "auto",
  requested: "auto",
  detected: { simulate_shallow_landslide: false, dfs_failure_source_variant: "precomputed_unsfin_schedule", evidence: [] },
  effective: { mode: "disabled", simulate_shallow_landslide: false, configured_variant: "precomputed_unsfin_schedule", active_variant: null },
  numeric_variants: {
    "hydrology.dfs_face_flux_variant": { source: "case_baseline", value: "both_thin_weighted" },
    "hydrology.dfs_manningbar_variant": { source: "case_baseline", value: "exponential_cv" },
    "hydrology.dfs_dry_face_velocity_variant": { source: "case_baseline", value: "keep_velocity_bj" },
    "hydrology.dfs_artivis_variant": { source: "case_baseline", value: "depth_ratio_bj" },
    "hydrology.dfs_absubar_variant": { source: "case_baseline", value: "max_component_bj" },
    "hydrology.dfs_flow_velocity_writer_variant": { source: "case_baseline", value: "half_sum_abs_fv_bj" },
    "hydrology.dfs_erosion_depth_writer_variant": { source: "case_baseline", value: "net_bed_change_bj" },
    "hydrology.dfs_sfdf_classify_cv_variant": { source: "case_baseline", value: "previous_committed_cv" },
    "hydrology.dfs_cvlimit_variant": { source: "case_baseline", value: "tanslo_cycle_cvstar_clamp_bj" },
    "hydrology.dfs_erodph_dt_variant": { source: "case_baseline", value: "accepted_dt_bj" },
    "hydrology.dfs_barrier_flux_variant": { source: "case_baseline", value: "bj_barrier_branch" },
    "hydrology.dfs_commit_cv_eps_variant": { source: "case_baseline", value: "no_clamp_bj" },
  },
  settings_snapshot: {},
  warnings: [],
  resolution_id: "cpr-test",
  resolution_hash: "test",
};

describe("RunModule runtime profile", () => {
  const enqueueScenario = vi.fn(async () => undefined);

  beforeEach(() => {
    enqueueScenario.mockClear();
    useTaichiFlowStore.setState({
      queue: [],
      metrics: { cpu_percent: 1, gpu_percent: 2, gpu_name: "test" },
      enqueueScenario,
      cancelQueueItem: vi.fn(),
      stopRunningItem: vi.fn(),
      retryQueueItem: vi.fn(),
      activeProject: {
        project_id: "project-run",
        name: "run",
        description: "",
        root_path: "C:\\tmp",
        created_at: "2026-08-09T00:00:00Z",
        updated_at: "2026-08-09T00:00:00Z",
      },
      parameterCatalog: {
        catalog_version: "taichi-flow-parameter-catalog-v3",
        editable_statuses: [],
        parameters: [],
        status_counts: {},
        runtime_profiles: {
          user_selectable: [
            { name: "cuda_production_default", label_zh: "CUDA 加速" },
            { name: "compat_default_off", label_zh: "CPU 兼容" },
          ],
        },
      },
      fetchParameterCatalog: vi.fn(async () => undefined),
      scenarioConfigurations: {
        "scenario-run": {
          scenario_id: "scenario-run",
          baseline: {},
          overrides: {},
          effective: {},
          bindings: [],
          validation: { valid: true, errors: [], warnings: [], issues: [] },
          compute_policy_resolution: disabledResolution,
          version: 1,
        },
        "scenario-run-2": {
          scenario_id: "scenario-run-2",
          baseline: {},
          overrides: {},
          effective: {},
          bindings: [],
          validation: { valid: true, errors: [], warnings: [], issues: [] },
          compute_policy_resolution: disabledResolution,
          version: 1,
        },
      },
      fetchScenarioConfiguration: vi.fn(async () => ({
        scenario_id: "scenario-run",
        baseline: {},
        overrides: {},
        effective: {},
        bindings: [],
        validation: { valid: true, errors: [], warnings: [], issues: [] },
        compute_policy_resolution: disabledResolution,
        version: 1,
      })),
    });
  });

  it("passes the selected CPU runtime profile when enqueueing", async () => {
    render(
      <MemoryRouter>
        <RunModule scenario={scenario} />
      </MemoryRouter>,
    );

    const select = screen.getByTestId("run-runtime-profile") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "compat_default_off" } });
    fireEvent.click(screen.getByRole("button", { name: "加入模拟队列" }));

    expect(enqueueScenario).toHaveBeenCalledWith("scenario-run", "compat_default_off", {
      erosion_probe: { enabled: false, probe_cells: [] },
    });
  });

  it("passes enabled erosion probe diagnostics when enqueueing", async () => {
    render(
      <MemoryRouter>
        <RunModule scenario={scenario} />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByTestId("run-erosion-probe-enabled"));
    fireEvent.change(screen.getByTestId("run-erosion-probe-cells"), {
      target: { value: "415,630\n534,590" },
    });
    fireEvent.click(screen.getByRole("button", { name: "加入模拟队列" }));

    expect(enqueueScenario).toHaveBeenCalledWith("scenario-run", "cuda_production_default", {
      erosion_probe: {
        enabled: true,
        probe_cells: [
          [415, 630],
          [534, 590],
        ],
      },
    });
  });

  it("restores parsed probe cells after disable then re-enable and keeps enqueue usable", () => {
    render(
      <MemoryRouter>
        <RunModule scenario={scenario} />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByTestId("run-erosion-probe-enabled"));
    fireEvent.change(screen.getByTestId("run-erosion-probe-cells"), {
      target: { value: "415,630\n534,590" },
    });
    expect(screen.getByRole("button", { name: "加入模拟队列" })).toBeEnabled();

    fireEvent.click(screen.getByTestId("run-erosion-probe-enabled"));
    expect(screen.getByTestId("run-erosion-probe-cells")).toHaveValue("415,630\n534,590");
    expect(screen.getByTestId("run-diagnostics-summary")).toHaveTextContent("诊断：关闭");
    expect(screen.getByRole("button", { name: "加入模拟队列" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "加入模拟队列" }));
    expect(enqueueScenario).toHaveBeenCalledWith("scenario-run", "cuda_production_default", {
      erosion_probe: { enabled: false, probe_cells: [] },
    });
    enqueueScenario.mockClear();

    fireEvent.click(screen.getByTestId("run-erosion-probe-enabled"));
    expect(screen.getByTestId("run-diagnostics-summary")).toHaveTextContent("诊断：开启 · 2 探针");
    expect(screen.getByRole("button", { name: "加入模拟队列" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "加入模拟队列" }));

    expect(enqueueScenario).toHaveBeenCalledWith("scenario-run", "cuda_production_default", {
      erosion_probe: {
        enabled: true,
        probe_cells: [
          [415, 630],
          [534, 590],
        ],
      },
    });
  });

  it("blocks an enabled erosion probe until it has at least one cell", () => {
    render(
      <MemoryRouter>
        <RunModule scenario={scenario} />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByTestId("run-erosion-probe-enabled"));
    expect(screen.getByRole("alert")).toHaveTextContent("至少需要一个探针格点");
    expect(screen.getByRole("button", { name: "加入模拟队列" })).toBeDisabled();

    fireEvent.change(screen.getByTestId("run-erosion-probe-cells"), {
      target: { value: "415,630" },
    });
    expect(screen.getByRole("button", { name: "加入模拟队列" })).toBeEnabled();

    fireEvent.click(screen.getByTestId("run-erosion-probe-enabled"));
    fireEvent.change(screen.getByTestId("run-erosion-probe-cells"), { target: { value: "" } });
    expect(screen.getByRole("button", { name: "加入模拟队列" })).toBeEnabled();
  });

  it("keeps an invalid raw probe draft scoped to its scenario instead of restoring stale valid cells", () => {
    function ScenarioSwitchHarness() {
      const [selected, setSelected] = useState<Scenario>(scenario);
      return (
        <MemoryRouter>
          <button type="button" onClick={() => setSelected(scenario)}>切换到主方案</button>
          <button type="button" onClick={() => setSelected(secondScenario)}>切换到第二方案</button>
          <RunModule scenario={selected} />
        </MemoryRouter>
      );
    }

    render(<ScenarioSwitchHarness />);
    fireEvent.click(screen.getByTestId("run-erosion-probe-enabled"));
    fireEvent.change(screen.getByTestId("run-erosion-probe-cells"), {
      target: { value: "415,630\n534,590" },
    });
    fireEvent.change(screen.getByTestId("run-erosion-probe-cells"), {
      target: { value: "415,630\n415,630" },
    });
    expect(screen.getByTestId("run-erosion-probe-cells")).toHaveValue("415,630\n415,630");
    expect(screen.getByRole("button", { name: "加入模拟队列" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "切换到第二方案" }));
    fireEvent.click(screen.getByRole("button", { name: "切换到主方案" }));

    expect(screen.getByTestId("run-erosion-probe-cells")).toHaveValue("415,630\n415,630");
    expect(screen.getByTestId("run-erosion-probe-cells")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("button", { name: "加入模拟队列" })).toBeDisabled();
  });

  it("shows a read-only failure-source policy summary", () => {
    render(
      <MemoryRouter>
        <RunModule scenario={scenario} />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("failure-source-policy-summary")).toHaveTextContent("自动 → 关闭浅层失稳");
  });

  it("shows the matching historical frozen options, not the first queue item", () => {
    const saved: QueueItem = {
      queue_item_id: "queue-current", project_id: "project-run", scenario_id: scenario.scenario_id,
      scenario_name: scenario.name, position: 2, status: "completed", simulation_id: "sim-current",
      runtime_profile: "cuda_production_default", effective_config: {}, compute_policy_resolution: disabledResolution,
      enqueued_at: "2026-09-10T00:00:00Z", started_at: null, finished_at: null, progress: 100, summary: "completed",
      run_options: { diagnostics: { erosion_probe: { enabled: true, probe_cells: [[728,620], [727,620]] } } },
    };
    useTaichiFlowStore.setState({queue: [
      {...saved, queue_item_id: "queue-old", simulation_id: "sim-old", run_options: {diagnostics: {erosion_probe: {enabled:false,probe_cells:[]}}}}, saved,
    ]});
    render(<MemoryRouter><RunModule scenario={{...scenario,status:"completed",latest_simulation_id:"sim-current"}} readOnly /></MemoryRouter>);
    expect(screen.getByTestId("frozen-run-summary")).toHaveTextContent("sim-current");
    expect(screen.getByTestId("frozen-run-summary")).toHaveTextContent("诊断：开启 · 2 探针");
    expect(screen.queryByText("打开项目并选择方案后，可在此进行预检、入队与运行控制。")).not.toBeInTheDocument();
    expect(screen.queryByTestId("run-erosion-probe-enabled")).not.toBeInTheDocument();
  });

  it("shows numeric variant effective values summary", () => {
    render(
      <MemoryRouter>
        <RunModule scenario={scenario} />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("numeric-variant-summary")).toHaveTextContent("数值变种生效值");
    expect(screen.getByTestId("numeric-variant-summary-list")).toBeInTheDocument();
  });
});
