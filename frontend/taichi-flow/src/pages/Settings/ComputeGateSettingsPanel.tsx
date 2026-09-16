import { useEffect } from "react";
import { SlidersHorizontal } from "lucide-react";
import { EddaComputeControlsSection } from "../../components/EddaComputeControlsSection";
import { EffectiveParameterField } from "../../components/EffectiveParameterField";
import { NumericVariantHelp } from "../../components/NumericVariantHelp";
import { HelpTip } from "../../components/HelpTip";
import { BOUNDARY_GATE_KEYS, EXPERIMENTAL_LIVE_KEY, FAILURE_SOURCE_POLICY_KEY, VARIANT_GATE_KEYS } from "../../constants/computeGates";
import { useTaichiFlowStore } from "../../stores/taichiFlowStore";

export function ComputeGateSettingsPanel({ baseline, effective, draft, onChange, disabled = false }: {
  baseline: Record<string, unknown>; effective: Record<string, unknown>; draft: Record<string, unknown>;
  onChange: (values: Record<string, unknown>) => void; disabled?: boolean;
}) {
  const catalog = useTaichiFlowStore((state) => state.parameterCatalog);
  const error = useTaichiFlowStore((state) => state.errors.parameters);
  const fetchCatalog = useTaichiFlowStore((state) => state.fetchParameterCatalog);
  useEffect(() => { if (!catalog) void fetchCatalog(); }, [catalog, fetchCatalog]);
  const own = (key: string) => Object.prototype.hasOwnProperty.call(draft, key);
  const value = (key: string) => own(key) ? draft[key] : effective[key] ?? baseline[key];
  const reset = (key: string) => { const next = { ...draft }; delete next[key]; onChange(next); };
  const live = value(FAILURE_SOURCE_POLICY_KEY) === "live";
  const unlocked = value(EXPERIMENTAL_LIVE_KEY) === true;
  const entries = catalog?.parameters || [];
  const field = (key: string, automatic = false) => {
    const entry = entries.find((item) => item.key === key);
    if (!entry) return null;
    const isVariant = (VARIANT_GATE_KEYS as readonly string[]).includes(key);
    return <EffectiveParameterField key={key} entry={entry}
      defaultValue={baseline[key]} overrideValue={own(key) ? draft[key] : undefined}
      effectiveValue={value(key)} disabled={disabled || (key === EXPERIMENTAL_LIVE_KEY && live)}
      autoCapable={automatic} autoOptionLabel="自动（按当前方案识别）"
      autoChipLabel="方案识别" baselineChipLabel="案例初始值" overrideChipLabel="当前方案覆盖"
      resetLabel="恢复案例初始设置" supportingText={automatic ? "修改只写入当前方案副本；自动模式按本方案输入解析。" : undefined}
      disabledValues={key === FAILURE_SOURCE_POLICY_KEY && !unlocked ? ["live"] : []}
      helpContent={isVariant ? <NumericVariantHelp entry={entry} value={own(key) ? draft[key] : undefined} resolvedValue={value(key)} /> : undefined}
      onReset={() => reset(key)} onChange={(raw) => {
        if (raw === "") { reset(key); return; }
        onChange({ ...draft, [key]: raw === "true" ? true : raw === "false" ? false : raw });
      }} />;
  };
  const eddaEntries = entries.filter((entry) => entry.control_family === "edda");
  return <section className="tf-card tf-mb-6 tf-compute-gate-settings" id="compute-gates" data-testid="compute-gate-settings">
    <h2 className="tf-subtitle tf-card-header tf-row tf-gap-2"><SlidersHorizontal size={16} />计算与数值
      <HelpTip content="仅修改当前方案。导入案例使用自己的初始配置，修改保存在独立副本中；CPU / CUDA 在加入队列前选择。" /></h2>
    {!catalog && <p role={error ? "alert" : "status"}>{error || "正在加载计算设置…"}</p>}
    {catalog?.control_registry && eddaEntries.length > 0 && <EddaComputeControlsSection
      entries={eddaEntries} controlRegistry={catalog.control_registry} baseline={baseline}
      draftPatch={draft} canEdit={!disabled} onDraftChange={onChange}
      title="计算模式门禁" subtitle="仅影响当前方案副本" overrideChipLabel="当前方案覆盖" baselineChipLabel="案例初始值" />}
    <section className="tf-card tf-card-flush tf-mt-4" aria-label="数值变种" data-testid="variant-gate-settings">
      <h3 className="tf-body tf-font-semibold">数值变种</h3>{VARIANT_GATE_KEYS.map((key) => field(key, true))}
    </section>
    <section className="tf-card tf-card-flush tf-mt-4" aria-label="失稳源策略" data-testid="failure-source-policy-settings">
      <h3 className="tf-body tf-font-semibold">失稳源策略</h3>{field(FAILURE_SOURCE_POLICY_KEY, true)}{field(EXPERIMENTAL_LIVE_KEY)}
      {!unlocked && <p className="tf-caption tf-text-secondary">实时双层为实验路径，需先解锁才能选择。开启解锁不会自动切换策略。</p>}
    </section>
    <section className="tf-card tf-card-flush tf-mt-4" aria-label="边界类型定义" data-testid="boundary-gate-settings">
      <h3 className="tf-body tf-font-semibold">边界类型定义</h3>{BOUNDARY_GATE_KEYS.map((key) => field(key))}
    </section>
  </section>;
}
