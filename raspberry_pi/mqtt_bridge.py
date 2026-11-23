"""
MQTT transport between the room boards and the edge brain.

Topics (telemetry and control are separate; <room> is the room id, e.g. f2_office_a):
  sb/v1/room/<room>/telemetry   board -> edge   QoS 1   schema sb.telemetry/1
  sb/v1/room/<room>/command     edge  -> board  QoS 1   schema sb.command/1 (reply to one telemetry message)
  sb/v1/room/<room>/ack         board -> edge   QoS 1   schema sb.ack/1     (command applied / rejected)
  sb/v1/room/<room>/status      board -> edge   retained, last will "offline"
  sb/v1/edge/status             edge  -> boards retained, last will "offline"

Telemetry is validated (validate_telemetry) and handed to the SAME ingestion function the HTTP
endpoint uses (EdgeBrain.inject_hardware_data), so there is one source of truth for the room's
state whichever transport the board uses.  Duplicates (same room and msg_id, e.g. a QoS 1
re-delivery) are dropped.  Each telemetry message gets one command back; a command not
acknowledged within ACK_TIMEOUT_S is marked "timeout" in the store and reported.  Staleness of
the room (no reading for HW_TIMEOUT_S) is handled by the edge brain for both transports.

Credentials come from the environment only (MQTT_USERNAME, MQTT_PASSWORD; MQTT_TLS=1 for TLS)
and are never logged.  One client per process (paho's network thread); reconnects with
back-off 1-30 s.
"""
from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
import uuid
from collections import OrderedDict, deque
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("mqtt_bridge")

PREFIX = "sb/v1"
TELEMETRY_SCHEMA, COMMAND_SCHEMA, ACK_SCHEMA = "sb.telemetry/1", "sb.command/1", "sb.ack/1"
ACK_TIMEOUT_S = float(os.environ.get("MQTT_ACK_TIMEOUT_S", "10"))
MAX_MSG_ID = 64
DEDUPE_PER_ROOM = 2000

# field -> (type, minimum, maximum); values outside the range are removed and reported
NUMERIC_FIELDS: Dict[str, Tuple[float, float]] = {
    "temperature": (-20.0, 70.0), "humidity": (0.0, 100.0), "pressure_hpa": (800.0, 1100.0),
    "co2": (300.0, 10000.0), "lux": (0.0, 200000.0), "measured_power_mW": (0.0, 1e7),
    "measured_voltage_v": (0.0, 60.0), "measured_current_mA": (0.0, 1e5), "mq2_raw": (0.0, 4095.0),
    "mq135_raw": (0.0, 4095.0), "mq135_adc_mv": (0.0, 5000.0),
    "ina219_shunt_voltage_mV": (-320.0, 320.0), "wifi_rssi_dbm": (-120.0, 0.0),
    "uptime_s": (0.0, 315360000.0),
    "scd41_temp": (-20.0, 70.0), "scd41_humidity": (0.0, 100.0), "mmwave_distance_cm": (0.0, 1000.0),
    "actuator_fan_speed": (0.0, 255.0), "actuator_light_level": (0.0, 255.0), "actuator_servo_angle": (0.0, 180.0),
    # manual/test holds reported by the board (seconds left), BLE MTU of the gateway link
    "rgb_hold_s": (0.0, 600.0), "fan_hold_s": (0.0, 600.0), "ble_mtu": (23.0, 517.0),
}
# INA219 offset noise with no load reads slightly below zero (e.g. -0.2 mA); within these floors the
# value is clamped to 0 instead of being reported as a problem
NOISE_FLOOR = {"measured_current_mA": 2.0, "measured_power_mW": 20.0, "measured_voltage_v": 0.05}
BOOL_FIELDS = ("motion_detected", "presence", "mmwave_presence", "mmwave_moving", "mmwave_stationary",
               "mq135_do_high", "fan_on", "relay_on", "bench_mode")
STRING_FIELDS = ("source", "co2_source", "presence_source", "firmware", "device_id", "actuator_rgb",
                 "fw_version", "actuator_ac_led", "actuator_status_led")


def topic(room_id: str, kind: str) -> str:
    return f"{PREFIX}/room/{room_id}/{kind}"


