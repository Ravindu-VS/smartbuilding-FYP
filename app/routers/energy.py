"""
Energy Router — Current consumption, history, and predictions.
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from datetime import datetime

from app.models.schemas import EnergyCurrentResponse, EnergyHistoryResponse, EnergyPredictionResponse

router = APIRouter(prefix="/energy", tags=["Energy"])

_energy_service = None


def get_energy_service():
    if _energy_service is None:
        raise HTTPException(status_code=503, detail="Energy service not initialized")
    return _energy_service


@router.get("/current",
            summary="Current energy consumption",
            description="Real-time energy consumption snapshot across the entire building")
async def get_current_energy():
    """Get current real-time energy consumption for the entire building."""
    service = get_energy_service()
    data = service.get_current_energy()
    return data


@router.get("/history",
            summary="Historical energy data",
            description="Retrieve historical energy consumption with configurable time range")
async def get_energy_history(
    hours: float = Query(default=24.0, ge=1.0, le=720.0,
                         description="Number of hours of history to retrieve")
):
    """Get historical energy data for the specified time range."""
    service = get_energy_service()
    data = service.get_energy_history(hours=hours)
    return data


@router.get("/prediction",
            summary="24-hour energy forecast",
            description="AI-powered energy consumption prediction for the next 24 hours using Random Forest")
async def get_energy_prediction():
    """Get 24-hour energy forecast using the Random Forest model."""
    service = get_energy_service()
    data = service.get_energy_prediction()
    return data
