import { useEffect, useMemo, useState } from "react";
import { Check, Download, FileJson, FileSpreadsheet, Folder } from "lucide-react";
import { useTaichiFlowStore } from "../../stores/taichiFlowStore";
import { Button } from "../../components/Button";
import { StatusBadge } from "../../components/StatusBadge";
import type { Scenario } from "../../types";
import { exportApi } from "../../api/taichiFlowAdapter";

function formatSize(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / k ** i).toFixed(1)} ${sizes[i]}`;
}

export function ExportData() {
  const activeProject = useTaichiFlowStore((state) => state.activeProject);
  const scenarios = useTaichiFlowStore((state) => state.scenarios);
  const resultFamilies = useTaichiFlowStore((state) => state.resultFamilies);
  const fetchResultFamilies = useTaichiFlowStore((state) => state.fetchResultFamilies);
  const createExport = useTaichiFlowStore((state) => state.createExport);
  const exports = useTaichiFlowStore((state) => state.exports);

  const [step, setStep] = useState<1 | 2 | 3 | 4>(1);
  const [selectedScenario, setSelectedScenario] = useState<Scenario | null>(null);
  const [selectedSimulationId, setSelectedSimulationId] = useState<string>("");
  const [selectedFiles] = useState<Set<string>>(new Set());
  const [selectedFamilies, setSelectedFamilies] = useState<Set<string>>(new Set());
  const [includeJson, setIncludeJson] = useState(true);
  const [includeCsv, setIncludeCsv] = useState(true);
  const [creating, setCreating] = useState(false);

  const completedScenarios = useMemo(() => scenarios.filter((s) => s.status === "completed"), [scenarios]);

  const families = useMemo(() => {
    if (!selectedSimulationId) return [];
    return resultFamilies[selectedSimulationId] || [];
  }, [resultFamilies, selectedSimulationId]);

  useEffect(() => {
    if (selectedScenario?.latest_simulation_id) {
      setSelectedSimulationId(selectedScenario.latest_simulation_id);
      fetchResultFamilies(selectedScenario.latest_simulation_id);
    }
  }, [selectedScenario, fetchResultFamilies]);

  const handleSelectScenario = (scenario: Scenario) => {
    setSelectedScenario(scenario);
    setStep(2);
  };

  const handleToggleFamily = (familyId: string) => {
    setSelectedFamilies((prev) => {
      const next = new Set(prev);
      if (next.has(familyId)) next.delete(familyId);
      else next.add(familyId);
      return next;
    });
  };

  const handleCreateExport = async () => {
    if (!selectedScenario || !selectedSimulationId) return;
    setCreating(true);
    try {
      await createExport(selectedScenario.scenario_id, selectedSimulationId, {
        selected_families: Array.from(selectedFamilies),
        selected_files: Array.from(selectedFiles),
        include_parameters_json: includeJson,
        include_parameters_csv: includeCsv,
      });
      setStep(4);
    } finally {
      setCreating(false);
    }
  };

  if (!activeProject) {
    return <div className="tf-empty-state tf-body">请先选择项目。</div>;
  }

  return (
    <div className="tf-page">
      <div className="tf-page-content tf-page-content--medium tf-animate-in">
        <div className="tf-page-header tf-mb-2">
          <div>
            <h1 className="tf-display tf-mb-2">导出数据</h1>
            <p className="tf-body tf-text-secondary">
              按参数方案选择输出结果和参数文件，生成结构清晰的导出包。
            </p>
          </div>
        </div>

        <div className="tf-step-bar">
          {[1, 2, 3, 4].map((s) => (
            <div key={s} className={`tf-step-segment${s <= step ? " done" : ""}`} />
          ))}
        </div>

        {step === 1 && (
          <StepCard title="步骤 1：选择方案">
            {completedScenarios.length === 0 ? (
              <p className="tf-body tf-text-secondary">没有已完成的方案。请先完成模拟。</p>
            ) : (
              <div className="tf-card-grid">
                {completedScenarios.map((s) => (
                  <button key={s.scenario_id} type="button" onClick={() => handleSelectScenario(s)} className="tf-selectable-card">
                    <div className="tf-body tf-font-semibold tf-mb-2">{s.name}</div>
                    <div className="tf-caption tf-text-tertiary">
                      {s.result_family_count} 个结果族 · {s.file_count} 个文件
                    </div>
                  </button>
                ))}
              </div>
            )}
          </StepCard>
        )}

        {step === 2 && selectedScenario && (
          <StepCard title="步骤 2：选择模拟记录">
            <div className="tf-stack-sm">
              <button type="button" onClick={() => setStep(3)} className="tf-selectable-card is-selected">
                <div className="tf-body tf-font-semibold tf-text-brand">最近完成：{selectedScenario.latest_simulation_id}</div>
                <div className="tf-caption tf-text-tertiary">方案：{selectedScenario.name}</div>
              </button>
            </div>
          </StepCard>
        )}

        {step === 3 && selectedScenario && (
          <StepCard title="步骤 3：选择数据">
            <div className="tf-stack-md">
              <div>
                <h4 className="tf-subtitle tf-mb-2">参数文件</h4>
                <div className="tf-stack-sm">
                  <label className="tf-check-row">
                    <input type="checkbox" checked={includeJson} onChange={(e) => setIncludeJson(e.target.checked)} />
                    <FileJson size={16} className="tf-text-tertiary" />
                    <span className="tf-body">effective_parameters.json</span>
                  </label>
                  <label className="tf-check-row">
                    <input type="checkbox" checked={includeCsv} onChange={(e) => setIncludeCsv(e.target.checked)} />
                    <FileSpreadsheet size={16} className="tf-text-tertiary" />
                    <span className="tf-body">effective_parameters.csv</span>
                  </label>
                </div>
              </div>

              <div>
                <h4 className="tf-subtitle tf-mb-2">结果族</h4>
                <div className="tf-stack-sm">
                  {families.map((family) => (
                    <label key={family.family_id} className="tf-check-card">
                      <input type="checkbox" checked={selectedFamilies.has(family.family_id)} onChange={() => handleToggleFamily(family.family_id)} />
                      <Folder size={16} className="tf-text-tertiary" />
                      <span className="tf-body tf-flex-1">{family.label}</span>
                      <span className="tf-caption tf-text-tertiary">{family.file_count} 个文件</span>
                    </label>
                  ))}
                </div>
              </div>

              <div className="tf-row tf-justify-end tf-gap-2">
                <Button variant="secondary" onClick={() => setStep(2)}>
                  上一步
                </Button>
                <Button onClick={() => setStep(4)} disabled={selectedFamilies.size === 0 && !includeJson && !includeCsv} icon={<Check size={16} />}>
                  确认选择
                </Button>
              </div>
            </div>
          </StepCard>
        )}

        {step === 4 && selectedScenario && (
          <StepCard title="步骤 4：确认并导出">
            <div className="tf-stack-md">
              <div className="tf-inset tf-stack-sm">
                <div className="tf-body tf-font-semibold">
                  {selectedScenario.name}_{new Date().toISOString().slice(0, 10)}.zip
                </div>
                <div className="tf-caption tf-text-secondary">
                  已选择 {selectedFamilies.size} 个结果族，参数文件 {includeJson || includeCsv ? "已包含" : "未包含"}
                </div>
              </div>

              {exports.filter((e) => e.scenario_id === selectedScenario.scenario_id).length > 0 && (
                <div className="tf-stack-sm">
                  {exports
                    .filter((e) => e.scenario_id === selectedScenario.scenario_id)
                    .map((e) => (
                      <div key={e.export_id} className="tf-inset tf-row tf-inset-row">
                        <div>
                          <div className="tf-body">{e.export_id}</div>
                          <div className="tf-caption tf-text-tertiary">
                            {formatSize(e.total_size)} · {e.file_count} 个文件
                          </div>
                        </div>
                        {e.status === "completed" ? (
                          <Button size="small" icon={<Download size={14} />} onClick={() => window.open(exportApi.downloadUrl(activeProject.project_id, e.export_id), "_blank", "noopener,noreferrer")}>
                            下载
                          </Button>
                        ) : (
                          <StatusBadge variant={e.status === "running" || e.status === "generating" ? "running" : e.status === "failed" ? "error" : "info"} />
                        )}
                      </div>
                    ))}
                </div>
              )}

              <div className="tf-row tf-justify-end tf-gap-2">
                <Button variant="secondary" onClick={() => setStep(3)}>
                  上一步
                </Button>
                <Button onClick={handleCreateExport} disabled={creating} icon={<Download size={16} />}>
                  {creating ? "生成中..." : "生成导出包"}
                </Button>
              </div>
            </div>
          </StepCard>
        )}
      </div>
    </div>
  );
}

function StepCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="tf-card">
      <h2 className="tf-title tf-card-header">{title}</h2>
      {children}
    </div>
  );
}
