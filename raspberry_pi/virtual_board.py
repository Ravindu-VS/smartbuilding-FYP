#!/usr/bin/env python3
"""
Virtual ESP32-S3 board for Room 101 (Office A): a software stand-in for the real board.

It behaves like the firmware (firmware/esp32_smart_building/esp32_smart_building.ino) on the wire: an HTTP POST
to /api/hardware/sensor-data every 3 s with exactly the fields of the firmware's buildTelemetry() (BME280,
BH1750, MQ-135 ADC, PIR, INA219 on the 12 V fan branch, relay/fan, light, AC and status LEDs, sensor_health).
It applies the edge brain's reply (fan ON/OFF through the relay, light level, ac_led, status_led) and reports
the applied states in the next reading, and it switches fan and light off when the edge brain cannot be reached
(the firmware's fail-safe). Where its numbers come from is chosen with --source:

  uci   replays the UCI Occupancy Detection dataset (Candanedo & Feldheim 2016; real 1-min measurements of
        temperature, humidity, light and CO2 in an office, with the true occupancy). Read from the tracked
        copies in Dataset/UCI/, so nothing is downloaded. The replay cannot react to the fan; the light adds its
        lux at the BH1750 and the INA219 follows the relay (both modelled).
  twin  Office A simulated by the digital twin's 5R1C room physics (synthetic Colombo weather, stochastic
        occupants, sensor noise and lag), driven by the edge brain's decisions: the fan stands in for the
        room's AC exactly as on the bench, so the room cools when the AI runs the AC.

The MQ-135 is modelled as the inverse of the Pi's eCO2 estimator (raspberry_pi/co2_estimator.py): the source's
CO2 sets the sensor resistance, the module's load resistor and the 10k/15k divider give the ADC millivolts, so
the edge brain estimates CO2 from them exactly as it does for the real board (30-min warm-up included).
PIR and INA219 values come from sensor models driven by the source's occupancy and the relay. Everything this
board sends is labelled "source": "virtual_board" and the edge brain stores it with provenance "synthetic": it is
never recorded or shown as a measurement of Room 101.

    python raspberry_pi/virtual_board.py                            # UCI replay, real time (3 s per reading)
    python raspberry_pi/virtual_board.py --source twin              # simulated Office A, closed loop
    python raspberry_pi/virtual_board.py --minutes-per-post 1       # 1 dataset/simulated minute per reading
    python raspberry_pi/virtual_board.py --drop ina219 --stop-after 100   # fault injection

Profile "bench_v1" reproduces the earlier sensor set (SCD41 NDIR CO2, LD2410C mmWave, MQ-2, INA226, damper
servo) that experiment 11 was run with; it is used only by experiments/run.py to reproduce those results.

When the real board is connected, stop this program; the edge brain then shows the real board and nothing else
changes.
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import math
import os
import random
import sys
import time
import urllib.error
import urllib.request
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Dict, Iterator, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

ROOM = "f2_office_a"
UCI_DIR = os.path.join(ROOT, "Dataset", "UCI", "occupancy+detection")
SENSORS = ("bme280", "bh1750", "mq135", "pir", "ina219")                      # final Room 101 board
SENSORS_V1 = ("bme280", "bh1750", "scd41", "ina226", "ld2410c", "servo", "pir", "mq2")   # profile bench_v1
PROFILES = ("room101", "bench_v1")


# --------------------------------------------------------------------------------------------------------- #
# data sources
# --------------------------------------------------------------------------------------------------------- #
def load_uci(directory: str = UCI_DIR) -> List[Dict]:
    """All UCI rows (training + both test files), time-ordered. Values are used exactly as recorded."""
    rows = []
    for path in sorted(glob.glob(os.path.join(directory, "*.txt"))):
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)                     # 7 names; each row starts with an extra row id
            for vals in reader:
                if not vals:
                    continue
                r = dict(zip(header, vals[-len(header):]))
                rows.append({"time": datetime.strptime(r["date"], "%Y-%m-%d %H:%M:%S"),
                             "temperature": float(r["Temperature"]), "humidity": float(r["Humidity"]),
                             "lux": float(r["Light"]), "co2": float(r["CO2"]),
                             "occupied": r["Occupancy"].strip() == "1", "file": os.path.basename(path)})
    rows.sort(key=lambda x: x["time"])
    dedup, last = [], None
    for r in rows:
        if r["time"] != last:
            dedup.append(r)
            last = r["time"]
    if not dedup:
        raise FileNotFoundError(f"no UCI files in {directory}")
    return dedup


class UciSource:
    name = "uci_replay"

    def __init__(self, start: Optional[str] = None, minutes_per_post: float = 0.05, loop: bool = True):
        self.rows = load_uci()
        self.i = 0
        if start:
            t0 = datetime.fromisoformat(start)
            self.i = next((k for k, r in enumerate(self.rows) if r["time"] >= t0), 0)
        self.step_min = float(minutes_per_post)
        self.loop = loop
        self._acc = 0.0

    def next(self, actuators: Dict) -> Dict:
        """Advance by minutes_per_post (rows are 1 min apart) and return the current row."""
        self._acc += self.step_min
        while self._acc >= 1.0:
            self._acc -= 1.0
            self.i += 1
            if self.i >= len(self.rows):
                if not self.loop:
                    raise StopIteration
                self.i = 0
        r = self.rows[self.i]
        return {"temperature": r["temperature"], "humidity": r["humidity"], "lux_room": r["lux"], "co2": r["co2"],
                "occupants": 1 if r["occupied"] else 0, "occupied": r["occupied"], "time": r["time"]}


class TwinSource:
    """Office A simulated with the twin's room physics, sensors and occupants (one room, no neighbours)."""
    name = "room_model"

    FAN_TO_SP = {150: 26.0, 200: 25.0, 255: 24.0}

    def __init__(self, seed: int = 101, start: Optional[str] = None, minutes_per_post: float = 0.05):
        from twin.building import TwinBuilding
        from twin.spec import build_spec
        spec = next(r for r in build_spec() if r.room_id == ROOM)
        self.spec = replace(spec, data_source="simulation")
        t0 = datetime.fromisoformat(start) if start else datetime(2026, 3, 2, 7, 0)
        self.b = TwinBuilding([self.spec], seed=seed, start=t0)
        self.b.advance(6 * 3600)                      # settle the thermal mass before the first reading
        self.step_s = float(minutes_per_post) * 60.0

    # the final board's AC indicator says what the room's AC is doing; the relay only says ON/OFF
    AC_LED_TO_HVAC = {"ECO": ("ECO", None), "LOW": ("LOW", None), "COOL": ("NORMAL", 25.0), "MAX": ("NORMAL", 24.0)}

    def apply(self, fan: int, led: int, servo: int, ac_led: Optional[str] = None) -> None:
        if ac_led in self.AC_LED_TO_HVAC:
            hvac, sp = self.AC_LED_TO_HVAC[ac_led]
        elif fan <= 0:
            hvac, sp = "ECO", None
        elif fan <= 100:
            hvac, sp = "LOW", None
        else:
            hvac, sp = "NORMAL", self.FAN_TO_SP.get(fan, 24.0 if fan > 200 else 26.0)
        light = "OFF" if led <= 0 else ("DIM" if led <= 127 else "ON")
        self.b.apply(ROOM, light, hvac, sp, vent_boost=servo >= 45)

    def next(self, actuators: Dict) -> Dict:
        self.apply(actuators["fan"], actuators["led"], actuators["servo"], actuators.get("ac_led"))
        self.b.advance(self.step_s)
        rd = self.b.read_sensors(self.step_s)[ROOM]
        tr = self.b.truth(ROOM)
        return {"temperature": rd["temperature"], "humidity": rd["humidity"], "lux_total": rd["light"],
                "co2": rd["co2"], "occupants": tr["occupants"], "occupied": tr["occupants"] > 0,
                "time": self.b.time, "pir_seconds": rd["pir_seconds"], "t_air_true": tr["t_air"]}


