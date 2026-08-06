from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from api.app import create_app


def test_directory_picker_lists_local_directories_and_typed_files(tmp_path: Path) -> None:
    root = tmp_path / "drive-c"
    child = root / "project-parent"
    child.mkdir(parents=True)
    (root / "not-a-directory.txt").write_text("not exposed", encoding="utf-8")

    app = create_app(
        state_dir=tmp_path / "state",
        scheduler_enabled=False,
        directory_roots=[root],
    )
    with TestClient(app) as client:
        roots = client.get("/api/system/directories")
        assert roots.status_code == 200
        assert roots.json()["roots"] == [
            {
                "name": "drive-c",
                "path": str(root.resolve()),
                "writable": True,
                "kind": "directory",
                "size": None,
            }
        ]

        listing = client.get("/api/system/directories", params={"path": str(root)})
        assert listing.status_code == 200
        payload = listing.json()
        assert payload["current_path"] == str(root.resolve())
        assert payload["parent_path"] is None
        assert payload["can_select"] is True
        assert payload["directories"] == [
            {
                "name": "project-parent",
                "path": str(child.resolve()),
                "writable": True,
                "kind": "directory",
                "size": None,
            }
        ]
        assert payload["files"] == [
            {
                "name": "not-a-directory.txt",
                "path": str((root / "not-a-directory.txt").resolve()),
                "writable": True,
                "kind": "file",
                "size": len("not exposed"),
            }
        ]


def test_directory_picker_rejects_non_local_and_invalid_paths(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "drive-c"
    root.mkdir()
    file_path = root / "file.txt"
    file_path.write_text("file", encoding="utf-8")

    app = create_app(
        state_dir=tmp_path / "state",
        scheduler_enabled=False,
        directory_roots=[root],
    )
    with TestClient(app) as client:
        outside = client.get("/api/system/directories", params={"path": str(tmp_path)})
        assert outside.status_code == 422
        assert outside.json()["code"] == "directory_path_not_local"

        missing = client.get("/api/system/directories", params={"path": str(root / "missing")})
        assert missing.status_code == 404
        assert missing.json()["code"] == "path_not_found"

        not_directory = client.get("/api/system/directories", params={"path": str(file_path)})
        assert not_directory.status_code == 409
        assert not_directory.json()["code"] == "directory_not_directory"

        network = client.get("/api/system/directories", params={"path": r"\\server\share"})
        assert network.status_code == 422
        assert network.json()["code"] == "network_path_not_supported"

        original_iterdir = Path.iterdir

        def deny_selected_root(path: Path):
            if path.resolve() == root.resolve():
                raise PermissionError("access denied for test")
            return original_iterdir(path)

        monkeypatch.setattr(Path, "iterdir", deny_selected_root)
        denied = client.get("/api/system/directories", params={"path": str(root)})
        assert denied.status_code == 403
        assert denied.json()["code"] == "directory_access_denied"


def test_directory_picker_has_a_typed_openapi_contract_without_legacy_routes(tmp_path: Path) -> None:
    root = tmp_path / "drive-c"
    root.mkdir()
    app = create_app(
        state_dir=tmp_path / "state",
        scheduler_enabled=False,
        directory_roots=[root],
    )

    schema = app.openapi()
    directory_schema = schema["paths"]["/api/system/directories"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert directory_schema["$ref"].endswith("/DirectoryListingResponse")
    properties = schema["components"]["schemas"]["DirectoryListingResponse"]["properties"]
    assert set(properties) == {"current_path", "parent_path", "roots", "directories", "files", "can_select"}
    location_properties = schema["components"]["schemas"]["DirectoryLocationResponse"]["properties"]
    assert set(location_properties) == {"name", "path", "writable", "kind", "size"}

    for legacy_path in {
        "/api/projects/list",
        "/api/projects/create",
        "/api/projects/open",
        "/api/simulations/start",
        "/api/simulation/{simulation_id}",
        "/api/results/export",
        "/ws/simulation/{simulation_id}",
    }:
        assert legacy_path not in schema["paths"]
