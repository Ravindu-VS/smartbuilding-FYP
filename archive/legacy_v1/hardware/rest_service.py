"""
REST API Hardware Service - Template for Future Implementation

Connects via REST API for IoT device control and management.

Phase 7+: Hardware Integration (Future Implementation)
"""

from hardware.service import HardwareService, ActuatorCommand, SensorReading
from typing import Dict, List, Optional, Any


class RESTHardwareService(HardwareService):
    """
    REST API-based hardware communication service.

    Future implementation for connecting via HTTP/HTTPS REST API to:
    - Home Assistant
    - OpenHAB
    - Custom building control APIs
    - Cloud-based building management

    Configuration example:
    ```python
    config = {
        "type": "rest",
        "base_url": "http://192.168.1.100:8080",
        "api_key": "sk_live_abc123xyz",
        "timeout": 5.0,
        "verify_ssl": False,
    }
    service = HardwareServiceFactory.create_from_config(config)
    ```

    REST Endpoints:
    - POST /api/actuators/{room_id}/{actuator_type} → send command
    - GET /api/sensors/{room_id}/{sensor_type} → read sensor
    - GET /api/status → service status
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        api_key: Optional[str] = None,
        timeout: float = 5.0,
        verify_ssl: bool = True,
    ):
        """
        Initialize REST hardware service.

        Args:
            base_url: Base URL of REST API
            api_key: Optional API authentication key
            timeout: Request timeout in seconds
            verify_ssl: Whether to verify SSL certificates
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.verify_ssl = verify_ssl

        # Will be initialized in initialize()
        self.session = None
        self.connected = False
        self.command_history: Dict[str, ActuatorCommand] = {}
        self.sensor_cache: Dict[str, SensorReading] = {}
        self.last_error: Optional[str] = None

        print(f"[TEMPLATE] RESTHardwareService created (not yet functional)")
        print(f"  API: {base_url}")

    def initialize(self):
        """
        Initialize REST connection.

        Future: Will create HTTP session with authentication
        """
        print("[TODO] Implement REST initialization")
        print("  Step 1: import requests")
        print("  Step 2: Create requests.Session()")
        print("  Step 3: Set API authentication headers")
        print("  Step 4: Test connection to {base_url}/api/status")
        self.connected = False

    def shutdown(self):
        """Gracefully close REST connection."""
        print("[TODO] Close REST session")
        if self.session:
            self.session.close()
        self.connected = False

    def send_actuator_command(self, command: ActuatorCommand) -> bool:
        """
        Send actuator command via REST API.

        Future: Will POST to /api/actuators endpoint like:
        ```
        POST /api/actuators/0/light
        {
            "value": 1.0,
            "actuator_id": "room_0_light",
            "timestamp": 1234567890
        }
        ```
        """
        if not self.connected:
            print("[OFFLINE] REST service not connected")
            return False

        endpoint = (
            f"{self.base_url}/api/actuators/{command.room_id}/"
            f"{command.actuator_type.value}"
        )
        payload = command.to_dict()

        print(f"[TODO] POST {endpoint}")
        print(f"  Payload: {payload}")

        self.command_history[command.actuator_id] = command
        return False  # Not connected

    def send_actuator_commands_batch(self, commands: List[ActuatorCommand]) -> Dict[str, bool]:
        """Send batch of commands via REST (single POST with array)."""
        print(f"[TODO] Batch POST {len(commands)} commands to REST API")
        return {cmd.actuator_id: False for cmd in commands}

    def get_sensor_reading(self, sensor_id: str) -> Optional[SensorReading]:
        """
        Get sensor reading from REST API.

        Future: Will GET from /api/sensors/{room}/{type}
        """
        if not self.connected:
            return self.sensor_cache.get(sensor_id)

        print(f"[TODO] GET sensor {sensor_id} from REST API")
        return self.sensor_cache.get(sensor_id)

    def get_all_sensor_readings(self) -> Dict[str, SensorReading]:
        """
        Get all sensor readings efficiently.

        Future: Will single GET /api/sensors endpoint
        """
        print(f"[TODO] GET all sensors from /api/sensors")
        return self.sensor_cache.copy()

    def is_connected(self) -> bool:
        """Check if connected to REST API."""
        return self.connected

    def get_status(self) -> Dict[str, Any]:
        """Get REST service status."""
        return {
            "type": "rest",
            "base_url": self.base_url,
            "connected": self.connected,
            "api_key_set": self.api_key is not None,
            "timeout": self.timeout,
            "verify_ssl": self.verify_ssl,
            "commands_sent": len(self.command_history),
            "last_error": self.last_error,
            "status": "NOT IMPLEMENTED (template for Phase 7+)",
        }


# ============================================================================
# REST INTEGRATION GUIDE (For Future Implementation)
# ============================================================================

"""
TO IMPLEMENT REST SUPPORT:

1. Install requests library:
   pip install requests

2. Complete initialize() method:
   - Create requests.Session()
   - Set authentication headers
   - Test connection with GET /api/status
   - Set self.connected = True on success

3. Complete send_actuator_command():
   - Build endpoint URL
   - POST with command data
   - Handle response status codes
   - Cache command in history

4. Complete get_sensor_reading():
   - Build endpoint URL
   - GET sensor data
   - Parse JSON response
   - Update sensor cache

5. Error handling:
   - Handle HTTP timeouts
   - Retry logic with exponential backoff
   - Graceful failure modes

6. Authentication:
   - Support API key headers
   - Support OAuth2 if needed
   - Support mTLS certificates

SAMPLE REST ENDPOINTS:

Send Actuator Command:
  POST /api/actuators/0/light
  {
    "value": 1.0,
    "actuator_id": "room_0_light",
    "timestamp": 1234567890
  }
  Response: {
    "success": true,
    "actuator_id": "room_0_light",
    "confirmed_value": 1.0
  }

Get Sensor Reading:
  GET /api/sensors/0/temperature
  Response: {
    "sensor_id": "room_0_temp",
    "value": 22.5,
    "unit": "celsius",
    "timestamp": 1234567890,
    "confidence": 0.95
  }

Get All Sensors:
  GET /api/sensors
  Response: {
    "sensors": [
      {"sensor_id": "room_0_temp", "value": 22.5, ...},
      {"sensor_id": "room_0_humidity", "value": 45.0, ...},
      ...
    ]
  }

Service Status:
  GET /api/status
  Response: {
    "connected": true,
    "devices": 12,
    "uptime": 3600,
    "version": "1.0.0"
  }
"""
