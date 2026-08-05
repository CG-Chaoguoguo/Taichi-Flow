import type { RasterProfile } from "../types";
import { RasterHistogram } from "./RasterHistogram";

type RasterSymbology = {
  stretch: "minmax" | "percent_clip" | "stddev" | "none";
  resampling: "nearest" | "bilinear";
  opacity: number;
};

type RasterSymbologyPanelProps = {
  profile?: RasterProfile | null;
  value: RasterSymbology;
  onChange: (next: RasterSymbology) => void;
};

export function RasterSymbologyPanel({ profile, value, onChange }: RasterSymbologyPanelProps) {
  if (!profile || profile.status !== "ready") return null;
  const continuous = profile.data_kind !== "categorical";
  return (
    <section className="tf-raster-symbology" aria-label="栅格符号系统">
      <div className="tf-caption tf-font-semibold tf-text-secondary">符号系统</div>
      <label className="tf-field tf-field--compact">
        <span>拉伸方式</span>
        <select value={value.stretch} disabled={!continuous} onChange={(event) => onChange({ ...value, stretch: event.target.value as RasterSymbology["stretch"] })}>
          <option value="minmax">最小—最大</option>
          <option value="percent_clip">2–98% 裁剪</option>
          <option value="stddev">标准差</option>
          <option value="none">不拉伸</option>
        </select>
      </label>
      <label className="tf-field tf-field--compact">
        <span>显示插值</span>
        <select value={value.resampling} disabled={profile.data_kind === "categorical"} onChange={(event) => onChange({ ...value, resampling: event.target.value as RasterSymbology["resampling"] })}>
          <option value="bilinear">双线性</option>
          <option value="nearest">最近邻</option>
        </select>
      </label>
      <label className="tf-field tf-field--compact">
        <span>透明度 {Math.round((1 - value.opacity) * 100)}%</span>
        <input type="range" min="0.1" max="1" step="0.05" value={value.opacity} onChange={(event) => onChange({ ...value, opacity: Number(event.target.value) })} />
      </label>
      <RasterHistogram profile={profile} />
    </section>
  );
}

export type { RasterSymbology };
