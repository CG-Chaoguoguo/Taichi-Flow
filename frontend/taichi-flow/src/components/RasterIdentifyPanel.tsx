import { Crosshair, Grid3X3, Info } from "lucide-react";
import type { RasterIdentifyLayer } from "../types";

type RasterIdentifyPanelProps = {
  coordinate?: { x: number; y: number } | null;
  layers: RasterIdentifyLayer[];
  loading?: boolean;
};

function numberText(value: number | null | undefined) {
  return value == null ? "—" : Number.isInteger(value) ? String(value) : value.toLocaleString("zh-CN", { maximumFractionDigits: 6 });
}

export function RasterIdentifyPanel({ coordinate, layers, loading }: RasterIdentifyPanelProps) {
  if (!coordinate && !loading) return null;
  return (
    <section className="tf-raster-identify-panel" aria-label="像元识别结果" aria-live="polite">
      <div className="tf-row tf-gap-2 tf-mb-2">
        <Crosshair size={15} />
        <strong className="tf-caption">原始像元值</strong>
        {loading && layers.length === 0 ? <span className="tf-caption tf-text-tertiary">读取中…</span> : null}
      </div>
      {coordinate ? <div className="tf-mono tf-caption tf-text-secondary">X: {numberText(coordinate.x)} · Y: {numberText(coordinate.y)}</div> : null}
      {layers.map((layer) => (
        <article key={layer.asset_id} className="tf-raster-identify-layer">
          <div className="tf-row tf-gap-2">
            <Info size={14} />
            <strong className="tf-caption tf-ellipsis">{layer.name || layer.asset_id}</strong>
            <span className={`tf-raster-value-status is-${layer.status}`}>{layer.status === "nodata" ? "NoData" : layer.status}</span>
          </div>
          <div className="tf-raster-identify-grid">
            <span>原始值</span><strong className="tf-mono">{layer.raw?.value_text || "NoData"}</strong>
            <span>行 / 列</span><strong className="tf-mono">{layer.row_one_based ?? "—"} / {layer.column_one_based ?? "—"}</strong>
            <span>像元中心</span><strong className="tf-mono">{layer.cell_center ? `${numberText(layer.cell_center.x)}, ${numberText(layer.cell_center.y)}` : "—"}</strong>
            <span>类型 / 单位</span><strong>{layer.dtype || "—"} / {layer.unit || "未声明"}</strong>
            <span>采样 / 源哈希</span><strong title={layer.source_sha256}>{layer.sampled_from === "source_base" ? "源栅格全分辨率" : layer.sampled_from} / {layer.source_sha256 ? layer.source_sha256.slice(0, 12) : "—"}</strong>
          </div>
          {layer.neighborhood ? (
            <div className="tf-raster-neighborhood" aria-label={`${layer.name || "图层"} 三乘三邻域`}>
              <div className="tf-row tf-gap-1 tf-mb-1"><Grid3X3 size={13} /> <span className="tf-caption">3×3 邻域</span></div>
              <table>
                <tbody>
                  {layer.neighborhood.value_text.map((row, rowIndex) => (
                    <tr key={rowIndex}>{row.map((value, columnIndex) => <td key={`${rowIndex}-${columnIndex}`}>{value}</td>)}</tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </article>
      ))}
    </section>
  );
}
