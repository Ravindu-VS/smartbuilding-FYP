"""
ESP32 test sender — for testing the edge brain WITHOUT the real board.

Posts readings in the same JSON format as firmware/esp32_smart_building every 3 s,
but with "source": "test_sender" (the firmware sends "sensor_node"). The edge brain
and the dashboard therefore show Office A as connected to a TEST SENDER, not to the
real ESP32, so test data can never be mistaken for real hardware data.

    python raspberry_pi/esp32_test_sender.py                    # http://127.0.0.1:8001
    python raspberry_pi/esp32_test_sender.py --url http://192.168.1.20:8001 --count 20

Stop it (Ctrl+C) and the dashboard should show Office A as NOT CONNECTED after the
board timeout (HW_TIMEOUT_S, 10 s by default).
"""
import argparse
import json
import math
import random
import time
import urllib.request


def make_reading(t: float, state: dict) -> dict:
    """A plausible reading; presence follows a slow on/off cycle so decisions change."""
    present = (int(t // 30) % 2) == 0
    lux = max(0.0, 180 + 40 * math.sin(t / 60) + random.uniform(-5, 5))
    return {
        "room_id": "f2_office_a",
        "source": "test_sender",
        "temperature": round(27.0 + 0.5 * math.sin(t / 90) + random.uniform(-0.05, 0.05), 2),
        "humidity": round(68 + random.uniform(-0.5, 0.5), 2),
        "pressure_hpa": 1009.8,
        "co2": round(520 + (250 if present else 0) + random.uniform(-10, 10), 1),
        "co2_source": "scd41_ndir",
        "lux": round(lux, 1),
        "motion_detected": present,
        "presence": present,
        "presence_source": "pir",
        "actuator_fan_speed": state.get("fan_speed", 0),
        "actuator_light_level": state.get("light_level", 0),
        "actuator_servo_angle": state.get("servo_angle", 0),
        "sensor_health": {"bme280": True, "bh1750": True, "scd41": True,
                          "ina226": False, "ld2410c": False, "servo": False},
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8001")
    ap.add_argument("--interval", type=float, default=3.0)
    ap.add_argument("--count", type=int, default=0, help="number of readings (0 = until Ctrl+C)")
    a = ap.parse_args()
    endpoint = a.url.rstrip("/") + "/api/hardware/sensor-data"
    state, n, t0 = {}, 0, time.time()
    print(f"Sending TEST readings to {endpoint} every {a.interval:.0f} s (source=test_sender)")
    try:
        while a.count == 0 or n < a.count:
            body = json.dumps(make_reading(time.time() - t0, state)).encode()
            req = urllib.request.Request(endpoint, data=body, headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=5) as r:
                    reply = json.loads(r.read())
                # Apply the decision like the firmware does, so the next reading reports it
                state = {k: reply.get(k, 0) for k in ("fan_speed", "light_level", "servo_angle")}
                print(f"#{n + 1}: {reply.get('control_mode')} p={reply.get('occupancy_probability')} "
                      f"fan={state['fan_speed']} light={state['light_level']}")
            except Exception as e:
                print(f"#{n + 1}: POST failed: {e}")
            n += 1
            time.sleep(a.interval)
    except KeyboardInterrupt:
        pass
    print("Stopped. Office A should show NOT CONNECTED after the board timeout.")


if __name__ == "__main__":
    main()