def validate_telemetry(room_from_topic: str, payload: Any, known_rooms) -> Tuple[Optional[Dict], List[str]]:
    """Return (clean payload for inject_hardware_data, problems).  clean is None when the message
    must be rejected (not JSON object, wrong schema, unknown room, room mismatch, bad msg_id)."""
    problems: List[str] = []
    if not isinstance(payload, dict):
        return None, ["payload is not a JSON object"]
    if payload.get("schema") not in (None, TELEMETRY_SCHEMA):
        return None, [f"unsupported schema {payload.get('schema')!r}"]
    room = payload.get("room_id", room_from_topic)
    if room != room_from_topic:
        return None, [f"room_id {room!r} does not match topic room {room_from_topic!r}"]
    if room not in known_rooms:
        return None, [f"unknown room {room!r}"]
    msg_id = payload.get("msg_id")
    if not isinstance(msg_id, str) or not 0 < len(msg_id) <= MAX_MSG_ID:
        return None, ["msg_id missing or invalid (string of 1-64 characters required)"]
    clean: Dict[str, Any] = {"room_id": room, "msg_id": msg_id}
    for k, (lo, hi) in NUMERIC_FIELDS.items():
        if k not in payload or payload[k] is None:
            continue
        v = payload[k]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
            problems.append(f"{k}: not a finite number, dropped")
            continue
        if k in NOISE_FLOOR and lo - NOISE_FLOOR[k] <= float(v) < lo:
            v = lo
        if not lo <= float(v) <= hi:
            problems.append(f"{k}: {v} outside {lo}..{hi}, dropped")
            continue
        clean[k] = float(v)
    for k in BOOL_FIELDS:
        if k in payload and payload[k] is not None:
            if isinstance(payload[k], bool) or payload[k] in (0, 1):
                clean[k] = bool(payload[k])
            else:
                problems.append(f"{k}: not a boolean, dropped")
    for k in STRING_FIELDS:
        if isinstance(payload.get(k), str):
            clean[k] = payload[k][:64]
    if isinstance(payload.get("sensor_health"), dict):
        clean["sensor_health"] = {str(k)[:32]: bool(v) for k, v in list(payload["sensor_health"].items())[:16]}
    ts = payload.get("ts")
    if ts is not None:
        clean["device_ts"] = str(ts)[:40]
    return clean, problems


def build_command(room_id: str, reply_to: str, decision: Dict) -> Dict:
    return {"schema": COMMAND_SCHEMA, "msg_id": uuid.uuid4().hex[:16], "in_reply_to": reply_to, "room_id": room_id,
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "hvac_action": decision["hvac_action"], "light_action": decision["light_action"],
            "fan_speed": decision["fan_speed"], "light_level": decision["light_level"],
            "servo_angle": decision["servo_angle"], "occupancy_probability": decision["occupancy_probability"],
            **{k: decision[k] for k in ("ac_led", "status_led") if decision.get(k)},
            "ttl_s": 30}


