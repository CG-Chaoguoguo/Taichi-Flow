import { useEffect, useMemo, useRef, useState } from "react";
import { SlidersHorizontal } from "lucide-react";
import { EddaComputeControlsSection } from "../../components/EddaComputeControlsSection";
import { EffectiveParameterField } from "../../components/EffectiveParameterField";
import { HelpTip } from "../../components/HelpTip";
import {
  BOUNDARY_GATE_KEYS,
  EXPERIMENTAL_LIVE_KEY,
  FAILURE_SOURCE_POLICY_KEY,
  VARIANT_GATE_KEYS,
} from "../../constants/computeGates";
import { useTaichiFlowStore } from "../../stores/taichiFlowStore";
import type { ParameterCatalogEntry } from "../../types";

function parseValue(value: string): boolean | string {
  if (value === "true") return true;
  if (value === "false") return false;
  return value;
}

export function ComputeGateSettingsPanel() {
  const catalog = useTaichiFlowStore((state) => state.parameterCatalog);
  const defaults = useTaichiFlowStore((state) => state.computeGateDefaults);
  const loading = useTaichiFlowStore((state) => Boolean(state.loading.computeGates || state.loading.parameters));
  const error = useTaichiFlowStore((state) => state.errors.computeGates || state.errors.parameters || null);
  const fetchParameterCatalog = useTaichiFlowStore((state) => state.fetchParameterCatalog);
  const fetchComputeGateDefaults = useTaichiFlowStore((state) => state.fetchComputeGateDefaults);
  const saveComputeGateDefaults = useTaichiFlowStore((state) => state.saveComputeGateDefaults);
  const addToast = useTaichiFlowStore((state) => state.addToast);
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const pendingSave = useRef<Record<string, unknown> | null>(null);
  const flushingSave = useRef(false);

  useEffect(() => {
    if (!catalog) void fetchParameterCatalog();
    void fetchComputeGateDefaults();
  }, [catalog, fetchComputeGateDefaults, fetchParameterCatalog]);

  useEffect(() => {
    if (defaults && !flushingSave.current && pendingSave.current === null) setDraft(defaults.values || {});
  }, [defaults]);

  const entriesByKey = useMemo(() => {
    const map = new Map<string, ParameterCatalogEntry>();
    for (const entry of catalog?.parameters || []) map.set(entry.key, entry);
    return map;
  }, [catalog]);
  const eddaEntries = useMemo(
    () => (catalog?.parameters || []).filter((entry) => entry.control_family === "edda"),
    [catalog],
  );
  const variantEntries = VARIANT_GATE_KEYS.map((key) => entriesByKey.get(key)).filter(Boolean) as ParameterCatalogEntry[];
  const boundaryEntries = BOUNDARY_GATE_KEYS.map((key) => entriesByKey.get(key)).filter(Boolean) as ParameterCatalogEntry[];
  const policyEntry = entriesByKey.get(FAILURE_SOURCE_POLICY_KEY);
  const experimentalEntry = entriesByKey.get(EXPERIMENTAL_LIVE_KEY);
  const baseline = defaults?.baseline || {};
  const liveUnlocked = draft[EXPERIMENTAL_LIVE_KEY] === true;
  const policyIsLive = draft[FAILURE_SOURCE_POLICY_KEY] === "live";

  const flushSaves = async () => {
    if (flushingSave.current) return;
    flushingSave.current = true;
    try {
      while (pendingSave.current) {
        const next = pendingSave.current;
        pendingSave.current = null;
        setSaveState("saving");
        try {
          await saveComputeGateDefaults(next);
          setSaveState("saved");
        } catch (reason) {
          pendingSave.current = null;
          setSaveState("error");
          addToast({ type: "error", message: reason instanceof Error ? reason.message : "计算门禁保存失败，已恢复服务端值" });
          await fetchComputeGateDefaults();
          const serverValues = useTaichiFlowStore.getState().computeGateDefaults?.values;
          if (serverValues) setDraft(serverValues);
        }
      }
    } finally {
      flushingSave.current = false;
      if (!pendingSave.current) window.setTimeout(() => setSaveState("idle"), 1200);
    }
  };

  const persist = (next: Record<string, unknown>) => {
    setDraft(next);
    pendingSave.current = next;
    void flushSaves();
  };

  const changeEntry = (entry: ParameterCatalogEntry, raw: string) => {
    void persist({ ...draft, [entry.key]: parseValue(raw) });
  };
  const resetEntry = (entry: ParameterCatalogEntry) => {
    const next = { ...draft };
    delete next[entry.key];
    void persist(next);
  };

  return (
    <div className="tf-card tf-mb-6 tf-compute-gate-settings" id="compute-gates" data-testid="compute-gate-settings">
      <h2 className="tf-subtitle tf-card-header">
          <span className="tf-row tf-gap-2">
          <SlidersHorizontal size={16} aria-hidden="true" />
          计算与数值
          <HelpTip content="计算模式门禁与边界类型对所有方案生效。数值变种和失稳源策略默认按方案与源码解析，只有明确选择才会全局覆盖。CPU / CUDA 后端请在每次加入队列前选择。" />
        </span>
      </h2>
      {loading && !defaults ? <div className="tf-caption tf-text-tertiary">正在加载计算门禁…</div> : null}
      {error ? <div className="tf-caption tf-text-danger" role="alert">{error}</div> : null}

      {catalog?.control_registry && eddaEntries.length ? (
        <EddaComputeControlsSection
          entries={eddaEntries}
          controlRegistry={catalog.control_registry}
          baseline={baseline}
          draftPatch={draft}
          canEdit
          onDraftChange={(next) => void persist(next)}
          title="计算模式门禁"
          subtitle="全局默认，写入所有方案的有效计算控制"
          overrideChipLabel="设置覆盖"
          baselineChipLabel="模板默认"
        />
      ) : null}

      <section className="tf-card tf-card-flush tf-mt-4" aria-labelledby="variant-gates-title" data-testid="variant-gate-settings">
        <div className="tf-row tf-gap-1" id="variant-gates-title">
          <div className="tf-body tf-font-semibold">数值变种</div>
          <HelpTip content="面通量与曼宁面平均公式默认按方案识别；明确选择后才全局覆盖。" />
        </div>
        {variantEntries.map((entry) => (
          <EffectiveParameterField
            key={entry.key}
            entry={entry}
            defaultValue={baseline[entry.key]}
            overrideValue={Object.prototype.hasOwnProperty.call(draft, entry.key) ? draft[entry.key] : undefined}
            effectiveValue={Object.prototype.hasOwnProperty.call(draft, entry.key) ? draft[entry.key] : undefined}
            disabled={false}
            autoCapable
            autoOptionLabel="自动（按方案识别）"
            autoChipLabel="自动识别"
            overrideChipLabel="全局设置覆盖"
            baselineChipLabel="自动识别"
            provenanceMode="deferred"
            supportingText="不展示某个案例的默认值；入队时按方案快照解析。"
            saveState={saveState}
            onChange={(value) => changeEntry(entry, value)}
            onReset={() => resetEntry(entry)}
          />
        ))}
      </section>

      <section className="tf-card tf-card-flush tf-mt-4" aria-labelledby="failure-source-policy-title" data-testid="failure-source-policy-settings">
        <div className="tf-row tf-gap-1" id="failure-source-policy-title">
          <div className="tf-body tf-font-semibold">失稳源策略</div>
          <HelpTip content="控制浅层失稳台账是否启用及其实现方式。一次性 triggerslide 注入不受此策略影响。" />
        </div>
        {policyEntry ? (
          <EffectiveParameterField
            key={policyEntry.key}
            entry={policyEntry}
            defaultValue={undefined}
            overrideValue={Object.prototype.hasOwnProperty.call(draft, policyEntry.key) ? draft[policyEntry.key] : undefined}
            effectiveValue={Object.prototype.hasOwnProperty.call(draft, policyEntry.key) ? draft[policyEntry.key] : undefined}
            disabled={false}
            autoCapable
            autoOptionLabel="自动（按 fssimul 与 Fortran 源码）"
            autoChipLabel="自动识别"
            overrideChipLabel={draft[FAILURE_SOURCE_POLICY_KEY] === "precomputed" ? "反事实覆盖" : draft[FAILURE_SOURCE_POLICY_KEY] === "live" ? "实验模式" : "全局设置覆盖"}
            baselineChipLabel="自动识别"
            provenanceMode="deferred"
            supportingText="Auto 只在方案解析时决定 disabled / precomputed / live。"
            saveState={saveState}
            disabledValues={liveUnlocked ? [] : ["live"]}
            onChange={(value) => changeEntry(policyEntry, value)}
            onReset={() => resetEntry(policyEntry)}
          />
        ) : null}
        {!liveUnlocked ? (
          <div className="tf-caption tf-text-tertiary tf-mt-2" data-testid="live-policy-locked-hint">
            实时双层为 Taichi 实验路径，可见但默认锁定。开启解锁不会改变当前计算模式。
          </div>
        ) : null}
        {experimentalEntry ? (
          <EffectiveParameterField
            key={experimentalEntry.key}
            entry={experimentalEntry}
            defaultValue={false}
            overrideValue={Object.prototype.hasOwnProperty.call(draft, experimentalEntry.key) ? draft[experimentalEntry.key] : undefined}
            effectiveValue={liveUnlocked}
            disabled={policyIsLive}
            overrideChipLabel="设置覆盖"
            baselineChipLabel="默认关闭"
            onChange={(value) => {
              if (policyIsLive && value === "false") {
                addToast({ type: "error", message: "当前策略为实时双层时不能关闭实验解锁，请先切换失稳源策略。" });
                return;
              }
              changeEntry(experimentalEntry, value);
            }}
            onReset={() => {
              if (policyIsLive) {
                addToast({ type: "error", message: "当前策略为实时双层时不能关闭实验解锁，请先切换失稳源策略。" });
                return;
              }
              resetEntry(experimentalEntry);
            }}
          />
        ) : null}
      </section>

      <section className="tf-card tf-card-flush tf-mt-4" aria-labelledby="boundary-gates-title" data-testid="boundary-gate-settings">
        <div className="tf-row tf-gap-1" id="boundary-gates-title">
          <div className="tf-body tf-font-semibold">边界类型定义</div>
          <HelpTip content="默认边界检测方式与边界类型，对后续运行立即生效。" />
        </div>
        {boundaryEntries.map((entry) => (
          <EffectiveParameterField
            key={entry.key}
            entry={entry}
            defaultValue={baseline[entry.key]}
            overrideValue={Object.prototype.hasOwnProperty.call(draft, entry.key) ? draft[entry.key] : undefined}
            effectiveValue={Object.prototype.hasOwnProperty.call(draft, entry.key) ? draft[entry.key] : baseline[entry.key]}
            disabled={false}
            overrideChipLabel="设置覆盖"
            baselineChipLabel="模板默认"
            onChange={(value) => changeEntry(entry, value)}
            onReset={() => resetEntry(entry)}
          />
        ))}
      </section>
    </div>
  );
}
