#!/usr/bin/env python3
"""
Bench check of the real room (Room 101) through the running edge brain.

    python3 scripts/check_hardware.py                       # sensors, 60 s
    python3 scripts/check_hardware.py --actuators           # + fan / LED / damper through a manual override
    python3 scripts/check_hardware.py --actuators --ask     # + asks you to confirm what you see on the bench

Start the edge brain first (scripts/start.sh edge, or run_local.bat) and power the board. The script only
reads the edge brain's API (and, with --actuators, sets a short manual override that it clears again); it
never invents a value. Every check is PASS, FAIL, MISSING (the board did not send it) or INFO.

The result is written to experiments/results/hardware_bench/<date_time>/ (result.json, summary.md). It counts
as a physical verification only when the readings came from the real board (firmware source "sensor_node");
readings from raspberry_pi/esp32_test_sender.py are labelled as a software check.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# plausible ranges for an indoor bench (outside them the sensor, its wiring or its address is suspect)
RANGES = {
    "Temperature": (5.0, 50.0), "Humidity": (5.0, 100.0), "Pressure_hPa": (850.0, 1100.0), "Light": (0.0, 100000.0),
    "CO2": (350.0, 5000.0), "SCD41_Temperature": (5.0, 50.0), "MQ2_raw": (0, 4095),
    "voltage_v": (0.0, 30.0), "current_mA": (-3000.0, 3000.0), "mmwave_distance_cm": (0, 800),
}


def api(base: str, path: str, body: Optional[dict] = None, timeout: float = 5.0) -> Any:
    req = urllib.request.Request(base.rstrip("/") + path, method="POST" if body is not None else "GET",
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def room_state(base: str, room: str) -> Optional[Dict[str, Any]]:
    st = api(base, "/api/rooms/current-state")
    return next((r for r in st.get("rooms", []) if r.get("room_id") == room), None)


class Report:
    def __init__(self):
        self.items: List[Dict[str, Any]] = []

    def add(self, group: str, name: str, status: str, detail: Any = "") -> None:
        self.items.append({"group": group, "check": name, "status": status, "detail": detail})
        print(f"  {status:8s} {group:10s} {name}" + (f"  ({detail})" if detail not in ("", None) else ""))

    def count(self, status: str) -> int:
        return sum(1 for i in self.items if i["status"] == status)


def wait_connected(base: str, room: str, wait_s: float) -> Dict[str, Any]:
    t0 = time.time()
    while True:
        st = api(base, "/api/hardware/status")
        link = next((r for r in st.get("rooms", []) if r.get("room_id") == room), st)
        if link.get("connected"):
            return link
        if time.time() - t0 > wait_s:
            return link
        print(f"  waiting for the board ({link.get('state')}) ...", flush=True)
        time.sleep(3)


def collect(base: str, room: str, seconds: float, every: float = 2.0) -> List[Dict[str, Any]]:
    out, t0, last_ts = [], time.time(), None
    while time.time() - t0 < seconds:
        r = room_state(base, room)
        if r and r.get("timestamp") and r.get("timestamp") != last_ts and (r.get("hardware") or {}).get("connected"):
            out.append(r)
            last_ts = r["timestamp"]
        time.sleep(every)
    return out


def values(samples, getter):
    vals = []
    for s in samples:
        try:
            v = getter(s)
        except (KeyError, TypeError):
            v = None
        vals.append(v)
    return vals


def check_series(rep: Report, group: str, name: str, vals: List[Any], rng=None, need_share: float = 0.9) -> None:
    present = [v for v in vals if v is not None]
    if not vals or not present:
        rep.add(group, name, "MISSING", "never sent - sensor not detected by the firmware, library missing, or wiring")
        return
    share = len(present) / len(vals)
    if share < need_share:
        rep.add(group, name, "FAIL", f"present in {share:.0%} of readings")
        return
    if rng is not None and not isinstance(present[0], bool):
        lo, hi = rng
        bad = [v for v in present if not lo <= v <= hi]
        if bad:
            rep.add(group, name, "FAIL", f"{len(bad)} values outside {lo}-{hi}: e.g. {bad[0]}")
            return
        nums = [float(v) for v in present]
        rep.add(group, name, "PASS", f"{min(nums):g}-{max(nums):g}, mean {statistics.fmean(nums):.2f}, "
                                     f"{len(set(nums))} distinct of {len(nums)}")
    else:
        rep.add(group, name, "PASS", f"values seen: {sorted(set(map(str, present)))}")


def sensors(rep: Report, samples: List[Dict[str, Any]]) -> None:
    S = lambda k: (lambda s: s["sensors"][k])
    check_series(rep, "BME280", "temperature (C)", values(samples, S("Temperature")), RANGES["Temperature"])
    check_series(rep, "BME280", "humidity (%)", values(samples, S("Humidity")), RANGES["Humidity"])
    check_series(rep, "BME280", "pressure (hPa)", values(samples, S("Pressure_hPa")), RANGES["Pressure_hPa"])
    check_series(rep, "BH1750", "illuminance (lux)", values(samples, S("Light")), RANGES["Light"])
    check_series(rep, "SCD41", "CO2 (ppm, NDIR)", values(samples, S("CO2")), RANGES["CO2"])
    rejected = [s["sensors"].get("CO2_rejected") for s in samples if s["sensors"].get("CO2_rejected")]
    if rejected:
        rep.add("SCD41", "non-NDIR CO2 values rejected", "INFO", rejected[0])
    check_series(rep, "SCD41", "temperature (C)", values(samples, S("SCD41_Temperature")), RANGES["SCD41_Temperature"],
                 need_share=0.5)
    P = lambda k: (lambda s: s["presence"][k])
    check_series(rep, "PIR", "motion (bool)", values(samples, P("pir_motion")))
    check_series(rep, "LD2410C", "presence (bool)", values(samples, P("mmwave_presence")))
    check_series(rep, "LD2410C", "distance (cm)", values(samples, P("mmwave_distance_cm")), RANGES["mmwave_distance_cm"])
    M = lambda k: (lambda s: s["power_measurement"][k] if s["power_measurement"]["available"] else None)
    check_series(rep, "INA226", "bus voltage (V)", values(samples, M("voltage_v")), RANGES["voltage_v"])
    check_series(rep, "INA226", "current (mA)", values(samples, M("current_mA")), RANGES["current_mA"])
    check_series(rep, "MQ-2", "raw ADC (gas, never used as CO2)", values(samples, S("MQ2_raw")), RANGES["MQ2_raw"])
    health = samples[-1].get("sensor_health") or {}
    if health:
        off = [k for k, v in health.items() if v is False]
        rep.add("firmware", "sensor_health reported by the board", "INFO" if not off else "FAIL",
                "all detected" if not off else f"not detected: {', '.join(off)}")
    else:
        rep.add("firmware", "sensor_health reported by the board", "MISSING")


def actuators(rep: Report, base: str, room: str, ask: bool) -> None:
    def set_levels(fan, led, servo, what):
        api(base, "/api/hardware/override", {"room_id": room, "fan_speed": fan, "light_level": led,
                                              "servo_angle": servo, "minutes": 3, "reason": f"bench check: {what}"})
        # the command goes out in the reply to the next reading; the board reports the applied levels in the
        # reading after that, so wait for two fresh readings
        got, t0, seen = None, time.time(), set()
        while time.time() - t0 < 25:
            r = room_state(base, room)
            if r and r.get("timestamp") and r["timestamp"] not in seen and (r.get("hardware") or {}).get("connected"):
                seen.add(r["timestamp"])
                got = r
                ds = r.get("device_state") or {}
                if len(seen) >= 2 and ds.get("hvac_speed") == fan and ds.get("light_level") == led:
                    break
            time.sleep(1.0)
        return got

    try:
        off = set_levels(0, 0, 0, "all off")
        lux_off = (off or {}).get("sensors", {}).get("Light")
        p_off = ((off or {}).get("power_measurement") or {}).get("current_mA")
        on = set_levels(255, 255, 90, "fan, LED and damper on")
        ds = (on or {}).get("device_state") or {}
        ctl = (on or {}).get("control") or {}
        for key, want, label in (("hvac_speed", 255, "fan PWM reported by the board"),
                                 ("light_level", 255, "LED PWM reported by the board"),
                                 ("servo_angle", 90, "damper angle reported by the board")):
            v = ds.get(key)
            rep.add("actuators", label, "MISSING" if v is None else ("PASS" if v == want else "FAIL"), f"{v} (commanded {want})")
        rep.add("actuators", "edge verified the previous command", {True: "PASS", False: "FAIL", None: "MISSING"}
                [ctl.get("previous_command_verified")], ctl.get("previous_command_verified"))
        lux_on = (on or {}).get("sensors", {}).get("Light")
        if lux_on is not None and lux_off is not None:
            d = lux_on - lux_off
            rep.add("actuators", "LED seen by the BH1750", "PASS" if d >= 5 else "INFO",
                    f"{d:+.0f} lux (off {lux_off:.0f}, on {lux_on:.0f})" + ("" if d >= 5 else
                    " - point the LED at the sensor if the AI should account for it"))
        p_on = ((on or {}).get("power_measurement") or {}).get("current_mA")
        if p_on is not None and p_off is not None:
            rep.add("actuators", "INA226 current with fan+LED on vs off", "INFO", f"{p_off:.0f} -> {p_on:.0f} mA")
        if ask and sys.stdin.isatty():
            for q in ("Is the fan running at full speed?", "Is the white LED fully on?", "Did the damper servo move to ~90 degrees?"):
                a = input(f"    {q} [y/n] ").strip().lower()
                rep.add("observed", q, "PASS" if a.startswith("y") else "FAIL", "operator")
        back = set_levels(0, 0, 0, "all off again")
        ds = (back or {}).get("device_state") or {}
        rep.add("actuators", "fan and LED off again", "PASS" if ds.get("hvac_speed") == 0 and ds.get("light_level") == 0
                else "FAIL", f"fan {ds.get('hvac_speed')}, LED {ds.get('light_level')}")
    finally:
        try:
            api(base, "/api/hardware/override", {"room_id": room, "clear": True})
        except Exception:     # noqa: BLE001
            print("  could not clear the manual override - clear it with POST /api/hardware/override {\"clear\": true}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", default=os.environ.get("EDGE_API", "http://127.0.0.1:8001"))
    ap.add_argument("--room", default="f2_office_a")
    ap.add_argument("--seconds", type=float, default=60.0, help="how long to record sensor readings")
    ap.add_argument("--wait", type=float, default=120.0, help="how long to wait for the board to connect")
    ap.add_argument("--interval", type=float, default=3.0, help="the board's report interval (firmware: 3 s)")
    ap.add_argument("--actuators", action="store_true", help="drive fan, LED and damper through a manual override")
    ap.add_argument("--ask", action="store_true", help="ask the operator to confirm what the actuators do")
    ap.add_argument("--out", default=os.path.join(ROOT, "experiments", "results", "hardware_bench"))
    a = ap.parse_args(argv)

    rep = Report()
    started = datetime.now()
    print(f"Edge brain: {a.api}")
    try:
        health = api(a.api, "/health")
    except (urllib.error.URLError, OSError) as e:
        print(f"  the edge brain does not answer ({e}); start it first (scripts/start.sh edge or run_local.bat)")
        return 2
    print(f"  {health.get('message')} API v{health.get('api_version')} on {health.get('platform')}")
    link = wait_connected(a.api, a.room, a.wait)
    if not link.get("connected"):
        rep.add("link", "board connected", "FAIL", f"state {link.get('state')} after {a.wait:.0f} s - check Wi-Fi, "
                "EDGE_SERVER_URL in secrets.h, and that this PC/Pi is reachable on port 8001")
        physical = False
        samples: List[Dict[str, Any]] = []
    else:
        physical = bool(link.get("real_board"))
        rep.add("link", "board connected", "PASS", f"sender {link.get('sender')}")
        if not physical:
            rep.add("link", "readings come from the real board", "INFO",
                    f"sender is '{link.get('sender')}' - this run is a software check, not a physical verification")
        print(f"Recording readings for {a.seconds:.0f} s ...")
        samples = collect(a.api, a.room, a.seconds)
        st = api(a.api, "/api/hardware/status")
        link = next((r for r in st.get("rooms", []) if r.get("room_id") == a.room), link)
        mi = link.get("mean_interval_s")
        rep.add("link", "readings received", "PASS" if len(samples) >= max(3, a.seconds / 10) else "FAIL",
                f"{len(samples)} distinct readings; mean interval {mi} s")
        if mi is not None:
            ok = 0.5 * a.interval <= mi <= 2.0 * a.interval
            rep.add("link", f"report interval about {a.interval:g} s", "PASS" if ok else "FAIL", f"{mi} s")
        if samples:
            sensors(rep, samples)
            ai = samples[-1].get("ai") or {}
            rep.add("edge", "occupancy estimate produced", "PASS" if ai else "FAIL",
                    {k: ai.get(k) for k in ("occupancy_probability", "estimator") if k in ai} or ai)
            prov = (samples[-1].get("provenance") or {}) if isinstance(samples[-1].get("provenance"), dict) else {}
            if prov:
                rep.add("edge", "provenance of the room's values", "INFO", prov)
        if a.actuators and samples:
            print("Actuators (manual override, cleared at the end) ...")
            actuators(rep, a.api, a.room, a.ask)

    verdict = "PASS" if rep.count("FAIL") == 0 and rep.count("MISSING") == 0 and samples else \
              ("FAIL" if rep.count("FAIL") else "INCOMPLETE")
    kind = "physical verification (real board)" if physical else "software check (not the real board)"
    out = os.path.join(a.out, started.strftime("%Y%m%d_%H%M%S"))
    os.makedirs(out, exist_ok=True)
    result = {"started": started.isoformat(timespec="seconds"), "finished": datetime.now().isoformat(timespec="seconds"),
              "api": a.api, "room_id": a.room, "kind": kind, "physical": physical, "verdict": verdict,
              "counts": {s: rep.count(s) for s in ("PASS", "FAIL", "MISSING", "INFO")},
              "board": link, "checks": rep.items, "readings": len(samples),
              "last_reading": samples[-1] if samples else None}
    with open(os.path.join(out, "result.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1, default=str)
    with open(os.path.join(out, "summary.md"), "w", encoding="utf-8") as f:
        f.write(f"# Hardware bench check - {started:%Y-%m-%d %H:%M}\n\n**{verdict}** - {kind}; room `{a.room}`; "
                f"{len(samples)} readings.\n\n| group | check | status | detail |\n|---|---|---|---|\n")
        for i in rep.items:
            f.write(f"| {i['group']} | {i['check']} | {i['status']} | {str(i['detail']).replace('|', '/')} |\n")
    print(f"\n{verdict} - {kind}: {rep.count('PASS')} pass, {rep.count('FAIL')} fail, {rep.count('MISSING')} missing")
    print(f"written to {os.path.relpath(out, ROOT)}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
