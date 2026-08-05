import type { RasterIdentifyResponse, RasterProfile } from "../types";
import { RasterIdentifyPanel } from "./RasterIdentifyPanel";
import { RasterSymbologyPanel, type RasterSymbology } from "./RasterSymbologyPanel";

type RasterLayerInspectorProps = {
  profile?: RasterProfile | null;
  identify?: RasterIdentifyResponse | null;
  identifyLoading?: boolean;
  symbology: RasterSymbology;
  onSymbologyChange: (next: RasterSymbology) => void;
};

export function RasterLayerInspector({ profile, identify, identifyLoading, symbology, onSymbologyChange }: RasterLayerInspectorProps) {
  return (
    <div className="tf-raster-layer-inspector">
      <RasterIdentifyPanel coordinate={identify?.coordinate} layers={identify?.layers || []} loading={identifyLoading} />
      {profile ? <RasterMetadataSummary profile={profile} /> : null}
      <RasterSymbologyPanel profile={profile} value={symbology} onChange={onSymbologyChange} />
    </div>
  );
}

function RasterMetadataSummary({ profile }: { profile: RasterProfile }) {
  const stats = profile.statistics;
  const transform = profile.transform;
  const dimensions = profile.width && profile.height ? `${profile.width} × ${profile.height}` : "—";
  const pixelSize = transform ? `${Math.abs(transform.a).toLocaleString("zh-CN")} × ${Math.abs(transform.e).toLocaleString("zh-CN")}` : "—";
  const crs = profile.crs || "工程坐标（CRS 未定义）";
  return (
    <section className="tf-raster-metadata" aria-label="栅格信息">
      <div className="tf-caption tf-font-semibold tf-text-secondary">栅格信息</div>
      {profile.status !== "ready" ? <div className="tf-caption tf-text-tertiary">档案状态：{profile.status}</div> : null}
      <div className="tf-raster-metadata-grid">
        <span>尺寸 / 波段</span><strong>{dimensions} / {profile.band_count ?? "—"}</strong>
        <span>类型 / NoData</span><strong>{profile.dtype || "—"} / {profile.nodata ?? "未声明"}</strong>
        <span>像元大小</span><strong>{pixelSize}</strong>
        <span>坐标参考</span><strong title={crs}>{crs}</strong>
        <span>有效 / NoData</span><strong>{stats ? `${(stats.valid_count ?? 0).toLocaleString("zh-CN")} / ${(stats.nodata_count ?? 0).toLocaleString("zh-CN")}` : "—"}</strong>
        <span>源哈希</span><strong className="tf-mono" title={profile.source_sha256}>{profile.source_sha256 ? profile.source_sha256.slice(0, 12) : "—"}</strong>
      </div>
    </section>
  );
}
