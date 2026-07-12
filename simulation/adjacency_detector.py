"""
Room Adjacency Detection and Analysis

Determines which zones share walls and calculates shared surface areas
for inter-zone heat transfer modeling.

Phase 3: Advanced physics module for multi-zone interactions.
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional, Set
import math


@dataclass
class AdjacencyInfo:
    """Information about two adjacent rooms."""
    room_id_1: int
    room_id_2: int
    shared_area: float  # m² of shared wall
    shared_perimeter: float  # m of shared wall perimeter
    wall_type: str  # "interior" or "exterior"
    shared_edge: str  # Direction of shared edge (N, S, E, W)

    def get_other_room(self, room_id: int) -> Optional[int]:
        """Get the adjacent room ID given one room."""
        if room_id == self.room_id_1:
            return self.room_id_2
        elif room_id == self.room_id_2:
            return self.room_id_1
        return None


@dataclass
class RoomBounds:
    """3D bounding box for a room."""
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    z_min: float = 0.0
    z_max: float = 3.0  # Default 3m height

    @property
    def width(self) -> float:
        """Width (x-direction)."""
        return self.x_max - self.x_min

    @property
    def depth(self) -> float:
        """Depth (y-direction)."""
        return self.y_max - self.y_min

    @property
    def height(self) -> float:
        """Height (z-direction)."""
        return self.z_max - self.z_min

    @property
    def center(self) -> Tuple[float, float, float]:
        """Center point of the room."""
        return (
            (self.x_min + self.x_max) / 2.0,
            (self.y_min + self.y_max) / 2.0,
            (self.z_min + self.z_max) / 2.0
        )

    def contains_point(self, x: float, y: float, z: float) -> bool:
        """Check if point is inside the bounding box."""
        return (self.x_min <= x <= self.x_max and
                self.y_min <= y <= self.y_max and
                self.z_min <= z <= self.z_max)


class AdjacencyDetector:
    """
    Analyzes room layouts to detect adjacencies and shared surfaces.

    Handles typical rectilinear building geometry.
    """

    # Tolerance for matching positions (mm)
    TOLERANCE = 0.01

    # Cardinal directions
    DIRECTIONS = {
        "N": (0, 1, "Y_MAX"),   # North = +Y
        "S": (0, -1, "Y_MIN"),  # South = -Y
        "E": (1, 0, "X_MAX"),   # East = +X
        "W": (-1, 0, "X_MIN"),  # West = -X
    }

    def __init__(self):
        """Initialize adjacency detector."""
        self.room_bounds: Dict[int, RoomBounds] = {}
        self.adjacencies: Dict[Tuple[int, int], AdjacencyInfo] = {}

    def add_room(self, room_id: int, x_min: float, x_max: float,
                 y_min: float, y_max: float,
                 z_min: float = 0.0, z_max: float = 3.0) -> None:
        """
        Register a room's spatial bounds.

        Args:
            room_id: Room identifier
            x_min: Minimum X coordinate (meters)
            x_max: Maximum X coordinate (meters)
            y_min: Minimum Y coordinate (meters)
            y_max: Maximum Y coordinate (meters)
            z_min: Minimum Z coordinate (default 0, floor level)
            z_max: Maximum Z coordinate (default 3, ceiling)
        """
        bounds = RoomBounds(x_min, x_max, y_min, y_max, z_min, z_max)
        self.room_bounds[room_id] = bounds

    def detect_all_adjacencies(self) -> Dict[Tuple[int, int], AdjacencyInfo]:
        """
        Detect all adjacent room pairs in the layout.

        Returns:
            Dictionary mapping (room_id_1, room_id_2) to AdjacencyInfo
        """
        self.adjacencies.clear()
        room_ids = sorted(self.room_bounds.keys())

        # Check all pairs of rooms
        for i in range(len(room_ids)):
            for j in range(i + 1, len(room_ids)):
                room_id_1 = room_ids[i]
                room_id_2 = room_ids[j]

                adjacency = self._check_adjacency(room_id_1, room_id_2)
                if adjacency is not None:
                    key = (min(room_id_1, room_id_2), max(room_id_1, room_id_2))
                    self.adjacencies[key] = adjacency

        return self.adjacencies

    def _check_adjacency(self, room_id_1: int, room_id_2: int) -> Optional[AdjacencyInfo]:
        """
        Check if two rooms are adjacent (share a wall).

        Args:
            room_id_1: First room ID
            room_id_2: Second room ID

        Returns:
            AdjacencyInfo if adjacent, None otherwise
        """
        bounds_1 = self.room_bounds[room_id_1]
        bounds_2 = self.room_bounds[room_id_2]

        # Check each possible adjacent direction
        for direction, (dx, dy, face) in self.DIRECTIONS.items():
            adjacency = self._check_direction_adjacency(
                room_id_1, bounds_1, room_id_2, bounds_2, direction, face
            )
            if adjacency is not None:
                return adjacency

        return None

    def _check_direction_adjacency(self, room_id_1: int, bounds_1: RoomBounds,
                                   room_id_2: int, bounds_2: RoomBounds,
                                   direction: str, face: str) -> Optional[AdjacencyInfo]:
        """
        Check adjacency in a specific direction.

        Args:
            room_id_1, bounds_1: First room
            room_id_2, bounds_2: Second room
            direction: Cardinal direction (N, S, E, W)
            face: Face identifier (X_MAX, X_MIN, Y_MAX, Y_MIN)

        Returns:
            AdjacencyInfo if adjacent in this direction, None otherwise
        """
        # Extract vertical overlap (Z overlap always present for interior walls)
        z_overlap = self._calculate_z_overlap(bounds_1, bounds_2)
        if z_overlap <= 0:
            return None

        # Check based on direction
        if face == "X_MAX":  # Room 1 on west, Room 2 on east
            if not self._approximately_equal(bounds_1.x_max, bounds_2.x_min):
                return None
            xy_overlap = self._calculate_y_overlap(bounds_1, bounds_2)
            if xy_overlap <= 0:
                return None
            shared_area = xy_overlap * z_overlap
            shared_perimeter = xy_overlap

        elif face == "X_MIN":  # Room 1 on east, Room 2 on west
            if not self._approximately_equal(bounds_1.x_min, bounds_2.x_max):
                return None
            xy_overlap = self._calculate_y_overlap(bounds_1, bounds_2)
            if xy_overlap <= 0:
                return None
            shared_area = xy_overlap * z_overlap
            shared_perimeter = xy_overlap

        elif face == "Y_MAX":  # Room 1 on south, Room 2 on north
            if not self._approximately_equal(bounds_1.y_max, bounds_2.y_min):
                return None
            xy_overlap = self._calculate_x_overlap(bounds_1, bounds_2)
            if xy_overlap <= 0:
                return None
            shared_area = xy_overlap * z_overlap
            shared_perimeter = xy_overlap

        elif face == "Y_MIN":  # Room 1 on north, Room 2 on south
            if not self._approximately_equal(bounds_1.y_min, bounds_2.y_max):
                return None
            xy_overlap = self._calculate_x_overlap(bounds_1, bounds_2)
            if xy_overlap <= 0:
                return None
            shared_area = xy_overlap * z_overlap
            shared_perimeter = xy_overlap

        else:
            return None

        if shared_area > 0:
            return AdjacencyInfo(
                room_id_1=min(room_id_1, room_id_2),
                room_id_2=max(room_id_1, room_id_2),
                shared_area=shared_area,
                shared_perimeter=shared_perimeter,
                wall_type="interior",
                shared_edge=direction
            )

        return None

    @staticmethod
    def _approximately_equal(a: float, b: float, tolerance: float = TOLERANCE) -> bool:
        """Check if two values are approximately equal."""
        return abs(a - b) <= tolerance

    @staticmethod
    def _calculate_x_overlap(bounds_1: RoomBounds, bounds_2: RoomBounds) -> float:
        """Calculate overlap in X direction."""
        x_min = max(bounds_1.x_min, bounds_2.x_min)
        x_max = min(bounds_1.x_max, bounds_2.x_max)
        return max(0.0, x_max - x_min)

    @staticmethod
    def _calculate_y_overlap(bounds_1: RoomBounds, bounds_2: RoomBounds) -> float:
        """Calculate overlap in Y direction."""
        y_min = max(bounds_1.y_min, bounds_2.y_min)
        y_max = min(bounds_1.y_max, bounds_2.y_max)
        return max(0.0, y_max - y_min)

    @staticmethod
    def _calculate_z_overlap(bounds_1: RoomBounds, bounds_2: RoomBounds) -> float:
        """Calculate overlap in Z direction (height)."""
        z_min = max(bounds_1.z_min, bounds_2.z_min)
        z_max = min(bounds_1.z_max, bounds_2.z_max)
        return max(0.0, z_max - z_min)

    def get_adjacent_rooms(self, room_id: int) -> List[Tuple[int, AdjacencyInfo]]:
        """
        Get all rooms adjacent to a given room.

        Args:
            room_id: Room identifier

        Returns:
            List of (adjacent_room_id, AdjacencyInfo) tuples
        """
        adjacent = []
        for (rid_1, rid_2), adjacency in self.adjacencies.items():
            if rid_1 == room_id:
                adjacent.append((rid_2, adjacency))
            elif rid_2 == room_id:
                adjacent.append((rid_1, adjacency))

        return adjacent

    def get_adjacency(self, room_id_1: int, room_id_2: int) -> Optional[AdjacencyInfo]:
        """
        Get adjacency info between two specific rooms.

        Args:
            room_id_1: First room ID
            room_id_2: Second room ID

        Returns:
            AdjacencyInfo if adjacent, None otherwise
        """
        key = (min(room_id_1, room_id_2), max(room_id_1, room_id_2))
        return self.adjacencies.get(key)

    def is_adjacent(self, room_id_1: int, room_id_2: int) -> bool:
        """
        Check if two rooms are adjacent.

        Args:
            room_id_1: First room ID
            room_id_2: Second room ID

        Returns:
            True if rooms share a wall, False otherwise
        """
        return self.get_adjacency(room_id_1, room_id_2) is not None

    def get_all_adjacencies(self) -> Dict[Tuple[int, int], AdjacencyInfo]:
        """
        Get all detected adjacencies.

        Returns:
            Dictionary of adjacencies
        """
        return self.adjacencies.copy()

    def print_adjacencies(self) -> None:
        """Print detected adjacencies to console."""
        if not self.adjacencies:
            print("No adjacencies detected")
            return

        print("Room Adjacencies:")
        print("-" * 70)
        for (room_id_1, room_id_2), info in sorted(self.adjacencies.items()):
            print(f"Room {room_id_1} ↔ Room {room_id_2}")
            print(f"  Direction: {info.shared_edge}")
            print(f"  Shared Area: {info.shared_area:.2f} m²")
            print(f"  Shared Perimeter: {info.shared_perimeter:.2f} m")
            print()


class RoomLayoutAnalyzer:
    """
    Analyzes overall room layout properties and statistics.
    """

    def __init__(self, detector: AdjacencyDetector):
        """
        Initialize analyzer.

        Args:
            detector: AdjacencyDetector instance
        """
        self.detector = detector

    def get_adjacency_stats(self) -> Dict:
        """
        Get statistics about room adjacencies.

        Returns:
            Dictionary of statistics
        """
        adjacencies = self.detector.get_all_adjacencies()

        if not adjacencies:
            return {
                "total_adjacencies": 0,
                "total_shared_area": 0.0,
                "average_shared_area": 0.0,
                "max_shared_area": 0.0,
            }

        shared_areas = [adj.shared_area for adj in adjacencies.values()]

        return {
            "total_adjacencies": len(adjacencies),
            "total_shared_area": sum(shared_areas),
            "average_shared_area": sum(shared_areas) / len(shared_areas),
            "max_shared_area": max(shared_areas),
            "min_shared_area": min(shared_areas),
        }

    def get_room_connectivity(self) -> Dict[int, int]:
        """
        Get number of adjacent rooms for each room.

        Returns:
            Dictionary mapping room_id to adjacency count
        """
        connectivity = {}

        for room_id in self.detector.room_bounds.keys():
            adjacent_rooms = self.detector.get_adjacent_rooms(room_id)
            connectivity[room_id] = len(adjacent_rooms)

        return connectivity

    def identify_isolated_rooms(self) -> List[int]:
        """
        Identify rooms with no adjacencies (isolated).

        Returns:
            List of isolated room IDs
        """
        connectivity = self.get_room_connectivity()
        return [room_id for room_id, count in connectivity.items() if count == 0]

    def identify_hub_rooms(self) -> List[int]:
        """
        Identify rooms with most adjacencies (hubs).

        Returns:
            List of hub room IDs
        """
        connectivity = self.get_room_connectivity()
        if not connectivity:
            return []

        max_adjacencies = max(connectivity.values())
        return [room_id for room_id, count in connectivity.items() if count == max_adjacencies]
