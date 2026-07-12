#!/usr/bin/env python3
"""
Smart Building Energy Management Simulation

Main entry point for running the building energy simulation.
Supports baseline rule-based and MPC controllers.

Usage:
    python main.py --days 30 --controller baseline
    python main.py --days 30 --controller mpc
    python main.py --help
"""

import argparse
import os
import sys
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import yaml

# Import simulation modules
from sim.building import BuildingThermalModel, ZoneState
from sim.hvac import HVACSystem
from sim.lighting import LightingSystem
from sim.occupancy import OccupancyGenerator
from sim.weather import WeatherGenerator
from sim.loads import PlugLoadGenerator
from sim.sensors import SensorSimulator
from sim.energy_meter import EnergyMeter

# Import control modules
from control.baseline_rule_controller import BaselineRuleController
from control.mpc_controller import MPCController
from control.optimizer import ObjectiveFunction

# Import data generation
from data.generator import DatasetGenerator


def load_config(config_path: str = "config.yaml") -> Dict:
    """
    Load configuration from YAML file.
    
    Args:
        config_path: Path to configuration file
        
    Returns:
        Configuration dictionary
    """
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    return config


def setup_simulation(config: Dict) -> tuple:
    """
    Initialize all simulation components.
    
    Args:
        config: Configuration dictionary
        
    Returns:
        Tuple of initialized components
    """
    random_seed = config['simulation'].get('random_seed', 42)
    
    # Building model
    building = BuildingThermalModel(
        zones_config=config['building']['zones'],
        initial_temp=22.0
    )
    
    # HVAC system
    hvac = HVACSystem(config['hvac'])
    for zone_name in building.get_zone_names():
        hvac.initialize_zone(zone_name, initial_setpoint=22.0)
    
    # Lighting system
    lighting = LightingSystem(config['lighting'])
    for zone in building.get_all_zones():
        lighting.initialize_zone(
            zone.name,
            baseline_watts=zone.config.lighting_baseline_watts
        )
    
    # Occupancy generator
    occupancy_gen = OccupancyGenerator(config['occupancy'], random_seed)
    for zone in building.get_all_zones():
        # Determine zone type from name
        if 'meeting' in zone.name.lower():
            zone_type = 'meeting'
        elif 'corridor' in zone.name.lower():
            zone_type = 'corridor'
        else:
            zone_type = 'office'
        
        occupancy_gen.initialize_zone(
            zone.name,
            max_occupancy=zone.config.occupancy_max,
            zone_type=zone_type
        )
    
    # Weather generator
    weather = WeatherGenerator(config['weather'], random_seed + 1)
    
    # Plug load generator
    plug_loads = PlugLoadGenerator(random_seed + 2)
    for zone in building.get_all_zones():
        plug_loads.initialize_zone(
            zone.name,
            baseline_watts=zone.config.plug_load_baseline_watts
        )
    
    # Sensor simulator
    sensors = SensorSimulator(config['sensors'], random_seed + 3)
    
    # Energy meter
    energy_meter = EnergyMeter()
    for zone_name in building.get_zone_names():
        energy_meter.initialize_zone(zone_name)
    
    return (building, hvac, lighting, occupancy_gen, weather, 
            plug_loads, sensors, energy_meter)


def setup_controller(controller_type: str, config: Dict, 
                     building, hvac, lighting):
    """
    Initialize controller.
    
    Args:
        controller_type: Type of controller ('baseline' or 'mpc')
        config: Configuration dictionary
        building: Building model
        hvac: HVAC system
        lighting: Lighting system
        
    Returns:
        Controller instance
    """
    if controller_type == 'mpc':
        return MPCController(
            config['controller'],
            building_model=building,
            hvac_system=hvac,
            lighting_system=lighting
        )
    else:
        return BaselineRuleController(config['controller'])


