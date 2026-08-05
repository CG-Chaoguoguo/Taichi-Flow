import { useEffect } from "react";
import { RefreshCw } from "lucide-react";
import { useTaichiFlowStore } from "../../stores/taichiFlowStore";
import { Button } from "../../components/Button";
import { EddaFlagsSection } from "../../components/EddaFlagsSection";

function MetricRow({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <div className="tf-row tf-justify-between tf-gap-2">
      <span className="tf-caption tf-text-secondary">{label}</span>
      <span className="tf-mono">{value ?? "—"}</span>
    </div>
  );
}

export function EddaConfigPanel({
  revisionId,
}: {
  revisionId?: string | null;
  draftPatch?: Record<string, unknown>;
  onDraftChange?: (patch: Record<string, unknown>) => void;
  canEdit?: boolean;
  onRequestManningUpload?: () => void;
}) {
  const caseConfig = useTaichiFlowStore((state) => state.caseConfigInterface);
  const fetchCaseConfigInterface = useTaichiFlowStore((state) => state.fetchCaseConfigInterface);
  const inputRevisions = useTaichiFlowStore((state) => state.inputRevisions);

  const resolvedRevision =
    revisionId ||
    inputRevisions.find((item) => item.status === "ready")?.revision_id ||
    inputRevisions[0]?.revision_id ||
    null;

  useEffect(() => {
    if (resolvedRevision) void fetchCaseConfigInterface(resolvedRevision);
  }, [resolvedRevision, fetchCaseConfigInterface]);

  const rainfall = caseConfig?.parsed_values?.rainfall;
  const manning = caseConfig?.parsed_values?.manning;
  const time = caseConfig?.parsed_values?.time;
  const rheology = caseConfig?.parsed_values?.rheology;
  const doubleLayer = caseConfig?.parsed_values?.double_layer;
  const unsupported = caseConfig?.audit?.recognized_unsupported_fields || [];

  if (!resolvedRevision) {
    return (
      <div className="tf-module-body tf-stack">
        <div className="tf-empty tf-body tf-text-tertiary">请先选择一个历史运行快照，或上传 edda_in 并使用“导入参数配置”。</div>
      </div>
    );
  }

  if (!caseConfig) {
    return (
      <div className="tf-module-body tf-stack">
        <div className="tf-empty tf-body tf-text-tertiary">正在解析 edda_in…</div>
        <Button size="small" icon={<RefreshCw size={14} />} onClick={() => void fetchCaseConfigInterface(resolvedRevision)}>
          重新解析
        </Button>
      </div>
    );
  }

  return (
    <div className="tf-module-body tf-stack tf-module-scroll" data-testid="edda-config-panel">
      <div className="tf-row tf-justify-between">
        <div>
          <div className="tf-body tf-font-semibold">{caseConfig.case_config_name || "edda_in"}</div>
          <div className="tf-caption tf-text-tertiary">案例根目录：{caseConfig.case_base_dir || "—"}</div>
        </div>
        <Button size="small" variant="secondary" icon={<RefreshCw size={14} />} onClick={() => void fetchCaseConfigInterface(resolvedRevision)}>
          刷新
        </Button>
      </div>

      <section className="tf-card tf-card-flush tf-config-section">
        <div className="tf-body tf-group-header tf-font-semibold">解析摘要</div>
        <div className="tf-card-body-sm tf-stack tf-gap-1">
          <MetricRow label="降雨模式" value={rainfall?.mode} />
          <MetricRow label="降雨时段数" value={rainfall?.periods?.length ?? rainfall?.cri_mps?.length} />
          <MetricRow label="曼宁来源" value={manning?.source} />
          <MetricRow label="全局曼宁" value={manning?.global} />
          <MetricRow label="模拟时长 simul" value={time?.simul} />
          <MetricRow label="输出间隔 tout" value={time?.tout} />
        </div>
      </section>

      <div className="tf-info-banner tf-caption">
        此处仅展示旧 edda_in 的只读解析结果。参数导入请使用方案“参数”标签；文件收录请使用“旧项目迁移向导”。
      </div>

      <section className="tf-card tf-card-flush tf-config-section">
        <div className="tf-body tf-group-header tf-font-semibold">时间 / 流变 / 土层</div>
        <div className="tf-card-body-sm tf-stack tf-gap-1">
          <MetricRow label="dtmin" value={time?.dtmin} />
          <MetricRow label="dtmax" value={time?.dtmax} />
          <MetricRow label="wavemax" value={time?.wavemax} />
          <MetricRow label="alpha1" value={rheology?.alpha1} />
          <MetricRow label="beta1" value={rheology?.beta1} />
          <MetricRow label="d50" value={rheology?.d50} />
          <MetricRow label="depth" value={doubleLayer?.depth} />
          <MetricRow label="rizero" value={doubleLayer?.rizero} />
          <MetricRow label="uww" value={doubleLayer?.uww} />
          <MetricRow label="ltstar" value={doubleLayer?.ltstar} />
          <MetricRow label="lbstar" value={doubleLayer?.lbstar} />
        </div>
      </section>

      <EddaFlagsSection caseConfig={caseConfig} />

      <section className="tf-card tf-card-flush tf-config-section">
        <div className="tf-body tf-group-header tf-font-semibold">文件输入审计</div>
        <div className="tf-card-body-sm">
          {(caseConfig.file_inputs || []).length === 0 ? (
            <div className="tf-caption tf-text-tertiary">无文件输入记录。</div>
          ) : (
            <div className="tf-period-table-wrap">
              <table className="tf-period-table">
                <thead>
                  <tr>
                    <th>族</th>
                    <th>状态</th>
                    <th>存在</th>
                    <th>备注</th>
                  </tr>
                </thead>
                <tbody>
                  {caseConfig.file_inputs.map((item) => {
                    const exists = item.exists || [];
                    const ok = exists.filter(Boolean).length;
                    return (
                      <tr key={item.family}>
                        <td className="tf-mono">{item.family}</td>
                        <td>{item.runtime_status || item.production_status || "—"}</td>
                        <td className="tf-mono">
                          {exists.length ? `${ok}/${exists.length}` : "—"}
                        </td>
                        <td className="tf-caption">{item.notes || item.blocked_reason || "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>

      {unsupported.length > 0 ? (
        <section className="tf-card tf-card-flush tf-config-section">
          <div className="tf-body tf-group-header tf-font-semibold">已识别但未支持的字段</div>
          <div className="tf-card-body-sm tf-caption tf-text-tertiary">{unsupported.join(" · ")}</div>
        </section>
      ) : null}
    </div>
  );
}
