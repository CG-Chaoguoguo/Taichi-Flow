import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Save, Copy } from "lucide-react";
import { projectApi, scenarioApi, TaichiFlowApiError } from "../../api/taichiFlowAdapter";
import { useTaichiFlowStore } from "../../stores/taichiFlowStore";
import { useScenarioSettings } from "../../hooks/useScenarioSettings";
import { Button } from "../../components/Button";
import { UnsavedChangesGuard } from "../../components/UnsavedChangesGuard";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { ComputeGateSettingsPanel } from "./ComputeGateSettingsPanel";
import type { ProjectInfo, Scenario, ScenarioConfiguration } from "../../types";
import type { ThemeMode } from "../../themePreference";

export function Settings() {
  const { projectId = "", scenarioId = "" } = useParams();
  return <ScenarioSettings key={projectId + "/" + scenarioId} projectId={projectId} scenarioId={scenarioId} />;
}

function ScenarioSettings({ projectId, scenarioId }: { projectId: string; scenarioId: string }) {
  const theme = useTaichiFlowStore((state) => state.theme);
  const setTheme = useTaichiFlowStore((state) => state.setTheme);
  const settings = useScenarioSettings();
  const navigate = useNavigate();
  const [loaded, setLoaded] = useState<{ project: ProjectInfo; scenario: Scenario; configuration: ScenarioConfiguration } | null>(null);
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const [confirmReload, setConfirmReload] = useState(false);
  useEffect(() => {
    let cancelled = false;
    setError("");
    void Promise.all([projectApi.get(projectId), scenarioApi.getScenario(projectId, scenarioId), scenarioApi.getConfiguration(projectId, scenarioId)])
      .then(([project, scenario, configuration]) => {
        if (cancelled) return;
        setLoaded({ project, scenario, configuration }); setDraft({ ...configuration.control_overrides });
        const store = useTaichiFlowStore.getState();
        const sameProject = store.activeProject?.project_id === projectId;
        store.setActiveProject(project, { hydrate: !sameProject });
        useTaichiFlowStore.setState((state) => ({
          scenarios: sameProject ? [...state.scenarios.filter((item) => item.scenario_id !== scenarioId), scenario] : [scenario],
          scenarioConfigurations: { ...(sameProject ? state.scenarioConfigurations : {}), [scenarioId]: configuration },
        }));
      }).catch((reason) => { if (!cancelled) setError(reason instanceof Error ? reason.message : "无法加载案例设置"); });
    return () => { cancelled = true; };
  }, [projectId, scenarioId, reload]);
  const dirty = Boolean(loaded && JSON.stringify(draft) !== JSON.stringify(loaded.configuration.control_overrides || {}));
  const canEdit = Boolean(loaded && (loaded.configuration.editable ?? ["draft", "ready"].includes(loaded.scenario.status)));
  const save = async () => {
    if (!loaded || !canEdit) throw new Error("请复制为可编辑方案后修改");
    setBusy(true); setError("");
    try {
      const scenario = await scenarioApi.updateScenario(projectId, scenarioId, { control_overrides: draft, expected_version: loaded.configuration.version });
      const configuration = await scenarioApi.getConfiguration(projectId, scenarioId);
      setLoaded({ ...loaded, scenario, configuration }); setDraft({ ...configuration.control_overrides });
      useTaichiFlowStore.setState((state) => ({
        scenarios: state.scenarios.map((item) => item.scenario_id === scenarioId ? scenario : item),
        scenarioConfigurations: { ...state.scenarioConfigurations, [scenarioId]: configuration },
      }));
      useTaichiFlowStore.getState().addToast({ type: "success", message: "当前方案设置已保存" });
    } catch (reason) {
      const message = reason instanceof TaichiFlowApiError && reason.code === "scenario_version_conflict"
        ? "此方案已被其他操作更新。草稿已保留，请重新加载后核对修改。"
        : (reason instanceof Error ? reason.message.replace(/[。.]$/, "") : "保存失败") + "。草稿已保留，请核对后重试。";
      setError(message);
      throw new Error(message);
    } finally { setBusy(false); }
  };
  return <div className="tf-page"><div className="tf-page-content tf-page-content--narrow tf-animate-in">
    <UnsavedChangesGuard dirty={dirty} save={save} />
    <div className="tf-page-header">
      <div><h1 className="tf-display tf-mb-2">案例设置</h1>
        <p className="tf-body tf-text-secondary">{loaded ? loaded.project.name + " / " + loaded.scenario.name + " · 仅影响当前方案" : "正在加载选定案例…"}</p></div>
      <div className="tf-actions-bar">
        <Button variant="secondary" icon={<ArrowLeft size={16} />} onClick={settings.returnFromSettings}>返回案例</Button>
        {loaded && canEdit && <Button icon={<Save size={16} />} disabled={!dirty || busy} onClick={() => void save().catch(() => undefined)}>{busy ? "保存中…" : "保存设置"}</Button>}
      </div>
    </div>
    {error && <div role="alert" className="tf-card tf-mb-6"><p className="tf-text-error">{error}</p>
      <Button variant="secondary" onClick={() => { if (dirty) setConfirmReload(true); else setReload((value) => value + 1); }}>重新加载</Button></div>}
    {confirmReload && <ConfirmDialog title="重新加载设置" onClose={() => setConfirmReload(false)}>
      <p>重新加载将放弃本次设置草稿。</p><div className="tf-dialog-footer">
        <Button variant="secondary" onClick={() => setConfirmReload(false)}>取消</Button>
        <Button onClick={() => { setConfirmReload(false); setReload((value) => value + 1); }}>放弃并重新加载</Button>
      </div></ConfirmDialog>}
    {loaded && <>
      <div className="tf-card tf-mb-6"><h2 className="tf-subtitle tf-card-header">外观</h2>
        <p className="tf-caption tf-text-secondary">外观保存在本机；下方计算设置属于当前方案。</p>
        <div className="tf-stack">{([
          ["light", "浅色"], ["dark", "深色"], ["system", "跟随系统"],
        ] as [ThemeMode, string][]).map(([key, label]) => <label key={key} className="tf-list-item">
          <input type="radio" name="theme" checked={theme === key} onChange={() => setTheme(key)} /><span>{label}</span>
        </label>)}</div>
      </div>
      {!canEdit && <div className="tf-card tf-mb-6"><p>此方案已冻结。复制后可以修改，原运行记录继续保留。</p>
        <Button icon={<Copy size={16} />} disabled={busy} onClick={async () => {
          setBusy(true); try { const copy = await scenarioApi.duplicateScenario(projectId, scenarioId); navigate("/editor/" + projectId + "/scenarios/" + copy.scenario_id + "/settings", { replace: true }); }
          catch (reason) { setError(reason instanceof Error ? reason.message : "复制失败"); } finally { setBusy(false); }
        }}>复制为可编辑方案</Button></div>}
      <ComputeGateSettingsPanel baseline={loaded.configuration.control_defaults ?? loaded.configuration.baseline} effective={loaded.configuration.control_defaults ?? loaded.configuration.baseline}
        draft={draft} onChange={setDraft} disabled={!canEdit || busy} />
      <div className="tf-card"><h2 className="tf-subtitle tf-card-header">关于</h2><p className="tf-caption tf-text-secondary">Taichi-Flow 计算工作台 · 0.1.0</p></div>
    </>}
  </div></div>;
}
