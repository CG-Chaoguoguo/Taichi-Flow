"""Summarize Chamoli CUDA t=900 20-frame grid diffs. Not a production import."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(r"C:\Users\Administrator\Desktop\Taichi-Flow\artifacts\chamoli_cuda_t900_zones")
OUT = ROOT / "frame_diff_summary.json"

FOCUS = [
    "Flow_depth_EDDA",
    "SFdepthEDDA",
    "MaxFFdepthEDDA",
    "Max_flow_depth_EDDA",
    "FFdepthEDDA",
    "DFdepthEDDA",
    "LS_ScarEDDA",
    "faildphEDDA",
    "Erosion_depth_EDDA",
]


def main() -> None:
    man = json.loads((ROOT / "run_manifest.json").read_text(encoding="utf-8"))
    keys = sorted(man.get("checkpoint_summaries", {}), key=lambda k: float(k))
    frames = []
    for key in keys:
        summary = man["checkpoint_summaries"][key]
        fams = {row["family"]: row for row in summary["families"]}
        focus_rows = {}
        for name in FOCUS:
            row = fams[name]
            focus_rows[name] = {
                "status": row["status"],
                "max_abs": row.get("max_abs_error"),
                "rmse": row.get("rmse"),
                "wet": row.get("wet_cell_count"),
            }
        frames.append(
            {
                "t": float(key),
                "pass_count": summary["pass_count"],
                "residual_count": summary["residual_count"],
                "missing_count": summary["missing_count"],
                "max_abs_error": summary["max_abs_error"],
                "focus": focus_rows,
            }
        )
    payload = {
        "status": man.get("status"),
        "elapsed_seconds": man.get("elapsed_seconds"),
        "backend": man.get("backend"),
        "t_end": man.get("t_end"),
        "n_frames": len(keys),
        "frames": frames,
        "parity_claim": False,
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"status={man.get('status')} elapsed={man.get('elapsed_seconds'):.1f}s frames={len(keys)}")
    print("t\tFlow_depth max/rmse/wet\tSF\tMaxFF\tpass/miss")
    for frame in frames:
        fd = frame["focus"]["Flow_depth_EDDA"]
        sf = frame["focus"]["SFdepthEDDA"]
        ff = frame["focus"]["MaxFFdepthEDDA"]
        def fmt(row: dict) -> str:
            if row["status"] == "pass":
                return "pass"
            if row["status"] == "missing":
                return "MISS"
            return f"{row['max_abs']:.3f}/{row['rmse']:.3f}/w{row['wet']}"
        print(
            f"{frame['t']:.0f}\t{fmt(fd)}\t{fmt(sf)}\t{fmt(ff)}\t"
            f"{frame['pass_count']}/{frame['missing_count']}"
        )
    for t in (45.0, 90.0, 900.0):
        key = f"{t:.1f}"
        summary = man["checkpoint_summaries"][key]
        print(f"\n== t={key} pass={summary['pass_count']} residual={summary['residual_count']} missing={summary['missing_count']}")
        for row in summary["families"]:
            if row["status"] == "residual":
                print(
                    f"  {row['family']:32s} max={row['max_abs_error']:.4f} "
                    f"rmse={row['rmse']:.4f} wet={row['wet_cell_count']}"
                )
            else:
                print(f"  {row['family']:32s} {row['status']}")


if __name__ == "__main__":
    main()
