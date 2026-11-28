#!/usr/bin/env python3
"""
MQTT test harness: a simulated room board (stands in for the ESP32-S3 when it is not available).

    python raspberry_pi/mqtt_device_sim.py --host 127.0.0.1 --interval 3 --count 100

It publishes sb.telemetry/1 messages for Room 101 (f2_office_a) with "source": "mqtt_device_sim",
applies the commands it receives (fan / LED / damper) to a small first-order room model and
acknowledges each one (sb.ack/1).  The edge brain stores its readings with provenance
"synthetic" - harness data is never recorded as a measurement of the real room.

Fault options for tests: --duplicate-every N (re-send the same msg_id), --bad-every N (an
out-of-range temperature), --no-ack (never acknowledge, to exercise the ack timeout),
--stop-after N (go silent, to exercise the stale-data timeout).
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import threading
import time
import uuid
from datetime import datetime, timezone

ROOM = "f2_office_a"
PREFIX = "sb/v1"


class SimRoom:
    """First-order thermal and CO2 response to the board's own actuators (illustrative only)."""

    def __init__(self, seed: int = 0):
        self.rng = random.Random(seed)
        self.t, self.co2, self.fan, self.led, self.servo = 28.5, 520.0, 0, 0, 0
        self.k = 0

    def step(self, dt: float) -> dict:
        self.k += 1
        occupied = (self.k // 40) % 3 != 2                     # occupied 2/3 of the time, in blocks
        t_out = 30.0
        self.t += dt / 900.0 * (t_out - self.t) - dt / 600.0 * (self.fan / 255.0) * 2.0 + (0.002 * dt if occupied else 0)
        self.co2 += dt * ((0.8 if occupied else 0.0) - (self.co2 - 420.0) * (0.002 + 0.004 * (self.servo > 45)))
        lux = 80.0 + 300.0 * self.led / 255.0 + self.rng.gauss(0, 3)
        return {"temperature": round(self.t + self.rng.gauss(0, 0.05), 2), "humidity": round(65 + self.rng.gauss(0, 0.5), 1),
                "co2": round(self.co2 + self.rng.gauss(0, 5), 0), "co2_source": "scd41_ndir", "lux": round(max(0.0, lux), 1),
                "motion_detected": occupied and self.rng.random() < 0.6, "presence": occupied,
                "presence_source": "pir", "actuator_fan_speed": self.fan, "actuator_light_level": self.led,
                "actuator_servo_angle": self.servo, "measured_power_mW": round(150 + 1.2 * self.fan * 10 + 2.0 * self.led, 1)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default=os.environ.get("MQTT_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("MQTT_PORT", "1883")))
    ap.add_argument("--interval", type=float, default=3.0)
    ap.add_argument("--count", type=int, default=0, help="messages to send (0 = forever)")
    ap.add_argument("--duplicate-every", type=int, default=0)
    ap.add_argument("--bad-every", type=int, default=0)
    ap.add_argument("--no-ack", action="store_true")
    ap.add_argument("--stop-after", type=int, default=0)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)
    import paho.mqtt.client as mqtt
    room = SimRoom(args.seed)
    received = {"commands": 0}
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"device-sim-{uuid.uuid4().hex[:6]}")
    user, pw = os.environ.get("MQTT_USERNAME"), os.environ.get("MQTT_PASSWORD")
    if user:
        c.username_pw_set(user, pw)
    c.will_set(f"{PREFIX}/room/{ROOM}/status", json.dumps({"state": "offline"}), qos=1, retain=True)
    connected = threading.Event()

    def on_connect(cl, ud, flags, rc, props=None):
        cl.subscribe(f"{PREFIX}/room/{ROOM}/command", qos=1)
        cl.publish(f"{PREFIX}/room/{ROOM}/status", json.dumps({"state": "online"}), qos=1, retain=True)
        connected.set()

    def on_message(cl, ud, msg):
        cmd = json.loads(msg.payload)
        received["commands"] += 1
        room.fan = int(max(0, min(255, cmd.get("fan_speed", 0))))
        room.led = int(max(0, min(255, cmd.get("light_level", 0))))
        if cmd.get("servo_angle", -1) >= 0:
            room.servo = int(min(180, cmd["servo_angle"]))
        if not args.no_ack:
            cl.publish(f"{PREFIX}/room/{ROOM}/ack", json.dumps({
                "schema": "sb.ack/1", "msg_id": cmd["msg_id"], "status": "applied",
                "applied": {"fan": room.fan, "led": room.led, "servo": room.servo}}), qos=1)

    c.on_connect, c.on_message = on_connect, on_message
    c.connect(args.host, args.port, keepalive=30)
    c.loop_start()
    if not connected.wait(10):
        print("could not connect to the broker", file=sys.stderr)
        return 1
    n, last_id = 0, None
    try:
        while args.count == 0 or n < args.count:
            n += 1
            if args.stop_after and n > args.stop_after:
                time.sleep(args.interval)
                continue
            vals = room.step(args.interval)
            msg_id = last_id if (args.duplicate_every and n % args.duplicate_every == 0 and last_id) else uuid.uuid4().hex[:16]
            if args.bad_every and n % args.bad_every == 0:
                vals["temperature"] = 999.0
            payload = {"schema": "sb.telemetry/1", "room_id": ROOM, "msg_id": msg_id, "source": "mqtt_device_sim",
                       "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), **vals}
            c.publish(f"{PREFIX}/room/{ROOM}/telemetry", json.dumps(payload), qos=1)
            last_id = msg_id
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        c.publish(f"{PREFIX}/room/{ROOM}/status", json.dumps({"state": "offline"}), qos=1, retain=True)
        c.loop_stop()
        c.disconnect()
    print(f"sent {n} telemetry messages, received {received['commands']} commands")
    return 0


if __name__ == "__main__":
    sys.exit(main())
