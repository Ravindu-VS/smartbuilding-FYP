export interface RoomSensorData {
  temperature: number;
  humidity: number;
  light: number;
  co2: number;
  humidity_ratio: number;
  occupancy?: number;
  edge_occupancy_probability?: number;
}

export interface RoomAIState {
  occupancy_probability: number;
  predicted_occupancy: number;
}

export interface RoomControlState {
  control_mode: string;
  hvac_action: string;
  light_action: string;
  hvac?: string;
  light?: string;
}

export interface RoomDeviceState {
  hvac_mode: string;
  hvac_speed: number;
  light_on: boolean;
}

export interface RoomEnergyState {
  estimated_power_watts: number;
  cumulative_energy_wh: number;
  optimization: {
    energy_saved_wh: number;
    percentage_saved: number;
    baseline_power_watts: number;
  }
}

export interface RoomGroundTruth {
  true_occupancy: number;
  max_occupancy: number;
}

export interface RoomState {
  room_id: string; // e.g., "f2_office_a"
  room_type: string;
  floor_id: number;
  display_name: string;
  source: string; // "hardware" or "simulation"
  timestamp: string;
  
  sensors: RoomSensorData;
  ai: RoomAIState;
  control: RoomControlState;
  device_state: RoomDeviceState;
  energy: RoomEnergyState;
  ground_truth: RoomGroundTruth;
  
  // Custom flags for the frontend
  isLive?: boolean;
}

export interface SystemState {
  total_power_watts: number;
  total_cumulative_energy_wh: number;
  energy_saved_wh: number;
  percentage_saved: number;
  baseline_power_watts: number;
  baseline_energy_wh: number;
  ai_power_watts: number;
  ai_energy_wh: number;
  
  total_rooms: number;
  occupied_rooms: number;
  empty_rooms: number;
  
  api_online: boolean;
  model_loaded: boolean;
  simulation_running: boolean;
  simulation_connected: boolean;
  simulation_time: string | null;
  update_interval: number;
  
  latency?: number; // Calculated frontend latency
}

export interface BuildingStatePayload {
  timestamp: string;
  rooms: RoomState[];
  floors?: any[];
  system: SystemState;
  message?: string;
}
