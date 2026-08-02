import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
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

export function ResultModule({ scenario }: { scenario: Scenario }) {
  const navigate = useNavigate();
  const resultFamilies = useTaichiFlowStore((state) => state.resultFamilies);
  const fetchResultFamilies = useTaichiFlowStore((state) => state.fetchResultFamilies);
  const [selectedFamily, setSelectedFamily] = useState<string | null>(null);

  useEffect(() => {
    if (scenario.latest_simulation_id) {
      fetchResultFamilies(scenario.latest_simulation_id);
    }
  }, [scenario.latest_simulation_id, fetchResultFamilies]);

  const families = scenario.latest_simulation_id ? resultFamilies[scenario.latest_simulation_id] || [] : [];

  if (scenario.status !== "completed") {
    return (
      <div style={{ padding: 32, textAlign: "center" }}>
        <p className="tf-body" style={{ color: "var(--color-foreground-secondary)" }}>
          该方案尚未完成模拟，暂无结果。
        </p>
        <p className="tf-caption" style={{ color: "var(--color-foreground-tertiary)", marginTop: 8 }}>
          当前状态：{scenario.status}
        </p>
      </div>
    );
  }

  return (
    <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 16, overflow: "auto" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span className="tf-caption" style={{ color: "var(--color-foreground-tertiary)" }}>
          模拟 ID: {scenario.latest_simulation_id}
        </span>
        <Button
          size="small"
          icon={<Download size={14} />}
          onClick={() => navigate(`/projects/${scenario.project_id}/export`)}
        >
          导出此方案
        </Button>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {families.length === 0 ? (
          <p className="tf-body" style={{ color: "var(--color-foreground-secondary)", textAlign: "center", padding: 24 }}>
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
    <div
      style={{
        borderRadius: "var(--radius-large)",
        border: `1px solid ${selected ? "var(--color-brand)" : "var(--color-border)"}`,
        background: selected ? "var(--color-brand-bg-subtle)" : "var(--color-surface)",
        overflow: "hidden",
      }}
    >
      <button
        onClick={onClick}
        style={{
          width: "100%",
          padding: 12,
          border: "none",
          background: "transparent",
          cursor: "pointer",
          textAlign: "left",
          display: "flex",
          alignItems: "center",
          gap: 10,
        }}
      >
        <span style={{ color: "var(--color-foreground-tertiary)", display: "inline-flex" }}>{familyIcon[family.family_id] || <Folder size={16} />}</span>
        <div style={{ flex: 1 }}>
          <div className="tf-body" style={{ fontWeight: 600, color: "var(--color-foreground)" }}>
            {family.label}
          </div>
          <div className="tf-caption" style={{ color: "var(--color-foreground-tertiary)" }}>
            {family.file_count} 个文件 · {(family.total_size / 1024 / 1024).toFixed(1)} MB
          </div>
        </div>
        <span style={{ transform: selected ? "rotate(180deg)" : "rotate(0)", transition: "transform 200ms ease", color: "var(--color-foreground-tertiary)" }}>▼</span>
      </button>
      {selected && (
        <div style={{ padding: "0 12px 12px", display: "flex", flexDirection: "column", gap: 8 }}>
          {family.files.slice(0, 5).map((file) => (
            <div
              key={file.filename}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: 8,
                borderRadius: "var(--radius-medium)",
                background: "var(--color-surface)",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                <FileText size={14} color="var(--color-foreground-tertiary)" />
                <span className="tf-caption tf-ellipsis" style={{ color: "var(--color-foreground)" }}>
                  {file.filename}
                </span>
              </div>
              <button style={{ color: "var(--color-brand)", display: "flex", alignItems: "center" }} title="下载" aria-label="下载" disabled={!simulationId} onClick={() => simulationId && window.open(resultApi.downloadUrl(projectId, simulationId, file.source_filename || file.filename), "_blank", "noopener,noreferrer")}>
                <Download size={14} />
              </button>
            </div>
          ))}
          {family.files.length > 5 && (
            <div className="tf-caption" style={{ color: "var(--color-foreground-tertiary)", textAlign: "center" }}>
              还有 {family.files.length - 5} 个文件
            </div>
          )}
        </div>
      )}
    </div>
  );
}