def run_simulation(
    config: Dict,
    controller_type: str = 'baseline',
    days: Optional[int] = None,
    verbose: bool = True
) -> Dict:
    """
    Run the building simulation.
    
    Args:
        config: Configuration dictionary
        controller_type: Type of controller to use
        days: Number of days to simulate (overrides config)
        verbose: Print progress information
        
    Returns:
        Dictionary with simulation results
    """
    # Setup
    sim_config = config['simulation']
    dt = sim_config['time_step_seconds']
    duration_days = days if days is not None else sim_config['duration_days']
    start_date = datetime.strptime(sim_config['start_date'], '%Y-%m-%d')
    
    total_steps = int(duration_days * 24 * 3600 / dt)
    
    if verbose:
        print(f"Starting simulation...")
        print(f"  Duration: {duration_days} days")
        print(f"  Time step: {dt} seconds")
        print(f"  Controller: {controller_type}")
        print(f"  Total steps: {total_steps}")
        print()
    
    # Initialize components
    (building, hvac, lighting, occupancy_gen, weather,
     plug_loads, sensors, energy_meter) = setup_simulation(config)
    
    controller = setup_controller(
        controller_type, config, building, hvac, lighting
    )
    
    optimizer = ObjectiveFunction(config)
    data_gen = DatasetGenerator(config['output'].get('log_dir', 'output/logs'))
    
    # Pre-generate meeting schedules
    for zone in building.get_all_zones():
        if 'meeting' in zone.name.lower():
            occupancy_gen.generate_meeting_schedule(
                zone.name, start_date, duration_days
            )
    
    # Simulation loop
    current_time = start_date
    dt_hours = dt / 3600.0
    
    # Progress tracking
    progress_interval = total_steps // 20 if total_steps > 20 else 1
    
    for step in range(total_steps):
        day_index = step * dt // (24 * 3600)
        hour_of_day = current_time.hour + current_time.minute / 60
        
        # Get weather
        weather_state = weather.get_weather(current_time)
        outdoor_temp = weather_state.outdoor_temp_c
        solar_irradiance = weather_state.solar_irradiance_w_m2
        
        # Get occupancy for all zones
        occupancies = occupancy_gen.get_all_occupancies(current_time, day_index)
        
        # Get daylight
        daylight_lux = lighting.get_daylight_lux(solar_irradiance, hour_of_day)
        
        # Prepare zone states for controller
        zone_states = {}
        for zone in building.get_all_zones():
            zone_states[zone.name] = {
                'temperature': zone.state.temperature,
                'illumination': zone.state.illumination,
                'occupancy': occupancies.get(zone.name, 0)
            }
        
        # Get control actions
        if controller_type == 'mpc':
            actions = controller.compute_all_actions(
                zone_states, outdoor_temp, daylight_lux, dt
            )
        else:
            actions = controller.compute_all_actions(
                zone_states, outdoor_temp, daylight_lux
            )
        
        # Apply controls and compute power
        hvac_powers = {}
        lighting_powers = {}
        plug_powers = {}
        internal_gains = {}
        thermal_powers = {}
        
        for zone in building.get_all_zones():
            zone_name = zone.name
            action = actions[zone_name]
            occupancy = occupancies.get(zone_name, 0)
            
            # Apply HVAC control
            hvac.set_setpoint(zone_name, action.hvac_setpoint)
            hvac.set_fan(zone_name, action.fan_on)
            
            # Compute HVAC output
            thermal, electrical, _ = hvac.compute_hvac_output(
                zone_name, zone.state.temperature, outdoor_temp
            )
            hvac_powers[zone_name] = electrical
            thermal_powers[zone_name] = thermal
            
            # Apply lighting control
            lighting.set_dimming(zone_name, action.dimming_level)
            total_lux, _, light_power = lighting.compute_lighting_output(
                zone_name, daylight_lux
            )
            lighting_powers[zone_name] = light_power
            zone.state.illumination = total_lux
            
            # Compute plug loads
            plug_power = plug_loads.compute_plug_load(
                zone_name, occupancy, hour_of_day
            )
            plug_powers[zone_name] = plug_power
            
            # Compute heat gains
            gains = zone.compute_heat_gains(
                occupancy, plug_power, light_power, solar_irradiance
            )
            internal_gains[zone_name] = gains
            
            # Update occupancy in state
            zone.state.occupancy = occupancy
        
        # Update thermal model
        building.step(outdoor_temp, thermal_powers, internal_gains, dt)
        
        # Update energy meter
        energy_meter.update(
            current_time, hvac_powers, lighting_powers, plug_powers, dt
        )
        
        # Evaluate comfort and record data
        for zone in building.get_all_zones():
            zone_name = zone.name
            action = actions[zone_name]
            occupancy = occupancies.get(zone_name, 0)
            
            # Compute comfort metrics
            comfort = optimizer.compute_comfort_metrics(
                zone.state.temperature,
                zone.state.illumination,
                occupancy > 0
            )
            
            # Add sensor noise for recorded data
            sensor_readings = sensors.sample_sensors(
                zone_name,
                zone.state.temperature,
                zone.state.illumination,
                occupancy,
                step * dt
            )
            
            # Record data
            data_gen.add_record(
                timestamp=current_time,
                zone_name=zone_name,
                zone_temp=sensor_readings['temperature'],
                wall_temp=zone.state.wall_temperature,
                outdoor_temp=outdoor_temp,
                humidity=zone.state.humidity,
                co2_ppm=zone.state.co2_ppm,
                illumination=sensor_readings['illumination'],
                occupancy=sensor_readings['occupancy'],
                solar_irradiance=solar_irradiance,
                cloud_cover=weather_state.cloud_cover,
                hvac_setpoint=action.hvac_setpoint,
                fan_on=action.fan_on,
                dimming_level=action.dimming_level,
                hvac_power_w=hvac_powers[zone_name],
                lighting_power_w=lighting_powers[zone_name],
                plug_power_w=plug_powers[zone_name],
                comfort_violation=comfort.comfort_score,
                temp_violation=comfort.temp_violation_deg,
                lux_violation=comfort.lux_violation,
                dt_hours=dt_hours
            )
        
        # Advance time
        current_time += timedelta(seconds=dt)
        
        # Progress update
        if verbose and step > 0 and step % progress_interval == 0:
            progress = (step / total_steps) * 100
            energy_summary = energy_meter.get_summary()
            print(f"  Progress: {progress:.0f}% | "
                  f"Energy: {energy_summary['total_kwh']:.1f} kWh | "
                  f"Day {day_index + 1}/{duration_days}")
    
    # Finalize and save results
    if verbose:
        print("\nSimulation complete!")
        print("Saving results...")
    
    # Create output directories
    log_dir = config['output'].get('log_dir', 'output/logs')
    plot_dir = config['output'].get('plot_dir', 'output/plots')
    os.makedirs(log_dir, exist_ok=True)
    os.makedirs(plot_dir, exist_ok=True)
    
    # Save data
    csv_filename = config['output'].get('csv_filename', 'simulation_log.csv')
    csv_path = data_gen.save_csv(csv_filename)
    
    # Get and save summary
    summary = data_gen.get_summary()
    energy_summary = energy_meter.get_summary()
    
    # Merge summaries
    full_summary = {
        **summary,
        **energy_summary,
        'simulation': {
            'duration_days': duration_days,
            'time_step_seconds': dt,
            'controller_type': controller_type,
            'start_date': start_date.isoformat(),
            'end_date': current_time.isoformat()
        }
    }
    
    summary_filename = config['output'].get('summary_filename', 'summary_metrics.json')
    summary_path = os.path.join(log_dir, summary_filename)
    with open(summary_path, 'w') as f:
        json.dump(full_summary, f, indent=2)
    
    if verbose:
        print(f"\nResults saved to:")
        print(f"  Data: {csv_path}")
        print(f"  Summary: {summary_path}")
        print()
        print("Summary Metrics:")
        print(f"  Total Energy: {full_summary['total_kwh']:.2f} kWh")
        print(f"  Peak Power: {full_summary['peak_kw']:.2f} kW")
        print(f"  Comfort Violation Hours: {full_summary['comfort_violation_hours']:.1f}")
        print(f"  Control Switches: {full_summary['control_switch_count']}")
    
    # Generate plots
    if verbose:
        print("\nGenerating plots...")
    
    generate_plots(data_gen, plot_dir, config)
    
    return full_summary


