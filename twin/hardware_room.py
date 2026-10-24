"""
The AI controller for the real room (Office A, the ESP32-S3 sensor node).

The same estimator, controller and safety layer as the simulated rooms, run in
real time on the board's readings (one decision per reading, about every 3 s):

    presence (PIR, or PIR + mmWave when the LD2410C is fitted)  -> seconds since motion
    CO2 from the SCD41 (NDIR) only; the MQ-2 is a combustible-gas sensor and its
        "estimate" is never used as CO2 (missing CO2 = no CO2 evidence)
    -> FusionEstimator (PIR + CO2)  -> MultiObjectiveController  -> SafetyLayer
    -> actuator commands for the board:
        fan  (stands in for the room's AC):   ECO 0, LOW 100, NORMAL 26/25/24 C -> 150/200/255
        LED  (stands in for the lighting):     OFF 0, DIM 102 (40 %), ON 255
        servo (fresh-air damper):              90 deg while the CO2 rule asks for fresh air, else 0
    vacancy rule: with presence sensors fitted, no PIR/mmWave detection for 15 min -> lights OFF and AC ECO
        (CO2 stays high for hours after people leave; replaying real office data showed CO2 evidence alone
        kept the lights on in most empty minutes - experiment 11)

The controller plans for the full-size Office A of the building model (its area,
lighting and AC sizes).  The board's fan does not cool the room, so the
controller's temperature prediction is not expected to be borne out by the
board's thermometer; that is stated in each explanation.  The outdoor temperature
is not measured: an assumed value (OUTDOOR_TEMP_C, default 30 C) is used and
reported as assumed.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from twin.controllers import FusionEstimator, MultiObjectiveController, Observation, ScheduleController
from twin.live import _reasoning
from twin.safety import SafetyLayer
from twin.spec import RoomSpec

TUNED_WEIGHTS = {"alpha": 1.0, "beta": 3.0, "gamma": 0.1, "light_margin": 0.03}
LED_PWM = {"OFF": 0, "DIM": 102, "ON": 255}
LIGHT_LEVEL = {"OFF": 0.0, "DIM": 0.4, "ON": 1.0}


FAN_PWM_NORMAL = {26.0: 150, 25.0: 200, 24.0: 255}


def fan_pwm(hvac: str, setpoint: Optional[float]) -> int:
    if hvac == "LOW":
        return 100
    if hvac == "NORMAL":
        sp = 24.0 if setpoint is None else float(setpoint)
        if sp in FAN_PWM_NORMAL:
            return FAN_PWM_NORMAL[sp]
        return 255 if sp < 24.0 else 150
    return 0


def _fmt(hvac: str, sp: Optional[float]) -> str:
    return f"{hvac} {sp:.0f} C" if hvac == "NORMAL" and sp is not None else hvac


class HardwareRoomController:
    VACANCY_S = 900.0     # lights off / AC to ECO after 15 min without any PIR or mmWave detection (ASHRAE 90.1-2016: timeout <= 20 min)

    def __init__(self, spec: RoomSpec, led_lux_full: Optional[float] = None, outdoor_c: float = 30.0,
                 vacancy_s: Optional[float] = None):
        self.spec = spec
        self.vacancy_s = float(self.VACANCY_S if vacancy_s is None else vacancy_s)
        self.room_id = spec.room_id
        self.outdoor_c = float(outdoor_c)
        self.led_lux_full = led_lux_full if led_lux_full and led_lux_full > 0 else None
        self._build()

    def _build(self) -> None:
        ov = dict(self.spec.controller_overrides)
        if self.led_lux_full:
            ov["lighting_lux_full"] = float(self.led_lux_full)
        self.lux_full = ov["lighting_lux_full"]
        self.estimator = FusionEstimator()
        self.controller = MultiObjectiveController(self.estimator, room_overrides={self.room_id: ov},
                                                   **TUNED_WEIGHTS)
        self.safety = SafetyLayer({self.room_id: False})
        # AI off: the conventional schedule of this room type, on real (local) time
        self.schedule = ScheduleController(room_hours={self.room_id: self.spec.schedule_hours})
        self.cmd = {"light": "OFF", "hvac": "ECO", "sp": None, "vent": False}
        self.last_presence: Optional[datetime] = None
        self._pending: List[tuple] = []
        self._last_notes: List[str] = []
        self.decisions = 0

    def set_led_calibration(self, lux_full: Optional[float]) -> None:
        """New LED calibration: the controller is rebuilt with it (its learning restarts)."""
        self.led_lux_full = lux_full if lux_full and lux_full > 0 else None
        self._build()

    # ------------------------------------------------------------------ #
    def step(self, now: datetime, temperature: Optional[float], humidity: Optional[float],
             lux: Optional[float], co2: Optional[float], humidity_ratio: Optional[float],
             presence: Optional[bool], rf_probability: Optional[float] = None, ai_enabled: bool = True) -> Dict:
        if presence:
            self.last_presence = now
        since = None if self.last_presence is None else max(0.0, (now - self.last_presence).total_seconds())
        missing = [n for n, v in (("temperature", temperature), ("humidity", humidity), ("light", lux)) if v is None]
        prev = dict(self.cmd)
        obs = Observation(
            room_id=self.room_id, room_type=self.spec.room_type, timestamp=now,
            temperature=temperature if temperature is not None else 25.0,
            humidity=humidity if humidity is not None else 60.0,
            light_lux=lux if lux is not None else 0.0, co2=co2,
            humidity_ratio=humidity_ratio if humidity_ratio is not None else 0.012,
            seconds_since_motion=since, current_light=prev["light"], current_hvac=prev["hvac"],
            current_setpoint=prev["sp"], outdoor_temperature=self.outdoor_c, hvac_power_w=None)
        costs: Dict = {}
        would = None
        if missing:
            # Without temperature/humidity/light the optimiser cannot be evaluated:
            # a stated fallback - lights follow presence, AC unchanged.
            p = self.estimator.probability(obs)
            light = "ON" if p >= 0.5 else "OFF"
            hvac, sp = prev["hvac"], prev["sp"]
            mode = "OCCUPIED" if p >= 0.6 else ("STANDBY" if p >= 0.2 else "EMPTY")
            reason = f"{', '.join(missing)} missing: fallback rule (lights follow presence, AC held)"
            p_ac = p_fut = None
        else:
            d = self.controller.decide(obs)       # the AI always runs (when off it only observes)
            p, light, hvac, sp, mode, reason, costs = (d.occupancy_probability, d.light_action, d.hvac_action,
                                                       d.setpoint_c, d.control_mode, d.reason, d.costs or {})
            p_ac, p_fut = costs.get("p_ac"), costs.get("p_future")
        # Vacancy rule (presence sensors fitted): CO2 decays for hours after people leave, so CO2 evidence alone
        # must not keep the lights or the AC on. Found by replaying real office data (experiment 11).
        vacant = presence is not None and (since is None or since > self.vacancy_s)
        if ai_enabled and vacant and (light != "OFF" or hvac != "ECO"):
            light, hvac, sp = "OFF", "ECO", None
            mode = "EMPTY"
            reason = (f"vacancy rule: no PIR/mmWave detection for {int(self.vacancy_s // 60)} min"
                      + (f" (last {since / 60:.0f} min ago)" if since is not None else " (none yet)")
                      + "; lights off, AC to ECO - CO2 alone does not keep them on")
        if not ai_enabled:
            if not missing:
                would = {"light_action": light, "hvac_action": hvac, "setpoint_c": sp, "reason": reason,
                         "reasoning": _reasoning(costs), "basis": "the AI observing this room (not applied)"}
            ds = self.schedule.decide(obs)
            light, hvac, mode = ds.light_action, ds.hvac_action, ds.control_mode
            sp = self.spec.design_setpoint if hvac == "NORMAL" else None
            start_h, end_h, wd = self.spec.schedule_hours
            fmt = lambda h: f"{int(h):02d}:{int(round((h % 1) * 60)):02d}"
            reason = (f"AI control is OFF: conventional schedule {fmt(start_h)}-{fmt(end_h)}"
                      + (" on weekdays" if wd else " every day"))
        va = self.safety.validate(self.room_id, light, hvac, sp, p, temperature, co2)
        new = {"light": va.light, "hvac": va.hvac, "sp": va.setpoint, "vent": va.vent_boost}
        event = None
        notes_changed = va.notes != self._last_notes
        self._last_notes = list(va.notes)
        if new != prev or (va.notes and notes_changed):
            event = self._event(now, obs, temperature, lux, co2, since, p, p_ac, p_fut, rf_probability,
                                (light, hvac, sp), va, prev, new, costs if ai_enabled else {}, missing,
                                None if ai_enabled else reason)
        self.cmd = new
        self.decisions += 1
        ai = {"occupancy_probability": round(p, 4), "predicted_occupancy": int(p >= 0.5 and not vacant),
              "vacant": vacant,
              "confidence": round(max(p, 1 - p), 4), "method": "fusion_pir_co2",
              "p_ac": round(p_ac, 4) if p_ac is not None else None,
              "p_future": round(p_fut, 4) if p_fut is not None else None,
              "seconds_since_presence": round(since, 1) if since is not None else None,
              "co2_used": co2 is not None,
              "random_forest_probability": round(rf_probability, 4) if rf_probability is not None else None}
        control = {"light_action": new["light"], "hvac_action": new["hvac"], "setpoint_c": new["sp"],
                   "vent_boost": new["vent"], "control_mode": mode, "controller": "mo" if ai_enabled else "schedule",
                   "mode": "ai" if ai_enabled else "conventional", "ai_would": would, "reason": reason,
                   "safety_notes": va.notes, "t_pred": round(costs["t_pred"], 2) if "t_pred" in costs else None,
                   "reasoning": _reasoning(costs) if ai_enabled else None,
                   "fan_speed": fan_pwm(new["hvac"], new["sp"]), "light_level": LED_PWM[new["light"]],
                   "servo_angle": 90 if new["vent"] else 0}
        return {"ai": ai, "control": control, "event": event}

    def _event(self, now, obs, temperature, lux, co2, since, p, p_ac, p_fut, p_rf, proposed, va, prev, new,
               costs, missing, conventional_reason: Optional[str] = None) -> Dict:
        changes = []
        if new["light"] != prev["light"]:
            changes.append(f"LED (lights) {prev['light']} -> {new['light']}")
        if new["hvac"] != prev["hvac"] or new["sp"] != prev["sp"]:
            changes.append(f"fan (AC) {_fmt(prev['hvac'], prev['sp'])} -> {_fmt(new['hvac'], new['sp'])}")
        if new["vent"] != prev["vent"]:
            changes.append(f"damper {'open' if new['vent'] else 'closed'}")
        own = self.lux_full * LIGHT_LEVEL[prev["light"]]
        daylight = max(0.0, (lux or 0.0) - own)
        why = [f"occupancy probability {p:.2f} now" + (f", {p_fut:.2f} over the next 30 min" if p_fut is not None else "")]
        if since is not None:
            why.append(f"last presence detected {since:.0f} s ago")
        else:
            why.append("no presence detected since start")
        why.append(f"CO2 {co2:.0f} ppm (SCD41)" if co2 is not None else "no CO2 reading (SCD41 absent or not ready)")
        if new["light"] != prev["light"] and lux is not None:
            why.append(f"daylight about {daylight:.0f} lux vs 300 lux target"
                       + ("" if self.led_lux_full else " (LED not calibrated: design 400 lux assumed)"))
        if "t_pred" in costs and (new["hvac"] != prev["hvac"] or new["sp"] != prev["sp"]):
            why.append(f"controller's model predicts {costs['t_pred']:.1f} C in 30 min for the full-size room "
                       f"(the board's fan does not cool the room)")
        if missing:
            why.append(f"{', '.join(missing)} missing: fallback rule used")
        if conventional_reason:
            why = [conventional_reason + " (occupancy is not considered)"]
        return {
            "kind": "decision", "source": "hardware", "sim_time": None,
            "real_time": now.isoformat(timespec="seconds"), "room_id": self.room_id, "room_name": self.spec.name,
            "floor_id": self.spec.floor_id, "controller": "schedule" if conventional_reason else "mo",
            "mode": "conventional" if conventional_reason else "ai",
            "summary": "; ".join(changes) if changes else "safety rule active",
            "why": why,
            "observed": {"temperature": temperature, "humidity": obs.humidity if not missing else None,
                         "light_lux": lux, "daylight_lux_est": round(daylight), "co2": co2,
                         "pir_seconds": round(since, 1) if since is not None else None,
                         "outdoor_c": self.outdoor_c, "outdoor_assumed": True,
                         "p_occupancy": round(p, 3), "p_ac": round(p_ac, 3) if p_ac is not None else None,
                         "p_future": round(p_fut, 3) if p_fut is not None else None,
                         "p_random_forest": round(p_rf, 3) if p_rf is not None else None},
            "simulator_truth": None,
            "proposed": {"light": proposed[0], "hvac": proposed[1], "setpoint": proposed[2]},
            "safety": {"accepted": va.accepted, "notes": va.notes},
            "validated": dict(new), "previous": dict(prev),
            "expected": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in costs.items()
                         if k in ("t_pred", "t_hold", "energy_kwh_horizon", "J_light", "J_ac",
                                  "J_light_options", "J_ac_options", "visual_discomfort_h", "thermal_discomfort_h")},
            "outcome": None,
        }

    def due_outcomes(self, now: datetime, temperature, lux, presence, co2) -> None:
        keep = []
        for due, ev in self._pending:
            if now >= due:
                ev["outcome"] = {"after_min": 15, "temperature": temperature, "lux": lux, "presence": presence,
                                 "co2": co2, "note": "real room: the fan is a stand-in for the AC"}
            else:
                keep.append((due, ev))
        self._pending = keep[-200:]

    def track(self, ev: Dict, now: datetime) -> None:
        self._pending.append((now + timedelta(minutes=15), ev))
