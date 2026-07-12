"""
MQTT Hardware Service - Template for Future Implementation

Connects to MQTT broker for IoT device control (ESP32, Arduino, etc.)

Phase 7+: Hardware Integration (Future Implementation)
"""

from hardware.service import HardwareService, ActuatorCommand, SensorReading
from typing import Dict, List, Optional, Any


class MQTTHardwareService(HardwareService):
    """
    MQTT-based hardware communication service.

    Future implementation for connecting to:
    - ESP32 WiFi modules
    - Arduino with MQTT shields
    - Smart building control systems
    - Industry-standard IoT platforms

    Configuration example:
    ```python
    config = {
        "type": "mqtt",
        "broker_address": "192.168.1.100",
        "broker_port": 1883,
        "client_id": "smart_building_controller",
        "username": "admin",
        "password": "secret",
        "topic_prefix": "building/",
    }
    service = HardwareServiceFactory.create_from_config(config)
    ```

    MQTT Topic Structure:
    - building/room/0/actuators/light → command payload: {"value": 1.0}
    - building/room/0/sensors/temperature → sensor update: {"value": 22.5}
    """

    def __init__(
        self,
        broker_address: str = "localhost",
        broker_port: int = 1883,
        client_id: str = "smart_building",
        username: Optional[str] = None,
        password: Optional[str] = None,
        topic_prefix: str = "building/",
    ):
        """
        Initialize MQTT hardware service.

        Args:
            broker_address: MQTT broker IP/hostname
            broker_port: MQTT broker port
            client_id: MQTT client identifier
            username: Optional authentication username
            password: Optional authentication password
            topic_prefix: Topic prefix for all messages
        """
        self.broker_address = broker_address
        self.broker_port = broker_port
        self.client_id = client_id
        self.username = username
        self.password = password
        self.topic_prefix = topic_prefix

        # Will be initialized in initialize()
        self.mqtt_client = None
        self.connected = False
        self.command_history: Dict[str, ActuatorCommand] = {}
        self.sensor_readings: Dict[str, SensorReading] = {}

        print(f"[TEMPLATE] MQTTHardwareService created (not yet functional)")
        print(f"  Broker: {broker_address}:{broker_port}")
        print(f"  Client: {client_id}")

    def initialize(self):
        """
        Initialize MQTT connection.

        Future: Will use paho-mqtt library to connect to broker
        """
        print("[TODO] Implement MQTT connection")
        print("  Step 1: import paho.mqtt.client as mqtt")
        print("  Step 2: Create MQTT client")
        print("  Step 3: Connect to broker")
        print("  Step 4: Subscribe to sensor topics")
        self.connected = False

    def shutdown(self):
        """Gracefully disconnect from MQTT broker."""
        print("[TODO] Implement MQTT disconnection")
        if self.mqtt_client:
            self.mqtt_client.disconnect()
        self.connected = False

    def send_actuator_command(self, command: ActuatorCommand) -> bool:
        """
        Send actuator command via MQTT.

        Future: Will publish to MQTT topic like:
        - Topic: building/room/0/actuators/light
        - Payload: {"value": 1.0, "timestamp": 1234567890}
        """
        if not self.connected:
            print("[OFFLINE] MQTT not connected, command not sent")
            return False

        print(f"[TODO] Publish to MQTT: {command.actuator_id} = {command.value}")
        self.command_history[command.actuator_id] = command
        return False  # Not connected

    def send_actuator_commands_batch(self, commands: List[ActuatorCommand]) -> Dict[str, bool]:
        """Send batch of commands via MQTT (efficient publishing)."""
        print(f"[TODO] Batch publish {len(commands)} commands via MQTT")
        return {cmd.actuator_id: False for cmd in commands}

    def get_sensor_reading(self, sensor_id: str) -> Optional[SensorReading]:
        """Get latest sensor reading from cache."""
        return self.sensor_readings.get(sensor_id)

    def get_all_sensor_readings(self) -> Dict[str, SensorReading]:
        """Get all cached sensor readings."""
        return self.sensor_readings.copy()

    def is_connected(self) -> bool:
        """Check if connected to MQTT broker."""
        return self.connected

    def get_status(self) -> Dict[str, Any]:
        """Get MQTT service status."""
        return {
            "type": "mqtt",
            "broker": self.broker_address,
            "port": self.broker_port,
            "connected": self.connected,
            "client_id": self.client_id,
            "commands_sent": len(self.command_history),
            "status": "NOT IMPLEMENTED (template for Phase 7+)",
        }

    # ========================================================================
    # SAMPLE CALLBACK METHODS (for MQTT message handling)
    # ========================================================================

    def on_connect(self, client, userdata, flags, rc):
        """Callback for MQTT connection."""
        print(f"[MQTT] Connected with result code {rc}")
        if rc == 0:
            self.connected = True
            # Subscribe to sensor topics
            # client.subscribe(f"{self.topic_prefix}room/+/sensors/#")

    def on_message(self, client, userdata, msg):
        """Callback for MQTT message received."""
        print(f"[MQTT] Message received: {msg.topic} = {msg.payload}")
        # Parse sensor reading from topic and payload
        # Update self.sensor_readings

    def on_disconnect(self, client, userdata, rc):
        """Callback for MQTT disconnection."""
        print(f"[MQTT] Disconnected with result code {rc}")
        self.connected = False


# ============================================================================
# MQTT INTEGRATION GUIDE (For Future Implementation)
# ============================================================================

"""
TO IMPLEMENT MQTT SUPPORT:

1. Install paho-mqtt:
   pip install paho-mqtt

2. Complete initialize() method:
   - Create MQTT client
   - Set on_connect, on_message callbacks
   - Connect to broker
   - Subscribe to sensor topics

3. Complete send_actuator_command():
   - Publish to device topic
   - Handle QoS and retained messages

4. Complete on_message():
   - Parse sensor reading from MQTT payload
   - Create SensorReading and cache

5. Add sensor polling (optional):
   - Implement keep-alive polling for devices

6. Error handling:
   - Handle connection failures
   - Retry logic with backoff
   - Graceful degradation if broker unavailable

SAMPLE TOPIC STRUCTURE:
- Command: building/room/0/actuators/light
- Response: building/room/0/actuators/light/status
- Sensor: building/room/0/sensors/temperature
- Heartbeat: building/heartbeat

PAYLOAD FORMAT (JSON):
{
    "actuator_id": "room_0_light",
    "value": 1.0,
    "timestamp": 1234567890,
    "unit": "bool",
    "room_id": 0
}
"""
