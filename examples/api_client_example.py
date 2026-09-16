"""Small httpx example for the Taichi-Flow project workflow.

The example follows the public domain API: project -> upload -> input revision
-> scenario -> queue -> status/results. It deliberately uses REST polling,
which is the current browser client's operational path.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Iterable

import httpx


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("taichi-flow-example")

BASE_URL = os.getenv("TAICHI_FLOW_API_URL", "http://127.0.0.1:8000")


class TaichiFlowClient:
    """Thin client for the Taichi-Flow project API."""

    def __init__(self, base_url: str = BASE_URL, *, timeout: float = 30.0) -> None:
        self.client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout)

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "TaichiFlowClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self.client.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json() if response.content else None

    def health_check(self) -> dict[str, Any]:
        return self._request("GET", "/api/health")

    def create_project(self, name: str, root_path: str, description: str = "") -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/projects",
            json={"name": name, "root_path": root_path, "description": description},
        )

    def upload_file(self, project_id: str, family: str, path: str | Path) -> dict[str, Any]:
        source = Path(path)
        with source.open("rb") as handle:
            return self._request(
                "POST",
                f"/api/projects/{project_id}/uploads/{family}",
                files={"file": (source.name, handle, "application/octet-stream")},
            )

    def create_input_revision(
        self,
        project_id: str,
        upload_ids: Iterable[str],
        version_tag: str = "example",
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/projects/{project_id}/input-revisions",
            json={"version_tag": version_tag, "upload_ids": list(upload_ids)},
        )

    def create_scenario(
        self,
        project_id: str,
        input_revision_id: str,
        *,
        name: str = "Taichi-Flow example",
        parameter_patch: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/projects/{project_id}/scenarios",
            json={
                "name": name,
                "input_revision_id": input_revision_id,
                "parameter_patch": parameter_patch or {},
            },
        )

    def enqueue(self, project_id: str, scenario_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/projects/{project_id}/queue",
            json={"scenario_id": scenario_id},
        )

    def list_simulations(self, project_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/projects/{project_id}/simulations")

    def get_simulation(self, project_id: str, simulation_id: str) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/api/projects/{project_id}/simulations/{simulation_id}",
        )

    def get_results(self, project_id: str, simulation_id: str) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/api/projects/{project_id}/results/{simulation_id}",
        )

    def download_result(
        self,
        project_id: str,
        simulation_id: str,
        filename: str,
        destination: str | Path,
    ) -> Path:
        response = self.client.get(
            f"/api/projects/{project_id}/results/{simulation_id}/files/{filename}"
        )
        response.raise_for_status()
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(response.content)
        return target


def _value(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if value:
            return str(value)
    raise KeyError(f"response did not contain any of {keys!r}: {payload!r}")


def example_workflow() -> None:
    """Run the small end-to-end project workflow against a running API."""

    project_root = Path(
        os.getenv(
            "TAICHI_FLOW_EXAMPLE_PROJECT_ROOT",
            str(Path.cwd() / ".runtime" / "examples" / "api-client"),
        )
    )
    dem_file = Path(__file__).with_name("data") / "dev_tiny_dem.asc"
    rainfall_file = Path(__file__).with_name("data") / "dev_rainfall.csv"

    with TaichiFlowClient() as client:
        health = client.health_check()
        logger.info("Taichi-Flow API status: %s", health.get("status"))

        project = client.create_project(
            "Taichi-Flow API example",
            str(project_root),
            "Small REST workflow example",
        )
        project_id = _value(project, "project_id", "id")

        dem = client.upload_file(project_id, "dem", dem_file)
        rainfall = client.upload_file(project_id, "rainfall", rainfall_file)
        upload_ids = [_value(dem, "upload_id", "asset_id", "id"), _value(rainfall, "upload_id", "asset_id", "id")]

        revision = client.create_input_revision(project_id, upload_ids)
        revision_id = _value(revision, "revision_id", "id")
        scenario = client.create_scenario(project_id, revision_id)
        scenario_id = _value(scenario, "scenario_id", "id")
        queue_item = client.enqueue(project_id, scenario_id)
        logger.info("Queued scenario %s: %s", scenario_id, queue_item)

        for _ in range(60):
            simulations = client.list_simulations(project_id)
            rows = simulations.get("simulations", simulations if isinstance(simulations, list) else [])
            if rows:
                simulation_id = _value(rows[-1], "simulation_id", "id")
                status = client.get_simulation(project_id, simulation_id)
                logger.info("Simulation %s: %s", simulation_id, status.get("status"))
                if status.get("status") in {"completed", "failed", "stopped", "cancelled", "interrupted"}:
                    if status.get("status") == "completed":
                        logger.info("Results: %s", client.get_results(project_id, simulation_id))
                    break
            time.sleep(1)


if __name__ == "__main__":
    example_workflow()
