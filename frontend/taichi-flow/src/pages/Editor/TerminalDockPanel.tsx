import { useEffect, useState } from "react";
import { isActiveScenario, useTaichiFlowStore } from "../../stores/taichiFlowStore";
import { runApi } from "../../api/taichiFlowAdapter";

export function TerminalDockPanel() {
  const activeProject = useTaichiFlowStore((state) => state.activeProject);
  const scenarios = useTaichiFlowStore((state) => state.scenarios);
  const editorSelection = useTaichiFlowStore((state) => state.editorSelection);
  const queue = useTaichiFlowStore((state) => state.queue);
  const [logs, setLogs] = useState<string[]>([]);

  const scenarioId =
    editorSelection?.kind === "scenario" || editorSelection?.kind === "result"
      ? editorSelection.scenarioId
      : editorSelection?.kind === "queue"
        ? queue.find((item) => item.queue_item_id === editorSelection.queueItemId)?.scenario_id
        : scenarios.find((item) => isActiveScenario(item) && item.status === "running")?.scenario_id || scenarios.find(isActiveScenario)?.scenario_id;

  const scenario = scenarios.find((item) => item.scenario_id === scenarioId && isActiveScenario(item));
  const simulationId = scenario?.latest_simulation_id;

  useEffect(() => {
    if (!activeProject || !simulationId) {
      setLogs([]);
      return;
    }
    const load = () => {
      void runApi
        .terminal(activeProject.project_id, simulationId)
        .then((response) => setLogs(response.entries.slice(-200)))
        .catch(() => undefined);
    };
    load();
    const timer = window.setInterval(load, 1000);
    return () => window.clearInterval(timer);
  }, [activeProject, simulationId]);

  if (!simulationId) {
    return <div className="tf-dock-empty tf-caption tf-text-tertiary">选择已运行的方案后，终端日志会显示在这里。</div>;
  }

  return (
    <div className="tf-terminal tf-dock-terminal">
      {logs.length === 0 ? (
        <div className="tf-caption tf-text-tertiary">暂无日志输出 · simulation_id: {simulationId}</div>
      ) : (
        logs.map((line, index) => (
          <div key={`${index}-${line.slice(0, 24)}`} className="tf-terminal-line">
            {line}
          </div>
        ))
      )}
    </div>
  );
}
