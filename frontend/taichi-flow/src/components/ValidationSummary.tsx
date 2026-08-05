import { AlertTriangle, CheckCircle2, XCircle } from "lucide-react";
import type { ValidationState } from "../types";

export function ValidationSummary({ validation }: { validation?: ValidationState | null }) {
  if (!validation) return <div className="tf-validation-summary is-neutral">尚未执行结构化预检</div>;
  const visibleErrors = validation.errors.slice(0, 3);
  const visibleWarnings = validation.warnings.slice(0, 2);
  const hiddenErrorCount = Math.max(0, validation.errors.length - visibleErrors.length);
  const hiddenWarningCount = Math.max(0, validation.warnings.length - visibleWarnings.length);
  return (
    <div className={`tf-validation-summary${validation.valid ? " is-valid" : " is-error"}`} data-qoder="validation-summary">
      <div className="tf-row tf-gap-2">
        {validation.valid ? <CheckCircle2 size={15} /> : <XCircle size={15} />}
        <strong>{validation.valid ? "运行预检通过" : `${validation.errors.length} 项阻断问题`}</strong>
      </div>
      {visibleErrors.map((error, index) => <div key={`${index}-${error}`} className="tf-caption">{error}</div>)}
      {hiddenErrorCount > 0 ? <div className="tf-caption tf-text-tertiary">另有 {hiddenErrorCount} 项，请在对应的中央编辑器中定位和修正。</div> : null}
      {visibleWarnings.map((warning, index) => <div key={`${index}-${warning}`} className="tf-caption tf-row tf-gap-1"><AlertTriangle size={12} />{warning}</div>)}
      {hiddenWarningCount > 0 ? <div className="tf-caption tf-text-tertiary">另有 {hiddenWarningCount} 项警告。</div> : null}
    </div>
  );
}
