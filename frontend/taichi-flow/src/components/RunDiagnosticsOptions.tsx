import { useMemo, useState } from "react";
import { Button } from "./Button";
import type { ErosionProbeRunOptions, SimulationRunOptions } from "../types";

export type ErosionProbeDiagnostics = ErosionProbeRunOptions;
export type RunDiagnosticsPayload = SimulationRunOptions["diagnostics"];
export type ErosionProbeDraftState = {
  rawText: string;
  error: string | null;
};

export type ErosionProbeSuggestion = {
  simulation_id: string;
  input_revision_id?: string;
  source_file: string;
  source_frame_s?: number | null;
  writer?: string;
  probe_cells: Array<[number, number]>;
};

type Props = {
  value: RunDiagnosticsPayload;
  onChange: (next: RunDiagnosticsPayload) => void;
  onValidationChange?: (valid: boolean) => void;
  /**
   * Run options retain only a validated payload.  The inspector owns this
   * companion state so an invalid raw draft survives a scenario/input-version
   * switch instead of silently falling back to the last valid payload.
   */
  probeDraft?: ErosionProbeDraftState;
  onProbeDraftChange?: (next: ErosionProbeDraftState) => void;
  onFillTopN?: () => Promise<ErosionProbeSuggestion | Array<[number, number]> | number[][]>;
  disabled?: boolean;
};

function parseProbeCells(text: string): { cells: Array<[number, number]>; error: string | null } {
  const cells: Array<[number, number]> = [];
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  for (const line of lines) {
    const parts = line.split(/[,，\s]+/).filter(Boolean);
    if (parts.length !== 2) {
      return { cells: [], error: `无效格点：${line}（需要 row,col）` };
    }
    const row = Number(parts[0]);
    const col = Number(parts[1]);
    if (!Number.isInteger(row) || !Number.isInteger(col) || row < 0 || col < 0) {
      return { cells: [], error: `无效格点：${line}（row/col 须为非负整数）` };
    }
    if (cells.some(([knownRow, knownCol]) => knownRow === row && knownCol === col)) {
      return { cells: [], error: `重复格点：${row},${col}` };
    }
    cells.push([row, col]);
    if (cells.length > 32) {
      return { cells: [], error: "探针格点最多 32 个" };
    }
  }
  return { cells, error: null };
}

function validateProbeCells(text: string, enabled: boolean): { cells: Array<[number, number]>; error: string | null } {
  const parsed = parseProbeCells(text);
  if (parsed.error || !enabled || parsed.cells.length > 0) return parsed;
  return { cells: parsed.cells, error: "启用侵蚀探针时至少需要一个探针格点" };
}

export function formatProbeCells(cells: Array<[number, number] | number[]>): string {
  return cells.map((cell) => `${cell[0]},${cell[1]}`).join("\n");
}

function normalizeSuggestion(value: ErosionProbeSuggestion | Array<[number, number]> | number[][]): ErosionProbeSuggestion {
  if (Array.isArray(value)) {
    return {
      simulation_id: "",
      source_file: "",
      probe_cells: value.map((cell) => [Number(cell[0]), Number(cell[1])] as [number, number]),
    };
  }
  return {
    ...value,
    probe_cells: value.probe_cells.map((cell) => [Number(cell[0]), Number(cell[1])] as [number, number]),
  };
}

