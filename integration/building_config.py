"""
Building Configuration — Universal Room Registry

Single source of truth for the entire multi-floor smart building.
Defines all 5 floors, 26 rooms, their physical properties, occupancy
schedules, energy parameters, and control tuning.

Replaces the hard-coded ROOM_ID_MAP from config.py.
All components (StateManager, Simulator, API, Dashboard) read from here.
"""

from typing import Dict, List, Any


# =============================================================================
# OCCUPANCY SCHEDULE TEMPLATES
# =============================================================================
# Each template defines hourly occupancy probability (0.0 - 1.0) for a 24h cycle.
# The simulator uses these to generate realistic stochastic occupancy.

SCHEDULE_OFFICE = {
    "type": "office",
    "description": "Standard office: 8:30am-6pm peak, lunch dip",
    "hourly": [
        0.00, 0.00, 0.00, 0.00, 0.00, 0.00,  # 00-05
        0.02, 0.10, 0.50, 0.85, 0.90, 0.88,  # 06-11
        0.60, 0.75, 0.90, 0.85, 0.70, 0.40,  # 12-17
        0.15, 0.05, 0.02, 0.00, 0.00, 0.00,  # 18-23
    ],
}

SCHEDULE_MEETING = {
    "type": "meeting",
    "description": "Meeting rooms: sporadic peaks during business hours",
    "hourly": [
        0.00, 0.00, 0.00, 0.00, 0.00, 0.00,
        0.00, 0.05, 0.30, 0.60, 0.80, 0.50,
        0.20, 0.40, 0.70, 0.65, 0.40, 0.15,
        0.05, 0.00, 0.00, 0.00, 0.00, 0.00,
    ],
}

SCHEDULE_LOBBY = {
    "type": "lobby",
    "description": "Lobby: morning/evening peaks, steady daytime",
    "hourly": [
        0.02, 0.01, 0.01, 0.01, 0.01, 0.02,
        0.10, 0.40, 0.70, 0.50, 0.40, 0.45,
        0.55, 0.50, 0.40, 0.35, 0.45, 0.60,
        0.70, 0.50, 0.30, 0.15, 0.08, 0.03,
    ],
}

SCHEDULE_RETAIL = {
    "type": "shop",
    "description": "Retail: opens 9am, peaks afternoon/evening",
    "hourly": [
        0.00, 0.00, 0.00, 0.00, 0.00, 0.00,
        0.00, 0.00, 0.05, 0.20, 0.40, 0.55,
        0.50, 0.45, 0.55, 0.65, 0.70, 0.75,
        0.80, 0.65, 0.40, 0.15, 0.05, 0.00,
    ],
}

SCHEDULE_GYM = {
    "type": "gym",
    "description": "Gym: early morning + evening peaks",
    "hourly": [
        0.00, 0.00, 0.00, 0.00, 0.00, 0.15,
        0.50, 0.70, 0.45, 0.20, 0.15, 0.20,
        0.30, 0.25, 0.20, 0.25, 0.40, 0.65,
        0.80, 0.70, 0.45, 0.20, 0.05, 0.00,
    ],
}

SCHEDULE_SPA = {
    "type": "lounge",
    "description": "Spa/lounge: steady daytime, slight evening peak",
    "hourly": [
        0.00, 0.00, 0.00, 0.00, 0.00, 0.00,
        0.00, 0.05, 0.10, 0.25, 0.35, 0.40,
        0.35, 0.30, 0.35, 0.40, 0.45, 0.50,
        0.55, 0.45, 0.30, 0.15, 0.05, 0.00,
    ],
}

SCHEDULE_KITCHEN = {
    "type": "kitchen",
    "description": "Kitchen: meal-time bursts (breakfast, lunch, evening)",
    "hourly": [
        0.00, 0.00, 0.00, 0.00, 0.00, 0.00,
        0.05, 0.30, 0.50, 0.15, 0.10, 0.20,
        0.80, 0.70, 0.15, 0.10, 0.10, 0.25,
        0.50, 0.30, 0.10, 0.05, 0.00, 0.00,
    ],
}

SCHEDULE_BATHROOM = {
    "type": "bathroom",
    "description": "Bathroom: short intermittent usage, follows building occupancy",
    "hourly": [
        0.02, 0.01, 0.01, 0.01, 0.01, 0.02,
        0.08, 0.20, 0.30, 0.25, 0.20, 0.22,
        0.25, 0.22, 0.20, 0.18, 0.20, 0.22,
        0.25, 0.20, 0.12, 0.08, 0.05, 0.03,
    ],
}

