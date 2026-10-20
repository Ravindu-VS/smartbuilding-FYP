"""
Copied from the thesis code (simulation/occupancy_scheduler.py, commit eb82674); the
office, meeting, kitchen and bathroom generators are unchanged.  Added for the
26-room building (see BuildingOccupancy at the end):
  * a profile generator for the other room types (lobby, shop, gym, lounge,
    residential, corridor, server, public bathrooms), driven by the hourly
    occupancy profiles in integration/building_config.py;
  * string room ids (hashed to a stable integer for the random streams);
  * forced occupancy events for the demonstration scenarios.

Stochastic occupancy model (ground truth for the digital twin).

Each room gets a minute-by-minute head count for each day, generated from a
seeded random process that depends only on (seed, room, date).  The same seed
therefore gives every controller exactly the same occupants, which is what a
fair controller comparison needs.

Room types (assumed behaviour, not calibrated to measured data):
  office    each desk occupant: works on 90% of weekdays (5% on weekends);
            arrival ~ N(08:30, 20 min), departure ~ N(17:15, 30 min);
            lunch break 30-60 min (80% of days); short absences
            (coffee, meetings, bathroom) at about 1 per 90 min, 5-20 min long.
  meeting   bookings start on the hour or half hour between 09:00 and 17:00
            with probability 0.30 per slot when free; 30/60/90 min long;
            2..max attendees.
  kitchen   visits as a Poisson process peaking around 08:45, 12:30 and
            15:30; visits last 3-12 min (15-35 min at lunch).
  bathroom  visits as a Poisson process (about 4 per hour during the working
            day), 2-6 min long, capped at room capacity.
"""
from __future__ import annotations

import math
from datetime import datetime
from functools import lru_cache
from typing import Dict

import numpy as np

MIN_PER_DAY = 1440


def _clip_min(x: float) -> int:
    return int(max(0, min(MIN_PER_DAY, round(x))))


