import type { CaseConfigInterface, InputBinding, InputFile } from "../types";
import { AssetBindingField } from "./AssetBindingField";

export type ManningSourceMode = "global" | "raster";

function resolveSource(draftPatch: Record<string, unknown>, baseline: Record<string, unknown>): ManningSourceMode {
  const raw = draftPatch["manning.source"] ?? baseline["manning.source"] ?? "global";
  return String(raw).includes("raster") || String(raw) === "spatial" ? "raster" : "global";
}

function resolveGlobal(
  draftPatch: Record<string, unknown>,
  baseline: Record<string, unknown>,
  iface: CaseConfigInterface | null,
): number {
  const raw = draftPatch["rheology.n_manning"] ?? baseline["rheology.n_manning"] ?? iface?.parsed_values?.manning?.global ?? 0.1;
  return Number.isFinite(Number(raw)) ? Number(raw) : 0.1;
}

export function ManningModeEditor({
  draftPatch,
  onDraftChange,
  baseline = {},
  bindings = [],
  assets = [],
  onBindingsChange = () => undefined,
  caseConfig = null,
  canEdit = true,
  readOnly = false,
}: {
  draftPatch: Record<string, unknown>;
  onDraftChange: (patch: Record<string, unknown>) => void;
  baseline?: Record<string, unknown>;
  bindings?: InputBinding[];
  assets?: InputFile[];
  onBindingsChange?: (bindings: InputBinding[]) => void;
  caseConfig?: CaseConfigInterface | null;
  canEdit?: boolean;
  readOnly?: boolean;
  onRequestUpload?: () => void;
}) {
  const source = resolveSource(draftPatch, baseline);
  const globalValue = resolveGlobal(draftPatch, baseline, caseConfig);
  const editable = canEdit && !readOnly;
  const binding = bindings.find((item) => item.binding_key === "manning.raster");
  const boundAsset = assets.find((asset) => asset.file_id === binding?.asset_id);

  const setSource = (next: ManningSourceMode) => {
    if (!editable) return;
    onDraftChange({
      ...draftPatch,
      "manning.source": next,
      ...(next === "global" && draftPatch["rheology.n_manning"] === undefined
        ? { "rheology.n_manning": globalValue }
        : {}),
    });
    if (binding) {
      onBindingsChange(bindings.map((item) => item.binding_key === "manning.raster" ? { ...item, active: next === "raster" } : item));
    }
  };

  return (
    <section className="tf-card tf-card-flush tf-config-section" data-testid="manning-mode-editor">
      <div className="tf-body tf-group-header tf-font-semibold">曼宁来源</div>
      <div className="tf-card-body-sm tf-stack tf-gap-2">
        <div className="tf-mode-switch" role="group" aria-label="曼宁来源切换">
          <button type="button" className={`tf-mode-switch-btn${source === "global" ? " is-active" : ""}`} disabled={!editable} onClick={() => setSource("global")}>均匀曼宁</button>
          <button type="button" className={`tf-mode-switch-btn${source === "raster" ? " is-active" : ""}`} disabled={!editable} onClick={() => setSource("raster")}>空间曼宁</button>
        </div>

        {source === "global" ? (
          <>
            <div className="tf-caption tf-text-tertiary">直接编辑全局系数；空间资产绑定会保留但保持未激活。</div>
            <label className="tf-body tf-font-medium" htmlFor="manning-global-input">全局曼宁系数（n）</label>
            <input
              id="manning-global-input"
              className="tf-input tf-full-width"
              type="number"
              step="any"
              disabled={!editable}
              value={globalValue}
              onChange={(event) => onDraftChange({ ...draftPatch, "manning.source": "global", "rheology.n_manning": Number(event.target.value) || 0 })}
            />
            {binding ? <div className="tf-caption tf-text-tertiary">已保留未激活绑定：{boundAsset?.name || binding.asset_id}</div> : null}
          </>
        ) : (
          <>
            <div className="tf-caption tf-text-tertiary">空间模式必须显式选择一个与 DEM 网格一致的项目资产。</div>
            <AssetBindingField
              label="空间曼宁栅格"
              pickerLabel="选择空间曼宁栅格资产"
              family="manning"
              binding={binding}
              assets={assets}
              disabled={!editable}
              onSelect={(asset) => {
                const next: InputBinding = {
                  binding_key: "manning.raster",
                  asset_id: asset.file_id,
                  family: "manning",
                  role: "manning-raster",
                  active: true,
                };
                onBindingsChange(binding
                  ? bindings.map((item) => item.binding_key === next.binding_key ? next : item)
                  : [...bindings, next]);
              }}
              onClear={() => onBindingsChange(bindings.map((item) => item.binding_key === "manning.raster" ? { ...item, active: false } : item))}
            />
            {!binding?.active || !boundAsset ? <div className="tf-banner tf-banner-warning">未绑定空间曼宁资产，运行预检将被阻止。</div> : null}
          </>
        )}
      </div>
    </section>
  );
}