# --------------------------------------------------------------------------------------------------------- #
# the board
# --------------------------------------------------------------------------------------------------------- #
class VirtualBoard:
    LED_LUX_FULL = 150.0          # what the light LED adds at the BH1750 at full brightness (modelled)
    PIR_HOLD_S = 2.5              # PIR output hold time after a motion (HC-SR501 at its shortest setting)

    # Sensor-model parameters, per 3-s sample: PIR output high when occupied / false trigger when empty;
    # LD2410C presence when occupied / false presence when empty (profile bench_v1 only). Defaults are "quiet
    # room" assumptions; experiment 11 also runs a noisy setting.
    QUIET = {"pir_detect": 0.45, "pir_false": 0.0003, "mm_detect": 0.97, "mm_false": 0.0005}
    NOISY = {"pir_detect": 0.45, "pir_false": 0.003, "mm_detect": 0.97, "mm_false": 0.01}

    # MQ-135 module and divider (docs/wiring/room101-wiring.html): AO -> R1 10k -> GPIO1 -> R2 15k -> GND,
    # module load resistor 1k, heater and module at 5 V. R0 is this virtual sensor's resistance at the
    # reference concentration; the edge brain does not know it and finds its own by baseline calibration.
    MQ_VCC_MV, MQ_RL_KOHM, MQ_DIVIDER, MQ_R0_KOHM = 5000.0, 1.0, 25.0 / 15.0, 12.0
    MQ_DO_THRESHOLD_PPM = 1000.0  # module comparator (potentiometer); DO is HIGH below it
    # 12 V fan branch (INA219, 0.1 ohm shunt) after the 1N5822 and the fuse
    RAIL_V, FAN_MA = 11.7, 150.0

    def __init__(self, source, seed: int = 1, interval_s: float = 3.0, drop: Optional[List[str]] = None,
                 sensor_model: Optional[Dict[str, float]] = None, profile: str = "room101",
                 uptime0_s: float = 0.0):
        if profile not in PROFILES:
            raise ValueError(f"unknown profile {profile!r} (use one of {PROFILES})")
        self.profile = profile
        self.sm = dict(self.QUIET, **(sensor_model or {}))
        self.src = source
        self.rng = random.Random(seed)
        self.interval = float(interval_s)
        self.drop = set(drop or [])
        known = SENSORS if profile == "room101" else SENSORS_V1
        bad = sorted(self.drop - set(known))
        if bad:
            raise ValueError(f"unknown sensor(s) for profile {profile}: {bad}")
        self.act = {"fan": 0, "led": 0, "servo": 0, "ac_led": "OFF", "status_led": "OFF"}
        self.scd41_hold: Optional[tuple] = None
        self.scd41_t = -1e9
        self.clock = float(uptime0_s)             # seconds since the (virtual) board booted
        self.seq = 0
        self.pressure = 1009.0 + self.rng.uniform(-2, 2)
        self.last_env: Optional[Dict] = None

    def health(self) -> Dict[str, bool]:
        if self.profile == "bench_v1":
            return {k: k not in self.drop for k in ("bme280", "bh1750", "scd41", "ina226", "ld2410c", "servo")}
        return {"bme280": "bme280" not in self.drop, "bh1750": "bh1750" not in self.drop,
                "mq135": "mq135" not in self.drop, "pir": "pir" not in self.drop,
                "ina219": "ina219" not in self.drop, "relay": True, "rgb": True}

    # ------------------------------------------------------------------ sensor models
    @classmethod
    def mq135_adc_mv(cls, co2_ppm: float, temp_c: Optional[float], rh_pct: Optional[float]) -> float:
        """ADC millivolts at GPIO1 for a CO2 concentration: the inverse of the Pi's estimator."""
        from raspberry_pi.co2_estimator import PARA, PARB, correction_factor
        rs_c = cls.MQ_R0_KOHM * (max(1.0, co2_ppm) / PARA) ** (-1.0 / PARB)
        rs = rs_c * correction_factor(temp_c, rh_pct)
        vout = cls.MQ_VCC_MV * cls.MQ_RL_KOHM / (rs + cls.MQ_RL_KOHM)
        return vout / cls.MQ_DIVIDER

    def _env_common(self, p: Dict, env: Dict, h: Dict) -> None:
        rng = self.rng
        if h["bme280"]:                               # BME280: +-0.01 C resolution, small noise
            p["temperature"] = round(env["temperature"] + rng.gauss(0, 0.03), 2)
            p["humidity"] = round(min(100.0, max(0.0, env["humidity"] + rng.gauss(0, 0.2))), 2)
            self.pressure += rng.gauss(0, 0.02)
            p["pressure_hpa"] = round(self.pressure, 1)
        if h["bh1750"]:                               # room light (+ the light LED when the source cannot)
            if "lux_total" in env:
                lux = env["lux_total"]
            else:
                lux = env["lux_room"] + self.LED_LUX_FULL * self.act["led"] / 255.0
            p["lux"] = round(max(0.0, lux * (1 + rng.gauss(0, 0.01))), 1)

    def _pir(self, env: Dict) -> bool:
        # PIR sampled at send time like the firmware (digitalRead): the output stays high ~2.5 s after a detected
        # motion. Twin source: the twin's own motion model; UCI: high in pir_detect of the samples when occupied
        # (people sitting still are often not seen), pir_false when empty.
        if "pir" in self.drop:
            return False
        if "pir_seconds" in env:
            return env["pir_seconds"] is not None and env["pir_seconds"] <= self.PIR_HOLD_S
        return self.rng.random() < (self.sm["pir_detect"] if env["occupied"] else self.sm["pir_false"])

    def reading(self) -> Dict:
        env = self.src.next(self.act)
        self.last_env = env
        self.clock += self.interval
        self.seq += 1
        return self._reading_v1(env) if self.profile == "bench_v1" else self._reading_room101(env)

    def _reading_room101(self, env: Dict) -> Dict:
        """Exactly the fields of the firmware's buildTelemetry() (+ data_source, the replay's name)."""
        rng, h = self.rng, self.health()
        stamp = int(self.clock * 1000)
        fan_on = self.act["fan"] > 0
        led = self.act["led"]
        p: Dict = {"schema": "sb.telemetry/1", "room_id": ROOM, "msg_id": f"{stamp:08X}{self.seq & 0xFFFF:04X}",
                   "source": "virtual_board", "device_id": "room101-virtual", "firmware": "virtual_board",
                   "fw_version": "virtual", "transport": "http", "ts": stamp, "uptime_s": stamp // 1000,
                   "data_source": self.src.name}
        self._env_common(p, env, h)
        pir = self._pir(env)
        p.update({"motion_detected": pir, "presence": pir, "presence_source": "pir"})
        if h["mq135"]:
            mv = self.mq135_adc_mv(env["co2"], env["temperature"], env["humidity"]) + rng.gauss(0, 3.0)
            mv = max(0.0, min(3100.0, mv))
            p.update({"mq135_raw": int(round(mv * 4095 / 3100)), "mq135_adc_mv": int(round(mv)),
                      "mq135_do_high": env["co2"] < self.MQ_DO_THRESHOLD_PPM})
        else:                                         # unplugged AO: the ADC floats near zero
            p.update({"mq135_raw": 0, "mq135_adc_mv": 0, "mq135_do_high": True})
        light_state = "OFF" if led == 0 else ("WHITE" if led == 255 else "CUSTOM")
        p.update({"fan_on": fan_on, "relay_on": fan_on, "actuator_rgb": light_state,
                  "actuator_ac_led": self.act["ac_led"], "actuator_status_led": self.act["status_led"],
                  "wifi_rssi_dbm": int(round(-58 + rng.gauss(0, 2)))})
        if h["ina219"]:                               # high side of the 12 V fan branch, 0.1 ohm shunt
            cur = (self.FAN_MA + rng.gauss(0, 4.0)) if fan_on else rng.gauss(0, 0.3)
            volt = self.RAIL_V - (0.25 if fan_on else 0.0) + rng.gauss(0, 0.01)
            p.update({"measured_voltage_v": round(volt, 3), "ina219_shunt_voltage_mV": round(cur * 0.1, 3),
                      "measured_current_mA": round(cur, 1), "measured_power_mW": round(volt * cur, 1)})
        p.update({"actuator_fan_speed": 255 if fan_on else 0, "actuator_light_level": led,
                  "actuator_servo_angle": 0, "rgb_hold_s": 0, "fan_hold_s": 0, "bench_mode": False, "ble_mtu": 0,
                  "sensor_health": h})
        return p

    def _reading_v1(self, env: Dict) -> Dict:
        """The earlier sensor set (profile bench_v1), kept to reproduce experiment 11."""
        rng, h = self.rng, self.health()
        p: Dict = {"room_id": ROOM, "source": "virtual_board", "data_source": self.src.name}
        self._env_common(p, env, h)
        if h["scd41"]:                                # SCD41: a new value every 5 s, held in between
            if self.clock - self.scd41_t >= 5.0 or self.scd41_hold is None:
                self.scd41_t = self.clock
                self.scd41_hold = (round(env["co2"] + rng.gauss(0, 8)),
                                   round(env.get("t_air_true", env["temperature"]) + 0.8 + rng.gauss(0, 0.1), 2),
                                   round(env["humidity"] - 2.0 + rng.gauss(0, 0.5), 2))
            co2, st, sh = self.scd41_hold
            p.update({"co2": float(co2), "co2_source": "scd41_ndir", "scd41_temp": st, "scd41_humidity": sh})
        else:
            p.update({"co2": 0.0, "co2_source": "none"})
        occupied = env["occupied"]
        pir = self._pir(env)
        p["motion_detected"] = pir
        mm = None
        if h["ld2410c"]:                              # LD2410C: presence incl. people sitting still
            mm = rng.random() < (self.sm["mm_detect"] if occupied else self.sm["mm_false"])
            moving = mm and rng.random() < 0.4
            p.update({"mmwave_presence": mm, "mmwave_moving": moving, "mmwave_stationary": bool(mm and not moving),
                      "mmwave_distance_cm": int(rng.uniform(80, 420)) if mm else 0})
        p["presence"] = bool(pir or mm)
        p["presence_source"] = "pir+mmwave" if mm is not None else "pir"
        if "mq2" not in self.drop:
            p["mq2_raw"] = int(min(4095, max(0, 860 + rng.gauss(0, 12))))
        if h["ina226"]:                               # 5 V supply: board + fan + LED + servo (modelled)
            cur = 110.0 + 210.0 * (self.act["fan"] / 255.0) ** 1.5 + 60.0 * self.act["led"] / 255.0 + rng.gauss(0, 3)
            volt = 5.05 - 0.0004 * cur + rng.gauss(0, 0.003)
            p.update({"measured_voltage_v": round(volt, 3), "measured_current_mA": round(cur, 1),
                      "measured_power_mW": round(volt * cur, 1)})
        p.update({"actuator_fan_speed": self.act["fan"], "actuator_light_level": self.act["led"],
                  "actuator_servo_angle": self.act["servo"], "sensor_health": h})
        return p

    # ------------------------------------------------------------------ actuators
    def apply_reply(self, reply: Dict) -> None:
        """What the firmware does with the edge brain's reply (missing fields keep their safe defaults)."""
        fan = int(max(0, min(255, reply.get("fan_speed", 0) or 0)))
        self.act["fan"] = (255 if fan > 0 else 0) if self.profile == "room101" else fan    # relay: ON/OFF
        self.act["led"] = int(max(0, min(255, reply.get("light_level", 0) or 0)))
        if self.profile == "bench_v1":
            if "servo" not in self.drop:
                self.act["servo"] = int(max(0, min(180, reply.get("servo_angle", self.act["servo"]) or 0)))
            return
        for k in ("ac_led", "status_led"):
            if isinstance(reply.get(k), str) and reply[k]:
                self.act[k] = reply[k]

    def fail_safe(self) -> None:
        """Edge brain unreachable: fan and light off (damper unchanged in bench_v1), AC LED off, status LOST."""
        self.act["fan"], self.act["led"] = 0, 0
        if self.profile == "room101":
            self.act["ac_led"], self.act["status_led"] = "OFF", "LOST"


