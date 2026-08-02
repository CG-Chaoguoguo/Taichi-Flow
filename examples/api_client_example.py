"""
Example API client for EDDA simulation service.

Demonstrates how to:
1. Upload DEM file
2. Start simulation
3. Monitor progress via WebSocket
4. Download results
"""
import requests
import json
import time
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# API base URL
BASE_URL = "http://localhost:8000"
API_URL = f"{BASE_URL}/api"
WS_URL = "ws://localhost:8000/ws"


class EDDAClient:
    """Client for EDDA API."""

    def __init__(self, base_url: str = BASE_URL):
        """
        Initialize client.

        Args:
            base_url: Base URL of API server
        """
        self.base_url = base_url
        self.api_url = f"{base_url}/api"
        self.ws_url = base_url.replace("http", "ws") + "/ws"
        self.session = requests.Session()

    def health_check(self):
        """Check API health."""
        response = self.session.get(f"{self.api_url}/health")
        response.raise_for_status()
        return response.json()

    def upload_dem(self, dem_file: str, session_id: str = None):
        """
        Upload DEM file.

        Args:
            dem_file: Path to DEM file
            session_id: Optional session ID

        Returns:
            Upload response
        """
        logger.info(f"Uploading DEM: {dem_file}")

        with open(dem_file, 'rb') as f:
            files = {'file': f}
            params = {}
            if session_id:
                params['session_id'] = session_id

            response = self.session.post(
                f"{self.api_url}/upload/dem",
                files=files,
                params=params
            )
            response.raise_for_status()

        result = response.json()
        logger.info(f"DEM uploaded: {result['message']}")
        return result

    def upload_rainfall(self, rainfall_file: str, session_id: str = None):
        """
        Upload rainfall file.

        Args:
            rainfall_file: Path to rainfall file
            session_id: Optional session ID

        Returns:
            Upload response
        """
        logger.info(f"Uploading rainfall: {rainfall_file}")

        with open(rainfall_file, 'rb') as f:
            files = {'file': f}
            params = {}
            if session_id:
                params['session_id'] = session_id

            response = self.session.post(
                f"{self.api_url}/upload/rainfall",
                files=files,
                params=params
            )
            response.raise_for_status()

        result = response.json()
        logger.info(f"Rainfall uploaded: {result['message']}")
        return result

    def start_simulation(self, dem_file: str, rainfall_file: str = None, config: dict = None):
        """
        Start simulation.

        Args:
            dem_file: Path to DEM file (on server)
            rainfall_file: Path to rainfall file (on server)
            config: Optional configuration dictionary

        Returns:
            Simulation response with ID
        """
        logger.info("Starting simulation...")

        data = {
            "dem_file": dem_file,
            "rainfall_file": rainfall_file,
            "config": config or {}
        }

        response = self.session.post(
            f"{self.api_url}/simulation/start",
            json=data
        )
        response.raise_for_status()

        result = response.json()
        logger.info(f"Simulation started: {result['simulation_id']}")
        return result

    def get_status(self, simulation_id: str):
        """
        Get simulation status.

        Args:
            simulation_id: Simulation ID

        Returns:
            Status information
        """
        response = self.session.get(
            f"{self.api_url}/simulation/{simulation_id}/status"
        )
        response.raise_for_status()
        return response.json()

    def pause_simulation(self, simulation_id: str):
        """Pause simulation."""
        response = self.session.post(
            f"{self.api_url}/simulation/{simulation_id}/pause"
        )
        response.raise_for_status()
        return response.json()

    def resume_simulation(self, simulation_id: str):
        """Resume simulation."""
        response = self.session.post(
            f"{self.api_url}/simulation/{simulation_id}/resume"
        )
        response.raise_for_status()
        return response.json()

    def stop_simulation(self, simulation_id: str):
        """Stop simulation."""
        response = self.session.post(
            f"{self.api_url}/simulation/{simulation_id}/stop"
        )
        response.raise_for_status()
        return response.json()

    def get_results(self, simulation_id: str):
        """
        Get simulation results.

        Args:
            simulation_id: Simulation ID

        Returns:
            List of result files
        """
        response = self.session.get(
            f"{self.api_url}/results/{simulation_id}"
        )
        response.raise_for_status()
        return response.json()

    def download_result(self, simulation_id: str, filename: str, output_path: str):
        """
        Download result file.

        Args:
            simulation_id: Simulation ID
            filename: File name to download
            output_path: Local path to save file
        """
        logger.info(f"Downloading: {filename}")

        response = self.session.get(
            f"{self.api_url}/results/{simulation_id}/download/{filename}",
            stream=True
        )
        response.raise_for_status()

        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        logger.info(f"Downloaded to: {output_path}")

    def monitor_websocket(self, simulation_id: str, callback=None):
        """
        Monitor simulation via WebSocket.

        Args:
            simulation_id: Simulation ID
            callback: Optional callback function for messages
        """
        try:
            import websocket
        except ImportError as exc:
            raise ImportError(
                "websocket-client is required for WebSocket monitoring. "
                "Install with: pip install websocket-client"
            ) from exc

        ws_url = f"{self.ws_url}/simulation/{simulation_id}"
        logger.info(f"Connecting to WebSocket: {ws_url}")

        def on_message(ws, message):
            data = json.loads(message)
            if callback:
                callback(data)
            else:
                logger.info(f"WebSocket message: {data}")

        def on_error(ws, error):
            logger.error(f"WebSocket error: {error}")

        def on_close(ws, close_status_code, close_msg):
            logger.info("WebSocket closed")

        def on_open(ws):
            logger.info("WebSocket connected")

        ws = websocket.WebSocketApp(
            ws_url,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
            on_open=on_open
        )

        ws.run_forever()


def example_workflow():
    """Example workflow using the API."""
    logger.info("=" * 60)
    logger.info("EDDA API Client Example")
    logger.info("=" * 60)

    # Create client
    client = EDDAClient()

    # Check health
    health = client.health_check()
    logger.info(f"API Status: {health['status']}")

    # Upload DEM (assuming file exists)
    dem_file = "examples/data/synthetic_dem.tif"
    if Path(dem_file).exists():
        upload_result = client.upload_dem(dem_file, session_id="example")
        dem_path = upload_result['file_path']
    else:
        logger.warning(f"DEM file not found: {dem_file}")
        logger.info("Please create DEM file first using examples/basic_simulation.py")
        return

    # Start simulation
    config = {
        "time": {
            "t_end": 300.0,  # 5 minutes
            "dt_output": 30.0  # Output every 30 seconds
        }
    }

    sim_result = client.start_simulation(
        dem_file=dem_path,
        config=config
    )
    sim_id = sim_result['simulation_id']

    # Monitor progress
    logger.info("Monitoring simulation progress...")
    for i in range(30):  # Check for 30 seconds
        time.sleep(1)
        status = client.get_status(sim_id)
        logger.info(
            f"Progress: {status['progress']:.1f}% | "
            f"Time: {status['current_time']:.1f}s | "
            f"Status: {status['status']}"
        )

        if status['status'] in ['completed', 'failed']:
            break

    # Get results
    if status['status'] == 'completed':
        results = client.get_results(sim_id)
        logger.info(f"Found {results['count']} result files")

        # Download first result
        if results['results']:
            first_result = results['results'][0]
            output_path = f"./downloaded_{first_result['filename']}"
            client.download_result(sim_id, first_result['filename'], output_path)

    logger.info("=" * 60)
    logger.info("Example complete!")
    logger.info("=" * 60)


if __name__ == "__main__":
    example_workflow()
