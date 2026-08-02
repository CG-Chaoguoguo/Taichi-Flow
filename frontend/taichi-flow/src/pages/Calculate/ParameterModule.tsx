import { useEffect, useMemo, useState } from "react";
import { RotateCcw, Save, Search } from "lucide-react";
import { useTaichiFlowStore } from "../../stores/taichiFlowStore";
import { Button } from "../../components/Button";
import type { ParameterCatalogEntry, Scenario } from "../../types";

function parseValue(value: string): number | boolean | string {
  if (value === "true") return true;
  if (value === "false") return false;
  if (value.trim() !== "" && Number.isFinite(Number(value))) return Number(value);
  return value;
}

export function ParameterModule({ scenario }: { scenario: Scenario }) {
  const catalog = useTaichiFlowStore((state) => state.parameterCatalog);
  const fetchParameterCatalog = useTaichiFlowStore((state) => state.fetchParameterCatalog);
  const updateScenario = useTaichiFlowStore((state) => state.updateScenario);
  const addToast = useTaichiFlowStore((state) => state.addToast);
  const [search, setSearch] = useState("");
  const [values, setValues] = useState<Record<string, unknown>>({ ...scenario.parameter_patch });
  const [changed, setChanged] = useState<Record<string, boolean>>({});

  useEffect(() => { if (!catalog) void fetchParameterCatalog(); }, [catalog, fetchParameterCatalog]);
  useEffect(() => {
    setValues({ ...scenario.parameter_patch });
    setChanged({});
  }, [scenario.scenario_id]);

  const entries = useMemo(() => (catalog?.parameters || []).filter((entry) => entry.editable && (entry.label.includes(search) || entry.key.includes(search))), [catalog, search]);
  const canEdit = scenario.status === "draft" || scenario.status === "ready";
  const groups = useMemo(() => {
    const grouped = new Map<string, ParameterCatalogEntry[]>();
    for (const entry of entries) {
      const group = entry.config_path?.split(".")[0] || "runtime";
      grouped.set(group, [...(grouped.get(group) || []), entry]);
    }
    return Array.from(grouped.entries());
  }, [entries]);

  const handleSave = async () => {
    const patch: Record<string, unknown> = {};
    Object.entries(changed).forEach(([key, isChanged]) => { if (isChanged) patch[key] = values[key]; });
    try {
      await updateScenario(scenario.scenario_id, { parameter_patch: patch });
      setChanged({});
      addToast({ type: "success", message: "参数方案已保存" });
    } catch (error) {
      addToast({ type: "error", message: error instanceof Error ? error.message : "参数保存失败" });
    }
  };

  const handleReset = async () => {
    setValues({});
    setChanged({});
    try {
      await updateScenario(scenario.scenario_id, { parameter_patch: {} });
      addToast({ type: "success", message: "已恢复服务端有效快照" });
    } catch (error) {
      addToast({ type: "error", message: error instanceof Error ? error.message : "恢复参数失败" });
    }
  };

  return (
    <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 16, overflow: "auto" }}>
      <div style={{ display: "flex", gap: 8 }}>
        <div style={{ flex: 1, display: "flex", alignItems: "center", gap: 8, padding: "6px 12px", borderRadius: "var(--radius-large)", border: "1px solid var(--color-border)", background: "var(--color-bg-canvas)" }}>
          <Search size={16} color="var(--color-foreground-tertiary)" />
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索可编辑参数..." style={{ flex: 1, border: "none", background: "transparent", outline: "none", color: "var(--color-foreground)" }} />
        </div>
        <Button size="small" icon={<Save size={14} />} onClick={() => void handleSave()} disabled={!canEdit || !catalog || entries.length === 0}>保存</Button>
      </div>
      <Button variant="ghost" size="small" icon={<RotateCcw size={14} />} onClick={() => void handleReset()} disabled={!canEdit || !catalog || entries.length === 0}>恢复服务端快照</Button>
      {!canEdit && <div className="tf-caption" style={{ color: "var(--color-foreground-tertiary)" }}>当前方案已有运行历史或已归档；请复制方案后再修改参数。</div>}
      {!catalog ? <div className="tf-body" style={{ color: "var(--color-foreground-tertiary)", padding: 24, textAlign: "center" }}>正在加载参数证据目录…</div> : groups.length === 0 ? <div className="tf-body" style={{ color: "var(--color-foreground-tertiary)", padding: 24, textAlign: "center" }}>没有具备生产消费证据的可编辑参数。</div> : groups.map(([group, groupEntries]) => (
        <section key={group} style={{ borderRadius: "var(--radius-large)", border: "1px solid var(--color-border)", overflow: "hidden" }}>
          <div className="tf-body" style={{ padding: "10px 12px", fontWeight: 600, background: "var(--color-surface-tertiary)" }}>{group}</div>
          <div style={{ padding: 8, display: "flex", flexDirection: "column", gap: 8 }}>
            {groupEntries.map((entry) => {
              const value = values[entry.key];
              const isChanged = Boolean(changed[entry.key]);
              return <div key={entry.key} style={{ padding: 10, borderRadius: "var(--radius-medium)", background: isChanged ? "var(--color-brand-bg-subtle)" : "transparent" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                  <label className="tf-body" style={{ fontWeight: 500 }}>{entry.label}{isChanged && <span style={{ color: "var(--color-brand)", marginLeft: 4 }}>●</span>}</label>
                  <span className="tf-mono" style={{ color: "var(--color-foreground-tertiary)" }}>{entry.key}</span>
                </div>
                <input type="text" value={value === undefined ? "" : String(value)} placeholder="使用服务端有效值" disabled={!canEdit} onChange={(event) => { setValues((current) => ({ ...current, [entry.key]: parseValue(event.target.value) })); setChanged((current) => ({ ...current, [entry.key]: true })); }} style={{ width: "100%", marginTop: 8, padding: "6px 8px", borderRadius: "var(--radius-medium)", border: "1px solid var(--color-border)", background: "var(--color-bg-canvas)", color: "var(--color-foreground)" }} />
                <div className="tf-caption" style={{ color: "var(--color-foreground-tertiary)", marginTop: 4 }}>{entry.runtime_status} · {entry.activation_condition || "服务端有效快照"}</div>
              </div>;
            })}
          </div>
        </section>
      ))}
    </div>
  );
}