def post(url: str, payload: Dict, timeout: float = 5.0) -> Dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=os.environ.get("EDGE_API", "http://127.0.0.1:8001"))
    ap.add_argument("--source", choices=("uci", "twin"), default="uci")
    ap.add_argument("--interval", type=float, default=3.0, help="seconds between readings (firmware: 3)")
    ap.add_argument("--minutes-per-post", type=float, default=None,
                    help="dataset / simulated minutes per reading (default: real time = interval/60)")
    ap.add_argument("--start", default=None, help="ISO time to start at (UCI: 2015-02-02..18; twin: any)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--count", type=int, default=0, help="readings to send (0 = until Ctrl+C)")
    ap.add_argument("--stop-after", type=int, default=0, help="go silent after N readings (stale-data test)")
    ap.add_argument("--noisy-sensors", action="store_true", help="higher PIR false-trigger rate")
    ap.add_argument("--drop", default="", help=f"comma list of sensors to treat as not fitted: {','.join(SENSORS)}")
    ap.add_argument("--warm", action="store_true",
                    help="start as a board that has been on for an hour (skips the MQ-135 30-min warm-up)")
    ap.add_argument("--log", default=None, help="CSV log of what was sent, with the source's true occupancy")
    a = ap.parse_args(argv)
    mpp = a.minutes_per_post if a.minutes_per_post is not None else a.interval / 60.0
    drop = [d.strip() for d in a.drop.split(",") if d.strip()]
    bad = [d for d in drop if d not in SENSORS]
    if bad:
        ap.error(f"unknown sensor(s): {bad}")
    src = UciSource(a.start, mpp) if a.source == "uci" else TwinSource(a.seed, a.start, mpp)
    board = VirtualBoard(src, seed=a.seed, interval_s=a.interval, drop=drop,
                         sensor_model=VirtualBoard.NOISY if a.noisy_sensors else None,
                         uptime0_s=3600.0 if a.warm else 0.0)
    endpoint = a.url.rstrip("/") + "/api/hardware/sensor-data"
    print(f"Virtual board ({src.name}) -> {endpoint} every {a.interval:g} s, {mpp:g} source-minutes per reading. "
          f"Labelled source=virtual_board (stored as synthetic). Ctrl+C stops.")
    log = None
    if a.log:
        log = open(a.log, "w", newline="", encoding="utf-8")
        w = csv.writer(log)
        w.writerow(["sent_at", "source_time", "true_occupied", "temperature", "source_co2", "mq135_adc_mv", "lux",
                    "motion", "presence", "reply_fan", "reply_led", "reply_ac_led", "p_occupied", "status"])
    n = 0
    try:
        while a.count == 0 or n < a.count:
            if a.stop_after and n >= a.stop_after:
                print(f"stopped sending after {n} readings (--stop-after); the edge brain should show NOT CONNECTED")
                while True:
                    time.sleep(1)
            try:
                payload = board.reading()
            except StopIteration:
                print("end of the dataset")
                break
            env = board.last_env
            status, reply = "ok", {}
            try:
                reply = post(endpoint, payload)
                board.apply_reply(reply)
            except (urllib.error.URLError, OSError, ValueError) as e:
                status = f"edge unreachable: {e}"
                board.fail_safe()
            n += 1
            if log:
                csv.writer(log).writerow([datetime.now().isoformat(timespec="seconds"), env["time"].isoformat(),
                                          int(env["occupied"]), payload.get("temperature"), env["co2"],
                                          payload.get("mq135_adc_mv"), payload.get("lux"),
                                          int(payload["motion_detected"]), int(payload["presence"]),
                                          reply.get("fan_speed"), reply.get("light_level"), reply.get("ac_led"),
                                          reply.get("occupancy_probability"), status])
                log.flush()
            print(f"#{n} {env['time']:%Y-%m-%d %H:%M} occ={int(env['occupied'])} T={payload.get('temperature')} "
                  f"CO2(source)={env['co2']:.0f} MQ135={payload.get('mq135_adc_mv')} mV lux={payload.get('lux')} -> "
                  + (f"p={reply.get('occupancy_probability')} fan={'ON' if board.act['fan'] else 'OFF'} "
                     f"light={board.act['led']} ac_led={board.act['ac_led']} status={board.act['status_led']}"
                     if status == "ok" else status), flush=True)
            time.sleep(a.interval)
    except KeyboardInterrupt:
        pass
    finally:
        if log:
            log.close()
    print("Virtual board stopped. Room 101 shows NOT CONNECTED after the board timeout (10 s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
