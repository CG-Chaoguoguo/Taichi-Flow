import { Link2, X } from "lucide-react";
import { useState } from "react";
import type { InputBinding, InputFile } from "../types";
import { AssetPickerDialog } from "./AssetPickerDialog";

export function AssetBindingField({
  label,
  pickerLabel,
  family,
  binding,
  assets,
  disabled = false,
  compact = false,
  sortable = false,
  onSelect,
  onClear,
}: {
  label: string;
  pickerLabel: string;
  family: string;
  binding?: InputBinding;
  assets: InputFile[];
  disabled?: boolean;
  compact?: boolean;
  sortable?: boolean;
  onSelect: (asset: InputFile) => void;
  onClear?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const asset = assets.find((item) => item.file_id === binding?.asset_id);
  return (
    <div className={`tf-asset-binding-field${compact ? " is-compact" : ""}`}>
      {!compact ? <span className="tf-caption tf-text-secondary">{label}</span> : null}
      <div className="tf-row tf-gap-1">
        <button
          type="button"
          className={`tf-asset-binding-button${asset ? " has-value" : ""}`}
          aria-label={pickerLabel}
          disabled={disabled}
          onClick={() => setOpen(true)}
        >
          <Link2 size={14} />
          <span className="tf-ellipsis">{asset?.name || "选择资产"}</span>
        </button>
        {asset && onClear ? (
          <button type="button" className="tf-icon-button tf-icon-button-sm" aria-label={`清除${label}`} disabled={disabled} onClick={onClear}>
            <X size={13} />
          </button>
        ) : null}
      </div>
      <AssetPickerDialog
        open={open}
        title={label}
        family={family}
        assets={assets}
        selectedAssetId={binding?.asset_id}
        sortable={sortable}
        onSelect={onSelect}
        onClose={() => setOpen(false)}
      />
    </div>
  );
}
