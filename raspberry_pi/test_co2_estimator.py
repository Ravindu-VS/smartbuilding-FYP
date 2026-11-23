"""MQ-135 CO2 estimate (raspberry_pi/co2_estimator.py)."""
import pytest

from raspberry_pi.co2_estimator import PARA, Mq135Co2Estimator, correction_factor


def make(tmp_path, **kw):
    return Mq135Co2Estimator(str(tmp_path / "cal.json"), warmup_s=0, **kw)


def test_resistance_follows_the_load_resistor_divider(tmp_path):
    est = make(tmp_path, vcc_mv=5000, rl_kohm=1.0)
    assert est.resistance(1000) == pytest.approx(4.0)        # 1 k * (5000 - 1000) / 1000
    est.divider = 1.5
    assert est.resistance(1000) == pytest.approx(1.0 * (5000 - 1500) / 1500)
    assert est.resistance(0) is None


def test_curve_round_trip_and_direction(tmp_path):
    est = make(tmp_path)
    est.r0 = est.r0_for(10.0, 420)
    assert est.ppm(10.0) == pytest.approx(420)
    assert est.ppm(5.0) > 420 > est.ppm(20.0)               # lower Rs = more gas
    assert est.r0_for(10.0, PARA) == pytest.approx(10.0)


def test_baseline_takes_cleanest_air_as_reference(tmp_path):
    est = make(tmp_path)
    t0 = 1_800_000_000
    clean = est.update(400, 25, 60, uptime_s=4000, now=t0)              # high Rs: clean air
    for i in range(6):
        out = est.update(900, 25, 60, uptime_s=4000, now=t0 + 3 * (i + 1))   # lower Rs: occupied
    assert clean["state"] == "provisional"
    assert out["co2_ppm"] > 600
    assert est.status()["r0_source"] == "abc"


def test_warmup_and_saturation_give_no_estimate(tmp_path):
    est = Mq135Co2Estimator(str(tmp_path / "c.json"), warmup_s=1800)
    assert est.update(800, 25, 60, uptime_s=60)["state"] == "warming_up"
    assert est.update(3200, 25, 60, uptime_s=4000)["state"] == "adc_saturated"
    assert est.update(None, 25, 60)["co2_ppm"] is None


def test_manual_calibration_persists_and_overrides_abc(tmp_path):
    est = make(tmp_path)
    est.update(600, 25, 60, uptime_s=4000)
    rs = est.last["rs_corrected_kohm"]
    est.calibrate_now(rs, 420, manual=True)
    again = Mq135Co2Estimator(str(tmp_path / "cal.json"), warmup_s=0)
    assert again.r0_source == "manual" and again.r0 == pytest.approx(est.r0)
    again.update(300, 25, 60, uptime_s=4000)                  # cleaner air must not move a manual R0
    assert again.r0 == pytest.approx(est.r0)


def test_correction_factor_is_one_near_reference_conditions():
    assert correction_factor(20, 33) == pytest.approx(1.0, abs=0.03)
    assert correction_factor(None, 50) == 1.0


def test_calibration_saved_for_another_circuit_is_set_aside(tmp_path):
    est = make(tmp_path, divider=1.0)
    est.update(600, 25, 60, uptime_s=4000)
    est.calibrate_now(est.last["rs_corrected_kohm"], 420, manual=True)
    same = make(tmp_path, divider=1.0)
    assert same.r0 == pytest.approx(est.r0) and same.discarded_calibration is None
    soldered = make(tmp_path, divider=25 / 15)              # the 10k/15k divider was added
    assert soldered.r0 is None and soldered.r0_source is None
    assert soldered.divider == pytest.approx(25 / 15)
    assert soldered.discarded_calibration["r0_source"] == "manual"
