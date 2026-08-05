import type { RasterProfile } from "../types";

type RasterLegendProps = {
  layers: Array<{ fileId: string; name: string; family: string }>;
  profiles: Record<string, RasterProfile>;
  activeLayerId?: string;
  onSelect?: (assetId: string) => void;
};

export function RasterLegend({ layers, profiles, activeLayerId, onSelect }: RasterLegendProps) {
  return (
    <div className="tf-raster-legend" aria-label="栅格图层图例">
      <div className="tf-caption tf-font-semibold tf-text-secondary">图层</div>
      {layers.length === 0 ? <div className="tf-caption tf-text-tertiary">暂无可见栅格图层</div> : null}
      {layers.map((layer) => {
        const profile = profiles[layer.fileId];
        const statistics = profile?.statistics;
        const min = statistics?.min;
        const max = statistics?.max;
        const ready = profile?.status === "ready";
        const statusLabel = !profile ? "待激活" : profile.status;
        return (
          <button
            type="button"
            className={`tf-raster-legend-row${activeLayerId === layer.fileId ? " is-active" : ""}`}
            key={layer.fileId}
            onClick={() => onSelect?.(layer.fileId)}
            title={ready ? `${min ?? "—"} 至 ${max ?? "—"}` : !profile ? "选择图层后准备栅格档案" : "栅格档案尚未就绪"}
          >
            <span className={`tf-raster-legend-ramp ${profile?.data_kind === "categorical" ? "is-categorical" : ""}`} />
            <span className="tf-raster-legend-copy">
              <span className="tf-caption tf-text-primary tf-ellipsis">{layer.name}</span>
              <span className="tf-caption tf-text-tertiary">
                {ready ? `${min ?? "—"} – ${max ?? "—"}${profile?.unit ? ` ${profile.unit}` : ""}` : statusLabel}
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );
}