SCHEDULE_SERVER_ROOM = {
    "type": "server",
    "description": "Server room: rare human entry, mostly automated",
    "hourly": [
        0.00, 0.00, 0.00, 0.00, 0.00, 0.00,
        0.00, 0.00, 0.05, 0.10, 0.10, 0.10,
        0.05, 0.05, 0.10, 0.10, 0.05, 0.02,
        0.00, 0.00, 0.00, 0.00, 0.00, 0.00,
    ],
}

SCHEDULE_CORRIDOR = {
    "type": "corridor",
    "description": "Corridor: follows building traffic patterns",
    "hourly": [
        0.01, 0.01, 0.01, 0.01, 0.01, 0.02,
        0.10, 0.30, 0.50, 0.40, 0.35, 0.40,
        0.50, 0.45, 0.40, 0.35, 0.40, 0.45,
        0.50, 0.30, 0.15, 0.08, 0.03, 0.02,
    ],
}

SCHEDULE_RESIDENTIAL = {
    "type": "residential",
    "description": "Residential: inverse office - high evening/night, low daytime",
    "hourly": [
        0.90, 0.95, 0.95, 0.95, 0.95, 0.85,
        0.70, 0.40, 0.15, 0.05, 0.05, 0.05,
        0.10, 0.10, 0.05, 0.05, 0.10, 0.30,
        0.55, 0.70, 0.80, 0.85, 0.90, 0.92,
    ],
}

SCHEDULE_EXECUTIVE = {
    "type": "executive",
    "description": "Executive: shorter hours, later start, early finish",
    "hourly": [
        0.00, 0.00, 0.00, 0.00, 0.00, 0.00,
        0.00, 0.02, 0.10, 0.50, 0.70, 0.75,
        0.50, 0.60, 0.70, 0.65, 0.40, 0.15,
        0.05, 0.00, 0.00, 0.00, 0.00, 0.00,
    ],
}

# Map room type → schedule
SCHEDULE_MAP = {
    "office": SCHEDULE_OFFICE,
    "meeting": SCHEDULE_MEETING,
    "lobby": SCHEDULE_LOBBY,
    "shop": SCHEDULE_RETAIL,
    "gym": SCHEDULE_GYM,
    "lounge": SCHEDULE_SPA,
    "kitchen": SCHEDULE_KITCHEN,
    "bathroom": SCHEDULE_BATHROOM,
    "server": SCHEDULE_SERVER_ROOM,
    "corridor": SCHEDULE_CORRIDOR,
    "residential": SCHEDULE_RESIDENTIAL,
    "executive": SCHEDULE_EXECUTIVE,
}


# =============================================================================
# THERMAL DEFAULTS PER ROOM TYPE
# =============================================================================
# Default 2R2C thermal parameters for each room type.
# These are used when creating Zone objects in the multi-floor simulator.

THERMAL_DEFAULTS = {
    "office":      {"R_wall": 0.004, "R_internal": 0.002, "C_zone": 150000, "C_wall": 500000},
    "meeting":     {"R_wall": 0.004, "R_internal": 0.002, "C_zone": 120000, "C_wall": 400000},
    "lobby":       {"R_wall": 0.003, "R_internal": 0.0015, "C_zone": 250000, "C_wall": 800000},
    "shop":        {"R_wall": 0.004, "R_internal": 0.002, "C_zone": 180000, "C_wall": 550000},
    "gym":         {"R_wall": 0.005, "R_internal": 0.0025, "C_zone": 200000, "C_wall": 600000},
    "lounge":      {"R_wall": 0.004, "R_internal": 0.002, "C_zone": 160000, "C_wall": 500000},
    "kitchen":     {"R_wall": 0.004, "R_internal": 0.002, "C_zone": 140000, "C_wall": 450000},
    "bathroom":    {"R_wall": 0.005, "R_internal": 0.003, "C_zone":  80000, "C_wall": 300000},
    "server":      {"R_wall": 0.006, "R_internal": 0.003, "C_zone": 100000, "C_wall": 350000},
    "corridor":    {"R_wall": 0.003, "R_internal": 0.0015, "C_zone": 100000, "C_wall": 350000},
    "residential": {"R_wall": 0.005, "R_internal": 0.0025, "C_zone": 160000, "C_wall": 500000},
    "executive":   {"R_wall": 0.004, "R_internal": 0.002, "C_zone": 170000, "C_wall": 520000},
}


# =============================================================================
# ENERGY PARAMETERS PER ROOM TYPE (Watts)
# =============================================================================