export function RunDiagnosticsOptions({
  value,
  onChange,
  onValidationChange,
  probeDraft,
  onProbeDraftChange,
  onFillTopN,
  disabled = false,
}: Props) {
  const [uncontrolledProbeDraft, setUncontrolledProbeDraft] = useState<ErosionProbeDraftState>(() => ({
    rawText: formatProbeCells(value.erosion_probe.probe_cells),
    error: validateProbeCells(formatProbeCells(value.erosion_probe.probe_cells), value.erosion_probe.enabled).error,
  }));
  const [filling, setFilling] = useState(false);
  const [fillError, setFillError] = useState<string | null>(null);
  const [fillSource, setFillSource] = useState<ErosionProbeSuggestion | null>(null);
  const currentProbeDraft = probeDraft ?? uncontrolledProbeDraft;

  const updateProbeDraft = (next: ErosionProbeDraftState) => {
    if (probeDraft) {
      onProbeDraftChange?.(next);
      return;
    }
    setUncontrolledProbeDraft(next);
  };

  const summary = useMemo(() => {
    const enabled = value.erosion_probe.enabled;
    const count = value.erosion_probe.probe_cells.length;
    if (!enabled) return "诊断：关闭";
    return `诊断：开启 · ${count} 探针`;
  }, [value.erosion_probe.enabled, value.erosion_probe.probe_cells.length]);

  const commitText = (text: string) => {
    const parsed = validateProbeCells(text, value.erosion_probe.enabled);
    updateProbeDraft({ rawText: text, error: parsed.error });
    onValidationChange?.(!parsed.error);
    if (parsed.error) return;
    onChange({
      ...value,
      erosion_probe: {
        ...value.erosion_probe,
        probe_cells: parsed.cells,
      },
    });
  };

  return (
    <div className="tf-card tf-stack-sm tf-run-diagnostics" data-testid="run-diagnostics-options">
      <div className="tf-row tf-justify-between">
        <span className="tf-body tf-font-medium">运行诊断（仅本次运行）</span>
        <span className="tf-caption tf-text-info" data-testid="run-diagnostics-summary">
          {summary}
        </span>
      </div>
      <label className="tf-row tf-gap-2" htmlFor="run-erosion-probe-enabled">
        <input
          id="run-erosion-probe-enabled"
          type="checkbox"
          data-testid="run-erosion-probe-enabled"
          checked={value.erosion_probe.enabled}
          disabled={disabled}
          onChange={(event) => {
            const enabled = event.target.checked;
            const parsed = validateProbeCells(currentProbeDraft.rawText, enabled);
            updateProbeDraft({ rawText: currentProbeDraft.rawText, error: parsed.error });
            onValidationChange?.(!parsed.error);
            onChange({
              ...value,
              erosion_probe: {
                ...value.erosion_probe,
                enabled,
              },
            });
          }}
        />
        <span className="tf-body">侵蚀分项诊断（仅本次运行）</span>
      </label>
      <label className="tf-stack-sm" htmlFor="run-erosion-probe-cells">
        <span className="tf-caption">探针格点（每行 row,col）</span>
        <textarea
          id="run-erosion-probe-cells"
          className="tf-input tf-run-diagnostics-textarea"
          data-testid="run-erosion-probe-cells"
          rows={5}
          disabled={disabled || !value.erosion_probe.enabled}
          value={currentProbeDraft.rawText}
          onChange={(event) => commitText(event.target.value)}
          aria-invalid={currentProbeDraft.error ? "true" : undefined}
          aria-describedby={currentProbeDraft.error ? "run-erosion-probe-error" : undefined}
          placeholder={"415,630\n534,590"}
        />
      </label>
      {currentProbeDraft.error ? <div id="run-erosion-probe-error" className="tf-caption tf-text-error" role="alert">{currentProbeDraft.error}</div> : null}
      {fillError ? <div className="tf-caption tf-text-error" role="alert">{fillError}</div> : null}
      <div className="tf-row tf-gap-2">
        <Button
          type="button"
          variant="secondary"
          className="tf-run-diagnostics-topn"
          disabled={disabled || !onFillTopN || filling}
          data-testid="run-erosion-probe-fill-topn"
          onClick={async () => {
            if (!onFillTopN) return;
            setFilling(true);
            setFillError(null);
            try {
              const suggestion = normalizeSuggestion(await onFillTopN());
              const normalizedText = formatProbeCells(suggestion.probe_cells);
              const parsed = validateProbeCells(normalizedText, true);
              if (parsed.error) throw new Error(parsed.error);
              updateProbeDraft({ rawText: normalizedText, error: null });
              onValidationChange?.(true);
              setFillSource(suggestion);
              onChange({
                erosion_probe: {
                  enabled: true,
                  probe_cells: parsed.cells,
                },
              });
            } catch (error) {
              setFillError(error instanceof Error ? error.message : "无法读取兼容运行的 Top-N 格点。");
            } finally {
              setFilling(false);
            }
          }}
        >
          按上次运行 Erosion_depth Top-N 填充
        </Button>
      </div>
      {fillSource?.simulation_id ? (
        <span className="tf-caption tf-text-tertiary" data-testid="run-erosion-probe-source">
          来源：{fillSource.simulation_id}
          {fillSource.source_frame_s == null ? "" : ` · t=${fillSource.source_frame_s}s`}
          {fillSource.input_revision_id ? ` · ${fillSource.input_revision_id}` : ""}
        </span>
      ) : null}
      <span className="tf-caption tf-text-tertiary">
        诊断结果写入本次运行的 diagnostics/erosion_probe_steps.csv，不写入方案参数。
      </span>
    </div>
  );
}

export function diagnosticsSummaryLabel(runOptions?: { diagnostics?: RunDiagnosticsPayload } | null): string | null {
  const probe = runOptions?.diagnostics?.erosion_probe;
  if (!probe?.enabled) return null;
  return `诊断：开启 · ${probe.probe_cells?.length ?? 0} 探针`;
}
