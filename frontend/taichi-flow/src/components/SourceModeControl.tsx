export type SourceMode = "uniform" | "raster";

export function SourceModeControl({
  value,
  onChange,
  disabled = false,
  label,
}: {
  value: SourceMode;
  onChange: (value: SourceMode) => void;
  disabled?: boolean;
  label: string;
}) {
  return (
    <select
      className="tf-input tf-input-compact tf-source-mode-control"
      aria-label={label}
      value={value}
      disabled={disabled}
      onChange={(event) => onChange(event.target.value as SourceMode)}
    >
      <option value="uniform">均匀值</option>
      <option value="raster">栅格资产</option>
    </select>
  );
}
