import { AlertTriangle, ArchiveRestore, CheckCircle2, ChevronDown, ChevronUp } from "lucide-react";
import { useState } from "react";
import { migrationApi } from "../api/taichiFlowAdapter";
import { useTaichiFlowStore } from "../stores/taichiFlowStore";
import type { LegacyMigrationPlan, Scenario } from "../types";
import { Button } from "./Button";

export function LegacyMigrationWizard({ scenario }: { scenario: Scenario }) {
  const project = useTaichiFlowStore((state) => state.activeProject);
  const fetchScenarios = useTaichiFlowStore((state) => state.fetchScenarios);
  const fetchInputFiles = useTaichiFlowStore((state) => state.fetchInputFiles);
  const fetchParameterTemplates = useTaichiFlowStore((state) => state.fetchParameterTemplates);
  const addToast = useTaichiFlowStore((state) => state.addToast);
  const [plan, setPlan] = useState<LegacyMigrationPlan | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [reportPath, setReportPath] = useState("");

  if (scenario.parameter_template_id) return null;

  const preview = async () => {
    if (!project) return;
    setBusy(true);
    try {
      setPlan(await migrationApi.previewLegacy(project.project_id, scenario.scenario_id));
      setExpanded(true);
    } catch (error) {
      addToast({ type: "error", message: error instanceof Error ? error.message : "迁移预览失败" });
    } finally {
      setBusy(false);
    }
  };

  const commit = async () => {
    if (!project || !plan) return;
    setBusy(true);
    try {
      const result = await migrationApi.commitLegacy(project.project_id, scenario.scenario_id, plan.scenario_version || scenario.version || 1);
      setReportPath(result.report_path);
      await Promise.all([fetchScenarios(), fetchInputFiles(), fetchParameterTemplates()]);
      addToast({ type: "success", message: "旧项目已迁移为结构化参数与输入快照" });
    } catch (error) {
      addToast({ type: "error", message: error instanceof Error ? error.message : "旧项目迁移失败" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="tf-legacy-wizard" data-qoder="legacy-migration-wizard">
      <div className="tf-row tf-gap-2">
        <ArchiveRestore size={16} />
        <div className="tf-flex-1">
          <div className="tf-body tf-font-semibold">旧项目兼容模式</div>
          <div className="tf-caption tf-text-tertiary">当前方案仍引用 edda_in。只有此向导会读取其中的路径；普通参数导入永远忽略路径。</div>
        </div>
      </div>
      {!plan ? (
        <Button size="small" fullWidth disabled={busy} onClick={() => void preview()}>{busy ? "正在解析…" : "生成迁移预览"}</Button>
      ) : (
        <div className="tf-stack tf-gap-2">
          <button type="button" className="tf-wizard-summary" onClick={() => setExpanded((value) => !value)}>
            <span><strong>{plan.existing_file_count}</strong> 个可收录 · <strong>{plan.missing_file_count}</strong> 个缺失 · <strong>{plan.proposed_bindings.length}</strong> 个拟绑定</span>
            {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
          {plan.unresolved_active_count > 0 ? (
            <div className="tf-inline-alert tf-inline-alert-danger" role="alert">
              <AlertTriangle size={14} />
              <span>{plan.unresolved_active_count} 个活动输入缺失；迁移可保存，但补齐前将阻止新运行。</span>
            </div>
          ) : null}
          {expanded ? (
            <div className="tf-migration-reference-list">
              {plan.file_references.map((reference) => (
                <div key={`${reference.native_family}-${reference.ordinal}`} className="tf-migration-reference">
                  {reference.exists ? <CheckCircle2 size={13} className="tf-text-success" /> : <AlertTriangle size={13} className="tf-text-warning" />}
                  <span className="tf-mono">{reference.native_family}</span>
                  <span className="tf-ellipsis" title={reference.path}>{reference.path}</span>
                  <span>{reference.active ? "活动" : "未激活"}</span>
                </div>
              ))}
            </div>
          ) : null}
          <div className="tf-caption tf-text-tertiary">提交前不会复制任何文件；提交后保留旧修订 ID 和回退信息，不重写历史运行。</div>
          <div className="tf-row tf-gap-2">
            <Button variant="ghost" size="small" onClick={() => setPlan(null)}>取消</Button>
            <Button variant="primary" size="small" disabled={busy} onClick={() => void commit()}>{busy ? "正在收录…" : "确认收录并迁移"}</Button>
          </div>
        </div>
      )}
      {reportPath ? <div className="tf-caption tf-text-success">迁移报告：<span className="tf-mono">{reportPath}</span></div> : null}
    </section>
  );
}
