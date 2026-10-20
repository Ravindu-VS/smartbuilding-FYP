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
