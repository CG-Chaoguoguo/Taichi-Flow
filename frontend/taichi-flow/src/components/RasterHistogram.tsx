import type { RasterProfile } from "../types";

type RasterHistogramProps = { profile?: RasterProfile | null };

export function RasterHistogram({ profile }: RasterHistogramProps) {
  const histogram = profile?.statistics?.histogram;
  if (!histogram?.counts?.length) {
    return <div className="tf-caption tf-text-tertiary">暂无有效像元统计。</div>;
  }
  const maximum = Math.max(...histogram.counts, 1);
  const sampleStep = Math.max(1, Math.ceil(histogram.counts.length / 64));
  return (
    <div className="tf-raster-histogram" aria-label="栅格直方图" role="img">
      {histogram.counts.filter((_, index) => index % sampleStep === 0).map((count, index) => (
        <span
          key={`${index}-${count}`}
          className="tf-raster-histogram-bar"
          style={{ height: `${Math.max(2, Math.round((count / maximum) * 100))}%` }}
          title={`计数 ${count}`}
        />
      ))}
    </div>
  );
}