ENERGY_PARAMS_BY_TYPE = {
    "office":      {"base_load": 80,  "light_on": 200, "light_dim": 80, "hvac_normal": 350, "hvac_eco": 50},
    "meeting":     {"base_load": 50,  "light_on": 250, "light_dim": 100, "hvac_normal": 300, "hvac_eco": 40},
    "lobby":       {"base_load": 100, "light_on": 400, "light_dim": 150, "hvac_normal": 500, "hvac_eco": 80},
    "shop":        {"base_load": 120, "light_on": 350, "light_dim": 120, "hvac_normal": 400, "hvac_eco": 60},
    "gym":         {"base_load": 150, "light_on": 300, "light_dim": 100, "hvac_normal": 600, "hvac_eco": 100},
    "lounge":      {"base_load": 60,  "light_on": 180, "light_dim": 70, "hvac_normal": 250, "hvac_eco": 40},
    "kitchen":     {"base_load": 200, "light_on": 250, "light_dim": 100, "hvac_normal": 350, "hvac_eco": 50},
    "bathroom":    {"base_load": 30,  "light_on": 100, "light_dim": 40, "hvac_normal": 150, "hvac_eco": 25},
    "server":      {"base_load": 800, "light_on": 100, "light_dim": 40, "hvac_normal": 1200, "hvac_eco": 400},
    "corridor":    {"base_load": 20,  "light_on": 120, "light_dim": 50, "hvac_normal": 100, "hvac_eco": 20},
    "residential": {"base_load": 60,  "light_on": 150, "light_dim": 60, "hvac_normal": 250, "hvac_eco": 40},
    "executive":   {"base_load": 100, "light_on": 220, "light_dim": 90, "hvac_normal": 380, "hvac_eco": 60},
}


# =============================================================================
# CONTROL TUNING PER ROOM TYPE
# =============================================================================

CONTROL_TUNING = {
    "office":      {"empty_threshold": 0.20, "occupied_threshold": 0.60},
    "meeting":     {"empty_threshold": 0.25, "occupied_threshold": 0.55},
    "lobby":       {"empty_threshold": 0.15, "occupied_threshold": 0.40},
    "shop":        {"empty_threshold": 0.15, "occupied_threshold": 0.45},
    "gym":         {"empty_threshold": 0.15, "occupied_threshold": 0.50},
    "lounge":      {"empty_threshold": 0.20, "occupied_threshold": 0.55},
    "kitchen":     {"empty_threshold": 0.15, "occupied_threshold": 0.50},
    "bathroom":    {"empty_threshold": 0.10, "occupied_threshold": 0.40},
    "server":      {"empty_threshold": 0.30, "occupied_threshold": 0.70},
    "corridor":    {"empty_threshold": 0.10, "occupied_threshold": 0.35},
    "residential": {"empty_threshold": 0.20, "occupied_threshold": 0.55},
    "executive":   {"empty_threshold": 0.20, "occupied_threshold": 0.60},
}


# =============================================================================
# BUILDING GEOMETRY (shared by the simulation and the 3D view)
# =============================================================================
# Plan positions are metres from the building's south-west corner: x runs east
# (0..30), z runs north (0..20). Each room has x, z (corner) and w, d (size in x, z).
# The 3D view draws exactly these rectangles (it receives them from the edge brain).
BUILDING_GEOMETRY = {
    "width_m": 30.0,          # x extent
    "depth_m": 20.0,          # z extent
    "floor_height_m": 3.5,    # floor-to-floor
    "slab_m": 0.3,            # room height = floor_height - slab = 3.2 m
    "north": "+z",            # z = 0 faces south, z = depth faces north
}


# =============================================================================
# BUILDING CONFIGURATION — THE SINGLE SOURCE OF TRUTH
# =============================================================================

