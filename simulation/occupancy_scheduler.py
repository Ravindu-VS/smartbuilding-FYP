"""
Occupancy Scheduler

Realistic per-room occupancy patterns based on room type and time.
Extends simple phase 1 model with building-realistic schedules.
"""

from typing import Dict, List
from datetime import datetime
import math


class OccupancyScheduler:
    """
    Generates realistic occupancy patterns per room.
    Accounts for room type, time of day, day of week.
    """

    def __init__(self, config: Dict = None):
        """
        Initialize occupancy scheduler.

        Args:
            config: Configuration dict with occupancy parameters
        """
        self.config = config or {}

        # Default schedules by zone type
        self.zone_schedules = {
            "office": {
                "start_hour": 7,      # Start of workday
                "peak_hour": 11,      # Peak occupancy time
                "end_hour": 18,       # End of workday
                "evening_start": 18,  # Evening hours
                "evening_peak": 0.2,  # 20% occupancy in evening
                "peak_occupancy": 0.9,  # 90% of max during peak hours
            },
            "meeting": {
                "start_hour": 8,
                "peak_hour": 14,
                "end_hour": 18,
                "evening_start": 18,
                "evening_peak": 0.1,
                "peak_occupancy": 0.4,  # Meetings are intermittent
            },
            "corridor": {
                "start_hour": 8,
                "peak_hour": 13,
                "end_hour": 18,
                "evening_start": 18,
                "evening_peak": 0.15,
                "peak_occupancy": 0.3,  # Always partial
            },
            "lobby": {
                "start_hour": 7,
                "peak_hour": 9,
                "end_hour": 18,
                "evening_start": 18,
                "evening_peak": 0.2,
                "peak_occupancy": 0.5,
            },
            "storage": {
                "start_hour": 8,
                "peak_hour": 12,
                "end_hour": 17,
                "evening_start": 17,
                "evening_peak": 0.05,
                "peak_occupancy": 0.2,  # Rarely occupied
            },
        }

    def get_room_occupancy(self, room_id: int, room_type: str,
                          timestamp: datetime, max_occupancy: int) -> float:
        """
        Get occupancy level (0.0 to 1.0) for a room at given time.

        Args:
            room_id: Room identifier
            room_type: Type of room ("office", "meeting", etc.)
            timestamp: Current time
            max_occupancy: Maximum occupancy for this room

        Returns:
            Occupancy fraction (0.0 to 1.0)
        """
        hour = timestamp.hour + timestamp.minute / 60.0
        weekday = timestamp.weekday()  # 0=Monday, 6=Sunday

        # Weekend occupancy is lower
        weekend_factor = 0.3 if weekday >= 5 else 1.0

        # Get schedule for this zone type
        schedule = self.zone_schedules.get(room_type, self.zone_schedules["office"])

        if room_type == "bathroom":
            return self._calculate_bathroom_occupancy(hour, schedule, timestamp)

        occupancy = self._calculate_occupancy_curve(hour, schedule)

        # Apply weekend factor
        occupancy *= weekend_factor

        # Add some randomness (±5%) for realism
        import random
        randomness = random.uniform(-0.05, 0.05)
        occupancy = max(0.0, min(1.0, occupancy + randomness))

        return occupancy

    def _calculate_occupancy_curve(self, hour: float, schedule: Dict) -> float:
        """
        Calculate occupancy curve for a single day.
        Uses smooth curves instead of step functions.

        Args:
            hour: Hour of day (0-24)
            schedule: Schedule dict for this zone type

        Returns:
            Occupancy fraction (0.0 to 1.0)
        """
        start = schedule["start_hour"]
        peak_hour = schedule["peak_hour"]
        end = schedule["end_hour"]
        evening_start = schedule["evening_start"]
        evening_peak = schedule["evening_peak"]
        peak_occupancy = schedule["peak_occupancy"]

        # Night hours (10pm to 6am)
        if hour < start or hour >= 22:
            return 0.0

        # Morning ramp-up (start hour to peak hour)
        if start <= hour <= peak_hour:
            progress = (hour - start) / (peak_hour - start)
            # Smooth curve using cosine
            occupancy = peak_occupancy * (1 - math.cos(progress * math.pi)) / 2
            return occupancy

        # Daytime plateau (peak hour to end hour)
        if peak_hour < hour < end:
            return peak_occupancy

        # Evening ramp-down (end hour to evening start)
        if end <= hour <= evening_start:
            # Handle case where end_hour == evening_start (no ramp period)
            if evening_start - end <= 0.01:  # Allow small floating point tolerance
                return evening_peak
            progress = (hour - end) / (evening_start - end)
            occupancy = peak_occupancy * (1 - progress) + evening_peak * progress
            return occupancy

        # Evening (low occupancy)
        if evening_start < hour < 22:
            return evening_peak

        return 0.0

    def _calculate_bathroom_occupancy(self, hour: float, schedule: Dict, timestamp: datetime) -> float:
        """
        Calculate discrete, event-based bathroom occupancy.
        Bathrooms have brief spikes rather than continuous probability curves.
        """
        start = schedule.get("start_hour", 7)
        end = schedule.get("end_hour", 19)

        # Not used late at night
        if hour < start or hour >= 22:
            return 0.0

        # Pseudo-random but deterministic based on day and minute to prevent jitter
        minute_of_day = int(hour * 60)
        day_seed = timestamp.toordinal()
        
        # Use simple integer hashing for stable pseudo-randomness
        import hashlib
        hash_input = f"{day_seed}_{minute_of_day}".encode()
        h = int(hashlib.md5(hash_input).hexdigest()[:8], 16)
        
        # During peak hours (e.g. 9-17) increase likelihood
        is_peak = (9 <= hour <= 17)
        chance = 10 if is_peak else 20  # 1 in 10 minutes vs 1 in 20 minutes
        
        # Check if this minute is a visit event
        is_occupied = (h % chance == 0)
        
        if is_occupied:
            # 80% chance of 1 person (which translates to 0.5 of max_occupancy 2)
            # 20% chance of 2 people (1.0)
            return 0.5 if (h % 10) < 8 else 1.0
            
        return 0.0

    def get_room_occupancy_count(self, room_id: int, room_type: str,
                                timestamp: datetime, max_occupancy: int) -> int:
        """
        Get occupancy as person count instead of fraction.

        Args:
            room_id: Room identifier
            room_type: Type of room
            timestamp: Current time
            max_occupancy: Maximum people in room

        Returns:
            Number of people in room (int)
        """
        fraction = self.get_room_occupancy(room_id, room_type, timestamp, max_occupancy)
        count = int(round(fraction * max_occupancy))
        return max(0, count)

    @staticmethod
    def is_business_hours(timestamp: datetime, start_hour: int = 8, end_hour: int = 18) -> bool:
        """
        Check if time is during business hours.

        Args:
            timestamp: Current time
            start_hour: Business hours start
            end_hour: Business hours end

        Returns:
            True if during business hours on a weekday
        """
        hour = timestamp.hour
        weekday = timestamp.weekday()  # 0=Monday, 6=Sunday

        return (weekday < 5 and start_hour <= hour < end_hour)

    @staticmethod
    def is_weekend(timestamp: datetime) -> bool:
        """
        Check if day is weekend.

        Args:
            timestamp: Current time

        Returns:
            True if Saturday or Sunday
        """
        return timestamp.weekday() >= 5
