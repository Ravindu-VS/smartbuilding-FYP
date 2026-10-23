"""
AI Router — Assistant, anomalies, occupancy prediction, and autonomous agent.
"""
from fastapi import APIRouter, HTTPException
from datetime import datetime
from typing import Optional

from app.models.schemas import (
    AssistantQuery,
    AssistantResponse,
    AnomalyListResponse,
    OccupancyPrediction,
)

router = APIRouter(prefix="/ai", tags=["AI"])

_assistant_service = None
_occupancy_service = None


def set_ai_services(assistant_service, occupancy_service):
    global _assistant_service, _occupancy_service
    _assistant_service = assistant_service
    _occupancy_service = occupancy_service


@router.post("/assistant", response_model=AssistantResponse,
             summary="Building Knowledge Assistant",
             description="RAG-powered AI assistant for building queries. Uses building manuals, energy policies, and live data.")
async def query_assistant(query: AssistantQuery):
    """
    Smart Building AI Assistant with RAG.
    Answers questions about energy usage, comfort, maintenance, and building policies.
    """
    if _assistant_service is None:
        raise HTTPException(status_code=503, detail="AI Assistant not initialized")

    try:
        result = _assistant_service.query(query.message)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/anomalies",
            summary="Predictive maintenance anomalies",
            description="Detect abnormal energy usage, equipment problems, and sensor drift")
async def get_anomalies():
    """Get current anomaly detections from the predictive maintenance module."""
    if _assistant_service is None:
        return {"anomalies": [], "total_count": 0}

    try:
        anomalies = _assistant_service.get_anomalies()
        return {
            "anomalies": anomalies,
            "total_count": len(anomalies),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/occupancy/{room_id}",
            summary="Real-time occupancy prediction",
            description="ML-based occupancy prediction for a specific room using sensor data")
async def predict_occupancy(room_id: str):
    """Predict occupancy for a specific room using its current sensor state."""
    if _occupancy_service is None:
        raise HTTPException(status_code=503, detail="Occupancy service not initialized")

    try:
        result = _occupancy_service.predict_for_room(room_id)
        result["room_id"] = room_id
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
