"""Real-time snapshots with REST polling as the reconnect fallback."""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect


router = APIRouter()


def _simulation_snapshot(store, simulation_id: str) -> dict[str, Any]:
    project_id, simulation = store.find_simulation(simulation_id)
    return {"type": "simulation_snapshot", "project_id": project_id, "simulation": simulation}


@router.websocket("/ws/simulations/{run_id}")
async def simulation_events(websocket: WebSocket, run_id: str):
    await websocket.accept()
    try:
        while True:
            snapshot = _simulation_snapshot(websocket.app.state.workbench, run_id)
            await websocket.send_json(snapshot)
            status = snapshot["simulation"]["status"]
            if status in {"completed", "failed", "stopped", "interrupted"}:
                await websocket.close(code=1000)
                return
            await asyncio.sleep(0.25)
    except WebSocketDisconnect:
        return
    except Exception as exc:  # noqa: BLE001 - close a stale subscription cleanly
        try:
            await websocket.send_json({"type": "error", "code": "realtime_snapshot_failed", "message": str(exc)})
            await websocket.close(code=1011)
        except Exception:
            return


@router.websocket("/ws/projects/{project_id}/queue")
async def queue_events(websocket: WebSocket, project_id: str):
    await websocket.accept()
    try:
        while True:
            store = websocket.app.state.workbench
            items = store.list_queue(project_id)
            await websocket.send_json({"type": "queue_snapshot", "project_id": project_id, "items": items})
            if items and all(item["status"] in {"completed", "failed", "stopped", "interrupted", "cancelled"} for item in items):
                await websocket.close(code=1000)
                return
            await asyncio.sleep(0.25)
    except WebSocketDisconnect:
        return
    except Exception as exc:  # noqa: BLE001 - close a stale subscription cleanly
        try:
            await websocket.send_json({"type": "error", "code": "realtime_snapshot_failed", "message": str(exc)})
            await websocket.close(code=1011)
        except Exception:
            return
