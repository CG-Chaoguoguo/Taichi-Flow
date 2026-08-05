import { useEffect, useState } from "react";
import { BarChart3, Download, FileText, Folder, Waves } from "lucide-react";
import { useTaichiFlowStore } from "../../stores/taichiFlowStore";
import { Button } from "../../components/Button";
import type { Scenario, ResultFamily } from "../../types";
import { resultApi } from "../../api/taichiFlowAdapter";

const familyIcon: Record<string, React.ReactNode> = {
  flow_depth: <Waves size={16} />,
  max_flow_depth: <Waves size={16} />,
  flow_velocity: <Waves size={16} />,
  max_flow_velocity: <Waves size={16} />,
  outnq: <BarChart3 size={16} />,
  hydrograph: <BarChart3 size={16} />,
};

export function ResultModule({ scenario, readOnly = false }: { scenario: Scenario; readOnly?: boolean }) {
  const resultFamilies = useTaichiFlowStore((state) => state.resultFamilies);
  const fetchResultFamilies = useTaichiFlowStore((state) => state.fetchResultFamilies);
  const setDockTab = useTaichiFlowStore((state) => state.setDockTab);
  const [selectedFamily, setSelectedFamily] = useState<string | null>(null);

  useEffect(() => {
    if (!readOnly && scenario.latest_simulation_id) {
      fetchResultFamilies(scenario.latest_simulation_id);
    }
  }, [readOnly, scenario.latest_simulation_id, fetchResultFamilies]);

  const families = scenario.latest_simulation_id ? resultFamilies[scenario.latest_simulation_id] || [] : [];

  if (readOnly) {
    return (
      <div className="tf-empty tf-body tf-text-secondary">
        打开项目并完成模拟后，可在此查看结果族。
      </div>
    );
  }

  if (scenario.status !== "completed") {
    return (
      <div className="tf-empty">
        <p className="tf-body tf-text-secondary">
          该方案尚未完成模拟，暂无结果。
        </p>
        <p className="tf-caption tf-text-tertiary tf-mt-2">
          当前状态：{scenario.status}
        </p>
      </div>
    );
  }

  return (
    <div className="tf-module-body tf-stack tf-module-scroll">
      <div className="tf-row tf-justify-between">
        <span className="tf-caption tf-text-tertiary">
          模拟 ID: {scenario.latest_simulation_id}
        </span>
        <Button
          size="small"
          icon={<Download size={14} />}
          onClick={() => setDockTab("export")}
        >
          导出此方案
        </Button>
      </div>

      <div className="tf-stack-sm">
        {families.length === 0 ? (
          <p className="tf-empty tf-body tf-text-secondary">
            暂无结果族数据
          </p>
        ) : (
          families.map((family) => (
            <ResultFamilyItem
              key={family.family_id}
              family={family}
              projectId={scenario.project_id}
              simulationId={scenario.latest_simulation_id}
              selected={selectedFamily === family.family_id}
              onClick={() => setSelectedFamily(selectedFamily === family.family_id ? null : family.family_id)}
            />
          ))
        )}
      </div>
    </div>
  );
}

function ResultFamilyItem({
  family,
  projectId,
  simulationId,
  selected,
  onClick,
}: {
  family: ResultFamily;
  projectId: string;
  simulationId: string | null;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <div className={`tf-card tf-card-flush${selected ? " active" : ""}`}>
      <button type="button" onClick={onClick} className="tf-card-trigger">
        <span className="tf-icon-inline">{familyIcon[family.family_id] || <Folder size={16} />}</span>
        <div className="tf-flex-1">
          <div className="tf-body tf-font-semibold">
            {family.label}
          </div>
          <div className="tf-caption tf-text-tertiary">
            {family.file_count} 个文件 · {(family.total_size / 1024 / 1024).toFixed(1)} MB
          </div>
        </div>
        <span className={`tf-chevron${selected ? " is-expanded" : ""}`}>▼</span>
      </button>
      {selected && (
        <div className="tf-card-detail">
          {family.files.slice(0, 5).map((file) => (
            <div key={file.filename} className="tf-inset tf-row tf-inset-row">
              <div className="tf-row tf-gap-2 tf-min-w-0">
                <FileText size={14} className="tf-text-tertiary" />
                <span className="tf-caption tf-ellipsis">
                  {file.filename}
                </span>
              </div>
              <button
                type="button"
                className="tf-icon-link"
                title="下载"
                aria-label="下载"
                disabled={!simulationId}
                onClick={() => simulationId && window.open(resultApi.downloadUrl(projectId, simulationId, file.source_filename || file.filename), "_blank", "noopener,noreferrer")}
              >
                <Download size={14} />
              </button>
            </div>
          ))}
          {family.files.length > 5 && (
            <div className="tf-caption tf-text-tertiary tf-text-center">
              还有 {family.files.length - 5} 个文件
            </div>
          )}
        </div>
      )}
    </div>
  );
}
