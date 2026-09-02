import { AlertTriangle, CheckCircle2, Cpu, Gauge, ShieldCheck } from "lucide-react";
import type { NumericalDiagnostics } from "../types";

function number(value: unknown, digits = 3): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return value.toLocaleString("zh-CN", { maximumFractionDigits: digits });
}

function scientific(value: unknown): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return value.toExponential(2);
}

function statusLabel(value: boolean | null | undefined): { text: string; ok: boolean } {
  if (value === true) return { text: "通过", ok: true };
  if (value === false) return { text: "未通过", ok: false };
  return { text: "待报告", ok: false };
}

export function NumericalDiagnosticsCard({ diagnostics }: { diagnostics: NumericalDiagnostics }) {
  const backend = diagnostics.backend || {};
  const integration = diagnostics.time_integration || {};
  const local = diagnostics.local_conservation || {};
  const ledger = diagnostics.global_volume_ledger || {};
  const classification = diagnostics.classification || {};
  const cudaOk = String(backend.live_arch || "").toLowerCase().includes("cuda")
    && backend.fallback_active !== true;
  const closure = statusLabel(classification.conservation_closure ?? ledger.passed);
  const nonfinite = Object.values(diagnostics.nonfinite_counts || {}).reduce(
    (sum, count) => sum + (typeof count === "number" && count > 0 ? count : 0),
    0,
  );

  return (
    <section className="tf-card tf-diagnostics-card" aria-label="数值运行诊断">
      <div className="tf-row tf-justify-between tf-diagnostics-heading">
        <div>
          <div className="tf-body tf-font-semibold">数值运行诊断</div>
          <div className="tf-caption tf-text-tertiary">
            诊断快照 · {diagnostics.status || "未知状态"}
          </div>
        </div>
        <span className={`tf-diagnostic-state${cudaOk && closure.ok ? " is-ok" : " is-warning"}`}>
          {cudaOk && closure.ok ? <CheckCircle2 size={15} /> : <AlertTriangle size={15} />}
          {cudaOk && closure.ok ? "运行链路通过" : "需要复核"}
        </span>
      </div>

      <div className="tf-diagnostics-grid">
        <div className="tf-diagnostic-item">
          <div className="tf-diagnostic-label"><Cpu size={14} />计算后端</div>
          <div className="tf-diagnostic-value">{String(backend.live_arch || backend.manager_backend || "—")}</div>
          <div className="tf-caption tf-text-tertiary">
            请求 {String(backend.requested_backend || "—")} · 精度 {String(backend.default_fp || "—")}
          </div>
        </div>
        <div className="tf-diagnostic-item">
          <div className="tf-diagnostic-label"><Gauge size={14} />时间步</div>
          <div className="tf-diagnostic-value">
            {number(integration.accepted_steps, 0)} 接受 · {number(integration.rejected_steps, 0)} 拒绝
          </div>
          <div className="tf-caption tf-text-tertiary">
            dt 均值 {number(integration.dt?.accepted_mean_s)} s · dtmin 触及 {number(integration.dt_min_hits, 0)} 次
          </div>
        </div>
        <div className="tf-diagnostic-item">
          <div className="tf-diagnostic-label"><ShieldCheck size={14} />逐步守恒</div>
          <div className="tf-diagnostic-value">最大相对误差 {scientific(local.max_abs_relative_error)}</div>
          <div className="tf-caption tf-text-tertiary">
            超限接受步 {number(local.accepted_step_violation_count, 0)} · 门槛 {scientific(local.tolerance || 1e-3)}
          </div>
        </div>
        <div className="tf-diagnostic-item">
          <div className="tf-diagnostic-label"><ShieldCheck size={14} />全局体积账本</div>
          <div className={`tf-diagnostic-value${closure.ok ? " is-ok" : " is-warning"}`}>
            {closure.text} · {scientific(ledger.relative_error)}
          </div>
          <div className="tf-caption tf-text-tertiary">
            源项 {number(ledger.source_total_m3)} m³ · 存储/汇 {number(ledger.sink_and_storage_total_m3)} m³
          </div>
        </div>
      </div>

      <div className="tf-diagnostics-footer">
        <span className="tf-caption tf-text-tertiary">
          CUDA 探针：{String(backend.cuda_probe_kernel || "未记录")} · 非有限值：{number(nonfinite, 0)}
        </span>
        <span className="tf-caption tf-text-tertiary">
          原 EDDA 严格 parity：{statusLabel(classification.strict_code_parity).text} · 离散收敛：未评估
        </span>
      </div>
    </section>
  );
}

