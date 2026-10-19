"""
Sensor Data Router — Handles IoT telemetry ingestion and retrieval.
"""
from fastapi import APIRouter, HTTPException, Depends
from typing import Optional
from datetime import datetime

from app.models.schemas import SensorIngestRequest, SensorIngestResponse, SensorReading

router = APIRouter(prefix="/sensors", tags=["Sensors"])

# Service instance (injected via app state)
_sensor_service = None


def get_sensor_service():
    if _sensor_service is None:
        raise HTTPException(status_code=503, detail="Sensor service not initialized")
    return _sensor_service


@router.post("/ingest", response_model=SensorIngestResponse,
             summary="Ingest sensor telemetry",
             description="Receive sensor data from ESP32 via WSO2 MI or direct HTTP POST")
async def ingest_sensor_data(payload: SensorIngestRequest):
    """
    Ingest real-time sensor telemetry.
    Accepts data from WSO2 Micro Integrator or direct ESP32 HTTP POST.
    """
    service = get_sensor_service()
    try:
        result = service.ingest_telemetry(payload.model_dump())
        return SensorIngestResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{room_id}/latest",
            summary="Get latest sensor reading",
            description="Retrieve the most recent sensor data for a specific room")
async def get_latest_sensor(room_id: str):
    """Get the most recent sensor reading for a room."""
    service = get_sensor_service()
    reading = service.get_latest_reading(room_id)
    if reading is None:
        raise HTTPException(status_code=404, detail=f"No data for room {room_id}")
    return reading
