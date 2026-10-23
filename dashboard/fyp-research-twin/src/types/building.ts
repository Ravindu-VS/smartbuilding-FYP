// Shapes of the edge brain's payload (raspberry_pi/edge_brain.py API v3, twin/live.py).
// Values the backend does not have are null; nothing here has a made-up default.

export interface SensorReadings {
  Temperature: number | null;
  Humidity: number | null;
  Light: number | null;
  CO2: number | null;
  HumidityRatio: number | null;
  PIR_seconds_since_motion?: number | null;   // simulated rooms
  CO2_source?: string | null;                 // hardware room: "scd41_ndir" only
  CO2_rejected?: string;                      // hardware room: why a reported value was not used
  Pressure_hPa?: number | null;
  MQ2_raw?: number | null;
}

export interface AcOption {
  J: number;
  kwh: number;
  recovery_kwh: number;
  discomfort_h: number;
  t_end: number;
}

export interface Reasoning {
  p_now: number | null;
  p_ac: number | null;
  p_future: number | null;
  p_prior: number | null;
  t_pred: number | null;
  t_hold: number | null;
  J_light_options: Record<string, number>;
  ac_options: Record<string, AcOption>;
}

export interface AIResult {
  occupancy_probability: number;
  predicted_occupancy: number;
  confidence: number;
  method: string;                  // "fusion_pir_co2"
  p_ac?: number | null;
  p_future?: number | null;
  random_forest_probability?: number | null;
  seconds_since_presence?: number | null;     // hardware room
  co2_used?: boolean;                         // hardware room
}

export interface AiWould {
  light_action: string;
  hvac_action: string;
  setpoint_c: number | null;
  reason: string;
  reasoning: Reasoning | null;
  basis: string;
}

export interface ControlDecision {
  light_action: string;
  hvac_action: string;
  setpoint_c: number | null;
  vent_boost: boolean;
  control_mode: string;
  controller: string;               // "mo" | "threshold_rf" | "schedule"
  mode?: 'ai' | 'conventional';
  ai_would?: AiWould | null;        // while AI is off: what it would do
  reason: string;
  safety_notes: string[];
  t_pred: number | null;
  reasoning?: Reasoning | null;
  fan_speed?: number;              // hardware room
  light_level?: number;
  servo_angle?: number;
  calibrating?: boolean;
}

export interface HardwareStatus {
  room_id: string;
  connected: boolean;
  state: 'connected' | 'lost' | 'never_connected';
  sender: string | null;
  real_board: boolean;
  last_seen: string | null;
  age_s: number | null;
  timeout_s: number;
  readings_received: number;
  mean_interval_s: number | null;
  led_calibration_lux: number | null;
  led_calibration: string;
  room_name?: string;
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
  light_level?: number | null;
  hvac_mode: string | null;
  hvac_speed: number | null;
  setpoint?: number | null;
  vent_boost?: boolean;
  servo_angle?: number | null;
}

export interface RoomEnergy {
  power_w?: number;
  hvac_w?: number;
  lighting_w?: number;
  plug_w?: number;
  estimated_power_watts?: number | null;
  measured_power_watts?: number | null;
  cumulative_energy_wh: number | null;
  basis?: string | null;
}

export interface RoomComfort {
  pmv: number | null;
  operative_c: number;
  lux_total: number;
  daylight_lux: number;
}

/** The room under one control mode; one copy is the building, the other the twin copy. */
export interface ModeView {
  copy: 'building' | 'twin';
  power_w: number;
  temperature: number;
  co2: number | null;
  pmv: number | null;
  light_action: string;
  hvac_action: string;
  setpoint_c: number | null;
  vent_boost: boolean;
  energy_wh: number;               // this mode, same minutes for both modes
}

export interface MeterSegment {
  mode: 'ai' | 'conventional';
  start: string;
  end: string | null;
  minutes: number;
  kwh: number;
  other_kwh: number;
  peak_kw: number;
  avg_kw: number | null;
  other_avg_kw: number | null;
  occ_min: number;
  uncomfortable_min: number;
  uncomfortable_pct: number | null;
  ai_saving_pct: number | null;
}

export interface RealRoomMeter {
  room_id: string;
  room_name: string;
  power_w: number | null;
  total_wh: number;
  segments: { mode: 'ai' | 'conventional'; start: string; end: string | null; seconds: number; wh: number; measured: boolean; avg_w: number | null }[];
  by_mode: Record<'ai' | 'conventional', { seconds: number; wh: number; avg_w: number | null }>;
  basis: string;
}

export interface Meter {
  ai_enabled: boolean;
  mode: 'ai' | 'conventional';
  power_kw: number;
  other_power_kw: number;
  total_kwh: number;
  current: MeterSegment | null;
  segments: MeterSegment[];
  building_by_mode: Record<'ai' | 'conventional', { minutes: number; kwh: number; avg_kw: number | null }>;
  same_hours?: { hour: number; ai_avg_kw: number | null; ai_minutes: number; conv_avg_kw: number | null; conv_minutes: number }[];
  real_rooms?: RealRoomMeter[];
}

