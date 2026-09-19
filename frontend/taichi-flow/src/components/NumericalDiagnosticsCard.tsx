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

const CPU_LIVE_ARCH_FAMILY = ["cpu", "x64", "arm64"] as const;

function backendLinkOk(backend: NonNullable<NumericalDiagnostics["backend"]>): boolean {
  if (backend.fallback_active === true) return false;
  const requested = String(backend.requested_backend || "").trim().toLowerCase();
  if (!requested) return false;
  const live = String(backend.live_arch || "").toLowerCase();
  if (requested === "cuda") return live.includes("cuda");
  if (requested === "cpu") {
    const liveIsCpuFamily = CPU_LIVE_ARCH_FAMILY.some((token) => live.includes(token));
    const managerIsCpu = String(backend.manager_backend || "").toLowerCase() === "cpu";
    return (liveIsCpuFamily || managerIsCpu) && !live.includes("cuda");
  }
  return false;
}

export function NumericalDiagnosticsCard({ diagnostics }: { diagnostics: NumericalDiagnostics }) {
  const backend = diagnostics.backend || {};
  const integration = diagnostics.time_integration || {};
  const local = diagnostics.local_conservation || {};
  const ledger = diagnostics.global_volume_ledger || {};
  const classification = diagnostics.classification || {};
  const probe = diagnostics.erosion_probe_diagnostics;
  const probeComplete = probe?.enabled === true && probe.diagnostics_incomplete === false
    && probe.capture_active === false && probe.buffered_record_count === 0
    && typeof probe.captured_record_count === "number"
    && probe.captured_record_count === probe.written_record_count;
  const linkOk = backendLinkOk(backend);
  const closure = statusLabel(classification.conservation_closure ?? ledger.passed);
  const ledgerUnavailable = ledger.available === false;
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
        <span className={`tf-diagnostic-state${linkOk && closure.ok ? " is-ok" : " is-warning"}`} data-testid="numerical-link-status">
          {linkOk && closure.ok ? <CheckCircle2 size={15} /> : <AlertTriangle size={15} />}
          {linkOk && closure.ok ? "运行链路通过" : "需要复核"}
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
            {ledgerUnavailable ? "未取得诊断" : `${closure.text} · ${scientific(ledger.relative_error)}`}
          </div>
          <div className="tf-caption tf-text-tertiary">
            {ledgerUnavailable
              ? String(ledger.capture_error || "体积账本捕获失败，不能作为守恒通过证据。")
              : `源项 ${number(ledger.source_total_m3)} m³ · 存储/汇 ${number(ledger.sink_and_storage_total_m3)} m³`}
          </div>
        </div>
      </div>

      <div className="tf-diagnostics-footer">
        {probe ? (
          <div className={`tf-caption ${probe.diagnostics_incomplete ? "tf-text-error" : "tf-text-secondary"}`}
            role={probe.diagnostics_incomplete ? "alert" : "status"} data-testid="erosion-probe-integrity">
            探针证据：{probe.enabled === false ? "关闭" : probe.diagnostics_incomplete ? "不完整，不能用于验收" : probeComplete ? "完整落盘" : "采集中或完整性待核验"}
            {probe.enabled ? ` · 采集 ${number(probe.captured_record_count, 0)} / 写入 ${number(probe.written_record_count, 0)} / 缓冲 ${number(probe.buffered_record_count, 0)}` : ""}
            {probe.write_error ? <div>{probe.write_error}</div> : null}
          </div>
        ) : <span className="tf-caption tf-text-tertiary">探针证据：旧记录未提供完整性信息</span>}
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
