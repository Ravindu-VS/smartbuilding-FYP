// Shapes of the edge brain's SSE payload (raspberry_pi/edge_brain.py, get_current_state).
// Values the backend does not have are null; nothing here has a made-up default.

export interface SensorReadings {
  Temperature: number | null;
  Humidity: number | null;
  Light: number | null;
  CO2: number | null;
  HumidityRatio: number | null;
  CO2_source?: string | null;      // "scd41_ndir" | "mq2_estimate" (hardware room only)
  Pressure_hPa?: number | null;
  MQ2_raw?: number | null;
}

export interface AIResult {
  occupancy_probability: number;
  predicted_occupancy: number;
  confidence: number;
  method: string;                  // "random_forest" | "heuristic_fallback"
}

export interface ControlDecision {
  light_action: string;
  hvac_action: string;
  control_mode: string;
  estimated_power_watts: number | null;
  fan_speed: number;
  light_level: number;
  servo_angle: number;
}

export interface HardwareStatus {
  room_id: string;
  connected: boolean;
  state: 'connected' | 'lost' | 'never_connected';
  sender: string | null;           // "esp32_board" for the firmware, e.g. "test_sender" otherwise
  real_board: boolean;
  last_seen: string | null;        // server time of the last reading
  age_s: number | null;            // age of the last reading when this state was sent
  timeout_s: number;
  readings_received: number;
  mean_interval_s: number | null;
}

export interface PresenceReadings {
  pir_motion: boolean | null;
  mmwave_presence: boolean | null;
  mmwave_moving: boolean | null;
  mmwave_stationary: boolean | null;
  mmwave_distance_cm: number | null;
  fused_presence: boolean | null;
  source: string | null;
}

export interface DeviceState {
  light_on: boolean | null;
  hvac_mode: string | null;
  hvac_speed: number | null;
  light_level?: number | null;
  servo_angle?: number | null;
}

export interface PowerMeasurement {
  voltage_v: number | null;
  current_mA: number | null;
  power_mW: number | null;
  available: boolean;
}

export interface RoomEnergy {
  estimated_power_watts: number | null;
  measured_power_watts?: number | null;
  cumulative_energy_wh: number | null;
}

export interface RoomState {
  room_id: string;
  room_type: string;
  floor_id: number;
  display_name: string;
  source: 'hardware' | 'simulated';
  timestamp: string | null;        // sim clock for simulated rooms, receive time for the hardware room
  sensors: SensorReadings;
  ai: AIResult | null;
  control: ControlDecision | null;
  device_state: DeviceState | null;
  energy: RoomEnergy | null;
  ground_truth: { true_occupancy: number; max_occupancy: number } | null;
  hardware?: HardwareStatus;
  presence?: PresenceReadings | null;
  power_measurement?: PowerMeasurement | null;
  sensor_health?: Record<string, boolean> | null;
}

export interface SystemState {
  total_rooms: number;
  simulated_rooms: number;
  hardware_room_id: string;
  rooms_with_data: number;
  occupied_rooms: number;
  empty_rooms: number;
  sim_estimated_power_watts: number;
  sim_cumulative_energy_wh: number;
  hardware_measured_power_watts: number | null;
  model_loaded: boolean;
  model_name: string | null;
  controller: string;
  ai_accuracy_simulated: { accuracy: number | null; room_ticks: number; reference: string };
  simulation_running: boolean;
  simulation_time: string | null;
  simulation_speed_factor: number;
  day_count: number;
  outdoor_temp_c: number;
  outdoor_humidity: number;
  update_interval: number;
  last_tick_age_s: number | null;
  data_stale: boolean;
  gpio_driving: boolean;
  started_at: string;
  hardware: HardwareStatus;
}

export interface BuildingStatePayload {
  timestamp: string;
  seq: number;
  rooms: RoomState[];
  hardware: HardwareStatus;
  system: SystemState;
}

export interface TwinSyncReport {
  matched: number;
  received: number;
  modelRooms: number;
  unmatched: string[];
  seq: number | null;
}
