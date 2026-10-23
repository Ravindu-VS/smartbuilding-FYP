import os
import time
import json
import logging
import paho.mqtt.client as mqtt

# Configure logging for Edge Gateway
logging.basicConfig(level=logging.INFO, format="%(asctime)s - [EDGE GATEWAY] - %(levelname)s - %(message)s")
logger = logging.getLogger("RaspberryPi_Edge_Gateway")

# MQTT Configuration
MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))

# PPO Agent Stub (Replace with stable-baselines3 model)
class EdgePPOAgent:
    def __init__(self):
        logger.info("Initializing Edge PPO Agent (Raspberry Pi 4B)...")
        # In the future: self.model = PPO.load("edge_ppo_model.zip")
        self.is_loaded = True
        logger.info("✓ PPO Agent ready for local inference.")

    def optimize_room(self, temp, humidity, occupancy):
        """ Runs edge inference to optimize the room's energy. """
        # Simple heuristic fallback mimicking PPO action
        if occupancy > 0:
            hvac = 22.0 if temp > 24.0 else 24.0
            lighting = 80
        else:
            hvac = 26.0  # Eco mode
            lighting = 0
            
        return {"hvac_setpoint": hvac, "lighting_level": lighting}

class EdgeGateway:
    def __init__(self):
        self.agent = EdgePPOAgent()
        self.client = mqtt.Client(client_id="rpi_edge_gateway")
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

    def start(self):
        logger.info(f"Connecting to MQTT broker at {MQTT_BROKER}:{MQTT_PORT}")
        try:
            self.client.connect(MQTT_BROKER, MQTT_PORT, 60)
            self.client.loop_start()
            logger.info("✓ Edge Gateway running. Listening for ESP32 telemetry...")
            
            # Keep gateway alive
            while True:
                time.sleep(10)
        except Exception as e:
            logger.error(f"Failed to start edge gateway: {e}")

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logger.info("Connected to MQTT Broker!")
            # Subscribe to ESP32 sensor telemetry
            client.subscribe("smartbuilding/room/+/sensors")
        else:
            logger.error(f"Failed to connect, return code {rc}")

    def on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            room_id = msg.topic.split("/")[2]
            
            temp = payload.get("temperature", 25.0)
            humidity = payload.get("humidity", 50.0)
            occ = payload.get("occupancy", 0)
            
            logger.info(f"Received telemetry from {room_id}: T={temp}°C, Occ={occ}")
            
            # Run Edge AI Optimization
            action = self.agent.optimize_room(temp, humidity, occ)
            
            # Publish control action back to ESP32
            control_topic = f"smartbuilding/room/{room_id}/control"
            self.client.publish(control_topic, json.dumps(action))
            logger.info(f"Published control action to {control_topic}: {action}")
            
        except Exception as e:
            logger.error(f"Error processing message: {e}")

if __name__ == "__main__":
    gateway = EdgeGateway()
    gateway.start()
