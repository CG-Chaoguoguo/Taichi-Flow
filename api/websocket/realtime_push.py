"""
WebSocket real-time push for simulation updates.
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request
from typing import Dict, Set
import logging
import json
import asyncio

logger = logging.getLogger(__name__)

router = APIRouter()

# Active WebSocket connections
active_connections: Dict[str, Set[WebSocket]] = {}


class ConnectionManager:
    """Manage WebSocket connections."""

    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, simulation_id: str):
        """
        Connect a WebSocket client.

        Args:
            websocket: WebSocket connection
            simulation_id: Simulation ID to subscribe to
        """
        await websocket.accept()

        if simulation_id not in self.active_connections:
            self.active_connections[simulation_id] = set()

        self.active_connections[simulation_id].add(websocket)
        logger.info(f"WebSocket connected for simulation: {simulation_id}")

    def disconnect(self, websocket: WebSocket, simulation_id: str):
        """
        Disconnect a WebSocket client.

        Args:
            websocket: WebSocket connection
            simulation_id: Simulation ID
        """
        if simulation_id in self.active_connections:
            self.active_connections[simulation_id].discard(websocket)

            if not self.active_connections[simulation_id]:
                del self.active_connections[simulation_id]

        logger.info(f"WebSocket disconnected for simulation: {simulation_id}")

    async def send_message(self, message: dict, simulation_id: str):
        """
        Send message to all connected clients for a simulation.

        Args:
            message: Message dictionary
            simulation_id: Simulation ID
        """
        if simulation_id not in self.active_connections:
            return

        # Send to all connected clients
        disconnected = set()
        for connection in self.active_connections[simulation_id]:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Failed to send message: {e}")
                disconnected.add(connection)

        # Remove disconnected clients
        for connection in disconnected:
            self.disconnect(connection, simulation_id)

    async def broadcast(self, message: dict):
        """
        Broadcast message to all connected clients.

        Args:
            message: Message dictionary
        """
        for sim_id in list(self.active_connections.keys()):
            await self.send_message(message, sim_id)


# Global connection manager
manager = ConnectionManager()


@router.websocket("/simulation/{simulation_id}")
async def websocket_simulation(websocket: WebSocket, simulation_id: str):
    """
    WebSocket endpoint for real-time simulation updates.

    Args:
        websocket: WebSocket connection
        simulation_id: Simulation ID to subscribe to

    Message format:
        {
            "type": "status" | "progress" | "output" | "error",
            "simulation_id": str,
            "timestamp": str,
            "data": {...}
        }
    """
    await manager.connect(websocket, simulation_id)

    try:
        # Send initial connection message
        await websocket.send_json({
            "type": "connected",
            "simulation_id": simulation_id,
            "message": f"Connected to simulation: {simulation_id}"
        })

        # Keep connection alive and handle incoming messages
        while True:
            try:
                # Receive message from client
                data = await websocket.receive_text()
                message = json.loads(data)

                # Handle client messages
                if message.get("type") == "ping":
                    await websocket.send_json({
                        "type": "pong",
                        "simulation_id": simulation_id
                    })

                elif message.get("type") == "subscribe":
                    # Client wants to subscribe to specific updates
                    await websocket.send_json({
                        "type": "subscribed",
                        "simulation_id": simulation_id,
                        "message": "Subscription confirmed"
                    })

            except WebSocketDisconnect:
                break
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "message": "Invalid JSON format"
                })
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                break

    except Exception as e:
        logger.error(f"WebSocket connection error: {e}", exc_info=True)

    finally:
        manager.disconnect(websocket, simulation_id)


async def send_status_update(simulation_id: str, status: str, data: dict = None):
    """
    Send status update to connected clients.

    Args:
        simulation_id: Simulation ID
        status: Status string
        data: Additional data
    """
    message = {
        "type": "status",
        "simulation_id": simulation_id,
        "status": status,
        "data": data or {}
    }
    await manager.send_message(message, simulation_id)


async def send_progress_update(simulation_id: str, progress: float, time_info: dict):
    """
    Send progress update to connected clients.

    Args:
        simulation_id: Simulation ID
        progress: Progress percentage (0-100)
        time_info: Time information dictionary
    """
    message = {
        "type": "progress",
        "simulation_id": simulation_id,
        "progress": progress,
        "time_info": time_info
    }
    await manager.send_message(message, simulation_id)


async def send_output_update(simulation_id: str, output_data: dict):
    """
    Send output data update to connected clients.

    Args:
        simulation_id: Simulation ID
        output_data: Output data dictionary
    """
    message = {
        "type": "output",
        "simulation_id": simulation_id,
        "data": output_data
    }
    await manager.send_message(message, simulation_id)


async def send_error(simulation_id: str, error_message: str):
    """
    Send error message to connected clients.

    Args:
        simulation_id: Simulation ID
        error_message: Error message
    """
    message = {
        "type": "error",
        "simulation_id": simulation_id,
        "error": error_message
    }
    await manager.send_message(message, simulation_id)


@router.get("/connections")
async def get_active_connections():
    """
    Get information about active WebSocket connections.

    Returns:
        Connection statistics
    """
    connections = {}
    for sim_id, conn_set in manager.active_connections.items():
        connections[sim_id] = len(conn_set)

    return {
        "active_simulations": len(connections),
        "total_connections": sum(connections.values()),
        "connections_per_simulation": connections
    }


# Background task to send periodic updates
async def periodic_update_task(app_state: dict):
    """
    Background task to send periodic updates to connected clients.

    Args:
        app_state: Application state dictionary
    """
    while True:
        try:
            # Send updates for all active simulations
            for sim_id, sim_data in app_state['simulations'].items():
                if sim_data['status'] == 'running':
                    # Send progress update
                    await send_progress_update(
                        sim_id,
                        sim_data['progress'],
                        {
                            't_current': sim_data['current_time'],
                            't_end': sim_data['end_time'],
                            'step_count': sim_data['step_count']
                        }
                    )

            # Wait before next update
            await asyncio.sleep(1.0)  # Update every second

        except Exception as e:
            logger.error(f"Periodic update error: {e}")
            await asyncio.sleep(5.0)
