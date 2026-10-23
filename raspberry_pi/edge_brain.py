"""
Edge Intelligence Brain (Raspberry Pi 4B, or a laptop during development)
=========================================================================

One process runs the whole live system:

    ESP32-S3 sensor node (the one real room) --HTTP POST every ~3 s--> this server
    This server:
        1. Accepts the board's readings (POST /api/hardware/sensor-data) and answers
           with the decision for the room's actuators (fan = AC, LED = lights,
           servo = fresh-air damper).  The project has exactly one real room:
           Office A (f2_office_a, data_source "hardware" in
           twin/building_config.py); every other room is simulated.
        2. Runs the digital twin (twin/live.py): the other 25 rooms of the 5-floor
           building on the thesis's ISO 13790 5R1C physics, with weather, occupants
           and sensor models, on a simulated clock (start/pause/speed/reset).
        3. AI control has one master switch for every room (POST /api/ai):
           ON  = the thesis method: PIR + CO2 occupancy estimator, multi-objective
                 controller (J = aE + bC + gS, tuned weights), then the safety layer;
           OFF = conventional control: the room's time schedule, same safety layer.
           Every decision is logged with its explanation.
        4. Meters the energy: the simulated building's meter (one segment per switch
           position) and each real room's INA226 meter, and compares AI with
           conventional control over the same minutes on an identical copy of the
           simulated building (same weather, occupants and noise).
        5. Streams one building state to the Next.js dashboard (GET /api/stream),
           pushed on every simulation step and on every board reading.

What is real and what is simulated is carried in every room record:
    source = "hardware"   a real room (Office A, f2_office_a). Values come only from
                          its board. With no reading for HW_TIMEOUT_S seconds the room
                          is NOT CONNECTED and has no sensor values.
    source = "simulated"  the other rooms (the digital twin).

Usage:
    python raspberry_pi/edge_brain.py

Environment variables:
    SPEED_FACTOR       simulated seconds per real second (default 360)
    TWIN_SEED          scenario seed (default 7): same seed = same weather and people
    TWIN_WARMUP        1 (default): the AI's 7-day learning week runs before
                       measurement starts (cached in output/twin_cache); 0: no learning week
    TARIFF_LKR_PER_KWH electricity price for cost figures (default 50, an assumption)
    API_HOST/API_PORT  listen address (default 0.0.0.0:8001)
    HW_TIMEOUT_S       seconds without a board reading before Office A is shown as
                       not connected (default 10; the firmware posts every 3 s)
    HW_LED_LUX_FULL    lux the board's LED adds at the BH1750 at full brightness.
                       Normally measured with the dashboard's "Calibrate LED" button
                       (stored in output/hw_calibration.json); this variable overrides it.
    OUTDOOR_TEMP_C     outdoor temperature assumed for the real room (default 30;
                       not measured, reported as assumed)
"""

import os
import sys
import json
import time
import math
import logging
import platform
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from collections import deque

from flask import Flask, request, jsonify, Response

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
                    datefmt='%H:%M:%S')
logger = logging.getLogger("EdgeBrain")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from twin.building_config import get_all_rooms                       # noqa: E402
from twin.controllers import Observation                                     # noqa: E402
from twin.hardware_room import HardwareRoomController                        # noqa: E402
from twin.live import CONTROLLERS, SCENARIOS, LiveTwin, controller_available  # noqa: E402
from twin.spec import room_number_map, spec_for_frontend                     # noqa: E402
from raspberry_pi.store import Store                                         # noqa: E402

DEFAULT_DB = os.path.join(PROJECT_ROOT, "output", "edge_store.sqlite3")
SNAPSHOT_S = float(os.environ.get("SNAPSHOT_S", "60"))     # real seconds between stored room snapshots

API_VERSION = 3
AI_DEFAULT_ON = os.environ.get("AI_DEFAULT", "on").lower() not in ("off", "0", "false")

ALL_ROOMS = [{
    "room_id": r["room_id"], "type": r["type"], "display_name": r.get("name", r["room_id"]),
    "max_occ": r.get("max_occupancy", 10), "floor_id": r["floor_id"], "floor_name": r.get("floor_name", ""),
    "data_source": r.get("data_source", "simulation"),
} for r in get_all_rooms()]
ROOM_IDS = [r["room_id"] for r in ALL_ROOMS]

# Real rooms: every room with data_source "hardware" in building_config.py
HARDWARE_ROOMS = [r for r in ALL_ROOMS if r["data_source"] == "hardware"]
if not HARDWARE_ROOMS:
    raise RuntimeError("building_config.py has no room with data_source='hardware'")
HARDWARE_ROOM = HARDWARE_ROOMS[0]                 # the first one (shown in the header)
HARDWARE_ROOM_ID = HARDWARE_ROOM["room_id"]
HARDWARE_IDS = [r["room_id"] for r in HARDWARE_ROOMS]
ROOM_NUMBERS = room_number_map()


def reading_provenance(sender: Optional[str]) -> str:
    """The real board identifies itself as "sensor_node"; anything else (the HTTP test sender,
    the MQTT device harness) is synthetic, never stored as a measurement of the real room."""
    return "room101_measured" if sender == "sensor_node" else "synthetic"

HW_TIMEOUT_S = float(os.environ.get("HW_TIMEOUT_S", "10"))
OUTDOOR_TEMP_C = float(os.environ.get("OUTDOOR_TEMP_C", "30"))
CALIBRATION_FILE = os.path.join(PROJECT_ROOT, "output", "hw_calibration.json")
CO2_SOURCE_NDIR = "scd41_ndir"        # the only CO2 reading used (the MQ-2 is not a CO2 sensor)


def humidity_ratio(temp_c: Optional[float], rh_pct: Optional[float]) -> Optional[float]:
    """Humidity ratio (kg water / kg dry air) from temperature and RH; None if either is missing."""
    if temp_c is None or rh_pct is None:
        return None
    p_sat = 610.78 * math.exp((17.27 * temp_c) / (237.7 + temp_c))
    p_w = max(0.0, min(1.0, rh_pct / 100.0)) * p_sat
    denom = 101325.0 - p_w
    if denom <= 0:
        return None
    return 0.622 * p_w / denom


# =============================================================================
# HARDWARE PAYLOAD PARSING
# =============================================================================
def _num(payload: Dict[str, Any], key: str) -> Optional[float]:
    """A finite number from the payload, or None if missing/invalid (never a default value)."""
    val = payload.get(key)
    if val is None or isinstance(val, bool):
        return None
    try:
        v = float(val)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _int(payload: Dict[str, Any], key: str) -> Optional[int]:
    v = _num(payload, key)
    return int(round(v)) if v is not None else None


def _bool(payload: Dict[str, Any], key: str) -> Optional[bool]:
    val = payload.get(key)
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)) and val in (0, 1):
        return bool(val)
    return None


def _round(v: Optional[float], nd: int) -> Optional[float]:
    return round(v, nd) if v is not None else None


