"""
Edge brain /metrics (Prometheus) and the shared JSON log format.

    python -m pytest tests/test_observability.py -q
"""
import io
import json
import logging
import os
import tempfile

import pytest

pytest.importorskip("prometheus_client")
from prometheus_client.parser import text_string_to_metric_families  # noqa: E402

import raspberry_pi.edge_brain as eb                                   # noqa: E402
from raspberry_pi.test_edge_brain import BOARD_READING, new_brain      # noqa: E402
from sbops.logs import JsonFormatter                                   # noqa: E402

eb.MQ135_CALIBRATION_FILE = os.path.join(tempfile.mkdtemp(prefix="mq135-obs-"), "mq135_calibration.json")


def _samples(text):
    out = {}
    for fam in text_string_to_metric_families(text):
        for s in fam.samples:
            out.setdefault(s.name, []).append((s.labels, s.value))
    return out


@pytest.fixture(scope="module")
def client():
    brain = new_brain()
    brain.tick(1.0)
    brain.inject_hardware_data(dict(BOARD_READING))
    brain.tick(1.0)
    old, eb.brain = eb.brain, brain
    yield eb.app.test_client()
    eb.brain = old


def test_metrics_endpoint_is_prometheus_text(client):
    r = client.get("/metrics")
    assert r.status_code == 200
    assert r.mimetype == "text/plain"
    m = _samples(r.get_data(as_text=True))
    assert m["sb_edge_up"][0][1] == 1.0
    assert m["sb_edge_ai_enabled"][0][1] in (0.0, 1.0)


def test_room_metrics_are_labelled_physical_or_simulated(client):
    m = _samples(client.get("/metrics").get_data(as_text=True))
    temps = m["sb_room_temperature_celsius"]
    sources = {lab["source"] for lab, _ in temps}
    assert sources == {"physical", "simulated"}         # BOARD_READING comes from the real board's sender id
    phys = [(lab, v) for lab, v in temps if lab["source"] == "physical"]
    assert len(phys) == 1 and phys[0][0]["room_id"] == eb.HARDWARE_ROOM_ID
    assert phys[0][1] == pytest.approx(BOARD_READING["temperature"])
    rooms = {lab["source"]: v for lab, v in m["sb_twin_rooms"]}
    assert rooms == {"physical": 1.0, "simulated_board": 0.0, "simulated": 25.0}


def test_ina219_values_are_converted_to_si_units(client):
    m = _samples(client.get("/metrics").get_data(as_text=True))
    power = [v for lab, v in m["sb_room_power_watts"] if lab["source"] == "physical"]
    assert power == [pytest.approx(BOARD_READING["measured_power_mW"] / 1000)]
    assert m["sb_room_current_amperes"][0][1] == pytest.approx(BOARD_READING["measured_current_mA"] / 1000)
    assert m["sb_room_bus_voltage_volts"][0][1] == pytest.approx(BOARD_READING["measured_voltage_v"])
    # the MQ-135 is exported as its raw response in mV, never as a ppm figure
    assert "sb_room_mq135_millivolts" in m
    assert not any("ppm" in name for name in m)


def test_board_link_metrics(client):
    m = _samples(client.get("/metrics").get_data(as_text=True))
    conn = {lab["room_id"]: v for lab, v in m["sb_board_connected"]}
    assert conn[eb.HARDWARE_ROOM_ID] == 1.0
    assert m["sb_room_motion"] == [({"room_id": eb.HARDWARE_ROOM_ID, "source": "physical"}, 1.0)]     # PIR from BOARD_READING
    assert m["sb_board_readings_total"][0][1] >= 1


def test_request_counter_and_latency_are_recorded(client):
    client.get("/health")
    client.get("/health")
    m = _samples(client.get("/metrics").get_data(as_text=True))
    health = [v for lab, v in m["sb_edge_http_requests_total"]
              if lab["endpoint"] == "/health" and lab["status"] == "200"]
    assert health and health[0] >= 2
    assert any(lab.get("endpoint") == "/health" for lab, _ in m["sb_edge_http_request_duration_seconds_count"])


def test_metrics_without_a_brain_reports_down():
    old, eb.brain = eb.brain, None
    try:
        m = _samples(eb.app.test_client().get("/metrics").get_data(as_text=True))
        assert m["sb_edge_up"][0][1] == 0.0
    finally:
        eb.brain = old


def test_json_log_line_has_service_level_and_context_and_redacts_secrets():
    stream = io.StringIO()
    h = logging.StreamHandler(stream)
    h.setFormatter(JsonFormatter("ingestion"))
    log = logging.getLogger("obs-test")
    log.handlers[:] = [h]
    log.propagate = False
    log.warning("rejected reading", extra={"room_id": "f2_office_a", "msg_id": "abc"})
    line = json.loads(stream.getvalue())
    assert line["service"] == "ingestion" and line["level"] == "WARNING"
    assert line["room_id"] == "f2_office_a" and line["msg"] == "rejected reading"
    assert line["ts"].endswith("Z")
    from sbops.logs import redact
    assert redact({"mqtt_password": "x", "room_id": "r"}) == {"mqtt_password": "***", "room_id": "r"}


def test_a_simulated_board_is_never_labelled_physical():
    brain = new_brain()
    brain.tick(1.0)
    brain.inject_hardware_data(dict(BOARD_READING, source="mqtt_device_sim"))
    brain.tick(1.0)
    old, eb.brain = eb.brain, brain
    try:
        m = _samples(eb.app.test_client().get("/metrics").get_data(as_text=True))
    finally:
        eb.brain = old
    sources = {lab["source"] for lab, _ in m["sb_room_temperature_celsius"]}
    assert sources == {"simulated_board", "simulated"}
    assert {lab["source"]: v for lab, v in m["sb_twin_rooms"]}["physical"] == 0.0