class MqttBridge:
    def __init__(self, ingest: Callable[[Dict], Dict], known_rooms, store=None, host: Optional[str] = None,
                 port: Optional[int] = None, client_id: Optional[str] = None,
                 on_event: Optional[Callable[[str, str, Optional[str]], None]] = None):
        self.ingest, self.known_rooms, self.store, self.on_event = ingest, set(known_rooms), store, on_event
        self.host = host or os.environ.get("MQTT_HOST", "127.0.0.1")
        self.port = int(port or os.environ.get("MQTT_PORT", "1883"))
        self.client_id = client_id or os.environ.get("MQTT_CLIENT_ID", f"edge-brain-{uuid.uuid4().hex[:6]}")
        self.username = os.environ.get("MQTT_USERNAME") or None
        self._password = os.environ.get("MQTT_PASSWORD") or None
        self.tls = os.environ.get("MQTT_TLS", "0") == "1"
        self.lock = threading.Lock()
        self.connected = False
        self.stats = {"received": 0, "accepted": 0, "rejected": 0, "duplicates": 0, "commands_sent": 0,
                      "acks": 0, "ack_timeouts": 0, "reconnects": 0, "field_problems": 0}
        self.last_error: Optional[str] = None
        self.last_connect: Optional[str] = None
        self.last_disconnect: Optional[str] = None
        self.device_status: Dict[str, str] = {}
        self.device_detail: Dict[str, Dict[str, Any]] = {}
        self._seen: Dict[str, "OrderedDict[str, None]"] = {}
        self._pending: Dict[str, Tuple[float, str]] = {}      # command msg_id -> (sent monotonic, room)
        self.recent_rejections: deque = deque(maxlen=20)
        self.client = None
        self._stop = threading.Event()

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        import paho.mqtt.client as mqtt
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=self.client_id, clean_session=True)
        if self.username:
            c.username_pw_set(self.username, self._password)
        if self.tls:
            c.tls_set()
        c.will_set(f"{PREFIX}/edge/status", json.dumps({"state": "offline"}), qos=1, retain=True)
        c.reconnect_delay_set(min_delay=1, max_delay=30)
        c.on_connect, c.on_disconnect, c.on_message = self._on_connect, self._on_disconnect, self._on_message
        self.client = c
        c.connect_async(self.host, self.port, keepalive=30)
        c.loop_start()
        threading.Thread(target=self._ack_watchdog, daemon=True, name="mqtt-ack-watchdog").start()
        logger.info("MQTT bridge connecting to %s:%d as %s (auth %s, TLS %s)", self.host, self.port, self.client_id,
                    "yes" if self.username else "no", "on" if self.tls else "off")

    def stop(self) -> None:
        self._stop.set()
        if self.client is not None:
            try:
                self.client.publish(f"{PREFIX}/edge/status", json.dumps({"state": "offline"}), qos=1, retain=True)
                self.client.disconnect()
            finally:
                self.client.loop_stop()

    # ------------------------------------------------------------------ callbacks
    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if getattr(reason_code, "is_failure", False):
            self.last_error = f"connect refused: {reason_code}"
            logger.warning("MQTT connect refused: %s", reason_code)
            return
        with self.lock:
            if self.last_connect is not None:
                self.stats["reconnects"] += 1
            self.connected = True
            self.last_connect = _now()
        client.subscribe([(f"{PREFIX}/room/+/telemetry", 1), (f"{PREFIX}/room/+/ack", 1),
                          (f"{PREFIX}/room/+/status", 1), (f"{PREFIX}/room/+/ble_status", 1)])
        client.publish(f"{PREFIX}/edge/status", json.dumps({"state": "online", "ts": _now()}), qos=1, retain=True)
        self._event("mqtt", f"MQTT connected to {self.host}:{self.port}")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        with self.lock:
            self.connected = False
            self.last_disconnect = _now()
        if not self._stop.is_set():
            self._event("mqtt", f"MQTT disconnected ({reason_code}); reconnecting")

    def _on_message(self, client, userdata, msg):
        try:
            parts = msg.topic.split("/")
            if len(parts) != 5 or parts[0] + "/" + parts[1] != PREFIX or parts[2] != "room":
                return
            room, kind = parts[3], parts[4]
            try:
                payload = json.loads(msg.payload.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                self._reject(room, "invalid JSON")
                return
            if kind == "telemetry":
                self._telemetry(room, payload)
            elif kind == "ack":
                self._ack(room, payload)
            elif kind in ("status", "ble_status"):
                state = payload.get("state") if isinstance(payload, dict) else None
                if state in ("online", "offline"):
                    if kind == "status" or self.device_status.get(room) != "online":
                        self.device_status[room] = state
                        self._event("hardware", f"board in {room} reports {state} ({kind})", room)
                    if kind == "status":
                        # firmware room101-2026.11.23b+: detail booting / running / error (+ failed sensors)
                        detail = payload.get("detail") if state == "online" else "offline"
                        failed = payload.get("failed") if isinstance(payload.get("failed"), str) else None
                        prev = self.device_detail.get(room, {})
                        self.device_detail[room] = {"detail": detail, "failed": failed}
                        if detail == "error" and (prev.get("detail") != "error" or prev.get("failed") != failed):
                            self._event("hardware", f"board in {room} reports sensor error: {failed}", room)
        except Exception as e:                  # never let a bad message kill the network thread
            self.last_error = f"{type(e).__name__}: {e}"
            logger.exception("MQTT message handling failed")

    # ------------------------------------------------------------------ handlers
    def _telemetry(self, room: str, payload: Any) -> None:
        with self.lock:
            self.stats["received"] += 1
        clean, problems = validate_telemetry(room, payload, self.known_rooms)
        if clean is None:
            self._reject(room, "; ".join(problems))
            return
        msg_id = clean["msg_id"]
        with self.lock:
            seen = self._seen.setdefault(room, OrderedDict())
            if msg_id in seen:
                self.stats["duplicates"] += 1
                return
            seen[msg_id] = None
            while len(seen) > DEDUPE_PER_ROOM:
                seen.popitem(last=False)
            if problems:
                self.stats["field_problems"] += len(problems)
        clean.setdefault("source", "mqtt")
        # the board labels each copy with its link; the BLE gateway republishes BLE copies here
        clean["transport"] = payload.get("transport") if payload.get("transport") in ("mqtt", "ble") else "mqtt"
        decision = self.ingest(clean)
        with self.lock:
            self.stats["accepted"] += 1
        cmd = build_command(room, msg_id, decision)
        info = self.client.publish(topic(room, "command"), json.dumps(cmd), qos=1)
        with self.lock:
            self.stats["commands_sent"] += 1
            self._pending[cmd["msg_id"]] = (time.monotonic(), room)
        if self.store is not None:
            self.store.add_command(cmd["ts"], room, cmd["msg_id"], "mqtt", cmd)
        if problems:
            self._event("mqtt", f"{room}: reading accepted with problems: {'; '.join(problems)}", room)
        return info

    def _ack(self, room: str, payload: Any) -> None:
        if not isinstance(payload, dict) or not isinstance(payload.get("msg_id"), str):
            self._reject(room, "ack without msg_id")
            return
        status = payload.get("status") if payload.get("status") in ("applied", "rejected") else "invalid"
        with self.lock:
            known = self._pending.pop(payload["msg_id"], None)
            if known:
                self.stats["acks"] += 1
        if self.store is not None:
            self.store.ack_command(payload["msg_id"], status, json.dumps(payload.get("applied"))[:500]
                                   if payload.get("applied") is not None else None)
        if status != "applied":
            self._event("hardware", f"board in {room} {status} command {payload['msg_id']}", room)

    def _ack_watchdog(self) -> None:
        while not self._stop.wait(1.0):
            now = time.monotonic()
            expired = []
            with self.lock:
                for mid, (t, room) in list(self._pending.items()):
                    if now - t > ACK_TIMEOUT_S:
                        expired.append((mid, room))
                        del self._pending[mid]
                self.stats["ack_timeouts"] += len(expired)
            for mid, room in expired:
                if self.store is not None:
                    self.store.ack_command(mid, "timeout")
                self._event("hardware", f"no acknowledgement from {room} for command {mid} within {ACK_TIMEOUT_S:.0f} s", room)

    def _reject(self, room: str, why: str) -> None:
        with self.lock:
            self.stats["rejected"] += 1
            self.recent_rejections.append({"ts": _now(), "room": room, "why": why})
        logger.warning("MQTT message from %s rejected: %s", room, why)

    def _event(self, kind: str, text: str, room: Optional[str] = None) -> None:
        if self.on_event is not None:
            try:
                self.on_event(kind, text, room)
            except Exception:
                logger.exception("event callback failed")

    # ------------------------------------------------------------------ status
    def status(self) -> Dict:
        with self.lock:
            return {"enabled": True, "connected": self.connected, "broker": f"{self.host}:{self.port}",
                    "client_id": self.client_id, "auth": bool(self.username), "tls": self.tls,
                    "last_connect": self.last_connect, "last_disconnect": self.last_disconnect,
                    "last_error": self.last_error, "stats": dict(self.stats), "pending_acks": len(self._pending),
                    "device_status": dict(self.device_status), "device_detail": dict(self.device_detail),
                    "recent_rejections": list(self.recent_rejections),
                    "topics": {"telemetry": topic("<room>", "telemetry"), "command": topic("<room>", "command"),
                               "ack": topic("<room>", "ack"), "status": topic("<room>", "status")}}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