def _load_led_calibration(room_id: str) -> Optional[float]:
    env = os.environ.get("HW_LED_LUX_FULL")
    if env not in (None, ""):
        try:
            v = float(env)
            return v if v > 0 else None
        except ValueError:
            return None
    try:
        with open(CALIBRATION_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        entry = data.get(room_id, data if "led_lux_full" in data else {})
        v = float(entry.get("led_lux_full", 0))
        return v if v > 0 else None
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def _save_led_calibration(room_id: str, entry: Dict[str, Any]) -> None:
    try:
        with open(CALIBRATION_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if "led_lux_full" in data:          # old single-room format
            data = {HARDWARE_ROOM_ID: data}
    except (OSError, ValueError):
        data = {}
    data[room_id] = entry
    try:
        os.makedirs(os.path.dirname(CALIBRATION_FILE), exist_ok=True)
        with open(CALIBRATION_FILE, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
    except OSError:
        pass


# =============================================================================
# PHYSICAL OUTPUT CONTROLLER (GPIO)
# =============================================================================
class PhysicalOutputController:
    """
    Records the output state per room. On a Raspberry Pi with RPi.GPIO installed it
    sets up GPIO, but no pin mapping is configured (_drive_gpio is empty), so no pin
    is driven: this is reported as gpio_driving=false.  The real actuators are on
    the ESP32 board, which applies the decision returned to each of its readings.
    """

    def __init__(self):
        self._is_pi = False
        self._gpio = None
        self._output_states: Dict[str, Dict[str, Any]] = {}
        try:
            import RPi.GPIO as GPIO
            self._gpio = GPIO
            self._gpio.setmode(GPIO.BCM)
            self._gpio.setwarnings(False)
            self._is_pi = True
            logger.info("RPi.GPIO available, but no pin mapping is configured: outputs are recorded only")
        except (ImportError, RuntimeError):
            logger.info("Not running on a Raspberry Pi: outputs are recorded only")

    @property
    def gpio_driving(self) -> bool:
        return False

    def update_room(self, room_id: str, control: Dict[str, Any]):
        self._output_states[room_id] = {"light": control.get("light_action", "OFF"),
                                        "hvac": control.get("hvac_action", "ECO"),
                                        "setpoint_c": control.get("setpoint_c"),
                                        "mode": control.get("control_mode", "EMPTY")}

    def clear_room(self, room_id: str):
        self._output_states.pop(room_id, None)

    def get_all_states(self) -> Dict[str, Dict]:
        return dict(self._output_states)

    def cleanup(self):
        if self._is_pi and self._gpio:
            self._gpio.cleanup()


# =============================================================================
# REAL ROOMS (one HardwareLink per board)
# =============================================================================
class HardwareLink:
    """Link state, AI controller, measured energy meter and history of one real room."""

    def __init__(self, room: Dict[str, Any], spec, outdoor_c: float):
        self.room = room
        self.room_id = room["room_id"]
        self.spec = spec
        self.ctrl = HardwareRoomController(spec, led_lux_full=_load_led_calibration(self.room_id), outdoor_c=outdoor_c)
        self.last_rx_mono: Optional[float] = None
        self.last_rx_iso: Optional[str] = None
        self.rx_count = 0
        self.intervals: deque = deque(maxlen=20)
        self.reading: Optional[Dict[str, Any]] = None
        self.sender: Optional[str] = None
        self.last_power_w: Optional[float] = None
        self.energy_wh = 0.0
        self.history: deque = deque(maxlen=600)
        self.connected_last = False
        self.led_cal: Optional[Dict[str, Any]] = None
        self.override: Optional[Dict[str, Any]] = None      # manual override {until_mono, fan, led, servo, reason}
        self.last_command: Optional[Dict[str, int]] = None  # last actuator command sent to the board
        self.verify_mismatches = 0
        self.segments: List[Dict[str, Any]] = []

    def status(self, now_mono: float) -> Dict[str, Any]:
        if self.last_rx_mono is None:
            state, age = "never_connected", None
        else:
            age = now_mono - self.last_rx_mono
            state = "connected" if age <= HW_TIMEOUT_S else "lost"
        mean_interval = (sum(self.intervals) / len(self.intervals)) if self.intervals else None
        if self.sender is None:
            sender = None
        elif self.sender == "sensor_node":
            sender = "esp32_board"
        else:
            sender = str(self.sender)
        return {
            "room_id": self.room_id, "room_name": self.room["display_name"],
            "connected": state == "connected", "state": state,
            "sender": sender, "real_board": sender == "esp32_board", "last_seen": self.last_rx_iso,
            "age_s": round(age, 2) if age is not None else None, "timeout_s": HW_TIMEOUT_S,
            "readings_received": self.rx_count,
            "mean_interval_s": round(mean_interval, 2) if mean_interval is not None else None,
            "led_calibration_lux": self.ctrl.led_lux_full,
            "led_calibration": (self.led_cal or {}).get("state", "done" if self.ctrl.led_lux_full else "none"),
        }

    # ---- measured energy meter, one segment per AI switch position ----
    def open_segment(self, mode: str, now: datetime) -> None:
        self.close_segment(now)
        self.segments.append({"mode": mode, "start": now.isoformat(timespec="seconds"), "end": None,
                              "seconds": 0.0, "wh": 0.0, "measured": False})
        self.segments = self.segments[-100:]

    def close_segment(self, now: datetime) -> None:
        if self.segments and self.segments[-1]["end"] is None:
            self.segments[-1]["end"] = now.isoformat(timespec="seconds")

    def meter(self) -> Dict[str, Any]:
        segs = []
        for s in self.segments[-12:]:
            h = s["seconds"] / 3600.0
            segs.append({**s, "seconds": round(s["seconds"], 2), "wh": round(s["wh"], 6),
                         "avg_w": round(s["wh"] / h, 3) if h > 0 and s["measured"] else None})
        by = {}
        for m in ("ai", "conventional"):
            secs = sum(s["seconds"] for s in self.segments if s["mode"] == m and s["measured"])
            wh = sum(s["wh"] for s in self.segments if s["mode"] == m and s["measured"])
            by[m] = {"seconds": round(secs, 1), "wh": round(wh, 4), "avg_w": round(wh / (secs / 3600.0), 3) if secs > 0 else None}
        return {"room_id": self.room_id, "room_name": self.room["display_name"],
                "power_w": self.last_power_w if self.last_rx_mono is not None else None,
                "total_wh": round(self.energy_wh, 4), "segments": segs, "by_mode": by,
                "basis": "INA226 on the board (measured); only while the board posts readings"}


# =============================================================================
# MAIN EDGE BRAIN
# =============================================================================
class EdgeBrain:
    """The digital twin, the real rooms' AI, the board links, the AI switch and the streamed state."""

    def __init__(self, speed_factor: float = 360.0, seed: Optional[int] = None, warmup: Optional[bool] = None,
                 ai_enabled: Optional[bool] = None, store_path: Optional[str] = None, models: bool = True):
        self._lock = threading.Lock()
        self._changed = threading.Condition()
        self._seq = 0
        self._started_iso = datetime.now().isoformat(timespec="seconds")
        if seed is None:
            seed = int(os.environ.get("TWIN_SEED", "7"))
        if warmup is None:
            warmup = os.environ.get("TWIN_WARMUP", "1") not in ("0", "false", "no")
        self.twin = LiveTwin(seed=seed, speed=speed_factor, warmup=warmup)
        self.spec_by_id = {r.room_id: r for r in self.twin.specs}
        self.links: Dict[str, HardwareLink] = {r["room_id"]: HardwareLink(r, self.spec_by_id[r["room_id"]], OUTDOOR_TEMP_C)
                                               for r in HARDWARE_ROOMS}
        self.physical_output = PhysicalOutputController()
        self.ai_enabled = AI_DEFAULT_ON if ai_enabled is None else bool(ai_enabled)
        self.twin.set_ai(self.ai_enabled)
        now = datetime.now()
        for link in self.links.values():
            link.open_segment("ai" if self.ai_enabled else "conventional", now)

        self._tick_count = 0
        self._last_tick_mono: Optional[float] = None
        self._last_notify_mono = 0.0
        self._update_interval = 0.25
        self._state_cache: Optional[tuple] = None

        # persistent store (history, decisions, events, predictions, commands); optional
        self.store: Optional[Store] = None
        self.store_error: Optional[str] = None
        if store_path:
            try:
                self.store = Store(store_path)
                self.store.add_event("system", f"edge brain started (schema v{self.store.schema_version()})")
            except Exception as e:
                self.store_error = f"{type(e).__name__}: {e}"
                logger.error("Store unavailable (%s): history is not persisted", self.store_error)
        self._last_snapshot_mono = 0.0
        self._last_event_seq = 0
        # trained models in the running system (shadow mode, thermal forecast, drift)
        self.models = None
        self.models_error: Optional[str] = None
        if models:
            try:
                from ml.serving import LiveModels
                self.models = LiveModels(store=self.store)
                self.twin.observers.append(self.models.observe_twin)
            except Exception as e:
                self.models_error = f"{type(e).__name__}: {e}"
                logger.error("Model service unavailable: %s", self.models_error)
        self.mqtt = None                    # set by main() when MQTT_ENABLED=1

        logger.info("EdgeBrain initialized (API v%d)", API_VERSION)
        logger.info("  Twin: %d simulated rooms, seed %d, speed %.0fx, learning week: %s",
                    len(self.twin.ids), seed, speed_factor, "yes" if warmup else "no")
        logger.info("  Real rooms: %s (board timeout %.0f s)", ", ".join(self.links), HW_TIMEOUT_S)
        logger.info("  AI control: %s", "ON" if self.ai_enabled else "OFF")

    # ─── change notification (SSE) ───
    @property
    def seq(self) -> int:
        return self._seq

    def _notify(self):
        with self._changed:
            self._seq += 1
            self._changed.notify_all()
        self._last_notify_mono = time.monotonic()

    def wait_for_change(self, last_seq: int, timeout: float) -> int:
        with self._changed:
            self._changed.wait_for(lambda: self._seq != last_seq, timeout=timeout)
            return self._seq

    # ─── the AI master switch ───
    def set_ai(self, enabled: bool) -> Dict[str, Any]:
        """One switch for every room: the simulated building and every real room."""
        enabled = bool(enabled)
        now = datetime.now()
        with self._lock:
            changed = enabled != self.ai_enabled
            self.ai_enabled = enabled
            if changed:
                for link in self.links.values():
                    link.open_segment("ai" if enabled else "conventional", now)
        meter = self.twin.set_ai(enabled)
        if changed:
            logger.info("AI control switched %s for every room", "ON" if enabled else "OFF")
            for link in self.links.values():
                self.twin.add_event(self._sys_event(
                    link, f"AI control switched {'ON' if enabled else 'OFF'}: the board gets "
                          f"{'AI' if enabled else 'conventional schedule'} decisions from its next reading", kind="switch"))
        self._notify()
        return {"ai_enabled": self.ai_enabled, "meter": meter}

    # ─── board links ───
    def _link_for(self, room_id: Optional[str]) -> HardwareLink:
        if room_id is None:
            if len(self.links) == 1:
                return next(iter(self.links.values()))
            raise ValueError(f"room_id is required (real rooms: {', '.join(self.links)})")
        link = self.links.get(room_id)
        if link is None:
            raise ValueError(f"'{room_id}' is not a real room on this server (real rooms: {', '.join(self.links)})")
        return link

    def hardware_status(self, now_mono: Optional[float] = None, room_id: Optional[str] = None) -> Dict[str, Any]:
        now_mono = time.monotonic() if now_mono is None else now_mono
        return self.links[room_id or HARDWARE_ROOM_ID].status(now_mono)

    def hardware_rooms(self, now_mono: Optional[float] = None) -> List[Dict[str, Any]]:
        now_mono = time.monotonic() if now_mono is None else now_mono
        return [link.status(now_mono) for link in self.links.values()]

    def start_led_calibration(self, room_id: Optional[str] = None) -> Dict[str, Any]:
        """Measure what a board's LED adds at its light sensor: one reading with the
        LED off, then one at full brightness (a few seconds, room light steady)."""
        with self._lock:
            link = self._link_for(room_id)
            if not link.status(time.monotonic())["connected"]:
                raise ValueError(f"the board in {link.room['display_name']} is not connected")
            link.led_cal = {"state": "off_requested", "lux_off": None, "lux_on": None}
        logger.info("LED calibration started (%s)", link.room_id)
        return {"status": "started", "room_id": link.room_id}

    def set_override(self, data: Dict[str, Any]) -> Dict[str, Any]:
        link = self._link_for(data.get("room_id"))
        with self._lock:
            if data.get("clear"):
                link.override = None
                self.twin.add_event(self._sys_event(link, "manual override cleared by the operator"))
                self._notify()
                return {"status": "cleared", "room_id": link.room_id}

            def bounded(key, hi, default=0):
                v = data.get(key, default)
                if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                    raise ValueError(f"{key} must be a number")
                return int(max(0, min(hi, round(v))))
            minutes = data.get("minutes", 30)
            if isinstance(minutes, bool) or not isinstance(minutes, (int, float)) or not 1 <= minutes <= 240:
                raise ValueError("minutes must be between 1 and 240")
            until = datetime.now() + timedelta(minutes=float(minutes))
            link.override = {"fan": bounded("fan_speed", 255), "led": bounded("light_level", 255),
                             "servo": bounded("servo_angle", 180), "until_mono": time.monotonic() + 60.0 * float(minutes),
                             "until_iso": until.isoformat(timespec="seconds"),
                             "reason": str(data.get("reason", "manual override"))[:120]}
            self.twin.add_event(self._sys_event(link, f"manual override until {until:%H:%M}: fan {link.override['fan']}, LED {link.override['led']}, "
                                  f"damper {link.override['servo']} ({link.override['reason']})"))
            if self.store is not None:
                self.store.add_event("manual_override", "override set", link.room_id,
                                     data={k: v for k, v in link.override.items() if k != "until_mono"})
            self._notify()
            return {"status": "ok", "room_id": link.room_id, "override": {k: v for k, v in link.override.items()
                                                                          if k != "until_mono"}}

    def _calibration_step(self, link: HardwareLink, lux: Optional[float], actuator_light: Optional[int]) -> Optional[int]:
        c = link.led_cal
        if c is None:
            return None
        st = c["state"]
        if st == "off_requested":
            c["state"] = "off_wait"
            return 0
        if st == "off_wait":
            if actuator_light == 0 and lux is not None:
                c["lux_off"], c["state"] = lux, "on_wait"
                return 255
            return 0
        if st == "on_wait":
            if actuator_light == 255 and lux is not None:
                c["lux_on"] = lux
                delta = c["lux_on"] - c["lux_off"]
                link.led_cal = None
                if delta < 5:
                    self.twin.add_event(self._sys_event(link, f"LED calibration: the LED adds only {delta:.0f} lux at the "
                                                              f"sensor - not used (check the LED points at the BH1750)"))
                    return None
                link.ctrl.set_led_calibration(delta)
                _save_led_calibration(link.room_id, {"led_lux_full": round(delta, 1), "lux_off": c["lux_off"],
                                                     "lux_on": c["lux_on"],
                                                     "measured_at": datetime.now().isoformat(timespec="seconds")})
                self.twin.add_event(self._sys_event(
                    link, f"LED calibration: LED adds {delta:.0f} lux at full brightness "
                          f"(off {c['lux_off']:.0f}, on {c['lux_on']:.0f}); the AI now subtracts it from daylight"))
                return None
            return 255
        return None

    def _sys_event(self, link: HardwareLink, text: str, kind: str = "system") -> Dict[str, Any]:
        return {"kind": kind, "source": "hardware", "sim_time": None,
                "real_time": datetime.now().isoformat(timespec="seconds"), "room_id": link.room_id,
                "room_name": link.room["display_name"], "floor_id": link.room["floor_id"], "summary": text}

    def inject_hardware_data(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Accept one reading from a board and return that room's decision.
        Fields the board did not send stay None (shown as missing), never a default.
        """
        link = self._link_for(payload.get("room_id"))
        msg_id = payload.get("msg_id") if isinstance(payload.get("msg_id"), str) else None
        transport = payload.get("transport") if payload.get("transport") in ("http", "mqtt") else "http"
        now_mono = time.monotonic()
        now = datetime.now()
        now_iso = now.isoformat(timespec="milliseconds")

        temp = _num(payload, "temperature")
        hum = _num(payload, "humidity")
        co2_reported = _num(payload, "co2")
        co2_source = payload.get("co2_source") if co2_reported is not None else None
        co2 = co2_reported if co2_source == CO2_SOURCE_NDIR else None
        lux = _num(payload, "lux")
        pressure_hpa = _num(payload, "pressure_hpa")
        pir = _bool(payload, "motion_detected")
        presence = _bool(payload, "presence")
        if presence is None:
            presence = pir
        actuator_fan = _int(payload, "actuator_fan_speed")
        actuator_light = _int(payload, "actuator_light_level")
        actuator_servo = _int(payload, "actuator_servo_angle")
        power_mw = _num(payload, "measured_power_mW")
        power_w = power_mw / 1000.0 if power_mw is not None else None

        hr = humidity_ratio(temp, hum)
        sensors = {
            "Temperature": _round(temp, 2), "Humidity": _round(hum, 2), "Light": _round(lux, 1),
            "CO2": _round(co2, 1), "HumidityRatio": _round(hr, 6),
            "CO2_source": co2_source if co2 is not None else None,
            "Pressure_hPa": _round(pressure_hpa, 1), "MQ2_raw": _int(payload, "mq2_raw"),
        }
        if co2_reported is not None and co2 is None:
            sensors["CO2_rejected"] = f"{co2_source or 'unknown source'}: not an NDIR CO2 reading, not used"
        scd41_temp = _num(payload, "scd41_temp")
        scd41_hum = _num(payload, "scd41_humidity")
        if scd41_temp is not None:
            sensors["SCD41_Temperature"] = round(scd41_temp, 2)
        if scd41_hum is not None:
            sensors["SCD41_Humidity"] = round(scd41_hum, 2)

        rf_p = None
        if self.twin.rf is not None:
            try:
                obs = Observation(room_id=link.room_id, room_type=link.room["type"], timestamp=now,
                                  temperature=temp if temp is not None else float("nan"),
                                  humidity=hum if hum is not None else float("nan"),
                                  light_lux=lux if lux is not None else float("nan"), co2=co2,
                                  humidity_ratio=hr if hr is not None else float("nan"), seconds_since_motion=None,
                                  current_light=link.ctrl.cmd["light"])
                rf_p = self.twin.rf.probabilities([obs])[0]
            except Exception:
                rf_p = None

        with self._lock:
            ai_on = self.ai_enabled
            result = link.ctrl.step(now, temp, hum, lux, co2, hr, presence, rf_probability=rf_p, ai_enabled=ai_on)
            control = result["control"]
            cal_level = self._calibration_step(link, lux, actuator_light)
            if cal_level is not None:
                control = dict(control, light_level=cal_level, calibrating=True)
            ov = link.override
            if ov is not None and now_mono < ov["until_mono"]:
                # manual override: the operator's levels go to the board (bounded), the AI is bypassed
                control = dict(control, fan_speed=ov["fan"], light_level=ov["led"], servo_angle=ov["servo"],
                               hvac_action="NORMAL" if ov["fan"] > 0 else "ECO",
                               light_action="ON" if ov["led"] > 127 else ("DIM" if ov["led"] > 0 else "OFF"),
                               mode="manual", manual_override={"reason": ov["reason"], "until": ov["until_iso"]})
            elif ov is not None:
                link.override = None
                self.twin.add_event(self._sys_event(link, "manual override ended; control returns to the "
                                      f"{'AI' if ai_on else 'conventional schedule'}"))
            # actuator-state verification: the board reports what it applied before this reading
            verified = None
            if link.last_command is not None and actuator_fan is not None and actuator_light is not None:
                verified = (actuator_fan == link.last_command["fan"] and actuator_light == link.last_command["led"])
                link.verify_mismatches = 0 if verified else link.verify_mismatches + 1
                if link.verify_mismatches == 3:
                    self.twin.add_event(self._sys_event(link, "the board's reported fan/LED levels have not matched the commands for 3 "
                                          "readings (check wiring or firmware)", kind="hardware"))
            control = dict(control, previous_command_verified=verified)
            link.last_command = {"fan": int(control["fan_speed"]), "led": int(control["light_level"])}
            link.ctrl.due_outcomes(now, temp, lux, presence, co2)
            reading = {
                "received_at": now_iso,
                "sensors": sensors,
                "presence": {
                    "pir_motion": pir, "mmwave_presence": _bool(payload, "mmwave_presence"),
                    "mmwave_moving": _bool(payload, "mmwave_moving"),
                    "mmwave_stationary": _bool(payload, "mmwave_stationary"),
                    "mmwave_distance_cm": _int(payload, "mmwave_distance_cm"),
                    "fused_presence": presence, "source": payload.get("presence_source"),
                },
                "device_state": {     # what the board reports it is doing (applied before this reading)
                    "light_on": (actuator_light > 0) if actuator_light is not None else None,
                    "hvac_mode": ("on" if actuator_fan > 0 else "off") if actuator_fan is not None else None,
                    "hvac_speed": actuator_fan, "light_level": actuator_light, "servo_angle": actuator_servo,
                },
                "power_measurement": {"voltage_v": _num(payload, "measured_voltage_v"),
                                      "current_mA": _num(payload, "measured_current_mA"),
                                      "power_mW": power_mw, "available": power_mw is not None},
                "sensor_health": payload.get("sensor_health") if isinstance(payload.get("sensor_health"), dict) else {},
                "ai": result["ai"],
                "control": control,
            }
            if link.last_rx_mono is not None:
                gap = now_mono - link.last_rx_mono
                link.intervals.append(gap)
                seg = link.segments[-1] if link.segments else None
                if gap <= HW_TIMEOUT_S and power_w is not None and link.last_power_w is not None:
                    wh = (power_w + link.last_power_w) / 2.0 * gap / 3600.0
                    link.energy_wh += wh
                    if seg is not None:
                        seg["wh"] += wh
                        seg["seconds"] += gap
                        seg["measured"] = True
            link.last_power_w = power_w
            link.last_rx_mono = now_mono
            link.last_rx_iso = now_iso
            link.rx_count += 1
            link.sender = payload.get("source") if isinstance(payload.get("source"), str) else "unknown"
            link.reading = reading
            link.history.append({
                "t": now.isoformat(timespec="seconds"), "mode": control.get("mode"),
                "temperature": sensors["Temperature"],
                "humidity": sensors["Humidity"], "co2": sensors["CO2"], "lux": sensors["Light"],
                "presence": presence, "p_occ": result["ai"]["occupancy_probability"],
                "p_rf": result["ai"]["random_forest_probability"], "light": control["light_action"],
                "hvac": control["hvac_action"], "setpoint": control["setpoint_c"],
                "power_w": round(power_w, 3) if power_w is not None else None})
        if result["event"] is not None:
            ev = self.twin.add_event(result["event"])
            link.ctrl.track(ev, now)
        self.physical_output.update_room(link.room_id, control)
        if self.store is not None:
            try:
                prov = reading_provenance(link.sender)
                self.store.add_reading(now_iso, link.room_id, prov, {
                    "temperature_c": temp, "humidity_pct": hum, "lux": lux, "co2_ppm": co2,
                    "co2_source": sensors.get("CO2_source"), "presence": presence, "pir": pir, "power_w": power_w},
                    room_number=ROOM_NUMBERS.get(link.room_id), source=f"{link.sender}/{transport}", msg_id=msg_id,
                    flags={"missing": [k for k, v in (("temperature", temp), ("humidity", hum), ("lux", lux),
                                                      ("co2", co2)) if v is None]})
                self.store.add_decision(now_iso, link.room_id, prov, controller="ai" if ai_on else "conventional",
                                        mode=control.get("mode"), p_occupied=result["ai"]["occupancy_probability"],
                                        proposed=(result.get("event") or {}).get("proposed") or {}, applied={
                                            "light": control["light_action"], "hvac": control["hvac_action"],
                                            "setpoint_c": control["setpoint_c"], "fan": control["fan_speed"],
                                            "led": control["light_level"], "servo": control["servo_angle"]},
                                        safety_notes=control.get("safety_notes") or [],
                                        model_version=(self.models.rf.version if self.models and self.models.rf.model else None),
                                        verified=control.get("previous_command_verified"))
            except Exception as e:
                logger.error("store write failed: %s", e)
        if self.models is not None and reading_provenance(link.sender) == "room101_measured":
            self.models.observe_real({"Temperature": temp, "Humidity": hum, "Light": lux, "CO2": co2, "HumidityRatio": hr})
        self._notify()

        logger.info("HARDWARE %s [%s]: T=%s Lux=%s CO2=%s Pres=%s -> P=%.2f -> lights %s, AC %s%s (fan %d, LED %d, servo %d)",
                    link.room_id, "AI" if ai_on else "AI OFF", temp, lux, co2, presence,
                    result["ai"]["occupancy_probability"], control["light_action"], control["hvac_action"],
                    f" {control['setpoint_c']:.0f}C" if control["setpoint_c"] else "",
                    control["fan_speed"], control["light_level"], control["servo_angle"])
        return {
            "room_id": link.room_id,
            "hvac_action": control["hvac_action"], "light_action": control["light_action"],
            "control_mode": control["control_mode"],
            "occupancy_probability": result["ai"]["occupancy_probability"],
            "fan_speed": control["fan_speed"], "light_level": control["light_level"],
            "servo_angle": control["servo_angle"],
        }

    def _hardware_room_state(self, link: HardwareLink, now_mono: Optional[float] = None) -> Dict[str, Any]:
        """A real room as the dashboard should show it: live values only while its board is connected."""
        now_mono = time.monotonic() if now_mono is None else now_mono
        status = link.status(now_mono)
        base = {
            "room_id": link.room_id, "room_type": link.room["type"], "floor_id": link.room["floor_id"],
            "display_name": link.room["display_name"], "source": "hardware", "hardware": status,
            "timestamp": link.last_rx_iso, "area_m2": link.spec.area, "design_setpoint_c": link.spec.design_setpoint,
            "meter": link.meter(),
        }
        r = link.reading
        if not status["connected"] or r is None:
            base.update({"sensors": {k: None for k in ("Temperature", "Humidity", "Light", "CO2", "HumidityRatio")},
                         "ai": None, "control": None, "device_state": None, "energy": None, "presence": None,
                         "power_measurement": None, "sensor_health": None, "ground_truth": None,
                         "comfort": None, "modes": None, "scenarios": []})
            return base
        pm = r["power_measurement"]
        base.update({
            "sensors": dict(r["sensors"]), "presence": dict(r["presence"]), "device_state": dict(r["device_state"]),
            "power_measurement": dict(pm), "sensor_health": dict(r["sensor_health"]),
            "ai": dict(r["ai"]), "control": dict(r["control"]),
            "energy": {"measured_power_watts": round(pm["power_mW"] / 1000.0, 3) if pm["available"] else None,
                       "cumulative_energy_wh": round(link.energy_wh, 4) if pm["available"] else None,
                       "basis": "measured (INA226 on the board)" if pm["available"] else None},
            "ground_truth": None,        # a real room has no ground truth
            "comfort": None, "modes": None, "scenarios": [],
        })
        return base

    # ─── simulation tick ───
    def tick(self, dt_real: Optional[float] = None):
        """Advance the twin by the real time elapsed, refresh the board links, notify the stream."""
        self._tick_count += 1
        now_mono = time.monotonic()
        if dt_real is None:
            dt_real = (now_mono - self._last_tick_mono) if self._last_tick_mono is not None else self._update_interval
        dt_real = max(0.0, min(dt_real, 2.0))
        steps = self.twin.advance_real(dt_real)
        self._last_tick_mono = time.monotonic()
        changed_hw = False
        with self._lock:
            for link in self.links.values():
                connected = link.status(self._last_tick_mono)["connected"]
                if connected != link.connected_last:
                    changed_hw = True
                    link.connected_last = connected
                    if not connected:
                        self.physical_output.clear_room(link.room_id)
        if steps or changed_hw or time.monotonic() - self._last_notify_mono > 1.0:
            self._notify()
        if self.store is not None:
            self._persist(time.monotonic())
        if self._tick_count % 120 == 0:
            c = self.twin.clock()
            logger.info("Tick #%d | %s | AI %s | sim %s %s | %.1f ms/step | boards: %s", self._tick_count, c["phase"],
                        "ON" if self.ai_enabled else "OFF", c["date"], c["time"], c["step_ms_median"] or 0.0,
                        ", ".join(f"{s['room_id']} {s['state']}" for s in self.hardware_rooms()))

    def _persist(self, now_mono: float) -> None:
        """Copy new timeline events and (every SNAPSHOT_S) a snapshot of every room into the store."""
        try:
            for ev in self.twin.get_timeline(after=self._last_event_seq, limit=200):
                self._last_event_seq = max(self._last_event_seq, ev["seq"])
                self.store.add_event(ev.get("kind") or "event", ev.get("summary") or ev.get("text") or "", ev.get("room_id"),
                                     data={k: v for k, v in ev.items() if k not in ("summary", "text")},
                                     ts=ev.get("real_time") or ev.get("sim_time"))
            if now_mono - self._last_snapshot_mono < SNAPSHOT_S:
                return
            self._last_snapshot_mono = now_mono
            state = self.get_current_state()
            rows = []
            for r in state["rooms"]:
                sens = r.get("sensors") or {}
                ctl = r.get("control") or {}
                hw = r.get("source") == "hardware"
                if hw and not (r.get("hardware") or {}).get("connected"):
                    continue                                   # nothing measured: no row (never a default)
                rows.append({"ts": r.get("timestamp") or state["timestamp"], "room_id": r["room_id"],
                             "room_number": ROOM_NUMBERS.get(r["room_id"]),
                             "provenance": reading_provenance(self.links[r["room_id"]].sender) if hw else "synthetic",
                             "mode": ctl.get("mode"), "temperature_c": sens.get("Temperature"),
                             "humidity_pct": sens.get("Humidity"), "co2_ppm": sens.get("CO2"), "lux": sens.get("Light"),
                             "occupants": None if hw else (r.get("ground_truth") or {}).get("true_occupancy"),
                             "p_occupied": (r.get("ai") or {}).get("occupancy_probability"),
                             "power_w": (r.get("energy") or {}).get("power_w") if not hw else
                             (r.get("energy") or {}).get("measured_power_watts"),
                             "energy_wh": None, "hvac": ctl.get("hvac_action"), "setpoint_c": ctl.get("setpoint_c"),
                             "light": ctl.get("light_action")})
            self.store.add_snapshots(rows)
        except Exception as e:
            logger.error("persist failed: %s", e)

    # ─── state ───
    def get_current_state(self) -> Dict[str, Any]:
        """The complete building state streamed to the dashboard (cached per change)."""
        seq = self._seq
        cache = self._state_cache
        now_mono = time.monotonic()
        if cache is not None and cache[0] == seq and now_mono - cache[1] < 0.5:
            return cache[2]
        with self._lock:
            hw_rooms = {rid: self._hardware_room_state(link, now_mono) for rid, link in self.links.items()}
            hw_list = [link.status(now_mono) for link in self.links.values()]
            hw_meters = [link.meter() for link in self.links.values()]
            ai_on = self.ai_enabled
        tw = self.twin
        with tw.lock:
            sim_rooms = tw.room_states()
            clock = tw.clock()
            floors = tw.floors()
            comp = tw.comparison()
            meter = tw.meter()
            alerts = tw.alerts()
            scenarios = [tw._scenario_dict(s) for s in tw.scenarios]
            timeline = tw.get_timeline(limit=15)
            ai_name = tw.ai_name
            watch = sorted(tw.watch)
        for r in sim_rooms:
            r["provenance"] = {"sensors": "synthetic", "ground_truth": "synthetic", "ai": "prediction",
                               "energy": "synthetic (simulated 5R1C physics)"}
            pred = self.models.thermal_for(r["room_id"]) if self.models is not None else None
            r["prediction"] = {"temperature_30min": pred} if pred else None
        for rid, r in hw_rooms.items():
            st = r.get("hardware") or {}
            meas = reading_provenance(self.links[rid].sender) if self.links[rid].sender else None
            r["provenance"] = {"sensors": meas if st.get("connected") else "unavailable",
                               "ai": "prediction" if st.get("connected") else "unavailable",
                               "energy": (meas + " (INA226)") if st.get("connected") and meas else "unavailable"}
            r["freshness"] = {"age_s": st.get("age_s"), "timeout_s": st.get("timeout_s"),
                              "stale": st.get("state") == "lost", "state": st.get("state")}
            r["prediction"] = None
        by_id = {r["room_id"]: r for r in sim_rooms}
        by_id.update(hw_rooms)
        for rid, r in by_id.items():
            r["room_number"] = ROOM_NUMBERS.get(rid)
        rooms = [by_id[rid] for rid in ROOM_IDS if rid in by_id]
        with_data = [r for r in rooms if r.get("ai")]
        predicted = sum(1 for r in with_data if r["ai"].get("predicted_occupancy") == 1)
        sim_power = sum(r["energy"]["power_w"] for r in sim_rooms)
        tick_age = (now_mono - self._last_tick_mono) if self._last_tick_mono is not None else None
        running = tick_age is not None and tick_age <= 3.0
        for f in floors:
            f["hardware_rooms"] = [rid for rid in self.links if self.spec_by_id[rid].floor_id == f["floor_id"]]
        hw_primary = hw_list[0]
        meter["real_rooms"] = hw_meters
        state = {
            "api_version": API_VERSION,
            "timestamp": datetime.now().isoformat(timespec="milliseconds"),
            "seq": seq,
            "ai_enabled": ai_on,
            "rooms": rooms,
            "hardware": hw_primary,
            "hardware_rooms": hw_list,
            "clock": clock,
            "floors": floors,
            "comparison": comp,
            "meter": meter,
            "scenarios": scenarios,
            "alerts": alerts,
            "timeline": timeline,
            "watch": watch,
            "system": {
                "total_rooms": len(ALL_ROOMS), "simulated_rooms": len(sim_rooms), "hardware_room_id": HARDWARE_ROOM_ID,
                "hardware_room_ids": list(self.links),
                "rooms_with_data": len(with_data), "occupied_rooms": predicted, "empty_rooms": len(with_data) - predicted,
                "people_simulated": sum(r["ground_truth"]["true_occupancy"] for r in sim_rooms),
                "sim_power_watts": round(sim_power),
                "ai_enabled": ai_on, "ai_controller": ai_name, "ai_controller_label": CONTROLLERS[ai_name],
                "estimator": "PIR + CO2 fusion (thesis); Random Forest shown for comparison",
                "phase": clock["phase"],
                "simulation_running": running and clock["running"] and clock["phase"] == "running",
                "simulation_time": f"{clock['weekday'][:3]} {clock['date']} {clock['time']}",
                "simulation_speed_factor": clock["speed"],
                "outdoor_temp_c": clock["outdoor_c"], "outdoor_humidity": clock["outdoor_rh"],
                "update_interval": self._update_interval,
                "last_tick_age_s": round(tick_age, 3) if tick_age is not None else None,
                "data_stale": not running,
                "gpio_driving": self.physical_output.gpio_driving,
                "started_at": self._started_iso,
                "random_forest_loaded": tw.rf is not None,
                "random_forest_source": getattr(tw.rf, "name", None),
                "store": {"enabled": self.store is not None, "error": self.store_error},
                "mqtt": {"enabled": self.mqtt is not None, "connected": bool(self.mqtt and self.mqtt.connected)},
                "models_loaded": self.models is not None,
                "hardware": hw_primary,
            },
        }
        self._state_cache = (seq, now_mono, state)
        return state

    def get_room_history(self, room_id: str) -> List[Dict]:
        if room_id in self.links:
            with self._lock:
                return list(self.links[room_id].history)
        return self.twin.room_history(room_id)


# =============================================================================
# FLASK API
# =============================================================================
app = Flask(__name__)
brain: Optional[EdgeBrain] = None


@app.after_request
def add_cors(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    response.headers['Access-Control-Allow-Methods'] = 'GET,POST,OPTIONS'
    return response


def _err(msg: str, code: int = 400):
    return jsonify({"status": "error", "message": msg}), code


@app.route('/health', methods=['GET'])
def health():
    c = brain.twin.clock() if brain else {}
    return jsonify({
        "status": "healthy", "message": "Edge Intelligence Brain", "api_version": API_VERSION,
        "phase": c.get("phase"), "ai_enabled": brain.ai_enabled if brain else None,
        "random_forest_loaded": bool(brain and brain.twin.rf is not None),
        "hardware": brain.hardware_status() if brain else None,
        "hardware_rooms": brain.hardware_rooms() if brain else None,
        "platform": f"{platform.system()} {platform.machine()} (Python {platform.python_version()})",
        "host": platform.node(),
    })


@app.route('/api/hardware/sensor-data', methods=['POST'])
def receive_sensor_data():
    """A board POSTs its readings here and gets its room's decision back."""
    try:
        payload = request.get_json(force=True, silent=True)
        if not isinstance(payload, dict) or not payload:
            return jsonify({"error": "Expected a JSON object"}), 400
        try:
            d = brain.inject_hardware_data(payload)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        # Keep this reply small: the firmware parses it into a 384-byte ArduinoJson document.
        return jsonify({"status": "ok", "room_id": d["room_id"], "hvac_action": d["hvac_action"],
                        "light_action": d["light_action"], "control_mode": d["control_mode"],
                        "occupancy_probability": d["occupancy_probability"], "fan_speed": d["fan_speed"],
                        "light_level": d["light_level"], "servo_angle": d["servo_angle"]}), 200
    except Exception as e:
        logger.error(f"Hardware endpoint error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/api/hardware/status', methods=['GET'])
def hardware_status():
    return jsonify({"rooms": brain.hardware_rooms(), **brain.hardware_status()})


@app.route('/api/hardware/calibrate-led', methods=['POST'])
def calibrate_led():
    data = request.get_json(force=True, silent=True) or {}
    try:
        return jsonify(brain.start_led_calibration(data.get("room_id")))
    except ValueError as e:
        return _err(str(e))


@app.route('/api/hardware/override', methods=['POST'])
def hardware_override():
    """Manual control of a real room: {"room_id", "fan_speed" 0-255, "light_level" 0-255, "servo_angle" 0-180,
    "minutes" 1-240, "reason"} or {"room_id", "clear": true}.  Values are bounded; the override ends by itself."""
    data = request.get_json(force=True, silent=True) or {}
    try:
        return jsonify(brain.set_override(data))
    except ValueError as e:
        return _err(str(e))


@app.route('/api/ai', methods=['GET', 'POST'])
def ai_switch():
    """GET: is AI control on?  POST {"enabled": true|false}: switch it for every room."""
    if request.method == 'GET':
        return jsonify({"ai_enabled": brain.ai_enabled, "meter": brain.twin.meter()})
    data = request.get_json(force=True, silent=True) or {}
    if not isinstance(data.get("enabled"), bool):
        return _err('send {"enabled": true} or {"enabled": false}')
    return jsonify({"status": "ok", **brain.set_ai(data["enabled"])})


@app.route('/api/meter', methods=['GET'])
def meter():
    with brain.twin.lock:
        m = brain.twin.meter(detail=True)
    m["real_rooms"] = [link.meter() for link in brain.links.values()]
    return jsonify(m)


@app.route('/api/rooms/current-state', methods=['GET'])
def get_current_state():
    return jsonify(brain.get_current_state())


@app.route('/api/stream', methods=['GET'])
def sse_stream():
    """Server-Sent Events: the full state as soon as anything changes; a comment every 5 s otherwise."""
    def generate():
        last_seq = -1
        while True:
            try:
                seq = brain.wait_for_change(last_seq, timeout=5.0)
                if seq == last_seq:
                    yield ": keepalive\n\n"
                    continue
                last_seq = seq
                data = json.dumps(brain.get_current_state(), default=str, separators=(",", ":"))
                yield f"id: {seq}\ndata: {data}\n\n"
                time.sleep(0.1)          # at most ~10 pushes per second per client
            except GeneratorExit:
                break
            except Exception as e:
                logger.error(f"SSE error: {e}")
                time.sleep(1)

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'Connection': 'keep-alive', 'X-Accel-Buffering': 'no'})


@app.route('/api/system/summary', methods=['GET'])
def system_summary():
    return jsonify(brain.get_current_state().get("system", {}))


@app.route('/api/building/config', methods=['GET'])
def building_config():
    cfg = spec_for_frontend(brain.twin.specs)
    cfg["controllers"] = [{"id": k, "label": v, "available": controller_available(k)[0],
                           "availability": controller_available(k)[1]} for k, v in CONTROLLERS.items()]
    cfg["scenarios"] = list(SCENARIOS)
    cfg["hardware_room_id"] = HARDWARE_ROOM_ID
    cfg["hardware_room_ids"] = HARDWARE_IDS
    cfg["api_version"] = API_VERSION
    return jsonify(cfg)


@app.route('/api/rooms/history', methods=['GET'])
def room_history():
    room_id = request.args.get('room_id')
    if room_id:
        if room_id not in ROOM_IDS:
            return _err(f"unknown room '{room_id}'", 404)
        return jsonify({room_id: brain.get_room_history(room_id)})
    return jsonify({rid: brain.get_room_history(rid) for rid in ROOM_IDS})


@app.route('/api/timeline', methods=['GET'])
def timeline():
    try:
        after = int(request.args.get("after", "0"))
        limit = max(1, min(400, int(request.args.get("limit", "100"))))
    except ValueError:
        return _err("after and limit must be integers")
    kinds = [k for k in request.args.get("kinds", "").split(",") if k]
    return jsonify(brain.twin.get_timeline(after=after, room_id=request.args.get("room_id"), limit=limit,
                                           kinds=kinds or None))


@app.route('/api/analytics', methods=['GET'])
def analytics():
    return jsonify(brain.twin.analytics())


@app.route('/api/simulation/control', methods=['POST'])
def simulation_control():
    """pause | resume | speed {speed} | fast_forward {minutes | until "HH:MM", weekday} |
    reset {seed?, controller?} | restart_comparison | watch {room_id}.
    ('reset-energy' is kept as restart_comparison.)"""
    data = request.get_json(force=True, silent=True) or {}
    action = data.get("action", "")
    tw = brain.twin
    try:
        if action == "pause":
            tw.set_running(False)
        elif action == "resume":
            tw.set_running(True)
        elif action == "speed":
            tw.set_speed(float(data["speed"]))
        elif action == "fast_forward":
            if data.get("until"):
                hh, mm = str(data["until"]).split(":")
                tw.fast_forward_until(int(hh), int(mm), weekday=bool(data.get("weekday", True)))
            else:
                tw.fast_forward(float(data.get("minutes", 60)))
        elif action == "reset":
            seed = data.get("seed")
            tw.reset(seed=int(seed) if seed is not None else None, controller=data.get("controller"))
            tw.set_ai(brain.ai_enabled)
        elif action in ("restart_comparison", "reset-energy"):
            tw.restart_comparison()
        elif action == "watch":
            tw.watch_room(data.get("room_id"))
        else:
            return _err(f"unsupported action '{action}'")
    except (KeyError, TypeError, ValueError) as e:
        return _err(f"{action}: {e}")
    brain._notify()
    return jsonify({"status": "ok", "clock": tw.clock()})


@app.route('/api/simulation/controller', methods=['POST'])
def set_controller():
    """Which AI runs when AI control is on: "mo" (thesis optimizer) or "threshold_rf"."""
    data = request.get_json(force=True, silent=True) or {}
    try:
        brain.twin.set_controller(str(data.get("controller", "")))
    except ValueError as e:
        return _err(str(e))
    brain._notify()
    return jsonify({"status": "ok", "controller": brain.twin.ai_name})


@app.route('/api/scenario', methods=['POST'])
def add_scenario():
    """{kind, room_id?, value, minutes}; kind in occupancy | heat_gain | co2 | window | heat_wave | overcast;
    {action: "clear"} stops all scenarios."""
    data = request.get_json(force=True, silent=True) or {}
    try:
        if data.get("action") == "clear":
            brain.twin.clear_scenarios()
            brain._notify()
            return jsonify({"status": "ok"})
        sc = brain.twin.add_scenario(str(data.get("kind", "")), data.get("room_id"),
                                     float(data.get("value", 0.0)), float(data.get("minutes", 60.0)))
    except (TypeError, ValueError) as e:
        return _err(str(e))
    brain._notify()
    return jsonify({"status": "ok", "scenario": sc})


@app.route('/api/physical/outputs', methods=['GET'])
def physical_outputs():
    return jsonify(brain.physical_output.get_all_states())


# =============================================================================
# BACKGROUND TICK LOOP
# =============================================================================
# ─── models, history, provenance, experiments (API v3 additions) ───
def _admin_ok() -> bool:
    """Model promotion/rollback change what runs: when ADMIN_TOKEN is set, require it."""
    token = os.environ.get("ADMIN_TOKEN")
    return not token or request.headers.get("X-Admin-Token") == token


@app.route('/api/models', methods=['GET'])
def models_status():
    from ml.registry import Registry
    out = {"registry": Registry().status(), "live": brain.models.summary() if brain.models else None,
           "live_error": brain.models_error,
           "controllers": [{"id": k, "label": v, "available": controller_available(k)[0],
                            "availability": controller_available(k)[1]} for k, v in CONTROLLERS.items()],
           "active_controller": brain.twin.ai_name, "random_forest_source": getattr(brain.twin.rf, "name", None)}
    return jsonify(out)


@app.route('/api/models/promote', methods=['POST'])
def models_promote():
    if not _admin_ok():
        return _err("admin token required", 403)
    from ml.registry import Registry
    data = request.get_json(force=True, silent=True) or {}
    task, version = str(data.get("task", "")), str(data.get("version", ""))
    reg = Registry()
    if task not in reg.tasks() or version not in reg.versions(task):
        return _err(f"unknown task/version {task} {version}")
    try:
        report = reg.promote(task, version)
    except PermissionError as e:
        return jsonify({"status": "rejected", "error": str(e), "report": reg.evaluate(task, version)}), 409
    if brain.models:
        brain.models.reload()
    if brain.store:
        brain.store.add_event("model", f"{task} {version} promoted (acceptance tests passed)", data={"report": report})
    return jsonify({"status": "promoted", "task": task, "version": version, "report": report})


@app.route('/api/models/rollback', methods=['POST'])
def models_rollback():
    if not _admin_ok():
        return _err("admin token required", 403)
    from ml.registry import Registry
    data = request.get_json(force=True, silent=True) or {}
    task = str(data.get("task", ""))
    try:
        v = Registry().rollback(task, reason=str(data.get("reason", "rollback via API"))[:200])
    except ValueError as e:
        return _err(str(e))
    if brain.models:
        brain.models.reload()
    if brain.store:
        brain.store.add_event("model", f"{task} rolled back to {v}")
    return jsonify({"status": "rolled_back", "task": task, "active": v})


@app.route('/api/history', methods=['GET'])
def history():
    """Persisted history of one room. ?room_id=...&since=ISO&until=ISO&limit=N&table=room_snapshots|readings|decisions|predictions"""
    if brain.store is None:
        return jsonify({"error": "no persistent store configured", "store_error": brain.store_error}), 503
    room_id = request.args.get("room_id", "")
    if room_id not in ROOM_IDS:
        return _err(f"unknown room_id {room_id!r}")
    table = request.args.get("table", "room_snapshots")
    try:
        limit = int(request.args.get("limit", "500"))
        rows = brain.store.history(room_id, request.args.get("since"), request.args.get("until"), limit, table)
    except ValueError as e:
        return _err(str(e))
    return jsonify({"room_id": room_id, "room_number": ROOM_NUMBERS.get(room_id), "table": table, "rows": rows,
                    "units": {"temperature_c": "degC", "humidity_pct": "%RH", "co2_ppm": "ppm", "lux": "lux",
                              "power_w": "W", "energy_wh": "Wh", "setpoint_c": "degC"}})


@app.route('/api/events', methods=['GET'])
def events():
    if brain.store is None:
        return jsonify({"events": brain.twin.get_timeline(limit=100), "persistent": False})
    try:
        limit = int(request.args.get("limit", "100"))
    except ValueError:
        return _err("limit must be an integer")
    return jsonify({"events": brain.store.events(limit, request.args.get("kind")), "persistent": True})


@app.route('/api/provenance', methods=['GET'])
def provenance():
    manifest_path = os.path.join(PROJECT_ROOT, "data", "manifest.json")
    manifest = None
    if os.path.exists(manifest_path):
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    return jsonify({
        "classes": (manifest or {}).get("provenance_classes"),
        "rooms": [{"room_id": rid, "room_number": ROOM_NUMBERS.get(rid),
                   "source": "hardware" if rid in brain.links else "simulated",
                   "measurements": "room101_measured (only while its board is connected)" if rid in brain.links
                   else "synthetic"} for rid in ROOM_IDS],
        "weather": "synthetic Colombo climate from published monthly normals (twin/climate.py), not measured",
        "store": brain.store.summary() if brain.store else None,
        "datasets": {k: {kk: v.get(kk) for kk in ("name", "licence", "accessed", "provenance", "landing_page")}
                     for k, v in ((manifest or {}).get("raw") or {}).items()},
    })


@app.route('/api/datasets', methods=['GET'])
def datasets():
    path = os.path.join(PROJECT_ROOT, "data", "manifest.json")
    if not os.path.exists(path):
        return _err("data/manifest.json missing", 404)
    with open(path, encoding="utf-8") as f:
        return jsonify(json.load(f))


@app.route('/api/experiments', methods=['GET'])
def experiments():
    base = os.path.join(PROJECT_ROOT, "experiments", "results")
    out = []
    if os.path.isdir(base):
        for name in sorted(os.listdir(base)):
            d = os.path.join(base, name)
            if not os.path.isdir(d):
                continue
            item = {"id": name, "files": sorted(os.listdir(d))}
            st = os.path.join(d, "status.json")
            if os.path.exists(st):
                with open(st, encoding="utf-8") as f:
                    item["status"] = json.load(f)
            out.append(item)
    return jsonify({"experiments": out})


@app.route('/api/hardware/mqtt', methods=['GET'])
def mqtt_status():
    if brain.mqtt is None:
        return jsonify({"enabled": False, "note": "MQTT bridge not started (set MQTT_ENABLED=1); boards use HTTP POST"})
    return jsonify(brain.mqtt.status())


def run_tick_loop(brain_instance: EdgeBrain, stop_event: threading.Event):
    logger.info("Edge Brain tick loop started")
    next_t = time.monotonic()
    while not stop_event.is_set():
        try:
            brain_instance.tick()
        except Exception as e:
            logger.error(f"Tick error: {e}", exc_info=True)
        next_t += brain_instance._update_interval
        delay = next_t - time.monotonic()
        if delay < 0:
            next_t = time.monotonic()
            delay = 0.005        # let API threads take the lock between learning-week chunks
        stop_event.wait(delay)
    logger.info("Edge Brain tick loop stopped")


def main():
    global brain
    logger.info("===================================================")
    logger.info("  EDGE INTELLIGENCE BRAIN  (API v%d)", API_VERSION)
    logger.info("  Running on %s %s", platform.system(), platform.machine())
    logger.info("===================================================")
    speed = float(os.environ.get("SPEED_FACTOR", "360"))
    db = os.environ.get("EDGE_DB", DEFAULT_DB)
    brain = EdgeBrain(speed_factor=speed, store_path=None if db.lower() in ("", "none", "off") else db)
    if os.environ.get("MQTT_ENABLED", "0") == "1":
        from raspberry_pi.mqtt_bridge import MqttBridge
        brain.mqtt = MqttBridge(brain.inject_hardware_data, HARDWARE_IDS, store=brain.store,
                                on_event=lambda kind, text, room: brain.twin.add_event(
                                    {"seq": None, "kind": kind, "summary": text, "room_id": room,
                                     "real_time": datetime.now().isoformat(timespec="seconds"),
                                     "sim_time": brain.twin.time.isoformat(timespec="minutes")}))
        brain.mqtt.start()
    stop_event = threading.Event()
    threading.Thread(target=run_tick_loop, args=(brain, stop_event), daemon=True, name="EdgeBrainTickLoop").start()
    port = int(os.environ.get("API_PORT", "8001"))
    host = os.environ.get("API_HOST", "0.0.0.0")
    logger.info("Starting API on %s:%d", host, port)
    logger.info("  Boards post to: POST http://<this machine's IP>:%d/api/hardware/sensor-data", port)
    logger.info("  SSE stream:     GET  http://<this machine's IP>:%d/api/stream", port)
    logger.info("  AI switch:      POST http://<this machine's IP>:%d/api/ai  {\"enabled\": true|false}", port)
    if brain.twin.phase == "learning":
        logger.info("  The AI's learning week is running first (progress on the dashboard); "
                    "it is cached for the next start.")
    try:
        app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        if brain.mqtt is not None:
            brain.mqtt.stop()
        brain.physical_output.cleanup()
        logger.info("Edge Brain shutdown complete.")


if __name__ == "__main__":
    main()
