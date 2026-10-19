"""
Sensor Gateway v2.0

Handles incoming data from ESP32/IoT devices.
Provides functions to parse, validate, normalize, and inject data into the HardwareRoomManager.

v2.0 additions:
- SCD41 NDIR CO₂ validation (0-5000 ppm)
- LD2410C mmWave presence fusion
- INA226 power measurement validation
- Sensor health status tracking
- Data quality scoring
"""
import logging
from hardware.hardware_room_manager import hardware_manager

logger = logging.getLogger("SensorGateway")

# Data quality bounds
BOUNDS = {
    "temperature": (-10.0, 60.0),
    "humidity": (0.0, 100.0),
    "co2": (200.0, 5000.0),
    "lux": (0.0, 65535.0),
    "pressure_hpa": (900.0, 1100.0),
    "measured_power_mW": (0.0, 50000.0),
    "measured_current_mA": (0.0, 5000.0),
    "measured_voltage_v": (0.0, 30.0),
}


def _clamp_and_warn(name: str, value: float) -> float:
    """Clamp a value to its valid bounds and log a warning if out of range."""
    lo, hi = BOUNDS.get(name, (None, None))
    if lo is None:
        return value
    if not (lo <= value <= hi):
        logger.warning(f"Sensor outlier: {name}={value} (bounds [{lo}, {hi}])")
        return max(lo, min(value, hi))
    return value


def compute_data_quality(payload: dict) -> float:
    """Compute a 0.0-1.0 data quality score based on sensor availability and validity."""
    checks = []

    # Core sensors (high weight)
    checks.append(1.0 if payload.get("sensor_health", {}).get("bme280", False) else 0.0)
    checks.append(1.0 if payload.get("sensor_health", {}).get("bh1750", False) else 0.0)

    # Advanced sensors (medium weight)
    checks.append(0.8 if payload.get("sensor_health", {}).get("scd41", False) else 0.0)
    checks.append(0.6 if payload.get("sensor_health", {}).get("ld2410c", False) else 0.0)
    checks.append(0.6 if payload.get("sensor_health", {}).get("ina226", False) else 0.0)

    # Source quality
    if payload.get("co2_source") == "scd41_ndir":
        checks.append(1.0)
    else:
        checks.append(0.3)  # MQ-2 estimate is low quality

    total = sum(checks) / (1.0 + 1.0 + 0.8 + 0.6 + 0.6 + 1.0)  # max possible
    return round(min(1.0, total), 3)


def process_incoming_sensor_data(payload: dict) -> bool:
    """
    Validates and processes raw sensor data from the physical hardware.
    
    Expected payload format (v2.0):
    {
        "room_id": "f2_office_a",
        "temperature": 27.5,
        "humidity": 60,
        "co2": 520,
        "co2_source": "scd41_ndir" | "mq2_estimate",
        "lux": 350,
        "pressure_hpa": 1013.2,
        "motion_detected": true,
        "presence": true,
        "presence_source": "pir+mmwave",
        "mmwave_presence": true,
        "mmwave_distance_cm": 120,
        "measured_voltage_v": 5.02,
        "measured_current_mA": 280.5,
        "measured_power_mW": 1408.1,
        "sensor_health": {...},
        "source": "sensor_node"
    }
    """
    try:
        room_id = payload.get("room_id")
        if not room_id:
            logger.error("Missing room_id in sensor payload")
            return False
            
        # Core sensor validation & normalization
        temp = _clamp_and_warn("temperature", float(payload.get("temperature", 24.0)))
        hum = _clamp_and_warn("humidity", float(payload.get("humidity", 50.0)))
        co2 = _clamp_and_warn("co2", float(payload.get("co2", 400.0)))
        lux = _clamp_and_warn("lux", float(payload.get("lux", 0.0)))
        
        sensors = {
            "temperature": temp,
            "humidity": hum,
            "co2": co2,
            "lux": lux,
            "co2_source": payload.get("co2_source", "mq2_estimate"),
        }

        # Pressure (from BME280)
        if "pressure_hpa" in payload:
            sensors["pressure_hpa"] = _clamp_and_warn(
                "pressure_hpa", float(payload["pressure_hpa"])
            )

        # MQ-2 raw value (secondary air quality)
        if "mq2_raw" in payload:
            sensors["mq2_raw"] = int(payload["mq2_raw"])

        # SCD41 supplementary readings
        if "scd41_temp" in payload:
            sensors["scd41_temperature"] = float(payload["scd41_temp"])
        if "scd41_humidity" in payload:
            sensors["scd41_humidity"] = float(payload["scd41_humidity"])

        # Presence data (fused PIR + mmWave)
        sensors["motion_detected"] = payload.get("motion_detected", False)
        sensors["presence"] = payload.get("presence", sensors["motion_detected"])
        sensors["presence_source"] = payload.get("presence_source", "pir")

        # mmWave specific fields
        if "mmwave_presence" in payload:
            sensors["mmwave_presence"] = payload["mmwave_presence"]
            sensors["mmwave_moving"] = payload.get("mmwave_moving", False)
            sensors["mmwave_stationary"] = payload.get("mmwave_stationary", False)
            sensors["mmwave_distance_cm"] = int(payload.get("mmwave_distance_cm", 0))

        # INA226 power measurement
        if "measured_power_mW" in payload:
            sensors["measured_voltage_v"] = _clamp_and_warn(
                "measured_voltage_v", float(payload.get("measured_voltage_v", 0))
            )
            sensors["measured_current_mA"] = _clamp_and_warn(
                "measured_current_mA", float(payload.get("measured_current_mA", 0))
            )
            sensors["measured_power_mW"] = _clamp_and_warn(
                "measured_power_mW", float(payload["measured_power_mW"])
            )

        # Actuator feedback
        if "actuator_fan_speed" in payload:
            sensors["actuator_fan_speed"] = int(payload["actuator_fan_speed"])
            sensors["actuator_light_level"] = int(payload.get("actuator_light_level", 0))
            sensors["actuator_servo_angle"] = int(payload.get("actuator_servo_angle", 0))

        # Sensor health
        sensors["sensor_health"] = payload.get("sensor_health", {})

        # Data quality score
        sensors["data_quality_score"] = compute_data_quality(payload)

        # Legacy occupancy_probability (if sent directly)
        occ_prob = payload.get("occupancy_probability")
        if occ_prob is not None:
            sensors["occupancy_probability"] = float(occ_prob)
            
        # Push to manager
        hardware_manager.update_sensors(room_id, sensors)
        return True
        
    except Exception as e:
        logger.error(f"Error processing sensor data: {e}")
        return False