def generate_plots(data_gen: DatasetGenerator, plot_dir: str, config: Dict):
    """
    Generate visualization plots.
    
    Args:
        data_gen: Dataset generator with records
        plot_dir: Output directory for plots
        config: Configuration dictionary
    """
    try:
        import matplotlib
        matplotlib.use('Agg')  # Non-interactive backend
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
    except ImportError:
        print("Warning: matplotlib not available. Skipping plot generation.")
        return
    
    os.makedirs(plot_dir, exist_ok=True)
    
    # Get zone names
    zone_names = list(set(r.zone_name for r in data_gen.records))
    
    # Prepare data
    for zone_name in zone_names:
        records = data_gen.get_zone_data(zone_name)
        if not records:
            continue
        
        timestamps = [r.timestamp for r in records]
        temps = [r.zone_temperature for r in records]
        setpoints = [r.hvac_setpoint for r in records]
        outdoor = [r.outdoor_temperature for r in records]
        occupancy = [r.occupancy for r in records]
        illumination = [r.illumination for r in records]
        total_power = [r.total_power_w / 1000 for r in records]  # kW
        hvac_power = [r.hvac_power_w / 1000 for r in records]
        lighting_power = [r.lighting_power_w / 1000 for r in records]
        
        # Figure 1: Temperature
        fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)
        
        ax1 = axes[0]
        ax1.plot(timestamps, temps, 'b-', label='Zone Temp', linewidth=0.8)
        ax1.plot(timestamps, setpoints, 'r--', label='Setpoint', linewidth=0.8)
        ax1.plot(timestamps, outdoor, 'g-', label='Outdoor', alpha=0.5, linewidth=0.8)
        ax1.axhspan(config['comfort']['temp_target_min'],
                    config['comfort']['temp_target_max'],
                    alpha=0.2, color='green', label='Comfort Zone')
        ax1.set_ylabel('Temperature (°C)')
        ax1.set_title(f'{zone_name} - Temperature Profile')
        ax1.legend(loc='upper right')
        ax1.grid(True, alpha=0.3)
        
        ax2 = axes[1]
        ax2.fill_between(timestamps, 0, occupancy, alpha=0.5, color='orange', label='Occupancy')
        ax2.set_ylabel('Occupancy')
        ax2.set_title('Occupancy')
        ax2.grid(True, alpha=0.3)
        
        ax3 = axes[2]
        ax3.stackplot(timestamps, hvac_power, lighting_power,
                      labels=['HVAC', 'Lighting'], alpha=0.7)
        ax3.plot(timestamps, total_power, 'k-', label='Total', linewidth=0.8)
        ax3.set_ylabel('Power (kW)')
        ax3.set_xlabel('Time')
        ax3.set_title('Power Consumption')
        ax3.legend(loc='upper right')
        ax3.grid(True, alpha=0.3)
        
        # Format x-axis
        ax3.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
        ax3.xaxis.set_major_locator(mdates.DayLocator(interval=5))
        plt.xticks(rotation=45)
        
        plt.tight_layout()
        plt.savefig(os.path.join(plot_dir, f'{zone_name}_temperature.png'), dpi=150)
        plt.close()
        
        # Figure 2: Lighting
        fig, axes = plt.subplots(2, 1, figsize=(14, 7), sharex=True)
        
        ax1 = axes[0]
        ax1.plot(timestamps, illumination, 'y-', label='Illumination', linewidth=0.8)
        ax1.axhspan(config['comfort']['lux_target_min'],
                    config['comfort']['lux_target_max'],
                    alpha=0.2, color='yellow', label='Target Range')
        ax1.set_ylabel('Illumination (lux)')
        ax1.set_title(f'{zone_name} - Lighting')
        ax1.legend(loc='upper right')
        ax1.grid(True, alpha=0.3)
        
        dimming = [r.dimming_level for r in records]
        ax2 = axes[1]
        ax2.plot(timestamps, dimming, 'm-', label='Dimming Level', linewidth=0.8)
        ax2.fill_between(timestamps, 0, occupancy, alpha=0.3, color='orange', label='Occupancy')
        ax2.set_ylabel('Dimming Level / Occupancy')
        ax2.set_xlabel('Time')
        ax2.set_title('Dimming Control')
        ax2.legend(loc='upper right')
        ax2.grid(True, alpha=0.3)
        
        ax2.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
        ax2.xaxis.set_major_locator(mdates.DayLocator(interval=5))
        plt.xticks(rotation=45)
        
        plt.tight_layout()
        plt.savefig(os.path.join(plot_dir, f'{zone_name}_lighting.png'), dpi=150)
        plt.close()
    
    # Building-wide summary plot
    fig, axes = plt.subplots(2, 1, figsize=(14, 8))
    
    # Aggregate power by timestamp
    from collections import defaultdict
    power_by_time = defaultdict(lambda: {'hvac': 0, 'lighting': 0, 'plug': 0})
    
    for record in data_gen.records:
        key = record.timestamp
        power_by_time[key]['hvac'] += record.hvac_power_w
        power_by_time[key]['lighting'] += record.lighting_power_w
        power_by_time[key]['plug'] += record.plug_power_w
    
    sorted_times = sorted(power_by_time.keys())
    hvac_total = [power_by_time[t]['hvac'] / 1000 for t in sorted_times]
    lighting_total = [power_by_time[t]['lighting'] / 1000 for t in sorted_times]
    plug_total = [power_by_time[t]['plug'] / 1000 for t in sorted_times]
    
    ax1 = axes[0]
    ax1.stackplot(sorted_times, hvac_total, lighting_total, plug_total,
                  labels=['HVAC', 'Lighting', 'Plug Loads'],
                  colors=['#2196F3', '#FFC107', '#4CAF50'], alpha=0.8)
    ax1.set_ylabel('Power (kW)')
    ax1.set_title('Building Total Power Consumption')
    ax1.legend(loc='upper right')
    ax1.grid(True, alpha=0.3)
    
    # Daily energy
    daily_energy = defaultdict(lambda: 0.0)
    dt_hours = config['simulation']['time_step_seconds'] / 3600
    for record in data_gen.records:
        day_key = record.timestamp.date()
        total_power = record.hvac_power_w + record.lighting_power_w + record.plug_power_w
        daily_energy[day_key] += total_power / 1000 * dt_hours
    
    days = sorted(daily_energy.keys())
    daily_kwh = [daily_energy[d] for d in days]
    
    ax2 = axes[1]
    ax2.bar(days, daily_kwh, color='steelblue', alpha=0.7)
    ax2.set_ylabel('Energy (kWh)')
    ax2.set_xlabel('Date')
    ax2.set_title('Daily Energy Consumption')
    ax2.grid(True, alpha=0.3, axis='y')
    plt.xticks(rotation=45)
    
    plt.tight_layout()
    plt.savefig(os.path.join(plot_dir, 'building_summary.png'), dpi=150)
    plt.close()
    
    print(f"Plots saved to {plot_dir}/")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Smart Building Energy Management Simulation',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --days 30 --controller baseline
  python main.py --days 7 --controller mpc
  python main.py --config custom_config.yaml --days 14
        """
    )
    
    parser.add_argument(
        '--days', type=int, default=None,
        help='Number of days to simulate (default: from config)'
    )
    parser.add_argument(
        '--controller', type=str, default='baseline',
        choices=['baseline', 'mpc'],
        help='Controller type (default: baseline)'
    )
    parser.add_argument(
        '--config', type=str, default='config.yaml',
        help='Path to configuration file (default: config.yaml)'
    )
    parser.add_argument(
        '--quiet', action='store_true',
        help='Suppress progress output'
    )
    
    args = parser.parse_args()
    
    # Load configuration
    try:
        config = load_config(args.config)
    except FileNotFoundError:
        print(f"Error: Configuration file '{args.config}' not found.")
        sys.exit(1)
    except yaml.YAMLError as e:
        print(f"Error parsing configuration file: {e}")
        sys.exit(1)
    
    # Run simulation
    try:
        results = run_simulation(
            config=config,
            controller_type=args.controller,
            days=args.days,
            verbose=not args.quiet
        )
    except KeyboardInterrupt:
        print("\nSimulation interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"Error during simulation: {e}")
        raise  # Re-raise for debugging
    
    print("\nDone!")
    return results


if __name__ == '__main__':
    main()
