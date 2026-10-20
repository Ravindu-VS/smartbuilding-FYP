"""
Copied from the thesis code (D:\\...\\Project, simulation/room_physics.py, commit eb82674,
unchanged at 08427b4) and generalised for the 26-room building:
  * geometry per room (exposed wall area, window area, roof area) instead of the
    fixed "2 external 6 m walls + roof" of the thesis's 36 m2 office;
  * per-room lighting, AC capacity, plug loads, occupant gains and daylight factor
    (from twin/spec.py), with the thesis values as defaults;
  * disturbance inputs for the demonstration scenarios: extra internal heat gain
    (W) and an extra CO2 source (m3/s), and a fresh-air boost fan (extra ACH)
    that the indoor-air-quality rule can switch on.
With no geometry/overrides the equations and numbers are exactly the thesis's
(checked by twin/test_twin.py against values computed with the thesis code).

Room physics for the digital twin: the five-resistance, one-capacitance
(5R1C) thermal network of the ISO 13790 simple hourly method, CO2 and
moisture mass balances, lighting and plug loads, and a split-type air
conditioner with a proportional thermostat.

Structure of the thermal network (per room):

    outdoor --[H_ve]-------------- AIR (theta_a)  <- convective gains, AC, adjacent rooms
                                    |
                                  [H_is]
                                    |
    outdoor --[H_w windows]------ SURFACE (theta_s)  <- part of radiant + solar gains
                                    |
                                  [H_ms]
                                    |
    sol-air --[H_em walls/roof]-- MASS (theta_m, C_m)  <- part of radiant + solar gains

As in ISO 13790 the surface node has no capacity (it is solved algebraically
each step) and theta_s is used as the mean radiant temperature; the operative
temperature is 0.3 theta_a + 0.7 theta_s.  Unlike the standard, the air node
carries a small capacity (room air + furnishings) so the thermostat can be
integrated explicitly.  Coupling and mass values are those of the "medium"
construction class; the sol-air temperatures include the standard's long-wave
radiation to the sky (h_r = 4.5 W/m2K, 11 K air-sky difference, form factor 1
for the roof and 0.5 for walls).  Envelope U-values, ventilation rates,
internal gains and the AC data are stated assumptions (see DEFAULT_PARAMS)
chosen to represent a small office in Colombo, not measured properties of a
real building.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Optional

RHO_AIR = 1.2        # kg/m3
CP_AIR = 1005.0      # J/(kg K)
H_FG = 2.45e6        # J/kg latent heat of vaporisation
CO2_OUTDOOR_PPM = 420.0

DEFAULT_PARAMS: Dict[str, float] = {
    # envelope (assumed typical values for a single-storey brick building)
    "u_wall": 2.0,               # W/m2K, plastered brick wall
    "u_roof": 1.0,               # W/m2K, roof slab with ceiling
    "u_window": 5.7,             # W/m2K, single clear glazing
    "u_internal": 2.0,           # W/m2K, internal partition
    "window_area": 2.4,          # m2 per room
    "shgc": 0.7,                 # solar heat gain coefficient of the glazing
    "absorptance": 0.6,          # opaque surfaces, for sol-air temperature
    "h_out": 20.0,               # W/m2K outside surface coefficient
    "external_walls": 2,         # number of 6 m x 3 m walls exposed to outdoors
    "has_roof": 1,
    # ISO 13790 "medium" class and 5R1C coefficients
    "cm_per_m2": 165000.0,       # J/K per m2 floor
    "am_factor": 2.5,            # effective mass area A_m = factor x floor area
    "at_factor": 4.5,            # internal surface area A_t = factor x floor area
    "h_ms": 9.1,                 # W/m2K, mass - surface
    "h_is": 3.45,                # W/m2K, surface - air
    "h_r_sky": 4.5,              # W/m2K, external radiative coefficient (5 x emissivity 0.9)
    "dt_sky": 11.0,              # K, average air - sky temperature difference
    "air_capacity_multiplier": 3.0,  # furniture/contents added to air node
    # ventilation
    "ach_infiltration": 0.5,     # 1/h, always
    "ach_mechanical": 1.0,       # 1/h outdoor air from a fresh-air fan interlocked with the AC
    # occupants (seated, light office work)
    "occupant_sensible_w": 75.0,
    "occupant_latent_w": 55.0,
    "occupant_co2_m3s": 5.2e-6,  # 0.0052 L/s CO2 per person
    # fresh-air boost fan (IAQ rule), extra outdoor air when on
    "ach_boost": 2.0,            # 1/h
    "boost_fan_w_per_m3h": 0.3,  # W per m3/h of extra air (specific fan power ~1 kJ/m3)
    # lighting
    "lighting_w": 280.0,         # installed LED power (about 8 W/m2)
    "lighting_lux": 400.0,       # illuminance at desk at full output
    "daylight_factor": 0.01,     # sensor position, fraction of outdoor illuminance
    # air conditioner (split unit, 18,000 BTU/h = 5.3 kW cooling)
    "ac_cool_capacity_w": 5275.0,
    "ac_heat_capacity_w": 0.0,   # no heating in Colombo
    "ac_cop_cool": 3.2,
    "ac_fan_w": 40.0,
    "ac_shr": 0.75,              # sensible heat ratio of the coil
    "ac_coil_w": 0.0095,         # kg/kg, coil saturation humidity ratio
    "setpoint_comfort": 24.0,    # degC
    "setpoint_setback": 27.0,    # degC
    "proportional_band": 1.0,    # K
}

# plug loads by room type: (base W, W per occupant present)
PLUG_LOADS = {
    "office": (40.0, 120.0),
    "meeting": (15.0, 25.0),
    "meeting_room": (15.0, 25.0),
    "kitchen": (150.0, 200.0),
    "bathroom": (10.0, 30.0),
}

HVAC_MODES = ("off", "setback", "comfort")


def saturation_humidity_ratio(t_c: float, pressure_pa: float = 101325.0) -> float:
    """Humidity ratio of saturated air (Magnus formula over water), kg/kg."""
    p_sat = 610.94 * math.exp(17.625 * t_c / (t_c + 243.04))
    return 0.621945 * p_sat / (pressure_pa - p_sat)


@dataclass
class RoomCommand:
    light_level: float = 0.0     # 0..1
    hvac_mode: str = "off"       # off | setback | comfort
    shading: float = 0.0         # 0..1
    comfort_setpoint: Optional[float] = None   # degC; None = DEFAULT_PARAMS["setpoint_comfort"]
    vent_boost: bool = False     # fresh-air boost fan (indoor air quality)


@dataclass
class RoomPhysicsState:
    t_air: float = 28.0
    t_mass: float = 28.0
    t_surface: float = 28.0      # ISO 13790 surface node = mean radiant temperature
    co2_ppm: float = CO2_OUTDOOR_PPM
    w: float = 0.015             # humidity ratio kg/kg
    # instantaneous outputs
    hvac_thermal_w: float = 0.0  # +heating / -cooling (sensible)
    hvac_electric_w: float = 0.0
    vent_w: float = 0.0          # boost fan electrical power (counted with HVAC energy)
    lighting_w: float = 0.0
    plug_w: float = 0.0
    daylight_lux: float = 0.0
    electric_lux: float = 0.0
    condensed_kg: float = 0.0    # water removed at saturation (see step)
    # cumulative energy (Wh)
    e_hvac_wh: float = 0.0
    e_lighting_wh: float = 0.0
    e_plug_wh: float = 0.0


class RoomPhysics:
    def __init__(self, room_id, zone_type: str, width: float, depth: float, height: float,
                 window_azimuth: float, params: Optional[Dict[str, float]] = None,
                 initial_temperature: float = 28.0, initial_w: float = 0.015,
                 geometry: Optional[Dict[str, float]] = None):
        self.room_id = room_id
        self.zone_type = zone_type
        p = dict(DEFAULT_PARAMS)
        p.update(params or {})
        self.p = p
        self.area = width * depth
        self.volume = width * depth * height
        self.window_azimuth = window_azimuth
        if geometry is None:          # thesis geometry: n external walls of the longer side + roof
            wall_gross = p["external_walls"] * max(width, depth) * height
            self.a_wall = max(0.0, wall_gross - p["window_area"])
            self.a_roof = self.area if p["has_roof"] else 0.0
        else:                         # explicit geometry from the building spec
            p["window_area"] = float(geometry["window_area"])
            self.a_wall = max(0.0, float(geometry["wall_area"]) - p["window_area"])
            self.a_roof = float(geometry.get("roof_area", 0.0))
        # disturbances (demonstration scenarios)
        self.extra_gain_w = 0.0
        self.extra_co2_m3s = 0.0
        self.extra_ach = 0.0          # e.g. a window left open
        self.c_air = RHO_AIR * CP_AIR * self.volume * p["air_capacity_multiplier"]
        self.c_mass = p["cm_per_m2"] * self.area
        self.a_m = p["am_factor"] * self.area
        self.a_t = p["at_factor"] * self.area
        self.h_ms = p["h_ms"] * self.a_m
        self.h_is = p["h_is"] * self.a_t
        self.h_win = p["u_window"] * p["window_area"]
        self.h_wall = p["u_wall"] * self.a_wall
        self.h_roof = p["u_roof"] * self.a_roof
        self.state = RoomPhysicsState(t_air=initial_temperature, t_mass=initial_temperature,
                                      t_surface=initial_temperature, w=initial_w)
        self.command = RoomCommand()

    # ------------------------------------------------------------------ #
    def setpoint(self) -> Optional[float]:
        mode = self.command.hvac_mode
        if mode == "comfort":
            sp = self.command.comfort_setpoint
            return self.p["setpoint_comfort"] if sp is None else sp
        if mode == "setback":
            return self.p["setpoint_setback"]
        return None

    def _ventilation_ach(self, ac_running: bool) -> float:
        return (self.p["ach_infiltration"] + (self.p["ach_mechanical"] if ac_running else 0.0)
                + (self.p["ach_boost"] if self.command.vent_boost else 0.0) + self.extra_ach)

    def step(self, dt: float, outdoor, window_irradiance: float, occupants: int,
             neighbour_flows_w: float) -> None:
        """Advance the room by dt seconds (dt should be <= 30 s)."""
        p, s, c = self.p, self.state, self.command
        light = max(0.0, min(1.0, c.light_level))
        shading = max(0.0, min(1.0, c.shading))

        # --- loads --------------------------------------------------------
        s.lighting_w = p["lighting_w"] * light
        if "plug_base_w" in p:
            base, per = p["plug_base_w"], p["plug_per_person_w"]
        else:
            base, per = PLUG_LOADS.get(self.zone_type, (20.0, 50.0))
        s.plug_w = base + per * occupants
        q_people_s = p["occupant_sensible_w"] * occupants
        q_internal = q_people_s + s.lighting_w + s.plug_w + self.extra_gain_w
        q_solar = p["window_area"] * p["shgc"] * window_irradiance * (1.0 - 0.7 * shading)

        # --- AC thermostat (proportional, cooling and optional heating) ---
        sp = self.setpoint()
        q_hvac = 0.0
        latent_removed_w = 0.0
        ac_running = sp is not None
        if sp is not None:
            band = p["proportional_band"]
            frac_cool = min(1.0, max(0.0, 0.5 + (s.t_air - sp) / band)) if s.t_air > sp - 0.5 * band else 0.0
            q_hvac = -p["ac_cool_capacity_w"] * frac_cool
            if p["ac_heat_capacity_w"] > 0 and s.t_air < sp - 2.0:
                q_hvac = p["ac_heat_capacity_w"] * min(1.0, (sp - 2.0 - s.t_air) / band)
            if q_hvac < 0:
                wet = min(1.0, max(0.0, (s.w - p["ac_coil_w"]) / 0.003))
                latent_removed_w = -q_hvac * (1.0 - p["ac_shr"]) / p["ac_shr"] * wet
        s.hvac_thermal_w = q_hvac
        if q_hvac < 0:
            s.hvac_electric_w = (-q_hvac + latent_removed_w) / p["ac_cop_cool"] + p["ac_fan_w"]
        elif q_hvac > 0:
            s.hvac_electric_w = q_hvac / 3.0 + p["ac_fan_w"]
        else:
            s.hvac_electric_w = p["ac_fan_w"] if ac_running else 0.0
        s.vent_w = (p["ach_boost"] * self.volume * p["boost_fan_w_per_m3h"]) if c.vent_boost else 0.0

        # --- thermal network: ISO 13790 5R1C (explicit Euler) -----------------
        ach = self._ventilation_ach(ac_running)
        h_ve = RHO_AIR * CP_AIR * ach * self.volume / 3600.0
        t_out = outdoor.temperature
        sky = p["h_r_sky"] * p["dt_sky"] / p["h_out"]
        t_sa_roof = t_out + p["absorptance"] * outdoor.ghi / p["h_out"] - 1.0 * sky
        t_sa_wall = t_out + p["absorptance"] * window_irradiance / p["h_out"] - 0.5 * sky
        phi_ia = 0.5 * q_internal                        # convective part of internal gains -> air
        phi_rad = 0.5 * q_internal + q_solar             # radiant internal + solar
        phi_m = self.a_m / self.a_t * phi_rad
        phi_st = max(0.0, 1.0 - self.a_m / self.a_t - self.h_win / (9.1 * self.a_t)) * phi_rad
        s.t_surface = ((self.h_is * s.t_air + self.h_ms * s.t_mass + self.h_win * t_out + phi_st)
                       / (self.h_is + self.h_ms + self.h_win))
        q_air = (self.h_is * (s.t_surface - s.t_air) + h_ve * (t_out - s.t_air)
                 + neighbour_flows_w + phi_ia + q_hvac)
        q_mass = (self.h_ms * (s.t_surface - s.t_mass) + self.h_roof * (t_sa_roof - s.t_mass)
                  + self.h_wall * (t_sa_wall - s.t_mass) + phi_m)
        s.t_air += q_air / self.c_air * dt
        s.t_mass += q_mass / self.c_mass * dt

        # --- CO2 balance (exact solution over dt) ---------------------------
        q_vent = ach * self.volume / 3600.0  # m3/s
        gen = (occupants * p["occupant_co2_m3s"] + self.extra_co2_m3s) * 1e6  # ppm*m3/s
        c_eq = CO2_OUTDOOR_PPM + gen / q_vent
        s.co2_ppm = c_eq + (s.co2_ppm - c_eq) * math.exp(-q_vent / self.volume * dt)

        # --- moisture balance ----------------------------------------------
        m_gen = occupants * p["occupant_latent_w"] / H_FG          # kg/s
        m_rem = latent_removed_w / H_FG                             # kg/s
        mass_air = RHO_AIR * self.volume
        dw = (m_gen - m_rem) / mass_air + (q_vent / self.volume) * (outdoor.humidity_ratio - s.w)
        s.w = max(0.002, s.w + dw * dt)
        # Room air cannot hold more than saturation.  When the AC cools humid air faster
        # than the fixed-SHR coil model removes moisture, the excess condenses on the
        # coil: it is removed from the air and the latent heat is extra work for the AC.
        w_sat = saturation_humidity_ratio(s.t_air)
        if s.w > w_sat:
            excess_kg = (s.w - w_sat) * mass_air
            s.w = w_sat
            if q_hvac < 0 and dt > 0:
                extra_latent_w = excess_kg * H_FG / dt
                s.hvac_electric_w += extra_latent_w / p["ac_cop_cool"]
                s.condensed_kg += excess_kg

        # --- light at the sensor -------------------------------------------
        s.daylight_lux = outdoor.illuminance_lux * p["daylight_factor"] * (1.0 - 0.8 * shading)
        s.electric_lux = p["lighting_lux"] * light

        # --- energy ---------------------------------------------------------
        h = dt / 3600.0
        s.e_hvac_wh += (s.hvac_electric_w + s.vent_w) * h
        s.e_lighting_wh += s.lighting_w * h
        s.e_plug_wh += s.plug_w * h

    # convenience ---------------------------------------------------------
    @property
    def total_power_w(self) -> float:
        s = self.state
        return s.hvac_electric_w + s.vent_w + s.lighting_w + s.plug_w

    @property
    def total_energy_wh(self) -> float:
        s = self.state
        return s.e_hvac_wh + s.e_lighting_wh + s.e_plug_wh

    @property
    def operative_temperature(self) -> float:
        """ISO 13790 Annex C: 0.3 x air + 0.7 x surface (mean radiant) temperature."""
        return 0.3 * self.state.t_air + 0.7 * self.state.t_surface