BUILDING_CONFIG = {
    "building_id": "SmartBuilding001",
    "name": "Smart Building Digital Twin",
    "total_floors": 5,
    "floors": [
        # ─── Floor 1: Retail & Lobby ───
        {
            "floor_id": 0,
            "name": "Retail & Lobby",
            "floor_type": "commercial",
            "rooms": [
                {"room_id": "f0_lobby",      "name": "Main Lobby",       "type": "lobby",    "area_m2": 180, "volume_m3": 630, "max_occupancy": 15, "x": 0, "z": 0, "w": 15, "d": 12},
                {"room_id": "f0_cafe",        "name": "Coffee Shop",      "type": "shop",     "area_m2": 180, "volume_m3": 630, "max_occupancy": 15, "x": 15, "z": 0, "w": 15, "d": 12},
                {"room_id": "f0_retail_a",    "name": "Retail Store A",   "type": "shop",     "area_m2": 80,  "volume_m3": 280, "max_occupancy": 10, "x": 0, "z": 12, "w": 10, "d": 8},
                {"room_id": "f0_retail_b",    "name": "Retail Store B",   "type": "shop",     "area_m2": 80,  "volume_m3": 280, "max_occupancy": 10, "x": 10, "z": 12, "w": 10, "d": 8},
                {"room_id": "f0_bathroom",    "name": "Public Restrooms", "type": "bathroom", "area_m2": 80,  "volume_m3": 280, "max_occupancy": 5, "x": 20, "z": 12, "w": 10, "d": 8},
            ],
        },
        # ─── Floor 2: Health & Recreation ───
        {
            "floor_id": 1,
            "name": "Health & Recreation",
            "floor_type": "recreation",
            "rooms": [
                {"room_id": "f1_gym",         "name": "Fitness Center",   "type": "gym",      "area_m2": 240, "volume_m3": 840, "max_occupancy": 20, "x": 0, "z": 0, "w": 20, "d": 12},
                {"room_id": "f1_spa",         "name": "Spa & Wellness",   "type": "lounge",   "area_m2": 120, "volume_m3": 420, "max_occupancy": 10, "x": 20, "z": 0, "w": 10, "d": 12},
                {"room_id": "f1_studio",      "name": "Yoga Studio",      "type": "gym",      "area_m2": 120, "volume_m3": 420, "max_occupancy": 12, "x": 0, "z": 12, "w": 15, "d": 8},
                {"room_id": "f1_lockers",     "name": "Locker Rooms",     "type": "bathroom", "area_m2": 120, "volume_m3": 420, "max_occupancy": 10, "x": 15, "z": 12, "w": 15, "d": 8},
            ],
        },
        # ─── Floor 3: Operations (AI Monitored — maps to original 4 rooms) ───
        {
            "floor_id": 2,
            "name": "Operations (AI Monitored)",
            "floor_type": "office",
            "is_primary_monitored": True,
            "rooms": [
                {"room_id": "f2_office_a",    "name": "Office A",         "type": "office",   "area_m2": 168, "volume_m3": 588, "max_occupancy": 10, "x": 0, "z": 0, "w": 14, "d": 12, "legacy_sim_id": 0, "data_source": "hardware", "sensors": ["temperature", "humidity", "co2", "lux"]},
                {"room_id": "f2_meeting_b",   "name": "Meeting Room B",   "type": "meeting",  "area_m2": 80,  "volume_m3": 280, "max_occupancy": 8, "x": 14, "z": 0, "w": 10, "d": 8,  "legacy_sim_id": 2, "data_source": "simulation"},
                {"room_id": "f2_kitchen",     "name": "Kitchen",          "type": "kitchen",  "area_m2": 48,  "volume_m3": 168, "max_occupancy": 4, "x": 24, "z": 0, "w": 6, "d": 8,  "legacy_sim_id": 1, "data_source": "simulation"},
                {"room_id": "f2_corridor",    "name": "Main Corridor",    "type": "corridor", "area_m2": 64,  "volume_m3": 224, "max_occupancy": 5, "x": 14, "z": 8, "w": 16, "d": 4,  "legacy_sim_id": 3, "data_source": "simulation"},
                {"room_id": "f2_office_b2",   "name": "Office B2",        "type": "office",   "area_m2": 112, "volume_m3": 392, "max_occupancy": 8, "x": 0, "z": 12, "w": 14, "d": 8, "data_source": "simulation"},
                {"room_id": "f2_server",      "name": "Server Room",      "type": "server",   "area_m2": 128, "volume_m3": 448, "max_occupancy": 2, "x": 14, "z": 12, "w": 16, "d": 8, "data_source": "simulation"},
            ],
        },
        # ─── Floor 4: Residential Apartments ───
        {
            "floor_id": 3,
            "name": "Residential Apartments",
            "floor_type": "residential",
            "rooms": [
                {"room_id": "f3_apt1_living", "name": "Apt 1 - Living",   "type": "residential", "area_m2": 120, "volume_m3": 420, "max_occupancy": 4, "x": 0, "z": 0, "w": 10, "d": 12},
                {"room_id": "f3_apt1_bed",    "name": "Apt 1 - Bedroom",  "type": "residential", "area_m2": 60,  "volume_m3": 210, "max_occupancy": 2, "x": 10, "z": 0, "w": 5, "d": 12},
                {"room_id": "f3_apt2_living", "name": "Apt 2 - Living",   "type": "residential", "area_m2": 120, "volume_m3": 420, "max_occupancy": 4, "x": 15, "z": 0, "w": 10, "d": 12},
                {"room_id": "f3_apt2_bed",    "name": "Apt 2 - Bedroom",  "type": "residential", "area_m2": 60,  "volume_m3": 210, "max_occupancy": 2, "x": 25, "z": 0, "w": 5, "d": 12},
                {"room_id": "f3_apt1_bath",   "name": "Apt 1 - Bathroom", "type": "bathroom",    "area_m2": 40,  "volume_m3": 140, "max_occupancy": 1, "x": 0, "z": 12, "w": 5, "d": 8},
                {"room_id": "f3_hallway",     "name": "Hallway",          "type": "corridor",    "area_m2": 160, "volume_m3": 560, "max_occupancy": 3, "x": 5, "z": 12, "w": 20, "d": 8},
                {"room_id": "f3_apt2_bath",   "name": "Apt 2 - Bathroom", "type": "bathroom",    "area_m2": 40,  "volume_m3": 140, "max_occupancy": 1, "x": 25, "z": 12, "w": 5, "d": 8},
            ],
        },
        # ─── Floor 5: Penthouse Suite ───
        {
            "floor_id": 4,
            "name": "Penthouse Suite",
            "floor_type": "residential",
            "rooms": [
                {"room_id": "f4_lounge",      "name": "Penthouse Lounge", "type": "residential", "area_m2": 240, "volume_m3": 840, "max_occupancy": 8, "x": 0, "z": 0, "w": 20, "d": 12},
                {"room_id": "f4_master",      "name": "Master Bedroom",   "type": "residential", "area_m2": 120, "volume_m3": 420, "max_occupancy": 2, "x": 20, "z": 0, "w": 10, "d": 12},
                {"room_id": "f4_terrace",     "name": "Roof Terrace",     "type": "lobby",       "area_m2": 160, "volume_m3": 560, "max_occupancy": 15, "x": 0, "z": 12, "w": 20, "d": 8},
                {"room_id": "f4_bath",        "name": "Luxury Bath",      "type": "bathroom",    "area_m2": 80,  "volume_m3": 280, "max_occupancy": 2, "x": 20, "z": 12, "w": 10, "d": 8},
            ],
        },
    ],
}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_all_rooms() -> List[Dict[str, Any]]:
    """Get a flat list of all rooms across all floors, with floor_id attached."""
    rooms = []
    for floor in BUILDING_CONFIG["floors"]:
        for room in floor["rooms"]:
            r = dict(room)
            r["floor_id"] = floor["floor_id"]
            r["floor_name"] = floor["name"]
            rooms.append(r)
    return rooms


