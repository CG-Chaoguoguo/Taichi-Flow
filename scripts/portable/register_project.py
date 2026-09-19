"""Create the private portable catalog and register its bundled project."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--name", required=True)
    parser.add_argument("--description", default="")
    args = parser.parse_args()
    root = args.root.resolve()
    sys.path.insert(0, str(root))
    from api.services.workbench_store import WorkbenchStore

    store = WorkbenchStore(args.state_dir.resolve())
    project = store.create_or_open_project(
        name=args.name,
        root_path=str(args.project.resolve()),
        description=args.description,
    )
    print(json.dumps(project, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
