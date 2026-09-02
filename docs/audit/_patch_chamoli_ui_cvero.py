"""Patch Chamoli UI scenario spatial_zones.zones with parsed cvero values."""
from __future__ import annotations

import json
from pathlib import Path

from api.services.parameter_templates import normalized_parameter_values
from api.services.reference_config_parser import parse_reference_config_file

CHAMOLI = Path(r"C:\Users\Administrator\Desktop\EDDA_test_project\Chamoli-EDDA file\Chamoli-EDDA file")
CASE = Path(
    r"C:\Users\Administrator\Desktop\Taichi-Flow\artifacts\chamoli_ui_case"
    r"\scenarios\scn-ece21ec5d9b24d3e9dda76124a6b4e6d"
)


def main() -> None:
    parsed = parse_reference_config_file(str(CHAMOLI / "edda_in.txt"), str(CHAMOLI))
    zones = normalized_parameter_values(parsed)["spatial_zones.zones"]
    print(json.dumps({k: v.get("cvero") for k, v in zones.items()}, indent=2))

    for name in ("effective_parameters.json", "scenario.json"):
        path = CASE / name
        data = json.loads(path.read_text(encoding="utf-8"))
        targets: list[dict] = []
        if name == "effective_parameters.json":
            targets.append(data)
        else:
            for key in ("effective_parameters", "parameter_baseline", "parameters"):
                nested = data.get(key)
                if isinstance(nested, dict):
                    targets.append(nested)
        for target in targets:
            zones_old = target.get("spatial_zones.zones") or {}
            for zid, zone in zones.items():
                row = dict(zones_old.get(zid) or {})
                row.update(zone)
                zones_old[zid] = row
            target["spatial_zones.zones"] = zones_old
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"patched {path}")


if __name__ == "__main__":
    main()