def get_all_room_ids() -> List[str]:
    """Get all room_id strings."""
    return [r["room_id"] for r in get_all_rooms()]


def get_floor_rooms(floor_id: int) -> List[Dict[str, Any]]:
    """Get rooms for a specific floor."""
    for floor in BUILDING_CONFIG["floors"]:
        if floor["floor_id"] == floor_id:
            return floor["rooms"]
    return []


def get_room_config(room_id: str) -> Dict[str, Any]:
    """Look up a room by its room_id."""
    for room in get_all_rooms():
        if room["room_id"] == room_id:
            return room
    return {}


def get_room_schedule(room_type: str) -> List[float]:
    """Get the hourly occupancy schedule for a room type."""
    schedule = SCHEDULE_MAP.get(room_type, SCHEDULE_OFFICE)
    return schedule["hourly"]


def get_room_thermal(room_type: str) -> Dict[str, float]:
    """Get thermal parameters for a room type."""
    return THERMAL_DEFAULTS.get(room_type, THERMAL_DEFAULTS["office"])


def get_room_energy_params(room_type: str) -> Dict[str, float]:
    """Get energy parameters for a room type."""
    return ENERGY_PARAMS_BY_TYPE.get(room_type, ENERGY_PARAMS_BY_TYPE["office"])


def get_room_control_tuning(room_type: str) -> Dict[str, float]:
    """Get control tuning thresholds for a room type."""
    return CONTROL_TUNING.get(room_type, CONTROL_TUNING["office"])


def get_total_room_count() -> int:
    """Get total number of rooms in the building."""
    return len(get_all_rooms())


def get_legacy_room_mapping() -> Dict[int, str]:
    """
    Get the legacy simulation ID → room_id mapping.
    Only Floor 3 rooms have legacy_sim_id (from the original 4-room Panda3D simulation).
    """
    mapping = {}
    for room in get_all_rooms():
        if "legacy_sim_id" in room:
            mapping[room["legacy_sim_id"]] = room["room_id"]
    return mapping
