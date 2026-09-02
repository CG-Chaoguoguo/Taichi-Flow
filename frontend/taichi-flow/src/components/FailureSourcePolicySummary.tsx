import type { ComputePolicyResolution } from "../types";

function modeLabel(mode: ComputePolicyResolution["effective"]["mode"]): string {
  if (mode === "precomputed") return "串行预计算 UNSFIN 台账";
  if (mode === "live") return "实时双层（Taichi 实验）";
  if (mode === "disabled") return "关闭浅层失稳；triggerslide 独立有效";
  return "等待严格解析";
}

export function summarizeFailureSourcePolicy(resolution?: ComputePolicyResolution): string {
  if (!resolution) return "正在解析失稳源策略";
  if (resolution.status === "blocked") {
    return resolution.blocking_issue?.message || "失稳源策略被阻断，不能入队";
  }
  if (resolution.status === "legacy_unrecorded") return "历史运行未记录失稳源解析结果";
  const mode = modeLabel(resolution.effective.mode);
  if (resolution.requested === "auto" || resolution.source === "auto") return `自动 → ${mode}`;
  if (resolution.effective.mode === "live") return `实验模式 → ${mode}`;
  if (resolution.effective.mode === "precomputed" && resolution.detected.simulate_shallow_landslide === false) {
    return `反事实覆盖 → ${mode}`;
  }
  return `全局设置覆盖 → ${mode}`;
}

export function FailureSourcePolicySummary({ resolution }: { resolution?: ComputePolicyResolution }) {
  const text = summarizeFailureSourcePolicy(resolution);
  const evidence = resolution?.detected?.evidence || [];
  const matchedEvidence = evidence.filter((item) => item.matched === true).length;
  const topologyStatus = resolution?.detected?.topology_status;
  const chip = !resolution
    ? "解析中"
    : resolution.status === "blocked"
      ? "已阻断"
      : resolution.status === "legacy_unrecorded"
        ? "历史未记录"
        : resolution.effective.mode === "live"
          ? "实验模式"
          : resolution.source === "global_override"
            ? "全局设置覆盖"
            : "自动识别";
  return (
    <div className="tf-card tf-card-flush" data-testid="failure-source-policy-summary">
      <div className="tf-row tf-justify-between tf-gap-2">
        <span className="tf-body tf-font-medium">失稳源策略</span>
        <span className={`tf-source-chip${resolution?.source === "global_override" ? " is-override" : ""}`}>{chip}</span>
      </div>
      <div className="tf-caption tf-text-secondary tf-mt-1">{text}</div>
      {resolution?.status === "blocked" ? (
        <>
          <div className="tf-caption tf-text-danger tf-mt-1">代码：{resolution.blocking_issue.code}</div>
          {evidence.length || topologyStatus ? (
            <div className="tf-caption tf-text-tertiary tf-mt-1">
              源码证据：{matchedEvidence}/{evidence.length} 条匹配
              {topologyStatus ? ` · 拓扑状态：${topologyStatus}` : ""}
            </div>
          ) : null}
        </>
      ) : null}
      {resolution?.warnings?.map((warning) => (
        <div className="tf-caption tf-text-warning tf-mt-1" key={warning}>{warning}</div>
      ))}
    </div>
  );
}