class OccupancyScheduler:
    def __init__(self, config: Dict = None):
        self.config = config or {}
        self.seed = int(self.config.get("seed", 0))
        self._caps: Dict[int, int] = {}

    # ------------------------------------------------------------------ #
    @lru_cache(maxsize=256)
    def _day_profile(self, room_id: int, zone_type: str, ordinal: int, max_occ: int) -> np.ndarray:
        rng = np.random.default_rng([self.seed, room_id, ordinal, 11])
        weekday = datetime.fromordinal(ordinal).weekday() < 5
        gen = {
            "office": self._office, "meeting": self._meeting, "meeting_room": self._meeting,
            "kitchen": self._kitchen, "bathroom": self._bathroom,
        }.get(zone_type, self._office)
        counts = gen(rng, weekday, max_occ)
        return np.minimum(counts, max_occ).astype(np.int16)

    def _office(self, rng, weekday, max_occ):
        counts = np.zeros(MIN_PER_DAY, dtype=int)
        for _ in range(max_occ):
            if rng.random() > (0.90 if weekday else 0.05):
                continue
            present = np.zeros(MIN_PER_DAY, dtype=bool)
            if weekday:
                arr = _clip_min(rng.normal(8.5 * 60, 20))
                dep = _clip_min(rng.normal(17.25 * 60, 30))
            else:
                arr = _clip_min(rng.normal(10 * 60, 45))
                dep = _clip_min(arr + rng.uniform(2, 5) * 60)
            arr, dep = max(arr, 7 * 60), min(max(dep, arr + 60), 20 * 60)
            present[arr:dep] = True
            if weekday and rng.random() < 0.8:
                ls = _clip_min(rng.normal(12.5 * 60, 15))
                present[ls:_clip_min(ls + rng.uniform(30, 60))] = False
            t = arr
            while True:
                t += int(rng.exponential(90))
                if t >= dep:
                    break
                present[t:_clip_min(t + rng.uniform(5, 20))] = False
            counts += present
        return counts

    def _meeting(self, rng, weekday, max_occ):
        counts = np.zeros(MIN_PER_DAY, dtype=int)
        if not weekday:
            return counts
        t = 9 * 60
        while t < 17 * 60:
            if rng.random() < 0.30:
                dur = int(rng.choice([30, 60, 90]))
                counts[t:min(t + dur, 18 * 60)] = int(rng.integers(2, max(3, max_occ + 1)))
                t += dur
            else:
                t += 30
        return counts

    def _poisson_visits(self, rng, rate_per_min, dur_lo, dur_hi):
        counts = np.zeros(MIN_PER_DAY, dtype=int)
        starts = np.nonzero(rng.random(MIN_PER_DAY) < rate_per_min)[0]
        for s in starts:
            lo, hi = (dur_lo[s], dur_hi[s]) if hasattr(dur_lo, "__len__") else (dur_lo, dur_hi)
            counts[s:_clip_min(s + rng.uniform(lo, hi))] += 1
        return counts

    def _kitchen(self, rng, weekday, max_occ):
        m = np.arange(MIN_PER_DAY) / 60.0
        scale = 1.0 if weekday else 0.08
        rate = scale * (0.05 * np.exp(-((m - 8.75) / 0.5) ** 2)
                        + 0.10 * np.exp(-((m - 12.5) / 0.6) ** 2)
                        + 0.04 * np.exp(-((m - 15.5) / 0.5) ** 2)
                        + 0.004 * ((m > 8) & (m < 18)))
        lunch = (m > 11.75) & (m < 13.75)
        lo = np.where(lunch, 15, 3)
        hi = np.where(lunch, 35, 12)
        return self._poisson_visits(rng, rate, lo, hi)

    def _bathroom(self, rng, weekday, max_occ):
        m = np.arange(MIN_PER_DAY) / 60.0
        work = (m >= 8) & (m < 18)
        rate = np.where(work, 4.0 / 60.0, np.where((m >= 7) & (m < 20), 0.5 / 60.0, 0.0))
        if not weekday:
            rate = rate * 0.05
        return self._poisson_visits(rng, rate, 2, 6)

    # ------------------------------------------------------------------ #
    def get_room_occupancy_count(self, room_id: int, room_type: str, timestamp: datetime, max_occupancy: int) -> int:
        prof = self._day_profile(int(room_id), str(room_type), timestamp.toordinal(), int(max_occupancy))
        return int(prof[timestamp.hour * 60 + timestamp.minute])

    def get_room_occupancy(self, room_id: int, room_type: str, timestamp: datetime, max_occupancy: int) -> float:
        """Occupancy as a fraction of max_occupancy (kept for older callers)."""
        if max_occupancy <= 0:
            return 0.0
        return self.get_room_occupancy_count(room_id, room_type, timestamp, max_occupancy) / float(max_occupancy)

    @staticmethod
    def is_business_hours(timestamp: datetime, start_hour: int = 8, end_hour: int = 18) -> bool:
        return timestamp.weekday() < 5 and start_hour <= timestamp.hour < end_hour


# ---------------------------------------------------------------------- #
# 26-room building: profile-driven generator and demonstration events
# ---------------------------------------------------------------------- #
import zlib
from datetime import timedelta
from typing import List, Optional, Tuple

# Mean length of one stay (minutes) per room type; an assumption, not measured.
STAY_MINUTES = {"lobby": 12.0, "shop": 25.0, "gym": 60.0, "lounge": 45.0, "residential": 150.0,
                "corridor": 3.0, "server": 20.0, "bathroom": 5.0, "executive": 90.0}

# Room types that use the thesis's generators (office floor behaviour)
THESIS_TYPES = ("office", "meeting", "kitchen")


def stable_room_index(room_id) -> int:
    """Stable integer for a room id (same on every machine and run)."""
    return room_id if isinstance(room_id, int) else zlib.crc32(str(room_id).encode()) & 0x7FFFFFFF


