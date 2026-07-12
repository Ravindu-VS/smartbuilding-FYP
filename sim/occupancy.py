"""
Occupancy Generator Module

Generates realistic occupancy patterns for different zone types.
Models typical office schedules, meeting room usage, and corridor traffic.
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple
from datetime import datetime, timedelta
import numpy as np


@dataclass
class OccupancyConfig:
    """Occupancy generator configuration."""
    workday_start_hour: int  # Work start time
    workday_end_hour: int  # Work end time
    weekend_probability: float  # Probability of weekend occupancy
    meeting_probability: float  # Probability of meeting room usage
    corridor_base_traffic: float  # Base corridor traffic fraction


class OccupancyGenerator:
    """
    Generates realistic occupancy patterns.
    
    Features:
    - Workday schedules with arrival/departure patterns
    - Weekend reduced occupancy
    - Meeting room booking patterns
    - Corridor traffic based on other zone occupancy
    - Lunch break patterns
    """
    
    def __init__(self, config: Dict, random_seed: int = 42):
        """
        Initialize occupancy generator.
        
        Args:
            config: Configuration dictionary
            random_seed: Random seed for reproducibility
        """
        self.config = OccupancyConfig(
            workday_start_hour=config.get('workday_start_hour', 8),
            workday_end_hour=config.get('workday_end_hour', 18),
            weekend_probability=config.get('weekend_probability', 0.1),
            meeting_probability=config.get('meeting_probability', 0.3),
            corridor_base_traffic=config.get('corridor_base_traffic', 0.2)
        )
        
        self.rng = np.random.default_rng(random_seed)
        
        # Zone maximum occupancy (to be set per zone)
        self.zone_max_occupancy: Dict[str, int] = {}
        
        # Zone types: 'office', 'meeting', 'corridor'
        self.zone_types: Dict[str, str] = {}
        
        # Pre-generated meeting schedule (for meeting rooms)
        self.meeting_schedule: Dict[str, List[Tuple[int, int, int]]] = {}
    
    def initialize_zone(
        self,
        zone_name: str,
        max_occupancy: int,
        zone_type: str = 'office'
    ) -> None:
        """
        Initialize a zone for occupancy generation.
        
        Args:
            zone_name: Zone name
            max_occupancy: Maximum number of occupants
            zone_type: Type of zone ('office', 'meeting', 'corridor')
        """
        self.zone_max_occupancy[zone_name] = max_occupancy
        self.zone_types[zone_name] = zone_type
    
    def generate_meeting_schedule(
        self,
        zone_name: str,
        start_date: datetime,
        num_days: int
    ) -> None:
        """
        Pre-generate meeting schedule for a meeting room.
        
        Args:
            zone_name: Meeting room name
            start_date: Start date of simulation
            num_days: Number of days to schedule
        """
        schedule = []
        
        for day in range(num_days):
            current_date = start_date + timedelta(days=day)
            is_weekend = current_date.weekday() >= 5
            
            if is_weekend and self.rng.random() > self.config.weekend_probability:
                continue
            
            # Generate 0-4 meetings per day
            num_meetings = self.rng.integers(0, 5)
            
            for _ in range(num_meetings):
                if self.rng.random() > self.config.meeting_probability:
                    continue
                
                # Meeting start time (working hours)
                start_hour = self.rng.integers(
                    self.config.workday_start_hour + 1,
                    self.config.workday_end_hour - 1
                )
                
                # Meeting duration (30 min to 2 hours)
                duration_minutes = int(self.rng.choice([30, 60, 90, 120]))
                
                # Attendees (2 to max)
                max_occ = self.zone_max_occupancy.get(zone_name, 10)
                attendees = self.rng.integers(2, max_occ + 1)
                
                schedule.append((day, start_hour * 60, duration_minutes, attendees))
        
        self.meeting_schedule[zone_name] = schedule
    
    def _is_workday(self, timestamp: datetime) -> bool:
        """Check if timestamp is during a workday."""
        return timestamp.weekday() < 5
    
    def _is_work_hours(self, hour: float) -> bool:
        """Check if hour is during work hours."""
        return self.config.workday_start_hour <= hour < self.config.workday_end_hour
    
    def _get_office_occupancy_factor(self, hour: float, is_workday: bool) -> float:
        """
        Get occupancy factor for office zones.
        
        Models:
        - Gradual arrival in morning
        - Lunch dip
        - Gradual departure in evening
        """
        if not is_workday:
            return self.config.weekend_probability
        
        if not self._is_work_hours(hour):
            return 0.05  # Small chance of after-hours work
        
        # Model typical office occupancy pattern
        work_start = self.config.workday_start_hour
        work_end = self.config.workday_end_hour
        
        # Normalize to 0-1 within work hours
        work_progress = (hour - work_start) / (work_end - work_start)
        
        # Arrival ramp (0-0.15)
        if work_progress < 0.15:
            factor = work_progress / 0.15 * 0.8
        # Morning peak (0.15-0.4)
        elif work_progress < 0.4:
            factor = 0.8 + 0.1 * (work_progress - 0.15) / 0.25
        # Lunch dip (0.4-0.55)
        elif work_progress < 0.55:
            factor = 0.9 - 0.3 * (work_progress - 0.4) / 0.15
        # Afternoon recovery (0.55-0.7)
        elif work_progress < 0.7:
            factor = 0.6 + 0.25 * (work_progress - 0.55) / 0.15
        # Departure ramp (0.7-1.0)
        else:
            factor = 0.85 - 0.8 * (work_progress - 0.7) / 0.3
        
        return max(0.0, min(1.0, factor))
    
    def _get_meeting_occupancy(
        self,
        zone_name: str,
        day_index: int,
        minute_of_day: int
    ) -> int:
        """Get meeting room occupancy from schedule."""
        if zone_name not in self.meeting_schedule:
            return 0
        
        for meeting in self.meeting_schedule[zone_name]:
            day, start_min, duration, attendees = meeting
            if day == day_index and start_min <= minute_of_day < start_min + duration:
                return attendees
        
        return 0
    
    def get_occupancy(
        self,
        zone_name: str,
        timestamp: datetime,
        day_index: int
    ) -> int:
        """
        Get occupancy for a zone at given timestamp.
        
        Args:
            zone_name: Zone name
            timestamp: Current datetime
            day_index: Day index from simulation start
            
        Returns:
            Number of occupants
        """
        zone_type = self.zone_types.get(zone_name, 'office')
        max_occ = self.zone_max_occupancy.get(zone_name, 10)
        
        hour = timestamp.hour + timestamp.minute / 60
        is_workday = self._is_workday(timestamp)
        minute_of_day = timestamp.hour * 60 + timestamp.minute
        
        if zone_type == 'office':
            base_factor = self._get_office_occupancy_factor(hour, is_workday)
            # Add some random variation
            noise = self.rng.normal(0, 0.1)
            factor = max(0, min(1, base_factor + noise))
            occupancy = int(round(max_occ * factor))
            
        elif zone_type == 'meeting':
            occupancy = self._get_meeting_occupancy(
                zone_name, day_index, minute_of_day
            )
            
        elif zone_type == 'corridor':
            # Corridor traffic based on time and randomness
            if is_workday and self._is_work_hours(hour):
                base_factor = self.config.corridor_base_traffic
                # Higher traffic during transition times
                if 7.5 <= hour <= 9.5 or 11.5 <= hour <= 13.5 or 17 <= hour <= 19:
                    base_factor *= 2
            else:
                base_factor = 0.05
            
            noise = self.rng.normal(0, 0.1)
            factor = max(0, min(1, base_factor + noise))
            occupancy = int(round(max_occ * factor))
            
        else:
            occupancy = 0
        
        return max(0, min(max_occ, occupancy))
    
    def get_all_occupancies(
        self,
        timestamp: datetime,
        day_index: int
    ) -> Dict[str, int]:
        """
        Get occupancies for all zones.
        
        Args:
            timestamp: Current datetime
            day_index: Day index from simulation start
            
        Returns:
            Dictionary mapping zone names to occupancy counts
        """
        return {
            zone_name: self.get_occupancy(zone_name, timestamp, day_index)
            for zone_name in self.zone_max_occupancy
        }
    
    def is_occupied(self, zone_name: str, timestamp: datetime, day_index: int) -> bool:
        """Check if a zone is currently occupied."""
        return self.get_occupancy(zone_name, timestamp, day_index) > 0
