"""
Smart Building ML API

FastAPI wrapper for occupancy inference and building control decisions.

Provides REST API endpoints for:
- Occupancy prediction with confidence and diagnostics
- Building control decisions (light, HVAC, energy mode)
- Batch processing for multiple sensor readings

Endpoints:
    POST /predict-occupancy  - Get occupancy probability
    POST /control-decision   - Get building control recommendations
    GET  /health            - Health check

Usage:
    uvicorn smart_building_api:app --reload
    then visit: http://localhost:8000/docs for interactive API docs
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Optional, List
import logging
from smart_building_controller import SmartBuildingController
from occupancy_inference_service import OccupancyInferenceService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Smart Building ML API",
    description="ML-powered building automation API",
    version="1.0.0"
)

# Enable CORS for dashboard/simulation integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global controller instance (loaded once on startup)
controller = None
inference_service = None


# Pydantic models for request/response validation
class SensorData(BaseModel):
    """Sensor readings from building."""
    Temperature: Optional[float] = None
    Humidity: Optional[float] = None
    Light: Optional[float] = None
    CO2: Optional[float] = None
    HumidityRatio: Optional[float] = None

    class Config:
        example = {
            "Temperature": 21.5,
            "Humidity": 35.0,
            "Light": 450.0,
            "CO2": 700.0,
            "HumidityRatio": 0.0045
        }


class OccupancyPredictionResponse(BaseModel):
    """Occupancy prediction response."""
    occupancy_probability: float
    occupancy_prediction: int
    confidence: float
    missing_values_count: int
    missing_values_detail: Dict[str, bool]


class ControlDecisionResponse(BaseModel):
    """Building control decision response."""
    occupancy_probability: float
    occupancy_prediction: int
    control_mode: str
    light_action: str
    hvac_action: str
    energy_mode: str
    confidence: float
    missing_values_count: int


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    message: str


@app.on_event("startup")
async def startup_event():
    """Initialize model on startup."""
    global controller, inference_service
    try:
        logger.info("Starting up Smart Building ML API...")

        # Initialize inference service
        inference_service = OccupancyInferenceService(
            "models/domain_adapted_occupancy_pipeline.pkl",
            threshold=0.20
        )
        logger.info("✓ Inference service initialized")

        # Initialize controller
        controller = SmartBuildingController(
            "models/domain_adapted_occupancy_pipeline.pkl",
            empty_threshold=0.20,
            occupied_threshold=0.60
        )
        logger.info("✓ Smart building controller initialized")
        logger.info("✓ API startup complete")

    except Exception as e:
        logger.error(f"Startup error: {e}")
        raise


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    logger.info("Shutting down Smart Building ML API")


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    if controller is None or inference_service is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    return HealthResponse(
        status="healthy",
        message="Smart Building ML API is running"
    )


@app.post("/predict-occupancy", response_model=OccupancyPredictionResponse)
async def predict_occupancy(sensor_data: SensorData):
    """
    Predict occupancy probability from sensor readings.

    Args:
        sensor_data: SensorData object with Temperature, Humidity, Light, CO2, HumidityRatio

    Returns:
        OccupancyPredictionResponse with probability, prediction, and confidence
    """
    if inference_service is None:
        raise HTTPException(status_code=503, detail="Inference service not initialized")

    try:
        # Convert Pydantic model to dict, remove None values
        sensor_dict = {k: v for k, v in sensor_data.dict().items() if v is not None}

        # Handle case where all values are None
        if not sensor_dict:
            raise HTTPException(
                status_code=400,
                detail="At least one sensor value must be provided"
            )

        # Get prediction
        result = inference_service.predict(sensor_dict)

        response = OccupancyPredictionResponse(
            occupancy_probability=result.occupancy_probability,
            occupancy_prediction=result.occupancy_prediction,
            confidence=result.confidence,
            missing_values_count=result.missing_count,
            missing_values_detail=result.missing_values
        )

        logger.info(f"Occupancy prediction: {result.occupancy_probability:.4f} "
                   f"(confidence: {result.confidence:.4f})")
        return response

    except Exception as e:
        logger.error(f"Prediction error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/control-decision", response_model=ControlDecisionResponse)
async def get_control_decision(sensor_data: SensorData):
    """
    Get building control recommendation from sensor readings.

    Args:
        sensor_data: SensorData object with sensor readings

    Returns:
        ControlDecisionResponse with control mode, light/HVAC actions
    """
    if controller is None:
        raise HTTPException(status_code=503, detail="Controller not initialized")

    try:
        # Convert Pydantic model to dict
        sensor_dict = {k: v for k, v in sensor_data.dict().items() if v is not None}

        if not sensor_dict:
            raise HTTPException(
                status_code=400,
                detail="At least one sensor value must be provided"
            )

        # Get control decision
        decision = controller.get_control_decision(sensor_dict)

        response = ControlDecisionResponse(
            occupancy_probability=decision.occupancy_probability,
            occupancy_prediction=decision.occupancy_prediction,
            control_mode=decision.control_mode,
            light_action=decision.light_action,
            hvac_action=decision.hvac_action,
            energy_mode=decision.energy_mode,
            confidence=decision.confidence,
            missing_values_count=decision.missing_values_count
        )

        logger.info(f"Control decision: {decision.control_mode} mode, "
                   f"Light={decision.light_action}, HVAC={decision.hvac_action}")
        return response

    except Exception as e:
        logger.error(f"Control decision error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/batch-occupancy", response_model=List[OccupancyPredictionResponse])
async def batch_predict_occupancy(sensor_data_list: List[SensorData]):
    """
    Predict occupancy for multiple sensor readings.

    Args:
        sensor_data_list: List of SensorData objects

    Returns:
        List of OccupancyPredictionResponse objects
    """
    if inference_service is None:
        raise HTTPException(status_code=503, detail="Inference service not initialized")

    if not sensor_data_list:
        raise HTTPException(
            status_code=400,
            detail="At least one sensor reading must be provided"
        )

    try:
        results = []
        for sensor_data in sensor_data_list:
            sensor_dict = {k: v for k, v in sensor_data.dict().items() if v is not None}
            result = inference_service.predict(sensor_dict)
            response = OccupancyPredictionResponse(
                occupancy_probability=result.occupancy_probability,
                occupancy_prediction=result.occupancy_prediction,
                confidence=result.confidence,
                missing_values_count=result.missing_count,
                missing_values_detail=result.missing_values
            )
            results.append(response)

        logger.info(f"Batch occupancy prediction for {len(results)} readings complete")
        return results

    except Exception as e:
        logger.error(f"Batch prediction error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/batch-control", response_model=List[ControlDecisionResponse])
async def batch_control_decisions(sensor_data_list: List[SensorData]):
    """
    Get building control recommendations for multiple sensor readings.

    Args:
        sensor_data_list: List of SensorData objects

    Returns:
        List of ControlDecisionResponse objects
    """
    if controller is None:
        raise HTTPException(status_code=503, detail="Controller not initialized")

    if not sensor_data_list:
        raise HTTPException(
            status_code=400,
            detail="At least one sensor reading must be provided"
        )

    try:
        results = []
        for sensor_data in sensor_data_list:
            sensor_dict = {k: v for k, v in sensor_data.dict().items() if v is not None}
            decision = controller.get_control_decision(sensor_dict)
            response = ControlDecisionResponse(
                occupancy_probability=decision.occupancy_probability,
                occupancy_prediction=decision.occupancy_prediction,
                control_mode=decision.control_mode,
                light_action=decision.light_action,
                hvac_action=decision.hvac_action,
                energy_mode=decision.energy_mode,
                confidence=decision.confidence,
                missing_values_count=decision.missing_values_count
            )
            results.append(response)

        logger.info(f"Batch control decisions for {len(results)} readings complete")
        return results

    except Exception as e:
        logger.error(f"Batch control error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    logger.info("Starting Smart Building ML API server...")
    logger.info("Available at: http://localhost:8000")
    logger.info("API documentation: http://localhost:8000/docs")
    uvicorn.run(app, host="0.0.0.0", port=8000)
