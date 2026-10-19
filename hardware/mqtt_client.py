"""
MQTT Client for Hardware Integration

Connects to a local/remote MQTT broker to subscribe to hardware sensor data
and publish actuator commands back to the ESP32.
"""
import json
import logging
import threading
try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False

from hardware.sensor_gateway import process_incoming_sensor_data

logger = logging.getLogger("MQTTClient")

class HardwareMQTTClient:
    def __init__(self, broker_url="localhost", broker_port=1883):
        self.broker_url = broker_url
        self.broker_port = broker_port
        self.client = None
        self.connected = False
        self._thread = None
        
        # Subscribe to: smartbuilding/sensors/f2_office_a
        self.sensor_topic = "smartbuilding/sensors/#"
        # Publish to: smartbuilding/actuators/f2_office_a/lights
        self.actuator_topic_base = "smartbuilding/actuators"
        
    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.connected = True
            logger.info(f"Connected to MQTT Broker at {self.broker_url}:{self.broker_port}")
            self.client.subscribe(self.sensor_topic)
        else:
            logger.error(f"Failed to connect to MQTT broker, return code {rc}")

    def on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode('utf-8'))
            logger.debug(f"Received MQTT message on {msg.topic}: {payload}")
            
            # The payload must contain "room_id", OR we can parse it from topic.
            # Assuming payload contains {"room_id": "f2_office_a", ...}
            process_incoming_sensor_data(payload)
        except json.JSONDecodeError:
            logger.error("Failed to decode MQTT payload as JSON.")
        except Exception as e:
            logger.error(f"Error handling MQTT message: {e}")

    def start(self):
        if not MQTT_AVAILABLE:
            logger.warning("paho-mqtt not installed. MQTT client will not start.")
            return

        self.client = mqtt.Client()
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

        def _run_loop():
            try:
                self.client.connect(self.broker_url, self.broker_port, 60)
                self.client.loop_forever()
            except Exception as e:
                logger.error(f"MQTT connection error: {e}")
                self.connected = False

        self._thread = threading.Thread(target=_run_loop, daemon=True)
        self._thread.start()
        logger.info("MQTT Client thread started.")

    def publish_actuator_command(self, room_id: str, command: dict):
        """
        Publish control decisions (e.g. lights ON, HVAC ECO) back to the hardware.
        """
        if not self.connected or not self.client:
            return
            
        topic = f"{self.actuator_topic_base}/{room_id}"
        try:
            self.client.publish(topic, json.dumps(command))
            logger.debug(f"Published actuator command to {topic}: {command}")
        except Exception as e:
            logger.error(f"Failed to publish MQTT command: {e}")

# Global instance
mqtt_client = HardwareMQTTClient()