export interface Disturbances {
  extra_gain_w: number;
  co2_release_ls: number;
  window_ach: number;
  forced_occupancy_until: string | null;
}

export interface RoomState {
  room_id: string;
  room_type: string;
  floor_id: number;
  display_name: string;
  source: 'hardware' | 'simulated';
  timestamp: string | null;
  sensors: SensorReadings;
  ai: AIResult | null;
  control: ControlDecision | null;
  device_state: DeviceState | null;
  energy: RoomEnergy | null;
  ground_truth: { true_occupancy: number; max_occupancy: number } | null;
  comfort?: RoomComfort | null;
  modes?: { ai: ModeView; conventional: ModeView } | null;
  meter?: RealRoomMeter;
  scenarios?: string[];
  disturbances?: Disturbances;
  area_m2?: number;
  design_setpoint_c?: number;
  watched?: boolean;
  hardware?: HardwareStatus;
  presence?: PresenceReadings | null;
  power_measurement?: { voltage_v: number | null; current_mA: number | null; power_mW: number | null; available: boolean } | null;
  sensor_health?: Record<string, boolean> | null;
  room_number?: number;                 // 101 = the real room, 102-126 = simulated (labels; ids stay the keys)
  provenance?: Record<string, string>;  // synthetic | room101_measured | prediction | unavailable
  prediction?: { temperature_30min?: ThermalPrediction | null } | null;
  freshness?: { age_s: number | null; timeout_s: number; stale: boolean; state: string } | null;
}

export interface ThermalPrediction {
  predicted_c: number; for_time: string; made_at: string; model: string; provenance: 'prediction';
}

export interface Clock {
  time: string;
  date: string;
  weekday: string;
  iso: string;
  speed: number;
  running: boolean;
  fast_forward_minutes: number;
  fast_forward_total_minutes: number;
  seed: number;
  phase: 'learning' | 'running';
  ai_enabled: boolean;
  learning_progress: number;
  learning_days: number;
  start: string;
  control_step_s: number;
  physics_step_s: number;
  step_ms_median: number | null;
  outdoor_c: number;
  outdoor_rh: number;
  outdoor_lux: number;
  cloud_cover: number;
  sun_altitude: number;
}

export interface FloorState {
  floor_id: number;
  power_w: number;
  ai_power_w: number;
  conv_power_w: number;
  ai_energy_kwh: number;
  conv_energy_kwh: number;
  people: number;
  rooms_occupied: number;
  rooms_predicted_occupied: number;
  mean_temperature: number | null;
  simulated_rooms: number;
  hardware_rooms?: string[];
}

export interface ResultSummary {
  total_kwh: number;
  end_use_kwh: { hvac: number; lighting: number; plug: number };
  floor_kwh: Record<string, number>;
  cost_lkr: number;
  power_w: number;
  peak_15min_kw: number;
  thermal_discomfort_pct: number;
  thermal_discomfort_basis: string;
  comfort_by_type: Record<string, { occupied_min: number; pmv_over_0_5_pct: number; mean_pmv: number }>;
  visual_discomfort_pct: number;
  co2_over_1000_pct: number;
  lights_on_empty_pct: number;
  ac_on_empty_pct: number;
  ac_onoff_per_room_day: number | null;
  occupied_room_minutes: number;
  minutes: number;
}

export interface Confusion {
  n: number; tp: number; fp: number; fn: number; tn: number;
  accuracy: number | null; precision: number | null; recall: number | null; f1: number | null;
}

export interface Comparison {
  ai_controller: string;
  ai_label: string;
  conventional_label: string;
  ai: ResultSummary;
  conventional: ResultSummary;
  saving_pct: number | null;
  basis: string;
  tariff_lkr_per_kwh: number;
  tariff_note: string;
  occupancy_fusion: Confusion;
  occupancy_random_forest: Confusion | null;
  since: string;
}

export interface TimelineEvent {
  seq: number;
  kind: 'decision' | 'assessment' | 'scenario' | 'system' | 'learning' | 'switch';
  mode?: 'ai' | 'conventional';
  source?: 'hardware';
  sim_time: string | null;
  real_time?: string;
  room_id: string | null;
  room_name: string | null;
  floor_id: number | null;
  controller?: string;
  summary: string;
  why?: string[];
  observed?: Record<string, number | boolean | null>;
  simulator_truth?: { occupants: number } | null;
  proposed?: { light: string; hvac: string; setpoint: number | null };
  safety?: { accepted: boolean; notes: string[] };
  validated?: { light: string; hvac: string; sp: number | null; vent: boolean };
  previous?: { light: string; hvac: string; sp: number | null; vent: boolean };
  expected?: Record<string, unknown>;
  reasoning?: Reasoning | null;
  outcome?: Record<string, number | boolean | string | null> | null;
}

export interface ScenarioInfo {
  id: number;
  kind: string;
  room_id: string | null;
  value: number;
  label: string;
  start: string;
  end: string;
}

export interface Alert { level: 'warning' | 'critical'; room_id: string; text: string }

