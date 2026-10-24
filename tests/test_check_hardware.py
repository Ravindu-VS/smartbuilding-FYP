"""scripts/check_hardware.py against a real edge-brain process fed by the HTTP test sender.

The test sender is not the board, so the run must be labelled a software check; sensors the sender does not
send (INA226, LD2410C) must come out MISSING, never PASS; the actuator round trip through the manual override
must be verified and the override cleared afterwards."""
import json
import os
import subprocess
import sys
import time
import urllib.request

import pytest

from tests.conftest import free_port, wait_for

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _up(url):
    try:
        with urllib.request.urlopen(url + "/health", timeout=2) as r:
            return r.status == 200
    except OSError:
        return False


@pytest.fixture
def edge_with_sender(tmp_path):
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    env = dict(os.environ, API_PORT=str(port), API_HOST="127.0.0.1", EDGE_DB=str(tmp_path / "edge.sqlite3"),
               TWIN_WARMUP="0", PYTHONUNBUFFERED="1")
    edge = subprocess.Popen([sys.executable, os.path.join(ROOT, "raspberry_pi", "edge_brain.py")], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    sender = None
    try:
        assert wait_for(lambda: _up(url), timeout=60), "edge brain did not start"
        sender = subprocess.Popen([sys.executable, os.path.join(ROOT, "raspberry_pi", "esp32_test_sender.py"),
                                   "--url", url, "--interval", "0.5"], cwd=ROOT,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        yield url
    finally:
        for p in (sender, edge):
            if p is not None:
                p.terminate()
                try:
                    p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    p.kill()


def test_bench_check_with_test_sender_is_labelled_software_and_reports_missing(edge_with_sender, tmp_path):
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import check_hardware
    out = tmp_path / "bench"
    t0 = time.time()
    rc = check_hardware.main(["--api", edge_with_sender, "--seconds", "8", "--wait", "30", "--interval", "0.5", "--actuators",
                              "--out", str(out)])
    assert time.time() - t0 < 120
    runs = list(out.iterdir())
    assert len(runs) == 1
    res = json.loads((runs[0] / "result.json").read_text())
    by = {(c["group"], c["check"]): c["status"] for c in res["checks"]}
    assert res["physical"] is False and "software check" in res["kind"]
    assert by[("link", "board connected")] == "PASS"
    assert by[("BME280", "temperature (C)")] == "PASS" and by[("BH1750", "illuminance (lux)")] == "PASS"
    assert by[("SCD41", "CO2 (ppm, NDIR)")] == "PASS"
    assert by[("INA226", "bus voltage (V)")] == "MISSING" and by[("LD2410C", "presence (bool)")] == "MISSING"
    assert by[("actuators", "fan PWM reported by the board")] == "PASS"
    assert by[("actuators", "LED PWM reported by the board")] == "PASS"
    assert by[("actuators", "edge verified the previous command")] == "PASS"
    assert by[("actuators", "fan and LED off again")] == "PASS"
    assert by[("link", "report interval about 0.5 s")] == "PASS"
    assert res["verdict"] != "PASS" and rc == 1                # missing sensors are never a PASS
    assert res["last_reading"]["provenance"]["energy"] == "unavailable"   # no INA226 data -> no energy label
    def not_manual():
        with urllib.request.urlopen(edge_with_sender + "/api/rooms/current-state", timeout=5) as r:
            room = next(x for x in json.loads(r.read())["rooms"] if x["room_id"] == "f2_office_a")
        return (room.get("control") or {}).get("mode") not in (None, "manual")
    assert wait_for(not_manual, timeout=10)                       # the override was cleared
