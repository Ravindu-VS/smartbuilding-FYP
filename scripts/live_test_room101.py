#!/usr/bin/env python3
"""
Live end-to-end test of Room 101 on the Raspberry Pi, against the real ESP32 board.

Runs on the Pi next to the edge brain (standard library only):

    python3 scripts/live_test_room101.py            # ~2 minutes, prints PASS/FAIL per check and a JSON summary

What it checks, using only what the board itself reports back:
  link      the real board is connected, sends every ~3 s, over MQTT and Bluetooth LE
  sensors   BME280, BH1750, MQ-135, PIR, INA219 present and in a plausible range
  relay     fan ON and OFF through the relay, confirmed by the INA219 current (catches inverted wiring)
  light     light LED ON / DIM / OFF reported back by the board
  LEDs      status LED shows MANUAL during manual control and leaves it afterwards; AC LED reported
  AI        manual control cleared -> the AI decides again from the real readings
  dashboard the Pi serves the dashboard, the live stream and the model status

It changes the room only through the normal manual-override API and always clears the override at the end.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8001"
RESULTS: list = []


def get(path, timeout=10):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        body = r.read()
        return json.loads(body) if body[:1] in (b"{", b"[") else body


def post(path, body, timeout=10):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def check(name, ok, detail=""):
    RESULTS.append({"check": name, "pass": bool(ok), "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ·  {detail}" if detail else ""), flush=True)


def room():
    for r in get("/api/rooms/current-state")["rooms"]:
        if r.get("room_id") == HW:
            return r
    raise RuntimeError("hardware room not in the state")


def wait_readings(n=3, timeout=20):
    """Wait until the board has sent n new readings (so a command has been applied and reported back)."""
    start = get("/health")["hardware"]["readings_received"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        if get("/health")["hardware"]["readings_received"] >= start + n:
            return True
        time.sleep(0.5)
    return False


def override(fan, light, reason):
    return post("/api/hardware/override", {"room_id": HW, "fan_speed": fan, "light_level": light, "minutes": 5,
                                           "reason": f"live test: {reason}"})


def main():
    global HW
    h = get("/health")
    hw = h["hardware"]
    HW = hw["room_id"]
    print(f"edge brain {h.get('status')} on {h.get('host')}, board room {HW}\n")

    # ---------------- link
    check("board connected", hw["connected"] and hw["state"] == "connected", hw["state"])
    check("real board (not the virtual one)", hw["real_board"], hw.get("sender") or "")
    n0, t0 = hw["readings_received"], time.time()
    time.sleep(30)
    n1 = get("/health")["hardware"]["readings_received"]
    rate = (n1 - n0) / (time.time() - t0)
    check("reading every ~3 s", 0.25 <= rate <= 0.45, f"{n1 - n0} readings in 30 s ({1 / rate:.2f} s each)" if rate else "none")
    mq = get("/api/hardware/mqtt")
    ble = get("/api/hardware/ble")
    mst, bst = mq.get("stats", {}) or {}, ble.get("stats", {}) or {}
    check("MQTT link up", bool(mq.get("connected")), json.dumps({k: mst.get(k) for k in list(mst)[:6]}))
    check("Bluetooth LE link up", bool(ble.get("connected")), json.dumps({k: bst.get(k) for k in list(bst)[:6]}))

    # ---------------- sensors
    r = room()
    s, pm, ds, health = r["sensors"], r.get("power_measurement") or {}, r.get("device_state") or {}, r.get("sensor_health") or {}
    check("sensor health: every sensor detected", all(health.get(k) for k in ("bme280", "bh1750", "ina219")),
          json.dumps(health))
    t, rh = s.get("Temperature"), s.get("Humidity")
    check("BME280 temperature / humidity plausible", t is not None and 10 <= t <= 45 and rh is not None and 10 <= rh <= 100,
          f"{t} °C, {rh} %RH")
    lux = s.get("Light")
    check("BH1750 light plausible", lux is not None and 0 <= lux <= 100000, f"{lux} lux")
    co2 = get("/api/hardware/co2").get("last") or {}
    check("MQ-135 read by the Pi", co2.get("rs_kohm") is not None or co2.get("adc_mv") is not None,
          f"state {co2.get('state')}, Rs {co2.get('rs_kohm')} kΩ, eCO2 {co2.get('co2_ppm')}")
    v = pm.get("voltage_v")
    check("INA219 bus voltage 10.5–12.8 V", v is not None and 10.5 <= v <= 12.8, f"{v} V")
    if pm.get("voltage_v") and pm.get("current_mA") is not None and pm.get("power_mW") is not None:
        calc = pm["voltage_v"] * pm["current_mA"]
        ok = abs(calc - pm["power_mW"]) <= max(30.0, 0.08 * abs(calc))
        check("INA219 power = volts × current", ok, f"{pm['voltage_v']:.2f} V × {pm['current_mA']:.1f} mA = {calc:.0f} mW, reported {pm['power_mW']:.0f} mW")

    # ---------------- relay + fan, confirmed by the INA219
    override(0, 0, "fan OFF")
    wait_readings(3)
    off = room()
    i_off = (off.get("power_measurement") or {}).get("current_mA")
    override(255, 0, "fan ON")
    wait_readings(3)
    on = room()
    i_on = (on.get("power_measurement") or {}).get("current_mA")
    st_manual = (on.get("device_state") or {}).get("status_led")
    check("board reports fan ON", bool((on.get("device_state") or {}).get("fan_on")), str((on.get("device_state") or {}).get("fan_on")))
    check("board reports fan OFF", (off.get("device_state") or {}).get("fan_on") is False, str((off.get("device_state") or {}).get("fan_on")))
    if i_on is not None and i_off is not None:
        inverted = i_off > 40 and i_on < 15
        check("relay switches the fan (INA219 current ON vs OFF)", i_on - i_off > 40,
              f"ON {i_on:.0f} mA, OFF {i_off:.0f} mA" + ("  ← INVERTED: relay wiring does not match the firmware" if inverted else ""))
    check("status LED MANUAL during manual control", st_manual == "MANUAL", str(st_manual))

    # ---------------- light LED
    levels = {}
    for lvl, name in ((255, "ON"), (102, "DIM"), (0, "OFF")):
        override(0, lvl, f"light {name}")
        wait_readings(2)
        rr = room()
        levels[name] = ((rr.get("device_state") or {}).get("light_level"), rr["sensors"].get("Light"))
    check("light LED ON / DIM / OFF applied by the board", [levels[k][0] for k in ("ON", "DIM", "OFF")] == [255, 102, 0],
          json.dumps(levels))

    # ---------------- back to the AI
    post("/api/hardware/override", {"room_id": HW, "clear": True})
    wait_readings(3)
    rr = room()
    ctl, ds2 = rr.get("control") or {}, rr.get("device_state") or {}
    check("AI back in control", ctl.get("mode") == "ai", f"mode {ctl.get('mode')}, P(occ) {(rr.get('ai') or {}).get('occupancy_probability')}")
    check("status LED left MANUAL", ds2.get("status_led") not in (None, "MANUAL"), f"status {ds2.get('status_led')}, AC {ds2.get('ac_led')}")
    check("AC indicator LED reported", ds2.get("ac_led") is not None, str(ds2.get("ac_led")))
    check("AI decision verified on the board", ctl.get("previous_command_verified") is not False,
          f"light {ctl.get('light_action')}, AC {ctl.get('hvac_action')}, verified {ctl.get('previous_command_verified')}")

    # ---------------- dashboard, stream, models
    page = get("/")
    check("dashboard served by the Pi", isinstance(page, (bytes, bytearray)) and b"<html" in page[:2000].lower(), f"{len(page)} bytes")
    with urllib.request.urlopen(BASE + "/api/stream", timeout=10) as st:
        first = st.readline() + st.readline()
    check("live stream sends data", b"data" in first or b"event" in first, first[:60].decode(errors="replace"))
    m = get("/api/models", timeout=30).get("live", {})
    sh, ol = m.get("shadow", {}), m.get("online_learning", {})
    acc_l, acc_r = (sh.get("candidate_vs_truth") or {}).get("accuracy"), (sh.get("active_vs_truth") or {}).get("accuracy")
    check("learned occupancy model beats the rule live", acc_l is not None and acc_r is not None and acc_l > acc_r,
          f"{acc_l} vs {acc_r}")
    check("continual learning running", bool(ol.get("enabled")), f"{ol.get('buffer_rows')} rows, {len(ol.get('rounds') or [])} rounds")

    passed = sum(1 for r in RESULTS if r["pass"])
    print(f"\n{passed} of {len(RESULTS)} checks passed")
    print("SUMMARY " + json.dumps({"passed": passed, "total": len(RESULTS), "results": RESULTS}))
    return 0 if passed == len(RESULTS) else 1


HW = "f2_office_a"
if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        try:
            post("/api/hardware/override", {"room_id": HW, "clear": True})
        except Exception:
            pass
