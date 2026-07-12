"""
Inter-Zone Heat Transfer

Calculates heat transfer between adjacent thermal zones.

Implements:
- Conductive heat transfer through shared walls
- Temperature-driven flow between zones
- Integration with adjacency information

Phase 3: Advanced physics module for multi-zone thermal coupling.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional
import math

from simulation.adjacency_detector import AdjacencyInfo


@dataclass
class WallProperties:
    """Properties of a wall separating two zones."""
    u_value: float = 0.3  # W/m²K (overall heat transfer coefficient)
    conductance: float = 0.0  # W/K = U × Area (calculated)
    thermal_resistance: float = 0.0  # K/W = 1 / Conductance

    def calculate_from_area(self, u_value: float, area: float) -> None:
        """
        Calculate conductance from U-value and area.

        Args:
            u_value: Heat transfer coefficient (W/m²K)
            area: Surface area (m²)
        """
        self.u_value = u_value
        self.conductance = u_value * area
        self.thermal_resistance = 1.0 / self.conductance if self.conductance > 0 else float('inf')


@dataclass
class InterZoneHeatFlow:
    """Heat transfer between two zones."""
    room_id_1: int
    room_id_2: int
    shared_wall_area: float  # m²
    heat_flow: float = 0.0  # W (positive = from room 1 to room 2)
    wall_properties: WallProperties = field(default_factory=WallProperties)

    def calculate_heat_flow(self, t_1: float, t_2: float) -> float:
        """
        Calculate steady-state heat flow between zones.

        Q = U × A × ΔT = (T_1 - T_2) / R

        Args:
            t_1: Temperature in room 1 (°C)
            t_2: Temperature in room 2 (°C)

        Returns:
            Heat flow (W). Positive = from room 1 to room 2
        """
        delta_t = t_1 - t_2
        self.heat_flow = self.wall_properties.conductance * delta_t
        return self.heat_flow


class InterZoneTransferManager:
    """
    Manages heat transfer between all adjacent zones.

    Coordinates with adjacency detector to find neighboring zones
    and calculates inter-zone heat flows.
    """

    def __init__(self):
        """Initialize inter-zone transfer manager."""
        self.heat_flows: Dict[tuple, InterZoneHeatFlow] = {}
        self.default_u_value = 0.3  # W/m²K, typical interior wall

    def add_heat_flow(self, room_id_1: int, room_id_2: int,
                      shared_area: float,
                      u_value: Optional[float] = None) -> InterZoneHeatFlow:
        """
        Register heat transfer between two zones.

        Args:
            room_id_1: First room ID
            room_id_2: Second room ID
            shared_area: Shared wall area (m²)
            u_value: Heat transfer coefficient (W/m²K), defaults to 0.3

        Returns:
            InterZoneHeatFlow instance
        """
        if u_value is None:
            u_value = self.default_u_value

        heat_flow = InterZoneHeatFlow(
            room_id_1=room_id_1,
            room_id_2=room_id_2,
            shared_wall_area=shared_area
        )

        # Calculate wall properties
        heat_flow.wall_properties.calculate_from_area(u_value, shared_area)

        # Store with normalized key (smaller ID first)
        key = (min(room_id_1, room_id_2), max(room_id_1, room_id_2))
        self.heat_flows[key] = heat_flow

        return heat_flow

    def from_adjacency(self, adjacency: AdjacencyInfo,
                       u_value: Optional[float] = None) -> InterZoneHeatFlow:
        """
        Create heat flow from adjacency info.

        Args:
            adjacency: AdjacencyInfo object
            u_value: Heat transfer coefficient (defaults to 0.3)

        Returns:
            InterZoneHeatFlow instance
        """
        return self.add_heat_flow(
            adjacency.room_id_1,
            adjacency.room_id_2,
            adjacency.shared_area,
            u_value
        )

    def update_all_flows(self, temperatures: Dict[int, float]) -> Dict[tuple, float]:
        """
        Update heat flows between all adjacent zones.

        Args:
            temperatures: Dictionary mapping room_id to temperature (°C)

        Returns:
            Dictionary of heat flows {(room_id_1, room_id_2): heat_flow_W}
        """
        flows = {}

        for key, heat_flow in self.heat_flows.items():
            room_id_1, room_id_2 = key

            # Get temperatures
            t_1 = temperatures.get(room_id_1, 20.0)
            t_2 = temperatures.get(room_id_2, 20.0)

            # Calculate heat flow
            flow = heat_flow.calculate_heat_flow(t_1, t_2)
            flows[key] = flow

        return flows

    def get_flow_to_room(self, room_id: int,
                        temperatures: Dict[int, float]) -> float:
        """
        Get total heat flow INTO a specific room from adjacent zones.

        Args:
            room_id: Room identifier
            temperatures: Dictionary of room temperatures

        Returns:
            Heat flow to room (W). Positive = heat flowing in
        """
        total_flow = 0.0

        for (rid_1, rid_2), heat_flow in self.heat_flows.items():
            flow = heat_flow.calculate_heat_flow(
                temperatures.get(rid_1, 20.0),
                temperatures.get(rid_2, 20.0)
            )

            # Determine if this flow is into or out of room_id
            if room_id == rid_1:
                # flow is from rid_1 to rid_2, so negative is into rid_1
                total_flow -= flow
            elif room_id == rid_2:
                # flow is from rid_1 to rid_2, so positive is into rid_2
                total_flow += flow

        return total_flow

    def get_all_flows(self) -> Dict[tuple, InterZoneHeatFlow]:
        """Get all registered heat flows."""
        return self.heat_flows.copy()

    def get_flow_between(self, room_id_1: int, room_id_2: int) -> Optional[float]:
        """
        Get heat flow between two specific rooms (from design).

        Args:
            room_id_1: First room ID
            room_id_2: Second room ID

        Returns:
            Heat flow (W) or None if not adjacent
        """
        key = (min(room_id_1, room_id_2), max(room_id_1, room_id_2))
        heat_flow = self.heat_flows.get(key)
        return heat_flow.heat_flow if heat_flow else None

    def set_wall_u_value(self, room_id_1: int, room_id_2: int,
                        u_value: float) -> bool:
        """
        Update U-value for wall between two rooms.

        Args:
            room_id_1: First room ID
            room_id_2: Second room ID
            u_value: New U-value (W/m²K)

        Returns:
            True if updated, False if rooms not adjacent
        """
        key = (min(room_id_1, room_id_2), max(room_id_1, room_id_2))

        if key in self.heat_flows:
            heat_flow = self.heat_flows[key]
            heat_flow.wall_properties.calculate_from_area(
                u_value, heat_flow.shared_wall_area
            )
            return True

        return False

    def print_configuration(self) -> None:
        """Print current inter-zone transfer configuration."""
        if not self.heat_flows:
            print("No inter-zone heat transfer configured")
            return

        print("Inter-Zone Heat Transfer Configuration:")
        print("-" * 70)
        for (room_id_1, room_id_2), heat_flow in sorted(self.heat_flows.items()):
            print(f"Room {room_id_1} ↔ Room {room_id_2}")
            print(f"  Shared Area: {heat_flow.shared_wall_area:.2f} m²")
            print(f"  U-value: {heat_flow.wall_properties.u_value:.3f} W/m²K")
            print(f"  Conductance: {heat_flow.wall_properties.conductance:.3f} W/K")
            print(f"  Resistance: {heat_flow.wall_properties.thermal_resistance:.3f} K/W")
            print()


class MultiZoneThermalModel:
    """
    Simplified multi-zone thermal model using resistance network.

    Each zone has uniform temperature and exchanges heat with:
    - Adjacent zones (via inter-zone conductances)
    - External environment (via external conductances)
    - Internal sources (solar, occupancy, equipment)
    """

    def __init__(self, room_capacitances: Dict[int, float]):
        """
        Initialize multi-zone model.

        Args:
            room_capacitances: Dict mapping room_id to thermal capacitance (J/K)
        """
        self.capacitances = room_capacitances
        self.transfer_manager = InterZoneTransferManager()
        self.external_conductances: Dict[int, float] = {}
        self.temperatures: Dict[int, float] = {}

    def set_external_conductance(self, room_id: int, conductance: float) -> None:
        """
        Set external heat transfer conductance for a room.

        G_ext = U_ext × A_ext (W/K)

        Args:
            room_id: Room identifier
            conductance: External conductance (W/K)
        """
        self.external_conductances[room_id] = max(0.0, conductance)

    def solve_zone_temperatures(self, initial_temps: Dict[int, float],
                               external_temp: float,
                               internal_gains: Dict[int, float],
                               dt: float) -> Dict[int, float]:
        """
        Solve zone temperatures using simple Euler integration.

        For each zone: dT/dt = (Q_in - Q_out) / C

        Args:
            initial_temps: Initial zone temperatures (°C)
            external_temp: Outdoor temperature (°C)
            internal_gains: Internal heat gains per zone (W)
            dt: Time step (seconds)

        Returns:
            Updated zone temperatures
        """
        self.temperatures = initial_temps.copy()
        new_temps = initial_temps.copy()

        # Calculate inter-zone flows
        inter_flows = self.transfer_manager.update_all_flows(self.temperatures)

        # Update each zone
        for room_id in self.temperatures.keys():
            # Get heat flow from adjacent zones
            inter_zone_flow = self.transfer_manager.get_flow_to_room(room_id, self.temperatures)

            # External heat transfer
            ext_conductance = self.external_conductances.get(room_id, 0.0)
            external_flow = ext_conductance * (external_temp - self.temperatures[room_id])

            # Internal gains
            internal_gain = internal_gains.get(room_id, 0.0)

            # Temperature change
            capacity = self.capacitances.get(room_id, 100000.0)
            dT_dt = (inter_zone_flow + external_flow + internal_gain) / capacity

            new_temps[room_id] = self.temperatures[room_id] + dT_dt * dt

        self.temperatures = new_temps
        return new_temps

    def get_current_temperatures(self) -> Dict[int, float]:
        """Get current zone temperatures."""
        return self.temperatures.copy()

    def print_thermal_network(self) -> None:
        """Print thermal network structure."""
        print("Multi-Zone Thermal Network:")
        print("-" * 70)
        print("Zones:", sorted(self.capacitances.keys()))
        print("\nZone Properties:")
        for room_id, capacity in sorted(self.capacitances.items()):
            ext_g = self.external_conductances.get(room_id, 0.0)
            print(f"  Room {room_id}: Capacity={capacity:.0f} J/K, External G={ext_g:.3f} W/K")
        print("\nInter-zone Connections:")
        self.transfer_manager.print_configuration()
