from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from api.app import create_app


def test_health_exposes_desktop_runtime_contract(tmp_path: Path) -> None:
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["service_id"] == "taichi-flow-api"
    assert payload["api_contract_version"] == 1
    assert len(payload["checkout_id"]) == 16
    assert all(character in "0123456789abcdef" for character in payload["checkout_id"])


def test_desktop_preview_origin_is_explicitly_allowed(tmp_path: Path) -> None:
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        response = client.options(
            "/api/health",
            headers={
                "Origin": "app://taichi-flow",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "app://taichi-flow"


def test_unknown_desktop_origin_is_not_allowed(tmp_path: Path) -> None:
    with TestClient(create_app(state_dir=tmp_path / "state", scheduler_enabled=False)) as client:
        response = client.options(
            "/api/health",
            headers={
                "Origin": "https://untrusted.example",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
