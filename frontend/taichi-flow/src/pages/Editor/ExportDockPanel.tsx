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

export function ExportDockPanel() {
  const activeProject = useTaichiFlowStore((state) => state.activeProject);
  const scenarios = useTaichiFlowStore((state) => state.scenarios);
  const resultFamilies = useTaichiFlowStore((state) => state.resultFamilies);
  const fetchResultFamilies = useTaichiFlowStore((state) => state.fetchResultFamilies);
  const createExport = useTaichiFlowStore((state) => state.createExport);
  const exports = useTaichiFlowStore((state) => state.exports);
  const editorSelection = useTaichiFlowStore((state) => state.editorSelection);

  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [selectedScenario, setSelectedScenario] = useState<Scenario | null>(null);
  const [selectedFamilies, setSelectedFamilies] = useState<Set<string>>(new Set());
  const [includeJson, setIncludeJson] = useState(true);
  const [includeCsv, setIncludeCsv] = useState(true);
  const [creating, setCreating] = useState(false);

  const completedScenarios = useMemo(() => scenarios.filter((item) => item.status === "completed"), [scenarios]);
  const families = selectedScenario?.latest_simulation_id ? resultFamilies[selectedScenario.latest_simulation_id] || [] : [];

  useEffect(() => {
    const preferredId =
      editorSelection?.kind === "result" || editorSelection?.kind === "scenario" ? editorSelection.scenarioId : undefined;
    const preferred = completedScenarios.find((item) => item.scenario_id === preferredId) || completedScenarios[0] || null;
    if (preferred && !selectedScenario) {
      setSelectedScenario(preferred);
      if (preferred.latest_simulation_id) void fetchResultFamilies(preferred.latest_simulation_id);
    }
  }, [completedScenarios, editorSelection, fetchResultFamilies, selectedScenario]);

  if (!activeProject) {
    return <div className="tf-dock-empty tf-caption">请先打开项目。</div>;
  }

  if (completedScenarios.length === 0) {
    return <div className="tf-dock-empty tf-caption tf-text-tertiary">没有已完成的方案，完成模拟后可在此导出。</div>;
  }

  const handleCreate = async () => {
    if (!selectedScenario?.latest_simulation_id) return;
    setCreating(true);
    try {
      await createExport(selectedScenario.scenario_id, selectedScenario.latest_simulation_id, {
        selected_families: Array.from(selectedFamilies),
        selected_files: [],
        include_parameters_json: includeJson,
        include_parameters_csv: includeCsv,
      });
      setStep(3);
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="tf-dock-panel tf-dock-export">
      <div className="tf-row tf-gap-2 tf-mb-2">
        <select
          className="tf-select"
          value={selectedScenario?.scenario_id || ""}
          onChange={(event) => {
            const next = completedScenarios.find((item) => item.scenario_id === event.target.value) || null;
            setSelectedScenario(next);
            setStep(1);
            setSelectedFamilies(new Set());
            if (next?.latest_simulation_id) void fetchResultFamilies(next.latest_simulation_id);
          }}
        >
          {completedScenarios.map((item) => (
            <option key={item.scenario_id} value={item.scenario_id}>
              {item.name}
            </option>
          ))}
        </select>
        <span className="tf-chip">步骤 {step}/3</span>
      </div>

      {step === 1 && selectedScenario ? (
        <div className="tf-stack-sm">
          <label className="tf-check-row">
            <input type="checkbox" checked={includeJson} onChange={(event) => setIncludeJson(event.target.checked)} />
            <FileJson size={14} />
            <span className="tf-caption">effective_parameters.json</span>
          </label>
          <label className="tf-check-row">
            <input type="checkbox" checked={includeCsv} onChange={(event) => setIncludeCsv(event.target.checked)} />
            <FileSpreadsheet size={14} />
            <span className="tf-caption">effective_parameters.csv</span>
          </label>
          {families.map((family) => (
            <label key={family.family_id} className="tf-check-row">
              <input
                type="checkbox"
                checked={selectedFamilies.has(family.family_id)}
                onChange={() =>
                  setSelectedFamilies((prev) => {
                    const next = new Set(prev);
                    if (next.has(family.family_id)) next.delete(family.family_id);
                    else next.add(family.family_id);
                    return next;
                  })
                }
              />
              <Folder size={14} />
              <span className="tf-caption">{family.label}</span>
            </label>
          ))}
          <Button size="small" icon={<Check size={14} />} onClick={() => setStep(2)} disabled={selectedFamilies.size === 0 && !includeJson && !includeCsv}>
            确认选择
          </Button>
        </div>
      ) : null}

      {step === 2 && selectedScenario ? (
        <div className="tf-stack-sm">
          <div className="tf-caption">
            将导出 {selectedScenario.name} · {selectedFamilies.size} 个结果族
          </div>
          <div className="tf-row tf-gap-2">
            <Button size="small" variant="secondary" onClick={() => setStep(1)}>
              上一步
            </Button>
            <Button size="small" icon={<Download size={14} />} onClick={() => void handleCreate()} disabled={creating}>
              {creating ? "生成中…" : "生成导出包"}
            </Button>
          </div>
        </div>
      ) : null}

      {step === 3 && selectedScenario ? (
        <div className="tf-stack-sm">
          {exports
            .filter((item) => item.scenario_id === selectedScenario.scenario_id)
            .slice(0, 5)
            .map((item) => (
              <div key={item.export_id} className="tf-dock-queue-row">
                <div className="tf-dock-queue-main">
                  <span className="tf-caption tf-ellipsis">{item.export_id}</span>
                  <span className="tf-caption tf-text-tertiary">
                    {formatSize(item.total_size)} · {item.file_count} 文件
                  </span>
                  {item.status === "completed" ? (
                    <Button
                      size="small"
                      icon={<Download size={12} />}
                      onClick={() => window.open(exportApi.downloadUrl(activeProject.project_id, item.export_id), "_blank", "noopener,noreferrer")}
                    >
                      下载
                    </Button>
                  ) : (
                    <StatusBadge variant={item.status === "failed" ? "error" : "running"} />
                  )}
                </div>
              </div>
            ))}
          <Button size="small" variant="secondary" onClick={() => setStep(1)}>
            继续导出
          </Button>
        </div>
      ) : null}
    </div>
  );
}
