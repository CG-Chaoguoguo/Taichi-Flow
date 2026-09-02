import { CheckCircle2, FileCheck2, FolderOpen, GitBranch, ShieldCheck, Upload, X } from "lucide-react";
import { useState } from "react";
import { casesApi } from "../api/taichiFlowAdapter";
import type { CaseImportCommitResult, CaseImportPreview } from "../types";
import { useTaichiFlowStore } from "../stores/taichiFlowStore";
import { Button } from "./Button";
import { DirectoryPickerDialog } from "./DirectoryPickerDialog";

type PickerTarget = "source" | "destination" | null;

function suggestedDestination(source: string): string {
  const normalized = source.trim().replace(/[\\/]+$/, "");
  return normalized ? `${normalized}-taichi-flow` : "";
}

export function LegacyCaseImportDialog({
  onClose,
  onCommitted,
}: {
  onClose: () => void;
  onCommitted: (result: CaseImportCommitResult) => void;
}) {
  const addToast = useTaichiFlowStore((state) => state.addToast);
  const [sourceRoot, setSourceRoot] = useState("");
  const [destinationRoot, setDestinationRoot] = useState("");
  const [caseName, setCaseName] = useState("");
  const [description, setDescription] = useState("");
  const [preview, setPreview] = useState<CaseImportPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [pickerTarget, setPickerTarget] = useState<PickerTarget>(null);

  const chooseNativeDirectory = async (target: Exclude<PickerTarget, null>) => {
    const nativePicker = window.taichiFlowDesktop?.selectDirectory;
    if (!nativePicker) {
      setPickerTarget(target);
      return;
    }
    setBusy(true);
    try {
      const current = target === "source" ? sourceRoot : destinationRoot;
      const result = await nativePicker({ defaultPath: current.trim() || undefined });
      if (!result.canceled && result.path) {
        if (target === "source") {
          setSourceRoot(result.path);
          if (!destinationRoot.trim()) setDestinationRoot(suggestedDestination(result.path));
        } else setDestinationRoot(result.path);
      }
    } catch (error) {
      addToast({ type: "error", message: error instanceof Error ? error.message : "无法打开系统目录窗口" });
    } finally {
      setBusy(false);
    }
  };

  const runPreview = async () => {
    if (!sourceRoot.trim()) return;
    setBusy(true);
    try {
      const next = await casesApi.previewImport(sourceRoot.trim());
      setPreview(next);
      if (!destinationRoot.trim()) setDestinationRoot(suggestedDestination(sourceRoot));
    } catch (error) {
      addToast({ type: "error", message: error instanceof Error ? error.message : "兼容算例预览失败" });
    } finally {
      setBusy(false);
    }
  };

  const commit = async () => {
    if (!preview || !destinationRoot.trim() || !preview.commit_allowed) return;
    setBusy(true);
    try {
      const result = await casesApi.commitImport({
        source_root: preview.source_root,
        destination_root: destinationRoot.trim(),
        expected_fingerprint: preview.case_fingerprint,
        name: caseName.trim() || preview.case_name,
        description: description.trim(),
      });
      onCommitted(result);
    } catch (error) {
      addToast({ type: "error", message: error instanceof Error ? error.message : "兼容算例导入失败" });
    } finally {
      setBusy(false);
    }
  };

  const summary = preview?.case_summary;
  const variantEntries = preview ? Object.entries(preview.variants).filter(([, value]) => value) : [];
  const sidecars = preview ? Object.values(preview.sidecars) : [];

  return (
    <div className="tf-dialog-overlay" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="tf-dialog tf-dialog-wide tf-acrylic" role="dialog" aria-modal="true" aria-labelledby="legacy-case-import-title">
        <div className="tf-dialog-header tf-row tf-gap-3">
          <div className="tf-icon-badge"><Upload size={17} /></div>
          <div className="tf-flex-1">
            <h2 id="legacy-case-import-title" className="tf-title tf-mb-1">导入兼容算例</h2>
            <p className="tf-caption tf-text-secondary">读取原始 edda_in 与活动输入，复制到独立项目；原目录不会写入，路径不会进入运行参数。</p>
          </div>
          <button type="button" className="tf-icon-button" aria-label="关闭" onClick={onClose}><X size={17} /></button>
        </div>

        <div className="tf-dialog-body tf-stack tf-gap-4">
          <div className="tf-form-grid tf-form-grid--two">
            <label className="tf-form-field">
              <span className="tf-caption tf-text-secondary">原始算例目录</span>
              <div className="tf-input-row">
                <input className="tf-input tf-mono tf-flex-1" value={sourceRoot} onChange={(event) => setSourceRoot(event.target.value)} placeholder="C:\\…\\原始案例目录" />
                <Button type="button" size="small" variant="secondary" icon={<FolderOpen size={14} />} onClick={() => void chooseNativeDirectory("source")} disabled={busy}>选择</Button>
              </div>
            </label>
            <label className="tf-form-field">
              <span className="tf-caption tf-text-secondary">独立目标目录</span>
              <div className="tf-input-row">
                <input className="tf-input tf-mono tf-flex-1" value={destinationRoot} onChange={(event) => setDestinationRoot(event.target.value)} placeholder="C:\\…\\目标项目目录" />
                <Button type="button" size="small" variant="secondary" icon={<FolderOpen size={14} />} onClick={() => void chooseNativeDirectory("destination")} disabled={busy}>选择</Button>
              </div>
            </label>
          </div>
          <div className="tf-form-grid tf-form-grid--two">
            <label className="tf-form-field"><span className="tf-caption tf-text-secondary">项目名称</span><input className="tf-input" value={caseName} onChange={(event) => setCaseName(event.target.value)} placeholder={preview?.case_name || "参考案例"} /></label>
            <label className="tf-form-field"><span className="tf-caption tf-text-secondary">说明（可选）</span><input className="tf-input" value={description} onChange={(event) => setDescription(event.target.value)} placeholder="保留原始 EDDA 语义的隔离验收项目" /></label>
          </div>

          {!preview ? (
            <div className="tf-info-banner tf-row tf-gap-2"><ShieldCheck size={16} /><span>预览阶段只读源目录；提交会校验指纹、活动输入和 DEM，再在目标目录原子生成项目。</span></div>
          ) : (
            <div className="tf-stack tf-gap-3" data-testid="legacy-case-import-preview">
              <div className="tf-row tf-justify-between tf-gap-3">
                <div className="tf-row tf-gap-2"><FileCheck2 size={17} className="tf-text-success" /><div><div className="tf-body tf-font-semibold">{preview.case_name}</div><div className="tf-caption tf-text-tertiary tf-mono">指纹 {preview.case_fingerprint.slice(0, 16)}…</div></div></div>
                <span className={`tf-source-chip${preview.commit_allowed ? " is-override" : ""}`}>{preview.commit_allowed ? "可提交" : "需补齐活动输入"}</span>
              </div>
              <div className="tf-metric-grid tf-metric-grid--compact">
                <div className="tf-metric-card"><span className="tf-caption tf-text-tertiary">网格</span><strong>{summary?.dimensions?.rows ?? "—"} × {summary?.dimensions?.cols ?? "—"}</strong><span className="tf-caption">{summary?.active_binding_count} 个活动绑定</span></div>
                <div className="tf-metric-card"><span className="tf-caption tf-text-tertiary">时间</span><strong>{summary?.simul_s}s / {summary?.tout_s}s</strong><span className="tf-caption">结束 / 输出间隔</span></div>
                <div className="tf-metric-card"><span className="tf-caption tf-text-tertiary">分区</span><strong>{summary?.nzon}</strong><span className="tf-caption">{summary?.rainfall_period_count} 个降雨时段 · {summary?.rainfall_mode}</span></div>
                <div className="tf-metric-card"><span className="tf-caption tf-text-tertiary">输入</span><strong>{summary?.active_binding_count}</strong><span className="tf-caption">活动文件 · 缺失声明 {summary?.missing_reference_count}</span></div>
              </div>
              <div className="tf-row tf-gap-2 tf-flex-wrap">
                <span className="tf-caption tf-text-tertiary">失稳/数值变种：</span>
                {variantEntries.map(([key, value]) => <span key={key} className="tf-source-chip"><GitBranch size={12} />{key}: {String(value)}</span>)}
              </div>
              <div className="tf-case-import-columns">
                <section className="tf-card tf-card-flush"><div className="tf-card-header tf-body tf-font-semibold">活动输入（{preview.bindings.length}）</div><div className="tf-card-body-sm tf-stack-sm">{preview.bindings.map((binding) => <div className="tf-row tf-gap-2" key={binding.binding_key}><CheckCircle2 size={13} className="tf-text-success" /><span className="tf-mono">{binding.binding_key}</span><span className="tf-caption tf-text-tertiary tf-ellipsis">{binding.path}</span></div>)}</div></section>
                <section className="tf-card tf-card-flush"><div className="tf-card-header tf-body tf-font-semibold">旁路文件</div><div className="tf-card-body-sm tf-stack-sm">{sidecars.map((sidecar) => <div key={sidecar.family} className="tf-row tf-justify-between"><span>{sidecar.family}</span><span className="tf-caption tf-text-tertiary">{sidecar.exists ? `${sidecar.line_count} 行 · ${sidecar.preview[0] || ""}` : "未找到"}</span></div>)}</div></section>
              </div>
              {preview.issues.length ? <div className="tf-inline-alert tf-inline-alert-warning" role="status">{preview.issues.filter((issue) => issue.severity === "warning").length} 项只读审计提示；不改变原始计算链路。{preview.issues.some((issue) => issue.severity === "error") ? ` ${preview.issues.filter((issue) => issue.severity === "error").length} 项活动输入错误。` : ""}</div> : null}
            </div>
          )}
        </div>

        <div className="tf-dialog-footer">
          <span className="tf-caption tf-text-tertiary">{preview ? "提交前再次校验源指纹；目标目录不得覆盖现有项目。" : "输入原始目录后生成只读审计预览。"}</span>
          <div className="tf-row tf-gap-2"><Button variant="secondary" onClick={onClose}>取消</Button>{preview ? <><Button variant="ghost" onClick={() => setPreview(null)} disabled={busy}>重新选择</Button><Button variant="primary" onClick={() => void commit()} disabled={busy || !destinationRoot.trim() || !preview.commit_allowed}>{busy ? "正在导入…" : "提交到独立项目"}</Button></> : <Button variant="primary" onClick={() => void runPreview()} disabled={busy || !sourceRoot.trim()}>{busy ? "正在解析…" : "生成预览"}</Button>}</div>
        </div>
      </section>
      {pickerTarget ? <DirectoryPickerDialog initialPath={pickerTarget === "source" ? sourceRoot : destinationRoot} title={pickerTarget === "source" ? "选择原始算例目录" : "选择独立目标目录"} description="仅选择目录，不会修改其中内容。" onCancel={() => setPickerTarget(null)} onSelect={(path) => { if (pickerTarget === "source") { setSourceRoot(path); if (!destinationRoot.trim()) setDestinationRoot(suggestedDestination(path)); } else setDestinationRoot(path); setPickerTarget(null); }} /> : null}
    </div>
  );
}
