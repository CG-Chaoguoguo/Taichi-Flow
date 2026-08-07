#!/usr/bin/env python3
"""Seed BJ_HXL_Text as a Taichi-Flow workbench project for local demo / acceptance.

Usage:
  python scripts/seed_bj_hxl_project.py
  python scripts/seed_bj_hxl_project.py --case-dir "C:\\path\\to\\BJ_HXL_Text" --base-url http://127.0.0.1:8000
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import httpx


DEFAULT_CASE = Path(
    r"C:\Users\Administrator\Desktop\EDDA_test_project\BJ_HXL_Text(1)\BJ_HXL_Text"
)


def _post(client: httpx.Client, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    response = client.post(path, json=payload or {})
    response.raise_for_status()
    return response.json() if response.content else {}


def _get(client: httpx.Client, path: str) -> Dict[str, Any]:
    response = client.get(path)
    response.raise_for_status()
    return response.json()


def seed(case_dir: Path, base_url: str) -> Dict[str, Any]:
    case_dir = case_dir.resolve()
    edda_in = case_dir / "edda_in.txt"
    dem = case_dir / "data" / "tutorial" / "bcdem.asc"
    if not edda_in.is_file():
        raise FileNotFoundError(f"Missing edda_in.txt under {case_dir}")
    if not dem.is_file():
        raise FileNotFoundError(f"Missing DEM at {dem}")

    with httpx.Client(base_url=base_url.rstrip("/"), timeout=60.0) as client:
        project = _post(
            client,
            "/api/projects/import",
            {"root_path": str(case_dir), "name": "BJ_HXL_Text", "description": "EDDA reference case seed"},
        )
        project_id = project["project_id"]

        uploads = []
        for family, path in (
            ("config", edda_in),
            ("dem", dem),
            ("slope", case_dir / "data" / "tutorial" / "bcslope.asc"),
            ("zones", case_dir / "data" / "tutorial" / "bczone.asc"),
            ("thickness", case_dir / "data" / "tutorial" / "bcltstar.asc"),
        ):
            if not path.is_file():
                continue
            uploads.append(
                _post(
                    client,
                    f"/api/projects/{project_id}/uploads/from-path",
                    {"family": family, "path": str(path)},
                )
            )

        revision = _post(
            client,
            f"/api/projects/{project_id}/input-revisions",
            {
                "version_tag": "bj-hxl-seed",
                "upload_ids": [item["upload_id"] for item in uploads],
            },
        )
        revision_id = revision["revision_id"]

        interface = _get(
            client,
            f"/api/projects/{project_id}/input-revisions/{revision_id}/config-interface",
        )
        rainfall = (interface.get("parsed_values") or {}).get("rainfall") or {}
        manning = (interface.get("parsed_values") or {}).get("manning") or {}

        scenario = _post(
            client,
            f"/api/projects/{project_id}/scenarios",
            {
                "name": "基准工况",
                "input_revision_id": revision_id,
                "parameter_patch": {},
            },
        )

        result = {
            "project_id": project_id,
            "revision_id": revision_id,
            "scenario_id": scenario["scenario_id"],
            "rainfall_mode": rainfall.get("mode"),
            "period_count": len(rainfall.get("periods") or rainfall.get("cri_mps") or []),
            "manning_source": manning.get("source"),
            "manning_global": manning.get("global"),
            "editor_url": f"http://127.0.0.1:5173/editor/{project_id}/scenarios/{scenario['scenario_id']}",
        }

        assert result["rainfall_mode"] == "raster_rifil", result
        assert result["period_count"] == 72, result
        assert "global" in str(result["manning_source"]), result
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", type=Path, default=DEFAULT_CASE)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    try:
        result = seed(args.case_dir, args.base_url)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
