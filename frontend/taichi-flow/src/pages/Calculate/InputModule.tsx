import { useEffect, useRef, useState } from "react";
import { AlertCircle, FileText, Info, Layers, Map, Monitor, Waves } from "lucide-react";
import { useTaichiFlowStore } from "../../stores/taichiFlowStore";
import { StatusBadge } from "../../components/StatusBadge";
import type { InputFile } from "../../types";

const familyLabels: Record<string, string> = {
  dem: "地形栅格",
  slope: "坡度栅格",
  zones: "分区栅格",
  thickness: "上层厚度",
  manning: "空间曼宁",
  rainfall: "降雨文件",
  groundwater: "地下水深",
  infiltration: "初始入渗",
  boundary: "边界文件",
  outflow: "出流边界",
  inflow: "入流过程",
  monitoring: "监测点选择",
  config: "参数配置",
};

const familyIcons: Record<string, React.ReactNode> = {
  dem: <Map size={16} />,
  slope: <Map size={16} />,
  zones: <Layers size={16} />,
  boundary: <Map size={16} />,
  rainfall: <Waves size={16} />,
  inflow: <Waves size={16} />,
  outflow: <Waves size={16} />,
  monitoring: <Monitor size={16} />,
  config: <FileText size={16} />,
};

function fileStatusBadge(status: InputFile["status"]) {
  switch (status) {
    case "ready":
      return <StatusBadge variant="success">就绪</StatusBadge>;
    case "warning":
      return <StatusBadge variant="warning">警告</StatusBadge>;
    case "invalid":
      return <StatusBadge variant="error">错误</StatusBadge>;
    case "unsupported":
      return <StatusBadge variant="neutral">不支持</StatusBadge>;
    case "parsing":
    case "visualizing":
      return <StatusBadge variant="info">处理中</StatusBadge>;
    case "metadata_only":
      return <StatusBadge variant="neutral">仅元数据</StatusBadge>;
    default:
      return <StatusBadge variant="neutral">未知</StatusBadge>;
  }
}

export function InputModule({ onFocusLayer }: { onFocusLayer: (id: string) => void }) {
  const inputFiles = useTaichiFlowStore((state) => state.inputFiles);
  const fetchInputFiles = useTaichiFlowStore((state) => state.fetchInputFiles);
  const uploadInput = useTaichiFlowStore((state) => state.uploadInput);
  const createInputRevision = useTaichiFlowStore((state) => state.createInputRevision);
  const addToast = useTaichiFlowStore((state) => state.addToast);
  const fileInput = useRef<HTMLInputElement>(null);
  const [uploadFamily, setUploadFamily] = useState("dem");

  useEffect(() => {
    fetchInputFiles();
  }, [fetchInputFiles]);

  const readyCount = inputFiles.filter((f) => f.status === "ready").length;

  return (
    <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 16 }}>
      <div
        style={{
          padding: 12,
          borderRadius: "var(--radius-large)",
          background: "var(--color-surface-tertiary)",
          display: "flex",
          alignItems: "center",
          gap: 10,
        }}
      >
        <Info size={16} color="var(--color-info)" />
        <span className="tf-caption" style={{ color: "var(--color-foreground-secondary)" }}>
          输入文件由项目共享，参数方案只读。修改输入将创建新的输入版本。
        </span>
      </div>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span className="tf-caption" style={{ color: "var(--color-foreground-secondary)" }}>
          {readyCount}/{inputFiles.length} 个文件就绪
        </span>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <select value={uploadFamily} onChange={(event) => setUploadFamily(event.target.value)} aria-label="输入文件族">
            {Object.entries(familyLabels).map(([family, label]) => <option key={family} value={family}>{label}</option>)}
          </select>
          <input
            ref={fileInput}
            type="file"
            hidden
            onChange={async (event) => {
              const file = event.target.files?.[0];
              if (!file) return;
              try {
                await uploadInput(uploadFamily, file);
                addToast({ type: "success", message: `${familyLabels[uploadFamily] || "输入文件"}已上传` });
              } catch (error) {
                addToast({ type: "error", message: error instanceof Error ? error.message : "输入文件上传失败" });
              } finally {
                event.target.value = "";
              }
            }}
          />
          <button
          className="tf-caption"
          style={{ color: "var(--color-brand)", cursor: "pointer", background: "transparent", border: "none" }}
          onClick={() => fileInput.current?.click()}
          >
          管理项目输入
          </button>
          <button
            className="tf-caption"
            style={{ color: "var(--color-brand)", cursor: inputFiles.length ? "pointer" : "not-allowed", background: "transparent", border: "none" }}
            disabled={inputFiles.length === 0}
            onClick={async () => {
              try {
                await createInputRevision(inputFiles.map((file) => file.file_id));
                addToast({ type: "success", message: "输入修订已发布" });
              } catch (error) {
                addToast({ type: "error", message: error instanceof Error ? error.message : "输入修订发布失败" });
              }
            }}
          >
            发布修订
          </button>
        </div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {inputFiles.length === 0 ? (
          <div className="tf-body" style={{ padding: 24, textAlign: "center", color: "var(--color-foreground-tertiary)" }}>暂无输入文件，请先上传。</div>
        ) : inputFiles.map((file) => (
          <button
            key={file.file_id}
            onClick={() => onFocusLayer(file.file_id)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              padding: "10px 12px",
              borderRadius: "var(--radius-large)",
              border: "1px solid var(--color-border)",
              background: "var(--color-surface)",
              cursor: "pointer",
              textAlign: "left",
              width: "100%",
              transition: "background-color 120ms ease",
            }}
            onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "var(--color-surface-hover)")}
            onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "var(--color-surface)")}
          >
            <span style={{ color: "var(--color-foreground-tertiary)", display: "inline-flex" }}>{familyIcons[file.family] || <FileText size={16} />}</span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="tf-body tf-ellipsis" style={{ fontWeight: 500 }}>
                {file.name}
              </div>
              <div className="tf-caption" style={{ color: "var(--color-foreground-tertiary)" }}>
                {familyLabels[file.family]} · {(file.size / 1024).toFixed(1)} KB
              </div>
              {file.warnings && file.warnings.length > 0 && (
                <div className="tf-caption" style={{ color: "var(--color-warning)", display: "flex", alignItems: "center", gap: 4, marginTop: 4 }}>
                  <AlertCircle size={12} />
                  {file.warnings[0]}
                </div>
              )}
            </div>
            {fileStatusBadge(file.status)}
          </button>
        ))}
      </div>
    </div>
  );
}
