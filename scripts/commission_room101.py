#!/usr/bin/env python3
"""
Room 101 commissioning runner: flash, deploy, then test the real hardware and record the evidence.

Run it on the Windows PC that has the ESP32-S3 on USB and SSH access to the Raspberry Pi:

    .venv\\Scripts\\python.exe scripts\\commission_room101.py --flash --deploy-pi
    .venv\\Scripts\\python.exe scripts\\commission_room101.py --only T09,T16        (re-run some tests)
    .venv\\Scripts\\python.exe scripts\\commission_room101.py --list                (show the tests)

It drives the board over MQTT (and SSH for the Pi), asks you only for what a script cannot see
(is the LED red? did the fan spin? a reference thermometer reading), and writes every observation
to docs/commissioning_runs/run_<time>.json and .md. A test is PASS only when its measured evidence
and, where needed, your physical confirmation agree. Nothing is ever marked PASS by default.

Requirements on the PC: the project .venv (paho-mqtt), Windows OpenSSH (ssh.exe/scp.exe) with the
Pi key, and for --flash the Arduino IDE (its bundled arduino-cli) with the ESP32 core installed.
"""
from __future__ import annotations

print("Room 101 commissioning runner: starting (the first start from the G: drive can take a minute) ...", flush=True)

import argparse
import datetime as dt
import glob
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections import deque
from typing import Any, Callable, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOM = "f2_office_a"
PREFIX = f"sb/v1/room/{ROOM}"
TOPIC = {k: f"{PREFIX}/{k}" for k in ("telemetry", "command", "ack", "status", "ble_status")}
EXPECTED_FW = "room101-2026.11.20"
PI_DIR = "/home/pi/Desktop/Project-pi-ble"
PI_FILES = ["raspberry_pi/ble_gateway.py", "raspberry_pi/mqtt_bridge.py", "raspberry_pi/edge_brain.py"]
SKETCH = os.path.join(ROOT, "firmware", "esp32_smart_building")
FQBN = "esp32:esp32:esp32s3"
FRESH_S = 10.0          # the Edge Brain marks the board lost after 10 s without telemetry

PASS, FAIL, BLOCKED, NOT_TESTED = "PASS", "FAIL", "BLOCKED", "NOT TESTED"

TESTS = [
    ("T24", "Firmware build/flash"), ("T01", "ESP32 boot and firmware version"),
    ("T10", "Wi-Fi association"), ("T11", "MQTT broker"), ("T12", "ESP32 -> MQTT telemetry"),
    ("T14", "Telemetry reaches the Edge Brain"), ("T19", "Backend/API"),
    ("T02", "BME280 vs reference"), ("T03", "BH1750 cover/uncover"), ("T20", "Digital twin live update"),
    ("T04", "MQ-135 raw response"), ("T05", "PIR motion"),
    ("T13", "MQTT command -> ack"), ("T09", "RGB colours (wiring)"), ("T16", "RGB MQTT control"),
    ("T07", "Relay switching"), ("T08", "Fan runs"), ("T06", "INA219 load measurement"), ("T15", "Fan MQTT control"),
    ("T21", "BLE pairing/connection"), ("T22", "BLE telemetry fallback"), ("T23", "BLE command/ack fallback"),
    ("T17", "MQTT recovery after broker restart"), ("T18", "Pi reboot recovery"),
]
NAMES = dict(TESTS)


# ───────────────────────────────────────────────────────────── console helpers
def say(text: str = "") -> None:
    print(text, flush=True)


def head(text: str) -> None:
    say("\n" + "=" * 78 + f"\n{text}\n" + "=" * 78)


class Asker:
    """Questions for the operator. --yes answers every confirmation with yes (only for dry runs)."""

    def __init__(self, auto: Optional[str] = None):
        self.auto = auto

    def yes(self, question: str) -> bool:
        if self.auto is not None:
            say(f"  ? {question} [auto: {self.auto}]")
            return self.auto == "y"
        while True:
            a = input(f"  ? {question} [y/n] ").strip().lower()
            if a in ("y", "yes"):
                return True
            if a in ("n", "no"):
                return False

    def number(self, question: str) -> Optional[float]:
        if self.auto is not None:
            say(f"  ? {question} [auto: skipped]")
            return None
        while True:
            a = input(f"  ? {question} (Enter to skip) ").strip().replace(",", ".")
            if not a:
                return None
            try:
                return float(a)
            except ValueError:
                say("    please type a number")

    def wait(self, instruction: str) -> None:
        if self.auto is not None:
            say(f"  > {instruction} [auto]")
            return
        input(f"  > {instruction}  -- press Enter when ready ")


