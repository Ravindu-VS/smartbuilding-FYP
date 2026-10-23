"""
Safety and constraint layer between a controller and the actuators.

Every proposed action passes through validate() before it reaches the building
(simulated or real).  The rules are simple and stated; when one changes the
proposed action the reason is recorded in the decision's explanation.

  R1 valid values      light in the room's options; HVAC in ECO/LOW/NORMAL;
                       comfort set-point clamped to 22..27 C.
  R2 equipment cooling rooms flagged equipment_cooled (the server room) keep the
                       AC in NORMAL at 24 C at all times, whatever the occupancy.
  R3 heat-stress guard if the room is probably occupied (P >= 0.6) and the air
                       is >= 32 C, the AC may not stay off.
  R4 indoor air        if the CO2 reading is above 1000 ppm while the room is
                       probably occupied, the fresh-air boost fan runs; it stops
                       below 800 ppm (hysteresis).  This rule is the only
                       ventilation control in the system; it is not part of the
                       multi-objective optimisation.
The same layer is applied to the controller under test and to the schedule
baseline, so both face identical constraints.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

LIGHT_OPTIONS = ("OFF", "DIM", "ON")
HVAC_OPTIONS = ("ECO", "LOW", "NORMAL")
SETPOINT_RANGE = (22.0, 27.0)
CO2_ON_PPM, CO2_OFF_PPM = 1000.0, 800.0
HEAT_GUARD_C = 32.0


@dataclass
class ValidatedAction:
    light: str
    hvac: str
    setpoint: Optional[float]
    vent_boost: bool
    accepted: bool                      # True when nothing was changed
    notes: List[str] = field(default_factory=list)


class SafetyLayer:
    def __init__(self, equipment_cooled: Dict[str, bool], light_options: Optional[Dict[str, tuple]] = None):
        self.equipment_cooled = equipment_cooled
        self.light_options = light_options or {}
        self._boost: Dict[str, bool] = {}

    def validate(self, room_id: str, light: str, hvac: str, setpoint: Optional[float],
                 p_occ: Optional[float], temperature: Optional[float], co2: Optional[float]) -> ValidatedAction:
        notes: List[str] = []
        opts = self.light_options.get(room_id, LIGHT_OPTIONS)
        if light not in opts:
            notes.append(f"R1: light '{light}' not available here -> OFF")
            light = "OFF"
        if hvac not in HVAC_OPTIONS:
            notes.append(f"R1: HVAC '{hvac}' invalid -> ECO")
            hvac, setpoint = "ECO", None
        if hvac == "NORMAL" and setpoint is not None:
            lo, hi = SETPOINT_RANGE
            if not lo <= setpoint <= hi:
                notes.append(f"R1: set-point {setpoint:.1f} C clamped to {lo:.0f}..{hi:.0f} C")
                setpoint = min(hi, max(lo, setpoint))
        if hvac != "NORMAL":
            setpoint = None
        if self.equipment_cooled.get(room_id) and not (hvac == "NORMAL" and (setpoint or 24.0) <= 24.0):
            notes.append("R2: equipment room - AC kept on at 24 C")
            hvac, setpoint = "NORMAL", 24.0
        if (hvac == "ECO" and p_occ is not None and p_occ >= 0.6
                and temperature is not None and temperature >= HEAT_GUARD_C):
            notes.append(f"R3: {temperature:.1f} C with people present - AC switched to NORMAL 26 C")
            hvac, setpoint = "NORMAL", 26.0
        boost = self._boost.get(room_id, False)
        if co2 is not None:
            if not boost and co2 > CO2_ON_PPM and (p_occ or 0.0) >= 0.5:
                boost = True
                notes.append(f"R4: CO2 {co2:.0f} ppm > {CO2_ON_PPM:.0f} - fresh-air fan ON")
            elif boost and co2 < CO2_OFF_PPM:
                boost = False
                notes.append(f"R4: CO2 {co2:.0f} ppm < {CO2_OFF_PPM:.0f} - fresh-air fan OFF")
        self._boost[room_id] = boost
        accepted = not any(n.startswith(("R1", "R2", "R3")) for n in notes)
        return ValidatedAction(light, hvac, setpoint, boost, accepted, notes)

    def reset(self):
        self._boost.clear()


# ---------------------------------------------------------------------- #
# Input checks and fail-safe fallback (sensor faults, stale data, policy failure)
# ---------------------------------------------------------------------- #
import math as _math
from datetime import datetime as _datetime

PLAUSIBLE = {"temperature": (5.0, 50.0), "humidity": (0.0, 100.0), "light": (0.0, 100000.0),
             "co2": (300.0, 10000.0)}
REQUIRED_INPUTS = ("temperature", "humidity", "light")
HOLD_S = 180.0          # a missing value may be replaced by the last valid one for at most 3 min
STALE_S = 300.0         # readings older than 5 min are stale: the controller is not trusted with them
STUCK_S = 1800.0        # a temperature reading unchanged to the last digit for 30 min is flagged stuck


class InputGuard:
    """
    Checks every reading before a controller sees it.
      - a value outside its plausible range is rejected (treated as missing);
      - a missing value is replaced by the last valid one for at most HOLD_S
        (flagged "held"); after that it stays missing;
      - a temperature that has not changed at all for STUCK_S is flagged "stuck";
      - readings older than STALE_S (no delivery, e.g. a network outage) are "stale".
    `check` returns the cleaned values and the list of problems; the caller decides
    (GuardedController falls back to the rule-based controller on any problem with
    a required input).
    """

    def __init__(self, hold_s: float = HOLD_S, stale_s: float = STALE_S, stuck_s: float = STUCK_S):
        self.hold_s, self.stale_s, self.stuck_s = hold_s, stale_s, stuck_s
        self._last: Dict[str, Dict[str, tuple]] = {}
        self._temp_since: Dict[str, tuple] = {}

    def check(self, room_id: str, values: Dict[str, Optional[float]], now: _datetime,
              age_s: float = 0.0) -> tuple:
        cleaned: Dict[str, Optional[float]] = {}
        problems: List[str] = []
        last = self._last.setdefault(room_id, {})
        for key, (lo, hi) in PLAUSIBLE.items():
            v = values.get(key)
            ok = v is not None and isinstance(v, (int, float)) and _math.isfinite(v) and lo <= v <= hi
            if v is not None and not ok:
                problems.append(f"{key} implausible ({v})")
            if ok:
                cleaned[key] = float(v)
                last[key] = (float(v), now)
            elif key in last and (now - last[key][1]).total_seconds() <= self.hold_s:
                cleaned[key] = last[key][0]
                problems.append(f"{key} held")
            else:
                cleaned[key] = None
                if key in REQUIRED_INPUTS:
                    problems.append(f"{key} missing")
        t = cleaned.get("temperature")
        if t is not None and values.get("temperature") is not None:
            prev = self._temp_since.get(room_id)
            if prev is None or prev[0] != values["temperature"]:
                self._temp_since[room_id] = (values["temperature"], now)
            elif (now - prev[1]).total_seconds() >= self.stuck_s:
                problems.append("temperature stuck")
        if age_s > self.stale_s:
            problems.append(f"stale ({age_s:.0f} s)")
        return cleaned, problems


def blocking(problems: List[str]) -> List[str]:
    """Problems that make the inputs unfit for a learned/optimising controller."""
    return [p for p in problems if p.endswith(("missing", "stuck")) or p.startswith("stale")]


class GuardedController:
    """
    Runs the primary controller only when its inputs pass InputGuard and it returns a
    valid decision; otherwise uses the fallback (the rule-based schedule) and says why:
      F1 inputs missing / stuck / stale     -> fallback
      F2 the primary raised an exception     -> fallback
      F3 the primary returned an invalid decision (unknown action, non-finite set-point)
    The decision then goes through SafetyLayer.validate like any other.
    """

    def __init__(self, primary, fallback):
        self.primary, self.fallback = primary, fallback
        self.name = f"Guarded[{getattr(primary, 'name', type(primary).__name__)}]"
        self.counts = {"F1": 0, "F2": 0, "F3": 0}
        self.last_error: Optional[str] = None

    def decide(self, obs, problems: Optional[List[str]] = None):
        bad = blocking(problems or [])
        if bad:
            self.counts["F1"] += 1
            return self._fallback(obs, "F1 inputs not usable: " + ", ".join(bad))
        try:
            d = self.primary.decide(obs)
        except Exception as e:          # report, never guess an action
            self.counts["F2"] += 1
            self.last_error = f"{type(e).__name__}: {e}"
            return self._fallback(obs, f"F2 controller failed ({self.last_error})")
        sp = getattr(d, "setpoint_c", None)
        if (getattr(d, "light_action", None) not in LIGHT_OPTIONS or getattr(d, "hvac_action", None) not in HVAC_OPTIONS
                or (sp is not None and not _math.isfinite(sp))):
            self.counts["F3"] += 1
            return self._fallback(obs, "F3 invalid decision from the controller")
        return d

    def _fallback(self, obs, why: str):
        d = self.fallback.decide(obs)
        d.reason = f"FAIL-SAFE ({why}); rule-based: {d.reason}"
        d.control_mode = d.control_mode
        return d
