import {
  AlertTriangle,
  ArrowLeft,
  Check,
  Crosshair,
  Files,
  Filter,
  FolderOpen,
  Link2,
  Unlink,
  Search,
  UploadCloud,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { deriveRainfallTimeline, regularTimeline, resizeRainfallTimeline } from "../rainfallTimeline";
import { useTaichiFlowStore } from "../stores/taichiFlowStore";
import type { InputBinding, InputFile, RainfallPeriod, RainfallTimeline } from "../types";
import { filenameOrdinal, sortAssetsByFilename, sortRainfallFiles } from "../utils/filenameSort";
import { AssetBindingField } from "./AssetBindingField";
import { Button } from "./Button";
import { SourceModeControl, type SourceMode } from "./SourceModeControl";

export { sortRainfallFiles } from "../utils/filenameSort";

export type RainfallDisplayUnit = "mm/h" | "m/s";

const MPS_TO_MMH = 3_600_000;

function canonicalSource(period: RainfallPeriod): SourceMode {
  return ["raster", "rifil", "raster_rifil"].includes(String(period.source || "")) ? "raster" : "uniform";
}

function periodId(period: RainfallPeriod): string {
  return period.period_id || `period-${period.index.toString().padStart(4, "0")}`;
}

function bindingKey(period: RainfallPeriod): string {
  return `rainfall.period.${period.index.toString().padStart(4, "0")}`;
}

function displayIntensity(value: number, unit: RainfallDisplayUnit): string {
  const converted = unit === "mm/h" ? value * MPS_TO_MMH : value;
  return Number.isFinite(converted) ? String(Number(converted.toPrecision(10))) : "0";
}

function periodHasActiveBinding(
  period: RainfallPeriod,
  activeRainBindings: InputBinding[],
): boolean {
  if (period.asset_id) return true;
  const id = periodId(period);
  const key = bindingKey(period);
  return activeRainBindings.some(
    (item) =>
      item.active !== false &&
      Boolean(item.asset_id) &&
      (item.period_id === id || item.binding_key === key),
  );
}

export type MappingCandidate = {
  asset: InputFile;
  targetIndex: number | null;
  issue?: string;
  file?: File;
  kind?: "upload" | "library";
};

/** Build fill-empty library auto-bind candidates for visible raster periods. */
export function buildLibraryAutoMapping(
  periods: RainfallPeriod[],
  rainAssets: InputFile[],
  visiblePeriods: RainfallPeriod[],
  activeRainBindings: InputBinding[],
): MappingCandidate[] {
  const visibleIds = new Set(visiblePeriods.map(periodId));
  const candidates: MappingCandidate[] = [];

  for (const period of periods) {
    if (!visibleIds.has(periodId(period))) continue;
    if (canonicalSource(period) !== "raster") continue;
    if (periodHasActiveBinding(period, activeRainBindings)) continue;

    const matches = rainAssets.filter((asset) => filenameOrdinal(asset.name) === period.index);
    if (matches.length === 0) {
      candidates.push({
        asset: {
          file_id: `missing-${period.index}`,
          family: "rainfall",
          name: `(时段 ${period.index})`,
          status: "ready",
          size: 0,
          updated_at: "",
        },
        targetIndex: period.index,
        issue: "未找到匹配文件",
        kind: "library",
      });
      continue;
    }
    if (matches.length > 1) {
      candidates.push({
        asset: matches[0],
        targetIndex: period.index,
        issue: `时段 ${period.index} 存在多个候选: ${matches.map((item) => item.name).join(", ")}`,
        kind: "library",
      });
      continue;
    }
    candidates.push({
      asset: matches[0],
      targetIndex: period.index,
      kind: "library",
    });
  }

  return candidates;
}

export function RainfallProcessEditor({
  periods,
  bindings,
  assets,
  canEdit,
  timeline,
  simulationEndS,
  onChange,
  onUpload,
  onClose,
}: {
  periods: RainfallPeriod[];
  bindings: InputBinding[];
  assets: InputFile[];
  canEdit: boolean;
  timeline?: RainfallTimeline | null;
  simulationEndS?: number | null;
  onChange: (periods: RainfallPeriod[], bindings: InputBinding[], timeline?: RainfallTimeline, simulationEndS?: number) => void;
  onUpload?: (files: File[]) => Promise<InputFile[]>;
  onClose?: () => void;
}) {
  const addToast = useTaichiFlowStore((state) => state.addToast);
  const [unit, setUnit] = useState<RainfallDisplayUnit>("mm/h");
  const [filter, setFilter] = useState("");
  const [mapping, setMapping] = useState<MappingCandidate[]>([]);
  const [mappingKind, setMappingKind] = useState<"upload" | "library">("upload");
  const [uploading, setUploading] = useState(false);
  const [selectedPeriodId, setSelectedPeriodId] = useState(periods[0] ? periodId(periods[0]) : "");
  const resolvedTimeline = useMemo(() => timeline || deriveRainfallTimeline(periods), [periods, timeline]);
  const fallbackInterval = resolvedTimeline.interval_s
    || (periods[0] ? Number(periods[0].end_s || 0) - Number(periods[0].start_s || 0) : 3600)
    || 3600;
  const [timelineDraft, setTimelineDraft] = useState({
    start: String(resolvedTimeline.start_s ?? 0),
    end: String(resolvedTimeline.end_s ?? fallbackInterval),
    interval: String(fallbackInterval),
  });
  const fileInput = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);
  const rainAssets = useMemo(
    () => assets.filter((asset) => asset.family === "rainfall"),
    [assets],
  );
  const activeRainBindings = useMemo(
    () => bindings.filter((binding) => binding.role === "rainfall-period" && binding.active !== false && Boolean(binding.asset_id)),
    [bindings],
  );
  const visiblePeriods = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    if (!needle) return periods;
    return periods.filter((period) => {
      const binding = activeRainBindings.find((item) => item.period_id === periodId(period));
      const asset = rainAssets.find((item) => item.file_id === (period.asset_id || binding?.asset_id));
      return `${period.index} ${periodId(period)} ${asset?.name || ""}`.toLowerCase().includes(needle);
    });
  }, [activeRainBindings, filter, periods, rainAssets]);

  const selectedPeriod = periods.find((period) => periodId(period) === selectedPeriodId);
  const selectedBinding = selectedPeriod
    ? activeRainBindings.find((item) => item.period_id === periodId(selectedPeriod) || item.binding_key === bindingKey(selectedPeriod))
    : undefined;
  const selectedAsset = rainAssets.find((asset) => asset.file_id === (selectedPeriod?.asset_id || selectedBinding?.asset_id));
  const rasterCount = periods.filter((period) => canonicalSource(period) === "raster").length;
  const uniformCount = periods.length - rasterCount;
  const mode = rasterCount && uniformCount ? "混合" : rasterCount ? "全栅格" : "全均匀";
  const timelinePreview = useMemo(() => {
    const parse = (value: string) => value.trim() === "" ? Number.NaN : Number(value);
    try {
      return { value: regularTimeline(parse(timelineDraft.start), parse(timelineDraft.end), parse(timelineDraft.interval)), error: null };
    } catch (reason) {
      return { value: null, error: reason instanceof Error ? reason.message : "降雨时间轴无效。" };
    }
  }, [timelineDraft]);
  const timelineChanged = Boolean(timelinePreview.value) && (
    resolvedTimeline.mode !== "regular"
    || Math.abs(Number(resolvedTimeline.start_s) - Number(timelinePreview.value?.start_s)) > 1e-9
    || Math.abs(Number(resolvedTimeline.end_s) - Number(timelinePreview.value?.end_s)) > 1e-9
    || Math.abs(Number(resolvedTimeline.interval_s) - Number(timelinePreview.value?.interval_s)) > 1e-9
    || (simulationEndS != null && Math.abs(Number(simulationEndS) - Number(timelinePreview.value?.end_s)) > 1e-9)
  );

  useEffect(() => {
    const nextInterval = resolvedTimeline.interval_s
      || (periods[0] ? Number(periods[0].end_s || 0) - Number(periods[0].start_s || 0) : 3600)
      || 3600;
    setTimelineDraft({
      start: String(resolvedTimeline.start_s ?? 0),
      end: String(resolvedTimeline.end_s ?? nextInterval),
      interval: String(nextInterval),
    });
  }, [periods, resolvedTimeline.end_s, resolvedTimeline.interval_s, resolvedTimeline.start_s]);

  const emitChange = (nextPeriods: RainfallPeriod[], nextBindings: InputBinding[]) => {
    onChange(nextPeriods, nextBindings, resolvedTimeline);
  };

  const emitPeriod = (period: RainfallPeriod, next: RainfallPeriod, nextBinding?: InputBinding | null) => {
    const nextPeriods = periods.map((item) => (periodId(item) === periodId(period) ? next : item));
    let nextBindings = [...bindings];
    const key = bindingKey(period);
    const existingIndex = nextBindings.findIndex((item) => item.binding_key === key);
    if (nextBinding) {
      if (existingIndex >= 0) nextBindings[existingIndex] = nextBinding;
      else nextBindings.push(nextBinding);
    } else if (nextBinding === null && existingIndex >= 0) {
      nextBindings = nextBindings.filter((_, index) => index !== existingIndex);
    }
    emitChange(nextPeriods, nextBindings);
  };

  const setSource = (period: RainfallPeriod, source: SourceMode) => {
    if (!canEdit) return;
    const existing = activeRainBindings.find((item) => item.binding_key === bindingKey(period));
    if (source === "uniform") {
      emitPeriod(
        period,
        { ...period, period_id: periodId(period), source: "uniform", asset_id: null, cri_mps: Math.max(0, Number(period.cri_mps || 0)) },
        null,
      );
      return;
    }
    emitPeriod(
      period,
      { ...period, period_id: periodId(period), source: "raster", cri_mps: null, asset_id: existing?.asset_id || period.asset_id || null },
      existing ? { ...existing, active: true } : undefined,
    );
  };

  const selectAsset = (period: RainfallPeriod, asset: InputFile) => {
    const id = periodId(period);
    emitPeriod(
      period,
      { ...period, period_id: id, source: "raster", cri_mps: null, asset_id: asset.file_id },
      {
        binding_key: bindingKey(period),
        asset_id: asset.file_id,
        family: "rainfall",
        role: "rainfall-period",
        period_id: id,
        ordinal: period.index,
        active: true,
      },
    );
    setSelectedPeriodId(id);
  };

  const prepareMapping = async (files: File[]) => {
    if (!onUpload || files.length === 0) return;
    const sorted = sortRainfallFiles(files);
    setUploading(true);
    try {
      const uploaded = await onUpload(sorted);
      const seen = new Set<number>();
      const candidates = uploaded.map((asset, index) => {
        const ordinal = filenameOrdinal(sorted[index]?.name || asset.name);
        const targetIndex = ordinal != null && periods.some((period) => period.index === ordinal)
          ? ordinal
          : periods[index]?.index ?? null;
        let issue: string | undefined;
        if (targetIndex == null) issue = "没有可映射的时段";
        else if (seen.has(targetIndex)) issue = `时段 ${targetIndex} 重复`;
        else seen.add(targetIndex);
        return { file: sorted[index], asset, targetIndex, issue, kind: "upload" as const };
      });
      setMappingKind("upload");
      setMapping(candidates);
    } finally {
      setUploading(false);
    }
  };

  const applyMappingCandidates = (candidates: MappingCandidate[]) => {
    const valid = candidates.filter((item) => !item.issue && item.targetIndex != null && !item.asset.file_id.startsWith("missing-"));
    if (!valid.length) return 0;
    const nextPeriods = periods.map((period) => {
      const candidate = valid.find((item) => item.targetIndex === period.index);
      return candidate
        ? { ...period, period_id: periodId(period), source: "raster" as const, cri_mps: null, asset_id: candidate.asset.file_id }
        : period;
    });
    const nextBindings = [...bindings];
    for (const candidate of valid) {
      const period = periods.find((item) => item.index === candidate.targetIndex);
      if (!period) continue;
      const next: InputBinding = {
        binding_key: bindingKey(period),
        asset_id: candidate.asset.file_id,
        family: "rainfall",
        role: "rainfall-period",
        period_id: periodId(period),
        ordinal: period.index,
        active: true,
      };
      const existingIndex = nextBindings.findIndex((item) => item.binding_key === next.binding_key);
      if (existingIndex >= 0) nextBindings[existingIndex] = next;
      else nextBindings.push(next);
    }
    emitChange(nextPeriods, nextBindings);
    return valid.length;
  };

  const applyMapping = () => {
    if (!mapping.length || mapping.some((item) => item.issue || item.targetIndex == null)) return;
    const count = applyMappingCandidates(mapping);
    setMapping([]);
    if (count > 0 && mappingKind === "library") {
      addToast({ type: "success", message: `已自动绑定 ${count} 个时段` });
    }
  };

  const autoBindByFilename = () => {
    if (!canEdit) return;
    const orderedAssets = sortAssetsByFilename(rainAssets);
    const candidates = buildLibraryAutoMapping(periods, orderedAssets, visiblePeriods, activeRainBindings);
    const bindable = candidates.filter((item) => !item.issue);
    if (!candidates.length) {
      addToast({ type: "info", message: "没有可自动绑定的未绑定时段" });
      return;
    }
    if (candidates.some((item) => item.issue)) {
      setMappingKind("library");
      setMapping(candidates);
      addToast({ type: "warning", message: "存在无法自动匹配的时段，请在映射预览中确认" });
      return;
    }
    if (!bindable.length) {
      addToast({ type: "info", message: "没有可自动绑定的未绑定时段" });
      return;
    }
    const count = applyMappingCandidates(bindable);
    addToast({ type: "success", message: `已自动绑定 ${count} 个时段` });
  };

  const bulkSource = (source: SourceMode) => {
    const visibleIds = new Set(visiblePeriods.map(periodId));
    const nextPeriods = periods.map((period) => {
      if (!visibleIds.has(periodId(period))) return period;
      return source === "uniform"
        ? { ...period, source: "uniform", asset_id: null, cri_mps: Math.max(0, Number(period.cri_mps || 0)) }
        : { ...period, source: "raster", cri_mps: null };
    });
    const nextBindings = source === "uniform"
      ? bindings.filter((binding) => !(binding.role === "rainfall-period" && binding.period_id && visibleIds.has(binding.period_id)))
      : bindings;
    emitChange(nextPeriods, nextBindings);
  };

  const applyTimeline = () => {
    if (!canEdit || !timelinePreview.value) return;
    const resized = resizeRainfallTimeline(periods, bindings, timelinePreview.value);
    onChange(resized.periods, resized.bindings, timelinePreview.value, Number(timelinePreview.value.end_s));
    if (!resized.periods.some((period) => periodId(period) === selectedPeriodId)) {
      setSelectedPeriodId(resized.periods[0] ? periodId(resized.periods[0]) : "");
    }
    setMapping([]);
  };

  const clearAllRainfallBindings = () => {
    if (!canEdit || activeRainBindings.length === 0) return;
    const nextPeriods = periods.map((period) => canonicalSource(period) === "raster" ? { ...period, asset_id: null } : period);
    const nextBindings = bindings.filter((binding) => binding.role !== "rainfall-period");
    emitChange(nextPeriods, nextBindings);
    setMapping([]);
    addToast({ type: "success", message: `已取消 ${activeRainBindings.length} 个降雨绑定，栅格时段仍保留。` });
  };

  return (
    <section className="tf-rainfall-workspace" data-qoder="rainfall-process-editor" data-testid="rainfall-process-editor">
      <header className="tf-rainfall-toolbar">
        <div className="tf-row tf-gap-2 tf-flex-1">
          {onClose ? <Button variant="ghost" size="small" icon={<ArrowLeft size={15} />} onClick={onClose}>返回画布</Button> : null}
          <div>
            <div className="tf-title-sm">编辑降雨过程</div>
            <div className="tf-caption tf-text-tertiary">{periods.length} 个时段 · {mode} · 保存时与参数及输入绑定原子提交</div>
          </div>
        </div>
        <div className="tf-row tf-gap-2">
          <div className="tf-mode-switch" role="group" aria-label="雨强显示单位">
            {(["mm/h", "m/s"] as RainfallDisplayUnit[]).map((item) => (
              <button key={item} type="button" className={`tf-mode-switch-btn${unit === item ? " is-active" : ""}`} onClick={() => setUnit(item)}>{item}</button>
            ))}
          </div>
          <input ref={fileInput} hidden type="file" multiple onChange={(event) => void prepareMapping(Array.from(event.target.files || []))} />
          <input
            ref={folderInput}
            hidden
            type="file"
            multiple
            {...({ webkitdirectory: "", directory: "" } as Record<string, string>)}
            onChange={(event) => void prepareMapping(Array.from(event.target.files || []))}
          />
          <Button size="small" icon={<Files size={15} />} disabled={!canEdit || !onUpload || uploading} onClick={() => fileInput.current?.click()}>
            多文件
          </Button>
          <Button size="small" icon={<FolderOpen size={15} />} disabled={!canEdit || !onUpload || uploading} onClick={() => folderInput.current?.click()}>
            文件夹
          </Button>
        </div>
      </header>

      <section className="tf-rainfall-timeline" aria-label="降雨时间轴">
        <div className="tf-rainfall-timeline-heading">
          <div>
            <div className="tf-body tf-font-semibold">时间轴</div>
            <div className="tf-caption tf-text-tertiary">
              时段数由开始、结束和间隔计算；表格边界只读。{resolvedTimeline.mode === "custom" ? " 当前导入的是非等间隔 capt 边界，应用后将转为等间隔。" : ""}
            </div>
          </div>
          <span className={`tf-chip${timelinePreview.error ? " tf-text-danger" : ""}`}>
            {timelinePreview.value ? `${timelinePreview.value.period_count} 个时段` : "时间轴无效"}
          </span>
        </div>
        <div className="tf-rainfall-timeline-controls">
          <label className="tf-caption">
            开始时间 (s)
            <input className="tf-input tf-mono" aria-label="降雨开始时间" type="number" disabled={!canEdit} value={timelineDraft.start} onChange={(event) => setTimelineDraft((current) => ({ ...current, start: event.target.value }))} />
          </label>
          <label className="tf-caption">
            结束时间 (s)
            <input className="tf-input tf-mono" aria-label="降雨结束时间" type="number" disabled={!canEdit} value={timelineDraft.end} onChange={(event) => setTimelineDraft((current) => ({ ...current, end: event.target.value }))} />
          </label>
          <label className="tf-caption">
            时段间隔 (s)
            <input className="tf-input tf-mono" aria-label="降雨时段间隔" type="number" min="0" disabled={!canEdit} value={timelineDraft.interval} onChange={(event) => setTimelineDraft((current) => ({ ...current, interval: event.target.value }))} />
          </label>
          <Button size="small" variant="primary" disabled={!canEdit || !timelinePreview.value || !timelineChanged} onClick={applyTimeline}>应用时间轴</Button>
        </div>
        {timelinePreview.error ? <div className="tf-caption tf-text-danger" role="alert">{timelinePreview.error}</div> : null}
      </section>

      <div
        className={`tf-rainfall-dropzone${uploading ? " is-busy" : ""}`}
        onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => {
          event.preventDefault();
          void prepareMapping(Array.from(event.dataTransfer.files || []));
        }}
      >
        <UploadCloud size={18} />
        <span>{uploading ? "正在按内容哈希收录资产…" : "拖放多个栅格或文件夹到此处，先生成映射预览，不会自动修改方案"}</span>
      </div>

      {mapping.length ? (
        <div className="tf-mapping-preview" role="region" aria-label="降雨文件映射预览">
          <div className="tf-row tf-justify-between">
            <div>
              <div className="tf-body tf-font-semibold">{mappingKind === "library" ? "库内自动映射" : "映射预览"}</div>
              <div className="tf-caption tf-text-tertiary">
                {mappingKind === "library"
                  ? "仅填充未绑定时段；按文件名末尾数字匹配时段编号。歧义项必须修正后才能应用。"
                  : "按文件名末尾数字优先匹配时段；歧义项必须修正后才能应用。"}
              </div>
            </div>
            <div className="tf-row tf-gap-2">
              <Button variant="ghost" size="small" onClick={() => setMapping([])}>取消</Button>
              <Button size="small" variant="primary" icon={<Check size={14} />} disabled={mapping.some((item) => Boolean(item.issue))} onClick={applyMapping}>应用映射</Button>
            </div>
          </div>
          <div className="tf-mapping-grid">
            {mapping.map((item) => (
              <div key={`${item.asset.file_id}-${item.targetIndex}-${item.issue || "ok"}`} className={`tf-mapping-item${item.issue ? " has-error" : ""}`}>
                <span className="tf-ellipsis">{item.file?.name || item.asset.name}</span>
                <span>→</span>
                <span>{item.targetIndex == null ? "未映射" : `时段 ${item.targetIndex}`}</span>
                {item.issue ? <span className="tf-text-danger">{item.issue}</span> : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <div className="tf-rainfall-controls">
        <label className="tf-search-box tf-flex-1">
          <Search size={15} />
          <input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="筛选时段、编号或资产名" />
        </label>
        <span className="tf-caption tf-text-tertiary"><Filter size={13} /> {visiblePeriods.length}/{periods.length}</span>
        <Button
          variant="ghost"
          size="small"
          icon={<Link2 size={14} />}
          disabled={!canEdit}
          onClick={autoBindByFilename}
        >
          按文件名自动绑定
        </Button>
        <Button variant="ghost" size="small" disabled={!canEdit} onClick={() => bulkSource("uniform")}>筛选项设为均匀</Button>
        <Button variant="ghost" size="small" disabled={!canEdit} onClick={() => bulkSource("raster")}>筛选项设为栅格</Button>
        <Button variant="ghost" size="small" icon={<Unlink size={14} />} disabled={!canEdit || activeRainBindings.length === 0} onClick={clearAllRainfallBindings}>取消全部降雨绑定</Button>
      </div>

      <div className="tf-rainfall-editor-grid">
        <div className="tf-rainfall-table-wrap">
          <table className="tf-rainfall-table">
            <thead>
              <tr>
                <th>#</th><th>开始 (s)</th><th>结束 (s)</th><th>来源</th><th>雨强 ({unit}) / 栅格资产</th><th>状态</th>
              </tr>
            </thead>
            <tbody>
              {visiblePeriods.map((period) => {
                const id = periodId(period);
                const source = canonicalSource(period);
                const binding = activeRainBindings.find((item) => item.period_id === id || item.binding_key === bindingKey(period));
                const asset = rainAssets.find((item) => item.file_id === (period.asset_id || binding?.asset_id));
                const valid = source === "uniform" ? Number(period.cri_mps) >= 0 : Boolean(asset && binding?.active !== false);
                return (
                  <tr key={id} className={selectedPeriodId === id ? "is-selected" : ""} onClick={() => setSelectedPeriodId(id)}>
                    <td className="tf-mono">{period.index}</td>
                    <td><input className="tf-input tf-input-compact tf-mono" aria-label={`第 ${period.index} 时段开始时间`} aria-readonly="true" title="由降雨时间轴生成" type="number" readOnly value={period.start_s ?? 0} /></td>
                    <td><input className="tf-input tf-input-compact tf-mono" aria-label={`第 ${period.index} 时段结束时间`} aria-readonly="true" title="由降雨时间轴生成" type="number" readOnly value={period.end_s ?? 0} /></td>
                    <td><SourceModeControl label={`第 ${period.index} 时段来源`} value={source} disabled={!canEdit} onChange={(next) => setSource(period, next)} /></td>
                    <td>
                      {source === "uniform" ? (
                        <input
                          className="tf-input tf-input-compact tf-mono tf-rainfall-value"
                          aria-label={`第 ${period.index} 时段雨强`}
                          type="number"
                          min="0"
                          step="any"
                          disabled={!canEdit}
                          value={displayIntensity(Number(period.cri_mps || 0), unit)}
                          onChange={(event) => {
                            const display = Math.max(0, Number(event.target.value) || 0);
                            emitPeriod(period, { ...period, source: "uniform", cri_mps: unit === "mm/h" ? display / MPS_TO_MMH : display });
                          }}
                        />
                      ) : (
                        <AssetBindingField
                          compact
                          label={`第 ${period.index} 时段栅格`}
                          pickerLabel={`为第 ${period.index} 时段选择栅格资产`}
                          family="rainfall"
                          binding={binding}
                          assets={rainAssets}
                          sortable
                          disabled={!canEdit}
                          onSelect={(nextAsset) => selectAsset(period, nextAsset)}
                          onClear={() => emitPeriod(period, { ...period, asset_id: null }, null)}
                        />
                      )}
                    </td>
                    <td>{valid ? <span className="tf-status-inline is-valid">就绪</span> : <span className="tf-status-inline is-error">需处理</span>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <aside className="tf-rainfall-preview">
          <div className="tf-body tf-font-semibold">选中栅格预览</div>
          {selectedAsset ? (
            <>
              <div className="tf-rainfall-source-card">
                <Crosshair size={18} />
                <span>此栅格的原始像元值请在中央专业浏览器中使用“识别”工具读取。</span>
              </div>
              <div className="tf-body tf-font-medium tf-ellipsis">{selectedAsset.name}</div>
              <dl className="tf-asset-meta">
                <div><dt>尺寸</dt><dd>{selectedAsset.raster_metadata?.cols || "—"} × {selectedAsset.raster_metadata?.rows || "—"}</dd></div>
                <div><dt>分辨率</dt><dd>{selectedAsset.raster_metadata?.cell_size ?? "—"}</dd></div>
                <div><dt>SHA-256</dt><dd className="tf-mono">{selectedAsset.sha256?.slice(0, 12) || "—"}</dd></div>
              </dl>
            </>
          ) : (
            <div className="tf-empty tf-caption tf-text-tertiary">选择一个栅格时段以查看资产元数据和预览。</div>
          )}
          {periods.some((period) => canonicalSource(period) === "raster" && !period.asset_id && !activeRainBindings.some((item) => item.period_id === periodId(period) && item.active)) ? (
            <div className="tf-banner tf-banner-warning"><AlertTriangle size={14} /> 存在未绑定栅格的时段，保存前必须补齐。</div>
          ) : null}
        </aside>
      </div>
    </section>
  );
}
