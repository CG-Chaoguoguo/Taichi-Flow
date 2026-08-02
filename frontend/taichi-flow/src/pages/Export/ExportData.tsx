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
    return (
      <div style={{ padding: 48 }}>
        <p className="tf-body" style={{ color: "var(--color-foreground-secondary)" }}>
          请先选择项目。
        </p>
      </div>
    );
  }

  return (
    <div style={{ height: "100%", overflow: "auto", padding: "32px" }}>
      <div style={{ maxWidth: 1000, margin: "0 auto" }}>
        <div style={{ marginBottom: 24 }}>
          <h1 className="tf-display" style={{ marginBottom: 4 }}>
            导出数据
          </h1>
          <p className="tf-body" style={{ color: "var(--color-foreground-secondary)" }}>
            按参数方案选择输出结果和参数文件，生成结构清晰的导出包。
          </p>
        </div>

        <div style={{ display: "flex", gap: 8, marginBottom: 24 }}>
          {[1, 2, 3, 4].map((s) => (
            <div
              key={s}
              style={{
                flex: 1,
                height: 6,
                borderRadius: 3,
                background: s <= step ? "var(--color-brand)" : "var(--color-surface-tertiary)",
              }}
            />
          ))}
        </div>

        {step === 1 && (
          <StepCard title="步骤 1：选择方案">
            {completedScenarios.length === 0 ? (
              <p className="tf-body" style={{ color: "var(--color-foreground-secondary)" }}>
                没有已完成的方案。请先完成模拟。
              </p>
            ) : (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 12 }}>
                {completedScenarios.map((s) => (
                  <button
                    key={s.scenario_id}
                    onClick={() => handleSelectScenario(s)}
                    style={{
                      padding: 16,
                      borderRadius: "var(--radius-large)",
                      border: "1px solid var(--color-border)",
                      background: "var(--color-surface)",
                      cursor: "pointer",
                      textAlign: "left",
                      transition: "box-shadow 120ms ease",
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.boxShadow = "var(--shadow-hover)")}
                    onMouseLeave={(e) => (e.currentTarget.style.boxShadow = "var(--shadow-rest)")}
                  >
                    <div className="tf-body" style={{ fontWeight: 600, marginBottom: 4 }}>
                      {s.name}
                    </div>
                    <div className="tf-caption" style={{ color: "var(--color-foreground-tertiary)" }}>
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
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <button
                onClick={() => setStep(3)}
                style={{
                  padding: 16,
                  borderRadius: "var(--radius-large)",
                  border: "1px solid var(--color-brand)",
                  background: "var(--color-brand-bg-subtle)",
                  cursor: "pointer",
                  textAlign: "left",
                }}
              >
                <div className="tf-body" style={{ fontWeight: 600, color: "var(--color-brand)" }}>
                  最近完成：{selectedScenario.latest_simulation_id}
                </div>
                <div className="tf-caption" style={{ color: "var(--color-foreground-tertiary)" }}>
                  方案：{selectedScenario.name}
                </div>
              </button>
            </div>
          </StepCard>
        )}

        {step === 3 && selectedScenario && (
          <StepCard title="步骤 3：选择数据">
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              <div>
                <h4 className="tf-subtitle" style={{ marginBottom: 8 }}>
                  参数文件
                </h4>
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
                    <input type="checkbox" checked={includeJson} onChange={(e) => setIncludeJson(e.target.checked)} />
                    <FileJson size={16} color="var(--color-foreground-tertiary)" />
                    <span className="tf-body">effective_parameters.json</span>
                  </label>
                  <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
                    <input type="checkbox" checked={includeCsv} onChange={(e) => setIncludeCsv(e.target.checked)} />
                    <FileSpreadsheet size={16} color="var(--color-foreground-tertiary)" />
                    <span className="tf-body">effective_parameters.csv</span>
                  </label>
                </div>
              </div>

              <div>
                <h4 className="tf-subtitle" style={{ marginBottom: 8 }}>
                  结果族
                </h4>
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {families.map((family) => (
                    <label
                      key={family.family_id}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 8,
                        padding: 10,
                        borderRadius: "var(--radius-medium)",
                        border: "1px solid var(--color-border)",
                        background: "var(--color-surface)",
                        cursor: "pointer",
                      }}
                    >
                      <input type="checkbox" checked={selectedFamilies.has(family.family_id)} onChange={() => handleToggleFamily(family.family_id)} />
                      <Folder size={16} color="var(--color-foreground-tertiary)" />
                      <span className="tf-body" style={{ flex: 1 }}>
                        {family.label}
                      </span>
                      <span className="tf-caption" style={{ color: "var(--color-foreground-tertiary)" }}>
                        {family.file_count} 个文件
                      </span>
                    </label>
                  ))}
                </div>
              </div>

              <div style={{ display: "flex", justifyContent: "flex-end", gap: 12 }}>
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
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              <div
                style={{
                  padding: 16,
                  borderRadius: "var(--radius-large)",
                  background: "var(--color-surface-tertiary)",
                  display: "flex",
                  flexDirection: "column",
                  gap: 8,
                }}
              >
                <div className="tf-body" style={{ fontWeight: 600 }}>
                  {selectedScenario.name}_{new Date().toISOString().slice(0, 10)}.zip
                </div>
                <div className="tf-caption" style={{ color: "var(--color-foreground-secondary)" }}>
                  已选择 {selectedFamilies.size} 个结果族，参数文件 {includeJson || includeCsv ? "已包含" : "未包含"}
                </div>
              </div>

              {exports.filter((e) => e.scenario_id === selectedScenario.scenario_id).length > 0 && (
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {exports
                    .filter((e) => e.scenario_id === selectedScenario.scenario_id)
                    .map((e) => (
                      <div
                        key={e.export_id}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "space-between",
                          padding: 12,
                          borderRadius: "var(--radius-medium)",
                          border: "1px solid var(--color-border)",
                          background: "var(--color-surface)",
                        }}
                      >
                        <div>
                          <div className="tf-body">{e.export_id}</div>
                          <div className="tf-caption" style={{ color: "var(--color-foreground-tertiary)" }}>
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

              <div style={{ display: "flex", justifyContent: "flex-end", gap: 12 }}>
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
    <div
      style={{
        padding: 24,
        borderRadius: "var(--radius-xlarge)",
        border: "1px solid var(--color-border)",
        background: "var(--color-surface)",
        boxShadow: "var(--shadow-rest)",
      }}
    >
      <h2 className="tf-title" style={{ marginBottom: 16 }}>
        {title}
      </h2>
      {children}
    </div>
  );
}
