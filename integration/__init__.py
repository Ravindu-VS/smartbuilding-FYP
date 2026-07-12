"""
Integration Layer Package

Connects the smart building simulation engine, trained occupancy ML model,
and web dashboard into a real-time digital twin system.

Modules:
    config              - Central configuration constants and room mappings
    simulation_bridge   - Adapter between SimulationEngine and integration layer
    state_manager       - Central live state store for all rooms
    energy_estimator    - Per-room and building-wide energy estimation
    live_update_service - Background service orchestrating the real-time loop
"""
