import { RotateCcw } from "lucide-react";

export type ZoneSoilRow = Record<string, unknown> & { zone_id?: number };

type ZoneFieldSpec = {
  key: string;
  label: string;
  optional?: boolean;
};

const TOP_FIELDS: ZoneFieldSpec[] = [
  { key: "K_sat_top", label: "K_sat" },
  { key: "alpha_top", label: "α" },
  { key: "theta_sat_top", label: "θsat" },
  { key: "theta_res_top", label: "θres" },
  { key: "c", label: "c" },
  { key: "phi", label: "φ" },
  { key: "phib", label: "φb" },
  { key: "gamma_s", label: "γs" },
  { key: "kero", label: "kero" },
  { key: "ctao", label: "ctao" },
  { key: "cvero", label: "cvero", optional: true },
];

const BOTTOM_FIELDS: ZoneFieldSpec[] = [
  { key: "K_sat_bottom", label: "K_sat" },
  { key: "alpha_bottom", label: "α" },
  { key: "theta_sat_bottom", label: "θsat" },
  { key: "theta_res_bottom", label: "θres" },
  { key: "c_bottom", label: "c" },
  { key: "phi_bottom", label: "φ" },
  { key: "phib_bottom", label: "φb" },
  { key: "gamma_s_bottom", label: "γs" },
];

export const ZONE_TAKEN_OVER_KEYS = [
  "soil.c",
  "soil.phi",
  "soil.gamma_s",
  "hydrology.K_sat",
  "erosion.tau_c",
  "erosion.ctao",
  "erosion.k_erosion",
] as const;

export function parseZoneSoilRows(value: unknown): ZoneSoilRow[] {
  if (!value || typeof value !== "object" || Array.isArray(value)) return [];
  const rows: ZoneSoilRow[] = [];
  for (const [key, row] of Object.entries(value as Record<string, ZoneSoilRow>)) {
    if (!row || typeof row !== "object") continue;
    const zoneId = Number(row.zone_id ?? key);
    if (!Number.isFinite(zoneId)) continue;
    rows.push({ ...row, zone_id: zoneId });
  }
  return rows.sort((left, right) => Number(left.zone_id) - Number(right.zone_id));
}

export function countSpatialZones(value: unknown): number {
  return parseZoneSoilRows(value).length;
}

function formatCell(value: unknown): string {
  if (value == null || value === "") return "";
  return String(value);
}

function parseCell(raw: string, optional: boolean): unknown {
  const text = raw.trim();
  if (text === "") return optional ? null : 0;
  const numeric = Number(text);
  return Number.isFinite(numeric) ? numeric : text;
}

function cloneZones(rows: ZoneSoilRow[]): Record<string, ZoneSoilRow> {
  const next: Record<string, ZoneSoilRow> = {};
  for (const row of rows) {
    const id = Number(row.zone_id);
    next[String(id)] = { ...row, zone_id: id };
  }
  return next;
}

function ZoneMatrixTable({
  title,
  caption,
  fields,
  rows,
  editable,
  onChangeCell,
}: {
  title: string;
  caption?: string;
  fields: ZoneFieldSpec[];
  rows: ZoneSoilRow[];
  editable: boolean;
  onChangeCell: (zoneId: number, key: string, value: unknown) => void;
}) {
  return (
    <div className="tf-zone-soil-block">
      <div className="tf-body tf-font-medium">{title}</div>
      {caption ? <div className="tf-caption tf-text-tertiary">{caption}</div> : null}
      <div className="tf-table-wrap tf-zone-soil-table-wrap">
        <table className="tf-table tf-table-compact tf-zone-soil-table">
          <thead>
            <tr>
              <th>区号</th>
              {fields.map((field) => (
                <th key={field.key}>{field.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const zoneId = Number(row.zone_id);
              return (
                <tr key={zoneId}>
                  <td>{zoneId}</td>
                  {fields.map((field) => (
                    <td key={field.key}>
                      <input
                        className="tf-input tf-input-compact"
                        aria-label={`分区 ${zoneId} ${title} ${field.label}`}
                        type="number"
                        step="any"
                        disabled={!editable}
                        value={formatCell(row[field.key])}
                        onChange={(event) => onChangeCell(zoneId, field.key, parseCell(event.target.value, Boolean(field.optional)))}
                      />
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function ZoneSoilEditor({
  draftPatch,
  baseline = {},
  onDraftChange,
  canEdit = true,
  readOnly = false,
}: {
  draftPatch: Record<string, unknown>;
  baseline?: Record<string, unknown>;
  onDraftChange: (patch: Record<string, unknown>) => void;
  canEdit?: boolean;
  readOnly?: boolean;
}) {
  const baselineZones = baseline["spatial_zones.zones"];
  const overrideZones = draftPatch["spatial_zones.zones"];
  const effective = overrideZones === undefined ? baselineZones : overrideZones;
  const rows = parseZoneSoilRows(effective);
  if (!rows.length) return null;

  const multiZone = rows.length > 1;
  const editable = canEdit && !readOnly && multiZone;
  const changed = overrideZones !== undefined;

  const commitRows = (nextRows: ZoneSoilRow[]) => {
    onDraftChange({
      ...draftPatch,
      "spatial_zones.zones": cloneZones(nextRows),
    });
  };

  const changeCell = (zoneId: number, key: string, value: unknown) => {
    if (!editable) return;
    const nextRows = parseZoneSoilRows(effective).map((row) => {
      if (Number(row.zone_id) !== zoneId) return row;
      const next = { ...row, [key]: value };
      if (key === "K_sat_top") next.K_sat = value;
      return next;
    });
    commitRows(nextRows);
  };

  const reset = () => {
    const next = { ...draftPatch };
    delete next["spatial_zones.zones"];
    onDraftChange(next);
  };

  return (
    <section className="tf-card tf-card-flush tf-config-section" data-testid="zone-soil-editor">
      <div className="tf-row tf-justify-between tf-gap-2">
        <div className="tf-body tf-font-semibold">按分区编辑双层土参数</div>
        <span className={`tf-source-chip${changed ? " is-override" : ""}`}>{changed ? "方案覆盖" : "案例默认"}</span>
      </div>
      <div className="tf-card-body-sm tf-stack tf-gap-2">
        <div className="tf-caption tf-text-tertiary">
          {multiZone
            ? "每个分区有独立的顶层/底层水力与强度参数；厚度 ltstar/lbstar 来自栅格或全局标量，不在此表。"
            : "当前案例仅 1 个分区，矩阵只读。"}
        </div>
        <ZoneMatrixTable
          title="顶层"
          fields={TOP_FIELDS}
          rows={rows}
          editable={editable}
          onChangeCell={changeCell}
        />
        <ZoneMatrixTable
          title="底层"
          caption="底层黏聚力 / 摩擦角 / 重度原 EDDA 读取但不参与双层土 FS 计算，仅作分区档案。"
          fields={BOTTOM_FIELDS}
          rows={rows}
          editable={editable}
          onChangeCell={changeCell}
        />
        <div className="tf-row tf-justify-end">
          <button
            type="button"
            className="tf-icon-button tf-icon-button-sm"
            aria-label="重置分区双层土参数"
            title="重置为案例默认值"
            disabled={!canEdit || !changed}
            onClick={reset}
          >
            <RotateCcw size={14} />
          </button>
        </div>
      </div>
    </section>
  );
}
