"""
Pydantic schemas for all API request/response models.
Provides type safety and automatic OpenAPI documentation.
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


# ═══════════════════════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════════════════════

class HVACMode(str, Enum):
    OFF = "off"
    COOLING = "cooling"
    HEATING = "heating"
    ECO = "eco"
    AUTO = "auto"


class DataSource(str, Enum):
    HARDWARE = "hardware"
    SIMULATED = "simulated"


class RoomType(str, Enum):
    OFFICE = "office"
    MEETING_ROOM = "meeting_room"
    CORRIDOR = "corridor"
    LOBBY = "lobby"
    SERVER_ROOM = "server_room"


# ═══════════════════════════════════════════════════════════════════════════
# SENSOR SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════

class SensorReading(BaseModel):
    """Raw sensor telemetry from ESP32 or simulation."""
    room_id: str = Field(..., description="Unique room identifier, e.g. 'f1_room_101'")
    temperature: float = Field(..., ge=-10, le=60, description="Temperature in °C")
    humidity: float = Field(..., ge=0, le=100, description="Relative humidity %")
    co2: float = Field(default=400.0, ge=0, le=5000, description="CO₂ concentration in ppm")
    lux: float = Field(default=0.0, ge=0, le=10000, description="Light intensity in lux")
    timestamp: Optional[datetime] = Field(default=None, description="Sensor reading timestamp")
    source: DataSource = Field(default=DataSource.SIMULATED)

    class Config:
        json_schema_extra = {
            "example": {
                "room_id": "f1_room_101",
                "temperature": 24.5,
                "humidity": 55.0,
                "co2": 450.0,
                "lux": 380.0,
                "source": "hardware"
            }
        }


class SensorIngestRequest(BaseModel):
    """Request body for sensor data ingestion (from WSO2 MI or direct)."""
    topic: Optional[str] = Field(default=None, description="MQTT topic path")
    room_id: Optional[str] = Field(default=None, description="Room ID override")
    telemetry: Dict[str, float] = Field(..., description="Sensor readings map")
    source: str = Field(default="hardware")
    timestamp: Optional[str] = None


class SensorIngestResponse(BaseModel):
    status: str
    room_id: str
    message: str
    occupancy_prediction: Optional[float] = None


# ═══════════════════════════════════════════════════════════════════════════
# ENERGY SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════

class EnergyCurrentResponse(BaseModel):
    """Current energy consumption snapshot."""
    timestamp: datetime
    total_power_watts: float
    hvac_power_watts: float
    lighting_power_watts: float
    plug_power_watts: float
    total_cumulative_energy_wh: float
    baseline_energy_wh: float
    ai_energy_wh: float
    energy_saved_wh: float
    percentage_saved: float
    comfort_score: float


class EnergyHistoryEntry(BaseModel):
    timestamp: datetime
    power_watts: float
    energy_wh: float
    zone: Optional[str] = None


class EnergyHistoryResponse(BaseModel):
    entries: List[EnergyHistoryEntry]
    total_records: int
    time_range_hours: float


class EnergyPredictionResponse(BaseModel):
    """24-hour energy forecast from Random Forest model."""
    timestamp: datetime
    predictions: List[Dict[str, float]]  # [{hour: 0, predicted_wh: 123.4}, ...]
    model_type: str = "RandomForest"
    confidence: Optional[float] = None


# ═══════════════════════════════════════════════════════════════════════════
# BUILDING SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════

class RoomState(BaseModel):
    """Complete state of a single room."""
    room_id: str
    room_name: str
    floor: int
    room_type: str
    temperature: float
    humidity: float
    co2: float
    lux: float
    occupancy: int
    occupancy_probability: float
    hvac_setpoint: float
    hvac_mode: str
    dimming_level: float
    power_watts: float
    cumulative_energy_wh: float
    data_source: str
    last_update: Optional[datetime] = None


class FloorState(BaseModel):
    floor_number: int
    rooms: List[RoomState]
    total_power_watts: float
    occupied_rooms: int


class BuildingStatusResponse(BaseModel):
    """Full building state for digital twin visualization."""
    timestamp: datetime
    building_name: str
    total_floors: int
    total_rooms: int
    occupied_rooms: int
    floors: List[FloorState]
    total_power_watts: float
    total_cumulative_energy_wh: float
    simulation_running: bool
    outdoor_temperature: Optional[float] = None


# ═══════════════════════════════════════════════════════════════════════════
# OPTIMIZATION SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════

class OptimizationWeights(BaseModel):
    """Multi-objective optimization cost weights."""
    alpha: float = Field(0.4, ge=0, le=1, description="Energy weight")
    beta: float = Field(0.35, ge=0, le=1, description="Comfort weight")
    gamma: float = Field(0.25, ge=0, le=1, description="Stability weight")


class OptimizationAction(BaseModel):
    """AI optimization decision for a room."""
    room_id: str
    hvac_setpoint: float
    dimming_level: float
    fan_on: bool
    reasoning: Optional[str] = None


class OptimizationResponse(BaseModel):
    timestamp: datetime
    actions: List[OptimizationAction]
    total_estimated_savings_percent: float
    controller_type: str  # "rule_based", "ppo", "mpc"


# ═══════════════════════════════════════════════════════════════════════════
# AI / ASSISTANT SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════

class AssistantQuery(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)


class AssistantResponse(BaseModel):
    response: str
    context_retrieved: Optional[Dict[str, Any]] = None
    llm_used: str


class AnomalyReport(BaseModel):
    room_id: str
    anomaly_type: str
    severity: str  # "low", "medium", "high", "critical"
    description: str
    detected_at: datetime
    anomaly_score: float


class AnomalyListResponse(BaseModel):
    anomalies: List[AnomalyReport]
    total_count: int


class OccupancyPrediction(BaseModel):
    room_id: str
    occupancy_probability: float
    occupancy_prediction: int
    confidence: float
    model_type: str = "LogisticRegression"


class AgentDecisionRequest(BaseModel):
    """Input for the autonomous energy agent."""
    temperature: float
    occupancy: str  # "low", "medium", "high"
    energy_price: str  # "low", "medium", "high"
    time_of_day: Optional[int] = None


class AgentDecisionResponse(BaseModel):
    decision: str
    actions: List[OptimizationAction]
    reasoning: str
    estimated_savings: float


# ═══════════════════════════════════════════════════════════════════════════
# AUTH SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════

class TokenRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


# ═══════════════════════════════════════════════════════════════════════════
# HEALTH / GENERAL
# ═══════════════════════════════════════════════════════════════════════════

class HealthResponse(BaseModel):
    status: str
    version: str
    uptime_seconds: float
    model_loaded: bool
    simulation_active: bool
    mqtt_connected: bool
    database_connected: bool
    redis_connected: bool