# ───────────────────────────────────────────────────────────── evidence
class Run:
    def __init__(self, args):
        self.started = dt.datetime.now()
        self.results: Dict[str, Dict[str, Any]] = {}
        self.meta = {"started": self.started.isoformat(timespec="seconds"), "host": platform.node(),
                     "pi": args.pi, "port": args.port, "expected_firmware": EXPECTED_FW,
                     "runner": "scripts/commission_room101.py"}

    def record(self, tid: str, status: str, actual: str, evidence: Optional[Dict[str, Any]] = None) -> None:
        self.results[tid] = {"id": tid, "component": NAMES.get(tid, tid), "status": status, "actual": actual,
                             "evidence": evidence or {}, "time": dt.datetime.now().isoformat(timespec="seconds")}
        say(f"  -> {tid} {status}: {actual}")

    def write(self) -> str:
        out = os.path.join(ROOT, "docs", "commissioning_runs")
        os.makedirs(out, exist_ok=True)
        stamp = self.started.strftime("%Y%m%d_%H%M%S")
        doc = {"meta": {**self.meta, "finished": dt.datetime.now().isoformat(timespec="seconds")},
               "results": [self.results[t] for t, _ in TESTS if t in self.results]}
        jpath = os.path.join(out, f"run_{stamp}.json")
        with open(jpath, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2, default=str)
        lines = [f"# Room 101 commissioning run {self.started:%d %b %Y %H:%M}", "",
                 f"Generated by `scripts/commission_room101.py` on `{self.meta['host']}`; Pi `{self.meta['pi']}`, "
                 f"board port `{self.meta['port']}`. Evidence for every row is in `{os.path.basename(jpath)}`.", "",
                 "| Test ID | Component | Status | Actual result |", "|---|---|---|---|"]
        for r in doc["results"]:
            lines.append(f"| {r['id']} | {r['component']} | {r['status']} | {r['actual'].replace('|', '/')} |")
        counts = {s: sum(1 for r in doc["results"] if r["status"] == s) for s in (PASS, FAIL, BLOCKED, NOT_TESTED)}
        lines += ["", "Totals: " + ", ".join(f"{k} {v}" for k, v in counts.items())]
        mpath = jpath[:-5] + ".md"
        with open(mpath, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return mpath


# ───────────────────────────────────────────────────────────── MQTT
class Bus:
    """One MQTT client that records every telemetry/ack/status message with its arrival time."""

    def __init__(self, host: str, port: int):
        import paho.mqtt.client as mqtt
        self.telemetry: deque = deque(maxlen=2000)
        self.acks: Dict[str, Dict[str, Any]] = {}
        self.status: deque = deque(maxlen=200)
        self.lock = threading.Lock()
        self.connected = threading.Event()
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                  client_id="room101-commission-" + uuid.uuid4().hex[:6], protocol=mqtt.MQTTv311)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(1, 5)
        self.client.connect_async(host, port, 15)
        self.client.loop_start()

    def _on_connect(self, client, _u, _f, rc, _p=None):
        if getattr(rc, "is_failure", False):
            return
        client.subscribe([(TOPIC["telemetry"], 1), (TOPIC["ack"], 1), (TOPIC["status"], 1)])
        self.connected.set()

    def _on_message(self, _c, _u, msg):
        now = time.monotonic()
        try:
            data = json.loads(msg.payload.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return
        if not isinstance(data, dict):
            return
        with self.lock:
            if msg.topic == TOPIC["telemetry"]:
                self.telemetry.append((now, data))
            elif msg.topic == TOPIC["ack"] and isinstance(data.get("msg_id"), str):
                self.acks[data["msg_id"]] = {"t": now, **data}
            elif msg.topic == TOPIC["status"]:
                self.status.append((now, data, bool(msg.retain)))

    def wait_connected(self, timeout: float = 10) -> bool:
        return self.connected.wait(timeout)

    def telemetry_since(self, t0: float) -> List[tuple]:
        with self.lock:
            return [(t, d) for t, d in self.telemetry if t >= t0]

    def latest(self) -> Optional[Dict[str, Any]]:
        with self.lock:
            return self.telemetry[-1][1] if self.telemetry else None

    def next_telemetry(self, timeout: float = 8, after: Optional[float] = None,
                       where: Optional[Callable[[Dict[str, Any]], bool]] = None) -> Optional[Dict[str, Any]]:
        t0 = time.monotonic() if after is None else after
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            for t, d in self.telemetry_since(t0):
                if where is None or where(d):
                    return d
            time.sleep(0.1)
        return None

    def command(self, fields: Dict[str, Any], timeout: float = 10) -> Optional[Dict[str, Any]]:
        mid = "commission-" + uuid.uuid4().hex[:12]
        msg = {"schema": "sb.command/1", "msg_id": mid, "room_id": ROOM, **fields}
        self.client.publish(TOPIC["command"], json.dumps(msg), qos=1)
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            with self.lock:
                if mid in self.acks:
                    return self.acks[mid]
            time.sleep(0.05)
        return None

    def close(self) -> None:
        self.client.disconnect()
        self.client.loop_stop()


# ───────────────────────────────────────────────────────────── Pi API and SSH
class Pi:
    def __init__(self, host: str, api_port: int, key: Optional[str]):
        self.host, self.api = host, f"http://{host}:{api_port}"
        self.key = key
        known = os.path.join(os.environ.get("TEMP", "/tmp"), "pi-transfer-known_hosts")
        if os.path.exists(known):
            self.ssh_opts = ["-o", f"UserKnownHostsFile={known}", "-o", f"HostKeyAlias={host}",
                             "-o", "StrictHostKeyChecking=yes"]
        else:
            self.ssh_opts = ["-o", "StrictHostKeyChecking=accept-new"]
        if key and os.path.exists(key):
            self.ssh_opts += ["-i", key]
        self.ssh_opts += ["-o", "ConnectTimeout=8"]

    def get(self, path: str, timeout: float = 6) -> Optional[Dict[str, Any]]:
        try:
            with urllib.request.urlopen(self.api + path, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError):
            return None

    def ssh(self, command: str, interactive: bool = False, timeout: float = 60) -> subprocess.CompletedProcess:
        """Run a command on the Pi. interactive=True gives it the terminal (sudo can ask for the password)."""
        if interactive:
            return subprocess.run(["ssh", "-t", *self.ssh_opts, f"pi@{self.host}", command], timeout=timeout)
        return subprocess.run(["ssh", "-o", "BatchMode=yes", *self.ssh_opts, f"pi@{self.host}", command],
                              capture_output=True, text=True, timeout=timeout)

    def scp(self, local: str, remote: str) -> subprocess.CompletedProcess:
        return subprocess.run(["scp", "-o", "BatchMode=yes", *self.ssh_opts, local, f"pi@{self.host}:{remote}"],
                              capture_output=True, text=True, timeout=120)

    def restart_edge(self) -> bool:
        r = self.ssh("systemctl --user restart edge-brain.service && systemctl --user is-active edge-brain.service")
        if r.returncode == 0:
            return True
        say("  Edge Brain is not a user service here; trying the system service (sudo may ask for the Pi password)")
        r = self.ssh("sudo systemctl restart edge-brain.service && systemctl is-active edge-brain.service",
                     interactive=True, timeout=120)
        return r.returncode == 0

    def wait_health(self, timeout: float = 90) -> Optional[Dict[str, Any]]:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            h = self.get("/health")
            if h and h.get("status") == "healthy":
                return h
            time.sleep(2)
        return None


def find_room(obj: Any) -> Optional[Dict[str, Any]]:
    """The Room 101 hardware state inside /api/rooms/current-state, wherever it is nested."""
    if isinstance(obj, dict):
        if obj.get("room_id") == ROOM and isinstance(obj.get("sensors"), dict):
            return obj
        for v in obj.values():
            hit = find_room(v)
            if hit:
                return hit
    elif isinstance(obj, list):
        for v in obj:
            hit = find_room(v)
            if hit:
                return hit
    return None


def arduino_cli() -> Optional[str]:
    candidates = [shutil.which("arduino-cli")]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(os.path.join(local, "Programs", "Arduino IDE", "resources", "app", "lib", "backend",
                                       "resources", "arduino-cli.exe"))
    candidates += glob.glob(r"C:\Program Files\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe")
    return next((c for c in candidates if c and os.path.exists(c)), None)


# ───────────────────────────────────────────────────────────── the tests
class Commissioning:
    def __init__(self, args):
        self.args = args
        self.ask = Asker("y" if args.yes else None)
        self.run = Run(args)
        self.pi = Pi(args.pi, args.api_port, os.path.expanduser(args.key) if args.key else None)
        self.bus: Optional[Bus] = None
        self.rgb_ok: Optional[bool] = None
        self.fan_ready: Optional[bool] = None

    def wanted(self, tid: str) -> bool:
        return not self.args.only or tid in self.args.only

    # -- setup steps -------------------------------------------------------
    def deploy_pi(self) -> bool:
        head("Deploy the updated Pi files (BLE gateway, MQTT bridge, Edge Brain)")
        stamp = dt.datetime.now().strftime("%Y%m%d%H%M%S")
        r = self.pi.ssh(f"cd {PI_DIR} && for f in {' '.join(PI_FILES)}; do cp -p \"$f\" \"$f.bak-{stamp}\"; done && echo ok")
        if r.returncode != 0:
            say(f"  could not back up the Pi files: {r.stderr.strip() or r.stdout.strip()}")
            return False
        for rel in PI_FILES:
            c = self.pi.scp(os.path.join(ROOT, *rel.split("/")), f"{PI_DIR}/{rel}")
            if c.returncode != 0:
                say(f"  scp {rel} failed: {c.stderr.strip()}")
                return False
        say(f"  copied {len(PI_FILES)} files; previous versions kept as *.bak-{stamp}")
        if not self.pi.restart_edge():
            say("  Edge Brain restart failed")
            return False
        ok = self.pi.wait_health(90) is not None
        say("  Edge Brain healthy after restart" if ok else "  Edge Brain did not report healthy within 90 s")
        return ok

    def flash(self) -> None:
        if not self.wanted("T24"):
            return
        head("T24 Build and flash the ESP32-S3")
        cli = arduino_cli()
        if not cli:
            self.run.record("T24", BLOCKED, "arduino-cli not found (install the Arduino IDE or put arduino-cli on PATH)")
            return
        if not os.path.exists(os.path.join(SKETCH, "secrets.h")):
            self.run.record("T24", BLOCKED, "firmware/esp32_smart_building/secrets.h is missing (copy secrets.example.h)")
            return
        say("  Close the Arduino IDE Serial Monitor first: it keeps the COM port busy.")
        self.ask.wait("Disconnect the 12 V fan/relay load supply during flashing (GPIOs change state at boot)")
        build = os.path.join(os.environ.get("TEMP", "/tmp"), "room101-esp32-build")
        cmd = [cli, "compile", "--upload", "--fqbn", FQBN, "--port", self.args.port, "--build-path", build, SKETCH]
        say("  " + " ".join(f'"{c}"' if " " in c else c for c in cmd))
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
        out = (p.stdout + p.stderr).splitlines()
        keep = [l for l in out if any(k in l for k in ("Sketch uses", "Global variables", "Hash of data verified",
                                                        "Hard resetting", "error", "Error", "Wrote"))]
        for l in keep[-12:]:
            say("    " + l.strip())
        verified = any("Hash of data verified" in l for l in out)
        if p.returncode == 0 and verified:
            self.run.record("T24", PASS, "compiled and uploaded; flash hash verified", {"output": keep[-20:]})
        else:
            self.run.record("T24", FAIL, f"arduino-cli exit {p.returncode}; hash verified={verified}",
                            {"output": out[-40:]})

    # -- connectivity ------------------------------------------------------
    def connectivity(self) -> bool:
        head("Connectivity: Pi API, broker and live board telemetry")
        bus_ok = self.bus.wait_connected(10)
        health = self.pi.get("/health")
        if self.wanted("T11"):
            if bus_ok:
                self.run.record("T11", PASS, f"runner connected to Mosquitto at {self.args.pi}:1883 and subscribed")
            else:
                self.run.record("T11", FAIL, f"cannot connect to Mosquitto at {self.args.pi}:1883")
        if not bus_ok:
            return False
        t0 = time.monotonic()
        say("  collecting 30 s of board telemetry ...")
        time.sleep(30)
        msgs = self.bus.telemetry_since(t0)
        boots = [d for _, d in msgs]
        if self.wanted("T01"):
            fw = [d.get("fw_version") for d in boots if d.get("fw_version")]
            if fw and fw[-1] == EXPECTED_FW:
                up = boots[-1].get("uptime_s")
                self.run.record("T01", PASS, f"board running {fw[-1]}, uptime {up} s, health {boots[-1].get('sensor_health')}",
                                {"last": boots[-1]})
            elif boots:
                self.run.record("T01", FAIL, f"board reports firmware {fw[-1] if fw else 'without fw_version (old image)'}; "
                                f"expected {EXPECTED_FW}", {"last": boots[-1]})
            else:
                self.run.record("T01", FAIL, "no telemetry from the board within 30 s")
        if self.wanted("T10"):
            rssi = [d.get("wifi_rssi_dbm") for d in boots if isinstance(d.get("wifi_rssi_dbm"), (int, float))]
            if rssi:
                self.run.record("T10", PASS, f"board on Wi-Fi, RSSI {min(rssi)}..{max(rssi)} dBm (SSID not recorded)",
                                {"rssi": rssi})
            else:
                self.run.record("T10", FAIL if not boots else NOT_TESTED, "no RSSI in telemetry")
        mqtt_msgs = [(t, d) for t, d in msgs if d.get("transport", "mqtt") == "mqtt"]
        if self.wanted("T12"):
            if len(mqtt_msgs) >= 5:
                gaps = [b[0] - a[0] for a, b in zip(mqtt_msgs, mqtt_msgs[1:])]
                schema_ok = all(d.get("schema") == "sb.telemetry/1" and d.get("room_id") == ROOM for _, d in mqtt_msgs)
                status = PASS if schema_ok and max(gaps) <= FRESH_S else FAIL
                self.run.record("T12", status, f"{len(mqtt_msgs)} messages in 30 s, mean interval "
                                f"{statistics.mean(gaps):.1f} s, max gap {max(gaps):.1f} s, schema ok={schema_ok}",
                                {"intervals_s": [round(g, 2) for g in gaps], "sample": mqtt_msgs[-1][1]})
            else:
                self.run.record("T12", FAIL, f"only {len(mqtt_msgs)} MQTT telemetry messages in 30 s")
        h2 = self.pi.get("/health")
        hw0 = (health or {}).get("hardware") or {}
        hw1 = (h2 or {}).get("hardware") or {}
        if self.wanted("T19"):
            mq, ble = self.pi.get("/api/hardware/mqtt"), self.pi.get("/api/hardware/ble")
            ok = bool(h2 and h2.get("status") == "healthy" and mq is not None and ble is not None)
            self.run.record("T19", PASS if ok else FAIL,
                            f"/health {'healthy' if h2 else 'unreachable'}, /api/hardware/mqtt {'ok' if mq else 'missing'}, "
                            f"/api/hardware/ble {'ok' if ble else 'missing'}",
                            {"health": h2, "mqtt": mq, "ble": ble})
        if self.wanted("T14"):
            n0, n1 = hw0.get("readings_received"), hw1.get("readings_received")
            ok = (hw1.get("state") == "connected" and hw1.get("real_board") and isinstance(n0, int)
                  and isinstance(n1, int) and n1 > n0)
            self.run.record("T14", PASS if ok else FAIL,
                            f"Edge Brain state {hw1.get('state')}, readings {n0} -> {n1}, mean interval "
                            f"{hw1.get('mean_interval_s')} s, real_board={hw1.get('real_board')}", {"before": hw0, "after": hw1})
        return bool(boots)

    # -- sensors -----------------------------------------------------------
    def samples(self, seconds: float, key: str) -> List[float]:
        t0 = time.monotonic()
        time.sleep(seconds)
        return [float(d[key]) for _, d in self.bus.telemetry_since(t0) if isinstance(d.get(key), (int, float))
                and not isinstance(d.get(key), bool)]

    def bme280(self) -> None:
        if not self.wanted("T02"):
            return
        head("T02 BME280 against a reference instrument")
        t0 = time.monotonic()
        time.sleep(15)
        msgs = [d for _, d in self.bus.telemetry_since(t0)]
        temps = [d["temperature"] for d in msgs if isinstance(d.get("temperature"), (int, float))]
        hums = [d["humidity"] for d in msgs if isinstance(d.get("humidity"), (int, float))]
        pres = [d["pressure_hpa"] for d in msgs if isinstance(d.get("pressure_hpa"), (int, float))]
        if not temps:
            self.run.record("T02", FAIL, "no BME280 values in 15 s of telemetry (sensor_health.bme280 false?)",
                            {"last": msgs[-1] if msgs else None})
            return
        t, h, p = statistics.median(temps), statistics.median(hums) if hums else None, statistics.median(pres) if pres else None
        say(f"  board: {t:.2f} C, {h if h is None else round(h, 1)} %RH, {p if p is None else round(p, 1)} hPa "
            f"(median of {len(temps)})")
        ref_t = self.ask.number("Reference thermometer reading next to the board, in C")
        ref_h = self.ask.number("Reference humidity reading, in %RH")
        ev = {"board_temperature_c": t, "board_humidity_pct": h, "board_pressure_hpa": p, "samples": len(temps),
              "reference_temperature_c": ref_t, "reference_humidity_pct": ref_h}
        plausible = 800 < (p or 0) < 1100 and 0 <= (h if h is not None else -1) <= 100
        if ref_t is None:
            self.run.record("T02", NOT_TESTED, f"board {t:.1f} C/{h:.1f} %RH/{p:.1f} hPa, plausible={plausible}; "
                            "no reference reading entered", ev)
            return
        dt_ok = abs(t - ref_t) <= 1.5
        dh_ok = ref_h is None or (h is not None and abs(h - ref_h) <= 8)
        status = PASS if dt_ok and dh_ok and plausible else FAIL
        self.run.record("T02", status, f"board {t:.1f} C vs reference {ref_t:.1f} C (limit 1.5 C)"
                        + (f", {h:.1f} vs {ref_h:.1f} %RH (limit 8)" if ref_h is not None and h is not None else "")
                        + f", pressure {p:.1f} hPa plausible={plausible}", ev)

    def light_and_twin(self) -> None:
        if not (self.wanted("T03") or self.wanted("T20")):
            return
        head("T03 BH1750 cover/uncover  +  T20 digital twin follows the change")
        self.ask.wait("Keep the BH1750 uncovered")
        open_lux = self.samples(10, "lux")
        twin_open = (find_room(self.pi.get("/api/rooms/current-state")) or {}).get("sensors", {}).get("Light")
        self.ask.wait("Now COVER the BH1750 completely with your hand or a cap and keep it covered")
        t_cover = time.monotonic()
        cov_lux = self.samples(10, "lux")
        twin_cov = (find_room(self.pi.get("/api/rooms/current-state")) or {}).get("sensors", {}).get("Light")
        dash = self.ask.yes("While covered, does the dashboard's Office A light value show the drop (look now)?")
        self.ask.wait("Uncover the sensor")
        ev = {"uncovered_lux": open_lux, "covered_lux": cov_lux, "twin_light_uncovered": twin_open,
              "twin_light_covered": twin_cov, "dashboard_confirmed": dash, "cover_started_s": round(t_cover, 1)}
        if not open_lux or not cov_lux:
            self.run.record("T03", FAIL, "no lux values in telemetry", ev)
            self.run.record("T20", NOT_TESTED, "no lux change to follow", ev)
            return
        lo, hi = statistics.median(cov_lux), statistics.median(open_lux)
        dropped = hi > 5 and lo <= 0.3 * hi
        if self.wanted("T03"):
            self.run.record("T03", PASS if dropped else FAIL,
                            f"{hi:.1f} lux uncovered -> {lo:.1f} lux covered" + ("" if dropped else
                            " (expected at least a 70 % drop; is the room lit?)"), ev)
        if self.wanted("T20"):
            twin_ok = isinstance(twin_open, (int, float)) and isinstance(twin_cov, (int, float)) and \
                twin_cov <= 0.5 * max(twin_open, 1e-6)
            status = PASS if twin_ok and dash and dropped else FAIL
            self.run.record("T20", status, f"Edge Brain room state Light {twin_open} -> {twin_cov}; "
                            f"dashboard confirmed={dash}", ev)

    def mq135(self) -> None:
        if not self.wanted("T04"):
            return
        head("T04 MQ-135 raw response (no ppm claim)")
        base = self.samples(12, "mq135_raw")
        self.ask.wait("Breathe slowly onto the MQ-135 from ~5 cm for about 10 s")
        stim = self.samples(15, "mq135_raw")
        ev = {"baseline_raw": base, "stimulus_raw": stim}
        if not base or not stim:
            self.run.record("T04", FAIL, "no MQ-135 values in telemetry", ev)
            return
        b, m = statistics.median(base), max(stim)
        valid = 0 < b < 4095
        rise = m - b
        status = PASS if valid and rise >= 20 else FAIL
        self.run.record("T04", status, f"raw baseline {b:.0f} -> peak {m:.0f} (+{rise:.0f} counts; needs >= 20)"
                        + ("" if rise >= 20 else "; a new MQ-135 needs a long heater burn-in"), ev)

    def pir(self) -> None:
        if not self.wanted("T05"):
            return
        head("T05 PIR motion")
        self.ask.wait("Wave your hand in front of the PIR")
        t0 = time.monotonic()
        on = self.bus.next_telemetry(15, after=t0, where=lambda d: d.get("motion_detected") is True)
        if not on:
            self.run.record("T05", FAIL, "no motion_detected=true within 15 s of waving")
            return
        t_on = time.monotonic() - t0
        self.ask.wait("Step out of the PIR's view and stay still (up to 3 minutes, its hold time)")
        t1 = time.monotonic()
        off = self.bus.next_telemetry(180, after=t1, where=lambda d: d.get("motion_detected") is False)
        if off:
            self.run.record("T05", PASS, f"motion true {t_on:.0f} s after waving, false again after "
                            f"{time.monotonic() - t1:.0f} s (PIR hold time)")
        else:
            self.run.record("T05", FAIL, "motion detected but never returned to false within 180 s")

    # -- actuators ---------------------------------------------------------
    def rgb(self) -> None:
        if not (self.wanted("T09") or self.wanted("T16") or self.wanted("T13")):
            return
        head("T13/T09/T16 RGB over MQTT (manual hold keeps the Edge Brain's automatic light level away)")
        say("  HW-478: common '-' to GND, one 220-330 ohm resistor in each R/G/B wire, R=GPIO6 G=GPIO7 B=GPIO5.")
        results, acks = {}, {}
        for color in ("RED", "GREEN", "BLUE", "WHITE", "OFF"):
            t0 = time.monotonic()
            ack = self.bus.command({"rgb": color, "hold_s": 20})
            acks[color] = ack
            tele = self.bus.next_telemetry(8, after=t0, where=lambda d, c=color: d.get("actuator_rgb") == c)
            if not ack:
                say(f"  {color}: no acknowledgement within 10 s")
                results[color] = False
                continue
            say(f"  {color}: ack {ack.get('status')} in {ack['t'] - t0:.1f} s, board reports "
                f"{tele.get('actuator_rgb') if tele else 'no matching telemetry'}")
            seen = self.ask.yes(f"Is the module {'dark (all off)' if color == 'OFF' else 'lit ' + color}?")
            results[color] = bool(ack.get("status") == "applied" and tele and seen)
        self.bus.command({"rgb": "OFF", "hold_s": 0})
        ev = {"per_color": results, "acks": acks}
        if self.wanted("T13"):
            got = [c for c, a in acks.items() if a and a.get("status") == "applied"]
            self.run.record("T13", PASS if len(got) == 5 else FAIL, f"{len(got)}/5 commands acknowledged 'applied'",
                            {"acks": acks})
        all_ok = all(results.values())
        self.rgb_ok = all_ok
        note = ", ".join(f"{c} {'ok' if ok else 'NO'}" for c, ok in results.items())
        if self.wanted("T09"):
            self.run.record("T09", PASS if all_ok else FAIL, note, ev)
        if self.wanted("T16"):
            self.run.record("T16", PASS if all_ok else FAIL, note + " (command, ack, telemetry and visual)", ev)
        if not all_ok:
            say("\n  RGB diagnosis: open the Arduino Serial Monitor (115200 baud), type D and press Enter.")
            say("  Each colour pin is driven HIGH for 4 s; measure GPIO-to-GND with a multimeter (~3.3 V expected).")
            say("  3.3 V but no light -> module, resistor or common-pin wiring. 0 V -> wrong pin or firmware.")

    def fan(self) -> None:
        wanted = [t for t in ("T07", "T08", "T06", "T15") if self.wanted(t)]
        if not wanted:
            return
        head("T07/T08/T06/T15 Relay, fan and INA219 under load")
        say("  Needed: 12 V supply -> fuse -> INA219 VIN+ -> VIN- -> relay COM/NO -> fan -> 12 V GND,")
        say("  INA219 VCC on 3.3 V (never 12 V), 12 V GND tied to ESP32 GND for the INA219 bus reading.")
        ready = self.ask.yes("Is the fused 12 V fan branch wired like that and its supply switched on?")
        self.fan_ready = ready
        if not ready:
            for t in wanted:
                self.run.record(t, BLOCKED, "12 V fan branch not available for this run")
            return
        off = self.samples(9, "measured_current_mA")
        t0 = time.monotonic()
        ack_on = self.bus.command({"relay": "ON", "hold_s": 25})
        tele_on = self.bus.next_telemetry(8, after=t0, where=lambda d: d.get("relay_on") is True)
        time.sleep(3)
        on = self.samples(9, "measured_current_mA")
        volts = [float(d["measured_voltage_v"]) for _, d in self.bus.telemetry_since(t0)
                 if isinstance(d.get("measured_voltage_v"), (int, float))]
        click = self.ask.yes("Did the relay click (and its LED light)?")
        spin = self.ask.yes("Is the fan spinning?")
        t1 = time.monotonic()
        ack_off = self.bus.command({"relay": "OFF", "hold_s": 0})
        tele_off = self.bus.next_telemetry(8, after=t1, where=lambda d: d.get("relay_on") is False)
        stopped = self.ask.yes("Has the fan stopped after the OFF command?")
        ev = {"ack_on": ack_on, "ack_off": ack_off, "current_off_mA": off, "current_on_mA": on, "bus_voltage_v": volts,
              "relay_click": click, "fan_spun": spin, "fan_stopped": stopped,
              "telemetry_on": tele_on is not None, "telemetry_off": tele_off is not None}
        acked = bool(ack_on and ack_off and ack_on.get("status") == "applied" and tele_on and tele_off)
        if "T07" in wanted:
            self.run.record("T07", PASS if acked and click and stopped else FAIL,
                            f"relay ON/OFF acknowledged={acked}, click={click}, released={stopped}", ev)
        if "T08" in wanted:
            self.run.record("T08", PASS if spin and stopped else FAIL, f"fan spun={spin}, stopped={stopped}", ev)
        if "T06" in wanted:
            if off and on:
                d_i = statistics.median(on) - statistics.median(off)
                v = statistics.median(volts) if volts else None
                ok = d_i >= 30 and v is not None and 5.0 <= v <= 14.0
                self.run.record("T06", PASS if ok else FAIL,
                                f"current {statistics.median(off):.1f} mA off -> {statistics.median(on):.1f} mA on "
                                f"(+{d_i:.1f} mA), bus {v if v is None else round(v, 2)} V", ev)
            else:
                self.run.record("T06", FAIL, "no INA219 current values in telemetry", ev)
        if "T15" in wanted:
            self.run.record("T15", PASS if acked and spin and stopped else FAIL,
                            f"MQTT ON -> fan spun={spin}; MQTT OFF -> stopped={stopped}; acks/telemetry ok={acked}", ev)

    # -- BLE fallback ------------------------------------------------------
    def ble(self) -> None:
        wanted = [t for t in ("T21", "T22", "T23") if self.wanted(t)]
        if not wanted:
            return
        head("T21/T22/T23 BLE fallback (board leaves MQTT for 60 s on command)")
        ble = self.pi.get("/api/hardware/ble") or {}
        if "T21" in wanted:
            self.run.record("T21", PASS if ble.get("connected") else FAIL,
                            f"gateway connected={ble.get('connected')}, MTU {ble.get('mtu')}, "
                            f"frame data {ble.get('frame_data_size')} B", {"ble": ble})
        if not ble.get("connected"):
            for t in ("T22", "T23"):
                if t in wanted:
                    self.run.record(t, BLOCKED, "BLE gateway not connected to the board", {"ble": ble})
            return
        t0 = time.monotonic()
        ack = self.bus.command({"test": "mqtt_pause", "seconds": 60})
        if not ack or ack.get("status") != "applied":
            for t in ("T22", "T23"):
                if t in wanted:
                    self.run.record(t, FAIL, f"board refused or did not acknowledge the MQTT pause: {ack}")
            return
        say("  board acknowledged; MQTT paused for 60 s, watching telemetry arrive through the BLE gateway ...")
        time.sleep(8)
        cmd_result = None
        if "T23" in wanted:
            target = {"rgb": "GREEN", "hold_s": 12} if self.rgb_ok is not False else None
            if target is None and self.fan_ready:
                target = {"relay": "ON", "hold_s": 8}
            if target:
                tc = time.monotonic()
                cack = self.bus.command(target, timeout=15)
                what = "LED green" if "rgb" in target else "relay clicked on / fan running"
                seen = self.ask.yes(f"Is the {what} now?") if cack else False
                cmd_result = {"command": target, "ack": cack, "latency_s": round(cack["t"] - tc, 2) if cack else None,
                              "observed": seen}
        h_samples = []
        while time.monotonic() - t0 < 58:
            h = (self.pi.get("/health") or {}).get("hardware") or {}
            h_samples.append(h.get("state"))
            time.sleep(4)
        ble_msgs = [(t, d) for t, d in self.bus.telemetry_since(t0 + 5) if d.get("transport") == "ble"]
        gaps = [b[0] - a[0] for a, b in zip(ble_msgs, ble_msgs[1:])]
        back = self.bus.next_telemetry(40, where=lambda d: d.get("transport") == "mqtt",
                                       after=time.monotonic())
        info = self.pi.get("/api/hardware/ble") or {}
        ev = {"ble_messages": len(ble_msgs), "gaps_s": [round(g, 2) for g in gaps], "edge_states": h_samples,
              "mqtt_back": back is not None, "ble_after": info, "command": cmd_result}
        if "T22" in wanted:
            ok = len(ble_msgs) >= 10 and gaps and max(gaps) <= FRESH_S and all(s == "connected" for s in h_samples)
            self.run.record("T22", PASS if ok else FAIL,
                            f"{len(ble_msgs)} telemetry messages via BLE in ~50 s, max gap "
                            f"{max(gaps) if gaps else float('nan'):.1f} s (limit {FRESH_S:.0f}), Edge Brain states "
                            f"{sorted(set(h_samples))}, MQTT back afterwards={back is not None}", ev)
        if "T23" in wanted:
            if cmd_result is None:
                self.run.record("T23", BLOCKED, "no working actuator to observe (RGB failed and no fan branch)", ev)
            else:
                ok = bool(cmd_result["ack"] and cmd_result["ack"].get("status") == "applied" and cmd_result["observed"])
                self.run.record("T23", PASS if ok else FAIL,
                                f"command over MQTT -> BLE: ack={'applied' if cmd_result['ack'] else 'none'} "
                                f"in {cmd_result['latency_s']} s, actuator observed={cmd_result['observed']}", ev)
        self.bus.command({"rgb": "OFF", "hold_s": 0})
        if self.fan_ready:
            self.bus.command({"relay": "OFF", "hold_s": 0})

    # -- recovery ----------------------------------------------------------
    def broker_restart(self) -> None:
        if not self.wanted("T17"):
            return
        head("T17 MQTT recovery: restart Mosquitto on the Pi (sudo will ask for the Pi password)")
        if not self.ask.yes("Restart the Mosquitto broker now?"):
            self.run.record("T17", NOT_TESTED, "operator skipped the broker restart")
            return
        t0 = time.monotonic()
        r = self.pi.ssh("sudo systemctl restart mosquitto && systemctl is-active mosquitto", interactive=True, timeout=120)
        if r.returncode != 0:
            self.run.record("T17", BLOCKED, "could not restart Mosquitto over SSH")
            return
        self.bus.wait_connected(20)
        back = self.bus.next_telemetry(90, after=t0 + 1, where=lambda d: d.get("transport", "mqtt") == "mqtt")
        dt_s = time.monotonic() - t0
        h = self.pi.wait_health(60)
        hw = (h or {}).get("hardware") or {}
        ok = back is not None and hw.get("state") == "connected"
        self.run.record("T17", PASS if ok else FAIL,
                        f"broker restarted; board MQTT telemetry back after {dt_s:.0f} s without a board reset; "
                        f"Edge Brain board state {hw.get('state')}", {"hardware": hw})

    def pi_reboot(self) -> None:
        if not self.wanted("T18") or self.args.skip_reboot:
            if self.wanted("T18"):
                self.run.record("T18", NOT_TESTED, "skipped (--skip-reboot)")
            return
        head("T18 Pi reboot recovery (sudo will ask for the Pi password)")
        pre = self.pi.ssh("systemctl is-enabled mosquitto; systemctl --user is-enabled edge-brain.service "
                          "2>/dev/null || systemctl is-enabled edge-brain.service; loginctl show-user pi -p Linger")
        say("  before reboot: " + " | ".join(pre.stdout.split()))
        if not self.ask.yes("Reboot the Raspberry Pi now?"):
            self.run.record("T18", NOT_TESTED, "operator skipped the reboot")
            return
        self.pi.ssh("sudo systemctl reboot", interactive=True, timeout=60)
        t0 = time.monotonic()
        say("  waiting for the Pi to go down and come back (up to 5 minutes) ...")
        time.sleep(20)
        h = self.pi.wait_health(300)
        if not h:
            self.run.record("T18", FAIL, "Edge Brain API did not come back within 5 minutes",
                            {"enabled_before": pre.stdout})
            return
        t_api = time.monotonic() - t0
        self.bus.wait_connected(30)
        back = self.bus.next_telemetry(180, after=t0 + 20)
        ble = None
        end = time.monotonic() + 120
        while time.monotonic() < end:
            ble = self.pi.get("/api/hardware/ble") or {}
            if ble.get("connected"):
                break
            time.sleep(5)
        svc = self.pi.ssh("systemctl is-active mosquitto; systemctl --user is-active edge-brain.service "
                          "2>/dev/null || systemctl is-active edge-brain.service")
        hw = ((self.pi.get("/health") or {}).get("hardware")) or {}
        ok = back is not None and hw.get("state") == "connected" and bool(ble and ble.get("connected"))
        self.run.record("T18", PASS if ok else FAIL,
                        f"API back after {t_api:.0f} s; board telemetry resumed={back is not None}; "
                        f"Edge board state {hw.get('state')}; BLE reconnected={bool(ble and ble.get('connected'))}; "
                        f"services {' '.join(svc.stdout.split())}",
                        {"enabled_before": pre.stdout, "services_after": svc.stdout, "ble": ble})

    # -- orchestration -----------------------------------------------------
    def main(self) -> int:
        head(f"Room 101 commissioning  ·  Pi {self.args.pi}  ·  board {self.args.port}")
        if self.args.deploy_pi and not self.deploy_pi():
            say("Pi deployment failed; fix it before testing (the new firmware needs the new BLE gateway).")
            return 2
        if self.args.flash:
            self.flash()
            say("  waiting 25 s for the board to boot, join Wi-Fi and connect ...")
            time.sleep(25)
        self.bus = Bus(self.args.pi, 1883)
        try:
            if not self.connectivity():
                say("No board telemetry: check power, Wi-Fi (secrets.h) and the Serial Monitor output.")
            else:
                self.bme280()
                self.light_and_twin()
                self.mq135()
                self.pir()
                self.rgb()
                self.fan()
                self.ble()
                self.broker_restart()
                self.pi_reboot()
        except KeyboardInterrupt:
            say("\ninterrupted - saving what was recorded")
        finally:
            try:
                self.bus.command({"rgb": "OFF", "hold_s": 0}, timeout=3)
                self.bus.command({"relay": "OFF", "hold_s": 0}, timeout=3)
            except Exception:  # noqa: BLE001 - best effort, the board fail-safe covers the rest
                pass
            self.bus.close()
            path = self.run.write()
        head("Summary")
        for tid, _ in TESTS:
            r = self.run.results.get(tid)
            if r:
                say(f"  {tid:4} {r['status']:10} {r['component']}: {r['actual'][:90]}")
        say(f"\nEvidence written to {path} (and the .json beside it).")
        return 0 if all(r["status"] == PASS for r in self.run.results.values()) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pi", default="172.16.0.57", help="Raspberry Pi address (broker and Edge Brain)")
    ap.add_argument("--api-port", type=int, default=8001)
    ap.add_argument("--port", default="COM8", help="ESP32-S3 serial port for --flash")
    ap.add_argument("--key", default=os.path.join("~", ".ssh", "smart-building-pi"), help="SSH key for pi@<pi>")
    ap.add_argument("--flash", action="store_true", help="compile and upload the firmware first (T24)")
    ap.add_argument("--deploy-pi", action="store_true", help="copy the updated Pi files and restart the Edge Brain")
    ap.add_argument("--only", type=lambda s: {x.strip().upper() for x in s.split(",") if x.strip()},
                    help="comma-separated test IDs, e.g. T09,T16")
    ap.add_argument("--skip-reboot", action="store_true", help="do not reboot the Pi (T18 recorded NOT TESTED)")
    ap.add_argument("--list", action="store_true", help="list the tests and exit")
    ap.add_argument("--yes", action="store_true", help=argparse.SUPPRESS)   # dry runs against a simulator only
    args = ap.parse_args()
    if args.list:
        for tid, name in TESTS:
            say(f"{tid}  {name}")
        return 0
    return Commissioning(args).main()


if __name__ == "__main__":
    sys.exit(main())