export interface SystemState {
  total_rooms: number;
  simulated_rooms: number;
  hardware_room_id: string;
  rooms_with_data: number;
  occupied_rooms: number;
  empty_rooms: number;
  people_simulated: number;
  sim_power_watts: number;
  hardware_room_ids: string[];
  ai_enabled: boolean;
  ai_controller: string;
  ai_controller_label: string;
  estimator: string;
  phase: string;
  simulation_running: boolean;
  simulation_time: string;
  simulation_speed_factor: number;
  outdoor_temp_c: number;
  outdoor_humidity: number;
  update_interval: number;
  last_tick_age_s: number | null;
  data_stale: boolean;
  gpio_driving: boolean;
  started_at: string;
  random_forest_loaded: boolean;
  hardware: HardwareStatus;
}

export interface BuildingStatePayload {
  api_version: number;
  timestamp: string;
  seq: number;
  ai_enabled: boolean;
  rooms: RoomState[];
  hardware: HardwareStatus;
  hardware_rooms: HardwareStatus[];
  meter: Meter;
  clock: Clock;
  floors: FloorState[];
  comparison: Comparison;
  scenarios: ScenarioInfo[];
  alerts: Alert[];
  timeline: TimelineEvent[];
  watch: string[];
  system: SystemState;
}

export interface BuildingConfigRoom {
  room_id: string; room_number?: number; name: string; type: string; floor_id: number;
  x: number; z: number; w: number; d: number; area_m2: number; max_occupancy: number;
  data_source: string; window_area_m2: number; lighting_w: number; ac_capacity_w: number;
  schedule_hours: [number, number, boolean]; equipment_cooled: boolean;
  design_setpoint_c: number; transit: boolean; neighbours: string[];
}

export interface BuildingConfig {
  building: { name: string; width_m: number; depth_m: number; floor_height_m: number; slab_m: number; floors: number };
  floors: { floor_id: number; name: string; floor_type: string; rooms: string[] }[];
  rooms: BuildingConfigRoom[];
  controllers: { id: string; label: string; available?: boolean; availability?: string }[];
  scenarios: string[];
  hardware_room_id: string;
  hardware_room_ids: string[];
  api_version: number;
}

export interface HistoryPoint {
  t: string;
  temperature: number | null;
  humidity?: number | null;
  co2: number | null;
  lux: number | null;
  occupants?: number;
  presence?: boolean | null;
  p_occ: number | null;
  p_rf: number | null;
  light: string;
  hvac: string;
  setpoint: number | null;
  power_w: number | null;
  pmv?: number | null;
  mode?: 'ai' | 'conventional' | null;
  ai_power_w?: number;
  ai_temperature?: number;
  conv_power_w?: number;
  conv_temperature?: number;
}

export interface SeriesPoint {
  t: string;
  mode: 'ai' | 'conventional';
  power_kw: number;
  ai_power_kw: number;
  conv_power_kw: number;
  meter_kwh: number;
  ai_kwh: number;
  conv_kwh: number;
  outdoor_c: number;
  occupied_rooms: number;
  people: number;
}

export interface TwinSyncReport {
  matched: number;
  received: number;
  modelRooms: number;
  unmatched: string[];
  seq: number | null;
}

// /api/models and /api/provenance (model registry, shadow mode, drift, data sources)
export interface LiveModel {
  task: string; role: 'shadow' | 'active'; version: string | null; loaded: boolean; error: string | null;
  approved_version: string | null; features: string[] | null; trained_utc: string | null;
  provenance_of_training_data: string | null;
}
export interface ConfusionSummary { n: number; accuracy: number | null; precision: number | null; recall: number | null; f1: number | null }
export interface DriftReport { rows: number; enough_data: boolean; status: string; max_psi?: number; features: Record<string, { psi?: number; out_of_range?: number; missing_share: number }> }
export interface ModelsStatus {
  registry: Record<string, { active: string | null; versions: string[]; candidates: string[]; last_event: { action: string; version: string; utc: string } | null }>;
  live: null | {
    loaded_at: string; models: LiveModel[];
    shadow: { task: string; version: string | null; compared_room_steps: number; agreement_with_active: number | null;
              candidate_vs_truth: ConfusionSummary; active_vs_truth: ConfusionSummary; active: string; note: string };
    thermal: { task: string; version: string | null; scored: number; live_mae_c: number | null; live_bias_c: number | null; basis: string };
    drift: { real_room_inputs_vs_occupancy_rf_training: DriftReport | null; simulated_inputs_vs_shadow_training: DriftReport | null };
    errors: string[];
  };
  live_error: string | null;
  controllers: { id: string; label: string; available: boolean; availability: string }[];
  active_controller: string; random_forest_source: string | null;
}
export interface ProvenanceStatus {
  classes: Record<string, string> | null;
  rooms: { room_id: string; room_number: number; source: string; measurements: string }[];
  weather: string;
  store: null | { schema_version: number; tables: Record<string, number>; provenance: Record<string, Record<string, number>> };
  datasets: Record<string, { name: string; licence: string; accessed: string; provenance: string; landing_page: string }>;
}