class BuildingOccupancy:
    """
    Minute-by-minute true head count for every room of the building.

    office / meeting / kitchen: the thesis generators (OccupancyScheduler).
    other types: for each of the room's `max_occupancy` places, a two-state
    (absent/present) Markov chain per minute whose long-run share of presence
    follows the type's hourly profile p(t) from building_config.py, with a mean
    stay of STAY_MINUTES[type]:  P(arrive) = p / (1 - p) / D,  P(leave) = 1 / D.
    Everything depends only on (seed, room, date), so every controller sees the
    same occupants.  force() overrides a room's count for a time window (demo).
    """

    def __init__(self, seed: int = 0, profiles: Optional[Dict[str, List[float]]] = None):
        self.seed = int(seed)
        self.thesis = OccupancyScheduler({"seed": self.seed})
        self.profiles = profiles or {}
        self._forced: Dict[str, List[Tuple[datetime, datetime, int]]] = {}

    @lru_cache(maxsize=512)
    def _profile_day(self, room_idx: int, room_type: str, ordinal: int, max_occ: int) -> np.ndarray:
        hourly = self.profiles.get(room_type)
        if not hourly or max_occ <= 0:
            return np.zeros(MIN_PER_DAY, dtype=np.int16)
        rng = np.random.default_rng([self.seed, room_idx, ordinal, 29])
        hours = np.arange(MIN_PER_DAY) / 60.0
        h0 = np.floor(hours).astype(int) % 24
        frac = hours - np.floor(hours)
        prof = np.asarray(hourly, dtype=float)
        p = np.clip(prof[h0] + (prof[(h0 + 1) % 24] - prof[h0]) * frac, 0.0, 0.97)
        d = STAY_MINUTES.get(room_type, 30.0)
        p_leave = min(1.0, 1.0 / d)
        present = rng.random(max_occ) < p[0]
        counts = np.zeros(MIN_PER_DAY, dtype=np.int16)
        u = rng.random((MIN_PER_DAY, max_occ))
        for m in range(MIN_PER_DAY):
            p_arrive = min(1.0, p[m] / (1.0 - p[m]) / d)
            present = np.where(present, u[m] >= p_leave, u[m] < p_arrive)
            counts[m] = int(present.sum())
        return counts

    def count(self, room_id, room_type: str, ts: datetime, max_occ: int) -> int:
        for start, end, n in reversed(self._forced.get(room_id, ())):     # the latest event wins
            if start <= ts < end:
                return int(n)
        idx = stable_room_index(room_id)
        if room_type in THESIS_TYPES:
            return self.thesis.get_room_occupancy_count(idx, room_type, ts, max_occ)
        prof = self._profile_day(idx, room_type, ts.toordinal(), int(max_occ))
        return int(prof[ts.hour * 60 + ts.minute])

    def force(self, room_id, count: int, start: datetime, minutes: float) -> None:
        """Demonstration event: room has `count` people from `start` for `minutes`."""
        self._forced.setdefault(room_id, []).append((start, start + timedelta(minutes=minutes), int(count)))

    def unforce(self, room_id, start: datetime, minutes: float) -> None:
        """Remove one forced event (the one force() added with these arguments)."""
        end = start + timedelta(minutes=minutes)
        lst = [e for e in self._forced.get(room_id, []) if not (e[0] == start and e[1] == end)]
        if lst:
            self._forced[room_id] = lst
        else:
            self._forced.pop(room_id, None)

    def clear_forced(self, room_id=None) -> None:
        if room_id is None:
            self._forced.clear()
        else:
            self._forced.pop(room_id, None)

    def forced_until(self, room_id, ts: datetime) -> Optional[datetime]:
        for start, end, _ in self._forced.get(room_id, ()):
            if start <= ts < end:
                return end
        return None
