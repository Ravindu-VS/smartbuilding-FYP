"""
Copied from the thesis code (simulation/climate.py, commit eb82674). Added at the end:
ScenarioClimate, which lays the demonstration disturbances (outdoor temperature
offset, overcast sky) over the same deterministic weather.

Synthetic outdoor climate for Colombo, Sri Lanka.

Built from published monthly climate normals (1991-2020) for Colombo as
tabulated on Wikipedia's "Colombo" article (temperature normals; humidity and
sunshine there are NOAA 1961-1990 values).  The generator reproduces the
monthly mean daily maximum/minimum temperature, the mean daytime relative
humidity and the sunshine fraction; it is NOT measured weather data.

Everything is deterministic for a given (seed, date), independent of how
often or in which order it is queried, so different controllers see the
same weather.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from functools import lru_cache

import numpy as np

LATITUDE_DEG = 6.93      # Colombo
LONGITUDE_DEG = 79.85
UTC_OFFSET_H = 5.5       # Sri Lanka Standard Time
STANDARD_MERIDIAN = UTC_OFFSET_H * 15.0

# Monthly normals, Jan..Dec
T_MAX = [31.4, 31.6, 32.0, 32.0, 31.5, 30.7, 30.3, 30.3, 30.4, 30.4, 30.6, 30.9]
T_MIN = [23.1, 23.6, 24.8, 25.3, 26.2, 26.1, 25.9, 25.9, 25.4, 24.7, 23.9, 23.5]
RH_DAY = [69, 69, 71, 75, 78, 79, 78, 77, 78, 78, 76, 73]
SUNSHINE_H = [248.0, 246.4, 275.9, 234.0, 201.5, 195.0, 201.5, 201.5, 189.0, 201.5, 210.0, 217.0]
DAYS_IN_MONTH = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
SOURCE = ("Colombo climate normals 1991-2020 (temperature) and NOAA 1961-1990 "
          "(humidity, sunshine) as tabulated in Wikipedia, 'Colombo', accessed 2026-10-08")

LUMINOUS_EFFICACY_LM_PER_W = 110.0  # global daylight efficacy (approximate)
PRESSURE_PA = 101325.0


def saturation_pressure_pa(t_c: float) -> float:
    """Magnus formula (over water)."""
    return 610.94 * math.exp(17.625 * t_c / (t_c + 243.04))


def humidity_ratio(t_c: float, rh_pct: float) -> float:
    pw = max(0.0, min(1.0, rh_pct / 100.0)) * saturation_pressure_pa(t_c)
    return 0.621945 * pw / (PRESSURE_PA - pw)


def relative_humidity(t_c: float, w: float) -> float:
    pw = w * PRESSURE_PA / (0.621945 + w)
    return max(0.0, min(100.0, 100.0 * pw / saturation_pressure_pa(t_c)))


def solar_position(ts: datetime):
    """Approximate solar altitude and azimuth (degrees) for Colombo local time."""
    doy = ts.timetuple().tm_yday
    decl = 23.45 * math.sin(math.radians(360.0 * (284 + doy) / 365.0))
    b = math.radians(360.0 * (doy - 81) / 364.0)
    eot_min = 9.87 * math.sin(2 * b) - 7.53 * math.cos(b) - 1.5 * math.sin(b)
    clock_h = ts.hour + ts.minute / 60.0 + ts.second / 3600.0
    solar_h = clock_h + (4.0 * (LONGITUDE_DEG - STANDARD_MERIDIAN) + eot_min) / 60.0
    hour_angle = math.radians(15.0 * (solar_h - 12.0))
    lat = math.radians(LATITUDE_DEG)
    d = math.radians(decl)
    sin_alt = math.sin(lat) * math.sin(d) + math.cos(lat) * math.cos(d) * math.cos(hour_angle)
    alt = math.asin(max(-1.0, min(1.0, sin_alt)))
    cos_az = (math.sin(d) - math.sin(alt) * math.sin(lat)) / max(1e-9, math.cos(alt) * math.cos(lat))
    az = math.degrees(math.acos(max(-1.0, min(1.0, cos_az))))
    if hour_angle > 0:
        az = 360.0 - az
    return math.degrees(alt), az


@dataclass
class OutdoorState:
    temperature: float          # degC
    humidity_ratio: float       # kg/kg
    relative_humidity: float    # %
    cloud_cover: float          # 0..1
    sun_altitude: float         # deg
    sun_azimuth: float          # deg (0 = N, 90 = E)
    ghi: float                  # global horizontal irradiance W/m2
    dni: float                  # direct normal W/m2
    dhi: float                  # diffuse horizontal W/m2
    illuminance_lux: float      # global horizontal illuminance
    wind_speed: float           # m/s
    precipitation: float        # mm/h (visual only)


class ColomboClimate:
    def __init__(self, seed: int = 0):
        self.seed = int(seed)

    @lru_cache(maxsize=64)
    def _day(self, ordinal: int):
        d = datetime.fromordinal(ordinal)
        m = d.month - 1
        rng = np.random.default_rng([self.seed, ordinal, 7])
        sun_frac = SUNSHINE_H[m] / (DAYS_IN_MONTH[m] * 12.1)
        mean_cloud = float(np.clip(1.0 - sun_frac, 0.05, 0.95))
        # day-to-day cloudiness: Beta with the monthly mean
        k = 4.0
        cloud = float(rng.beta(mean_cloud * k, (1 - mean_cloud) * k))
        return {
            "tmax": T_MAX[m] + float(rng.normal(0, 0.7)) - 1.2 * (cloud - mean_cloud),
            "tmin": T_MIN[m] + float(rng.normal(0, 0.5)),
            "rh": RH_DAY[m],
            "cloud": cloud,
            "phases": rng.uniform(0, 2 * math.pi, 3),
            "wind": float(rng.uniform(2.0, 4.5)),
        }

    def _temperature(self, ts: datetime, day: dict, prev: dict) -> float:
        h = ts.hour + ts.minute / 60.0 + ts.second / 3600.0
        tmin, tmax = day["tmin"], day["tmax"]
        if h < 6.0:   # night cooling from yesterday's 14:00 max to today's 06:00 min
            x = (h + 10.0) / 16.0
            return prev["tmax"] + (tmin - prev["tmax"]) * (1 - math.cos(math.pi * x)) / 2
        if h <= 14.0:  # morning warm-up
            x = (h - 6.0) / 8.0
            return tmin + (tmax - tmin) * (1 - math.cos(math.pi * x)) / 2
        nxt = self._day(ts.toordinal() + 1)
        x = (h - 14.0) / 16.0
        return tmax + (nxt["tmin"] - tmax) * (1 - math.cos(math.pi * x)) / 2

    def at(self, ts: datetime) -> OutdoorState:
        day = self._day(ts.toordinal())
        prev = self._day(ts.toordinal() - 1)
        t = self._temperature(ts, day, prev)
        h = ts.hour + ts.minute / 60.0
        p = day["phases"]
        cloud = day["cloud"] + 0.12 * math.sin(2 * math.pi * h / 5.0 + p[0]) + 0.08 * math.sin(2 * math.pi * h / 2.3 + p[1])
        if 14.0 <= h <= 18.0:   # afternoon convection
            cloud += 0.10
        cloud = float(min(1.0, max(0.0, cloud)))
        alt, az = solar_position(ts)
        if alt > 0:
            cz = math.sin(math.radians(alt))
            ghi_clear = 1098.0 * cz * math.exp(-0.057 / max(cz, 1e-3))   # Haurwitz clear sky
            ghi = ghi_clear * (1.0 - 0.75 * cloud ** 3.4)                 # Kasten & Czeplak cloud factor
            kd = min(1.0, 0.25 + 0.75 * cloud)
            dhi = kd * ghi
            dni = (ghi - dhi) / max(cz, 0.05)
        else:
            ghi = dni = dhi = 0.0
        t_mean = 0.5 * (day["tmax"] + day["tmin"])
        w = humidity_ratio(t_mean, day["rh"])
        w = min(w, humidity_ratio(t, 100.0))
        rain = max(0.0, (cloud - 0.8) * 25.0) if 13.0 <= h <= 19.0 else 0.0
        return OutdoorState(
            temperature=t, humidity_ratio=w, relative_humidity=relative_humidity(t, w),
            cloud_cover=cloud, sun_altitude=alt, sun_azimuth=az, ghi=ghi, dni=dni, dhi=dhi,
            illuminance_lux=LUMINOUS_EFFICACY_LM_PER_W * ghi, wind_speed=day["wind"], precipitation=rain)

    @staticmethod
    def irradiance_on_window(o: OutdoorState, window_azimuth_deg: float) -> float:
        """Total irradiance (W/m2) on a vertical window facing window_azimuth_deg."""
        if o.ghi <= 0:
            return 0.0
        alt = math.radians(o.sun_altitude)
        cos_inc = math.cos(alt) * math.cos(math.radians(o.sun_azimuth - window_azimuth_deg))
        beam = o.dni * max(0.0, cos_inc)
        diffuse = 0.5 * o.dhi
        ground = 0.5 * 0.2 * o.ghi
        return beam + diffuse + ground


class ScenarioClimate:
    """
    The Colombo climate with optional demonstration disturbances:
      temp_offset_k   added to the outdoor air temperature (heat-wave scenario);
      daylight_scale  multiplies the solar irradiance and illuminance (0.15 = heavy
                      overcast) - the sun position is unchanged.
    With no disturbance it returns exactly ColomboClimate.at(ts).
    """

    def __init__(self, seed: int = 0):
        self.base = ColomboClimate(seed=seed)
        self.temp_offset_k = 0.0
        self.daylight_scale = 1.0

    def at(self, ts: datetime) -> OutdoorState:
        o = self.base.at(ts)
        if self.temp_offset_k == 0.0 and self.daylight_scale == 1.0:
            return o
        t = o.temperature + self.temp_offset_k
        w = min(o.humidity_ratio, humidity_ratio(t, 100.0))
        k = max(0.0, self.daylight_scale)
        cloud = o.cloud_cover if k >= 1.0 else max(o.cloud_cover, min(1.0, 1.0 - k))
        return replace(o, temperature=t, humidity_ratio=w, relative_humidity=relative_humidity(t, w),
                       cloud_cover=cloud, ghi=o.ghi * k, dni=o.dni * k, dhi=o.dhi * k,
                       illuminance_lux=o.illuminance_lux * k)

    irradiance_on_window = staticmethod(ColomboClimate.irradiance_on_window)
