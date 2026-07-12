"""
Room Configuration Loader

Loads room layouts and properties from configuration files.
Supports JSON format with fallback to Phase 1 defaults.
"""

import json
from pathlib import Path
from typing import List, Dict, Any
from models import RoomConfig, ThermalProperties


class RoomConfigLoader:
    """
    Loads and validates room configurations from JSON files.
    Provides default Phase 1 configuration if file not found.
    """

    def __init__(self, config_dict: Dict[str, Any] = None):
        """
        Initialize loader with config dictionary.

        Args:
            config_dict: Configuration dictionary (from CLI or file)
        """
        self.config = config_dict or {}
        self.rooms: List[RoomConfig] = []

    def load_rooms(self) -> List[RoomConfig]:
        """
        Load rooms from config file or use defaults.

        Returns:
            List of RoomConfig objects
        """
        config_file = self.config.get("config_file", "room_config.json")

        # Try to load from file
        if Path(config_file).exists():
            self.rooms = self._load_from_file(config_file)
            print(f"[OK] Loaded {len(self.rooms)} rooms from {config_file}")
        else:
            # Fall back to Phase 1 default
            self.rooms = self._default_phase1_config()
            print(f"[OK] Using Phase 1 default configuration ({len(self.rooms)} rooms)")

        return self.rooms

    @staticmethod
    def _load_from_file(filepath: str) -> List[RoomConfig]:
        """
        Load room configuration from JSON file.

        Args:
            filepath: Path to JSON configuration file

        Returns:
            List of RoomConfig objects

        Raises:
            json.JSONDecodeError: If JSON is invalid
            ValueError: If room config is invalid
        """
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in {filepath}: {e}")

        rooms = []
        building_info = data.get("building", {})

        if "rooms" not in data:
            raise ValueError("Config must have 'rooms' key")

        for room_data in data["rooms"]:
            try:
                room = RoomConfigLoader._parse_room(room_data)
                rooms.append(room)
            except Exception as e:
                raise ValueError(f"Error parsing room {room_data.get('room_id', '?')}: {e}")

        return rooms

    @staticmethod
    def _parse_room(room_data: Dict[str, Any]) -> RoomConfig:
        """
        Parse a single room from JSON data.

        Args:
            room_data: Room data dictionary from JSON

        Returns:
            RoomConfig object

        Raises:
            ValueError: If required fields missing or invalid
        """
        required = ["room_id", "name", "zone_type", "position", "dimensions"]
        for field in required:
            if field not in room_data:
                raise ValueError(f"Missing required field: {field}")

        # Parse thermal properties if provided
        thermal_data = room_data.get("thermal", {})
        thermal_props = ThermalProperties(
            thermal_mass_j_k=thermal_data.get("thermal_mass_j_k", 50000.0),
            u_value_w_m2k=thermal_data.get("u_value_w_m2k", 0.3),
            infiltration_rate_ach=thermal_data.get("infiltration_rate_ach", 0.5),
            solar_gain_factor=thermal_data.get("solar_gain_factor", 0.3),
        )

        return RoomConfig(
            room_id=int(room_data["room_id"]),
            name=str(room_data["name"]),
            zone_type=str(room_data["zone_type"]),
            position=room_data["position"],
            dimensions=room_data["dimensions"],
            max_occupancy=int(room_data.get("max_occupancy", 4)),
            thermal_properties=thermal_props,
            doors=room_data.get("doors", {}),
        )

    @staticmethod
    def _default_phase1_config() -> List[RoomConfig]:
        """
        Return Phase 1 default: 4 rooms in 2x2 grid.

        Returns:
            List of 4 RoomConfig objects (2x2 grid layout)
        """
        configs = [
            RoomConfig(
                room_id=0,
                name="Office A",
                zone_type="office",
                position={"x": -8, "y": -8, "z": 0},
                dimensions={"width": 6, "depth": 6, "height": 3},
                max_occupancy=4,
                thermal_properties=ThermalProperties(
                    thermal_mass_j_k=50000,
                    u_value_w_m2k=0.3,
                    infiltration_rate_ach=0.5,
                )
            ),
            RoomConfig(
                room_id=1,
                name="Office B",
                zone_type="office",
                position={"x": 0, "y": -8, "z": 0},
                dimensions={"width": 6, "depth": 6, "height": 3},
                max_occupancy=4,
                thermal_properties=ThermalProperties(
                    thermal_mass_j_k=50000,
                    u_value_w_m2k=0.3,
                    infiltration_rate_ach=0.5,
                )
            ),
            RoomConfig(
                room_id=2,
                name="Meeting Room",
                zone_type="meeting",
                position={"x": -8, "y": 0, "z": 0},
                dimensions={"width": 6, "depth": 6, "height": 3},
                max_occupancy=8,
                thermal_properties=ThermalProperties(
                    thermal_mass_j_k=55000,
                    u_value_w_m2k=0.3,
                    infiltration_rate_ach=0.5,
                )
            ),
            RoomConfig(
                room_id=3,
                name="Corridor",
                zone_type="corridor",
                position={"x": 0, "y": 0, "z": 0},
                dimensions={"width": 6, "depth": 6, "height": 3},
                max_occupancy=30,
                thermal_properties=ThermalProperties(
                    thermal_mass_j_k=45000,
                    u_value_w_m2k=0.35,
                    infiltration_rate_ach=0.8,
                )
            ),
        ]
        return configs

    @staticmethod
    def example_config() -> Dict[str, Any]:
        """
        Return an example configuration dictionary suitable for JSON.

        Returns:
            Dictionary that can be saved as room_config.json
        """
        return {
            "building": {
                "name": "Smart Office Building",
                "description": "Example 4-room office layout",
                "layout_type": "2x2_grid"
            },
            "rooms": [
                {
                    "room_id": 0,
                    "name": "Office A",
                    "zone_type": "office",
                    "position": {"x": -8, "y": -8, "z": 0},
                    "dimensions": {"width": 6, "depth": 6, "height": 3},
                    "max_occupancy": 4,
                    "thermal": {
                        "thermal_mass_j_k": 50000,
                        "u_value_w_m2k": 0.3,
                        "infiltration_rate_ach": 0.5,
                        "solar_gain_factor": 0.3
                    }
                },
                {
                    "room_id": 1,
                    "name": "Office B",
                    "zone_type": "office",
                    "position": {"x": 0, "y": -8, "z": 0},
                    "dimensions": {"width": 6, "depth": 6, "height": 3},
                    "max_occupancy": 4,
                    "thermal": {
                        "thermal_mass_j_k": 50000,
                        "u_value_w_m2k": 0.3,
                        "infiltration_rate_ach": 0.5,
                        "solar_gain_factor": 0.3
                    }
                },
                {
                    "room_id": 2,
                    "name": "Meeting Room",
                    "zone_type": "meeting",
                    "position": {"x": -8, "y": 0, "z": 0},
                    "dimensions": {"width": 6, "depth": 6, "height": 3},
                    "max_occupancy": 8,
                    "thermal": {
                        "thermal_mass_j_k": 55000,
                        "u_value_w_m2k": 0.3,
                        "infiltration_rate_ach": 0.5,
                        "solar_gain_factor": 0.3
                    }
                },
                {
                    "room_id": 3,
                    "name": "Corridor",
                    "zone_type": "corridor",
                    "position": {"x": 0, "y": 0, "z": 0},
                    "dimensions": {"width": 6, "depth": 6, "height": 3},
                    "max_occupancy": 30,
                    "thermal": {
                        "thermal_mass_j_k": 45000,
                        "u_value_w_m2k": 0.35,
                        "infiltration_rate_ach": 0.8,
                        "solar_gain_factor": 0.2
                    }
                }
            ]
        }

    @staticmethod
    def save_example_config(filepath: str = "room_config_example.json"):
        """
        Save an example configuration file.

        Args:
            filepath: Path to save example config to
        """
        config = RoomConfigLoader.example_config()
        with open(filepath, 'w') as f:
            json.dump(config, f, indent=2)
        print(f"[OK] Saved example config to {filepath}")
