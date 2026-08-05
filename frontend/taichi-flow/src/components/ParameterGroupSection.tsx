import { ChevronDown } from "lucide-react";
import type { ReactNode } from "react";

export function ParameterGroupSection({
  group,
  label,
  fieldCount,
  modifiedCount = 0,
  issueCount = 0,
  expanded,
  onToggle,
  children,
}: {
  group: string;
  label: string;
  fieldCount: number;
  modifiedCount?: number;
  issueCount?: number;
  expanded: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  const contentId = `parameter-group-content-${group.replace(/[^a-zA-Z0-9_-]/g, "-")}`;

  return (
    <section className="tf-card tf-card-flush tf-parameter-group" data-testid={`parameter-group-${group}`}>
      <button
        type="button"
        className="tf-parameter-group-trigger"
        aria-expanded={expanded}
        aria-controls={contentId}
        onClick={onToggle}
      >
        <ChevronDown size={15} aria-hidden="true" className={`tf-parameter-group-chevron${expanded ? " is-expanded" : ""}`} />
        <span className="tf-flex-1 tf-font-semibold">{label}</span>
        <span className="tf-parameter-group-count">{fieldCount} 项</span>
        {modifiedCount > 0 ? <span className="tf-parameter-group-badge is-modified">已改 {modifiedCount}</span> : null}
        {issueCount > 0 ? <span className="tf-parameter-group-badge is-error">问题 {issueCount}</span> : null}
      </button>
      <div id={contentId} className="tf-parameter-group-content" hidden={!expanded}>
        <div className="tf-card-body-sm">{children}</div>
      </div>
    </section>
  );
}
