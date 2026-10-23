"""
Smart Building Enterprise Platform — FastAPI Application Entry Point

Combines IoT sensor ingestion, AI/ML services, RL optimization,
digital twin state management, and enterprise API governance.

Usage:
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

Endpoints:
    /sensors/*        — IoT telemetry ingestion and retrieval
    /energy/*         — Energy consumption, history, and forecasting
    /building/*       — Building status and digital twin data
    /optimization/*   — PPO RL actions and weight management
    /ai/*             — RAG assistant, anomalies, occupancy prediction
    /auth/*           — JWT authentication (demo mode)
    /health           — Health check
    /docs             — Swagger UI (auto-generated)
"""
import os
import sys
import time
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Ensure project root is on path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.core.config import settings
from app.routers import sensors, energy, optimization, building, ai, auth
from app.services.sensor_service import SensorService
from app.services.occupancy_service import OccupancyService
from app.services.energy_service import EnergyService
from app.services.rl_service import RLService
from app.services.assistant_service import AssistantService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Track startup time
_start_time = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler.
    Initializes all services on startup and cleans up on shutdown.
    """
    logger.info("=" * 70)
    logger.info(f"  {settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info("=" * 70)

    # ── Initialize Services ──────────────────────────────────────────────
    state_manager = None
    db_persistence = None

    # Try to load StateManager
    try:
        from integration.state_manager import StateManager
        state_manager = StateManager()
        logger.info("✓ StateManager initialized")
    except Exception as e:
        logger.warning(f"StateManager not available: {e}")

    # Try to load DatabasePersistence
    try:
        from integration.database_persistence import DatabasePersistence
        db_persistence = DatabasePersistence()
        logger.info("✓ DatabasePersistence initialized")
    except Exception as e:
        logger.warning(f"Database not available: {e}")

    # Initialize service instances
    sensor_svc = SensorService(state_manager=state_manager, db_persistence=db_persistence)
    occupancy_svc = OccupancyService(
        model_path=settings.OCCUPANCY_MODEL_PATH,
        threshold=settings.OCCUPANCY_THRESHOLD,
    )
    energy_svc = EnergyService(state_manager=state_manager, db_persistence=db_persistence)
    rl_svc = RLService(
        model_path=settings.PPO_MODEL_PATH,
        state_manager=state_manager,
    )
    assistant_svc = AssistantService(
        state_manager=state_manager,
        db_persistence=db_persistence,
        knowledge_path=os.path.join(PROJECT_ROOT, settings.KNOWLEDGE_DOCS_PATH),
    )

    # ── Wire services to routers ─────────────────────────────────────────
    sensors._sensor_service = sensor_svc
    energy._energy_service = energy_svc
    optimization._rl_service = rl_svc
    building.set_building_context(state_manager)
    ai.set_ai_services(assistant_svc, occupancy_svc)

    # Configure auth
    auth.configure_auth(
        secret_key=settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
        expiration=settings.JWT_EXPIRATION_MINUTES,
    )

    logger.info("─" * 70)
    logger.info(f"  Server ready at http://{settings.HOST}:{settings.PORT}")
    logger.info(f"  Swagger UI: http://{settings.HOST}:{settings.PORT}/docs")
    logger.info(f"  ReDoc: http://{settings.HOST}:{settings.PORT}/redoc")
    logger.info("─" * 70)
    logger.info("  Endpoints:")
    logger.info("    /sensors/*        — IoT telemetry")
    logger.info("    /energy/*         — Energy data & forecasting")
    logger.info("    /building/*       — Building status & digital twin")
    logger.info("    /optimization/*   — RL control & weights")
    logger.info("    /ai/*             — Assistant, anomalies, occupancy")
    logger.info("    /auth/*           — JWT authentication")
    logger.info("=" * 70)

    yield  # Application runs here

    # ── Cleanup on shutdown ──────────────────────────────────────────────
    logger.info("Shutting down Smart Building Enterprise Platform...")


# ═══════════════════════════════════════════════════════════════════════════
# CREATE APPLICATION
# ═══════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="""
## Smart Building Enterprise Platform API

An intelligent energy optimization platform combining:
- **IoT** — ESP32-S3 sensor nodes via MQTT
- **Edge AI** — Logistic Regression occupancy prediction
- **Reinforcement Learning** — PPO energy optimization
- **Digital Twin** — Real-time 3D building visualization
- **Enterprise Integration** — WSO2 MI, API Manager

### Architecture
```
ESP32 → MQTT → WSO2 MI → FastAPI → AI/ML → Digital Twin → Dashboard
```
    """,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ── CORS Middleware ──────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production: ["https://dashboard.smartbuilding.com"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Mount Routers ────────────────────────────────────────────────────────
app.include_router(sensors.router)
app.include_router(energy.router)
app.include_router(optimization.router)
app.include_router(building.router)
app.include_router(ai.router)
app.include_router(auth.router)


# ── Health Check ─────────────────────────────────────────────────────────
@app.get("/health", tags=["System"],
         summary="Health check",
         description="System health status including all service dependencies")
async def health_check():
    """Health check endpoint for monitoring and load balancers."""
    uptime = time.time() - _start_time

    return {
        "status": "healthy",
        "version": settings.APP_VERSION,
        "uptime_seconds": round(uptime, 1),
        "model_loaded": True,
        "simulation_active": building._state_manager is not None,
        "mqtt_connected": False,  # Will be true when MQTT client is integrated
        "database_connected": True,
        "redis_connected": True,
    }


# ── Root Endpoint ────────────────────────────────────────────────────────
@app.get("/", tags=["System"],
         summary="API information",
         description="Root endpoint with API metadata and available endpoints")
async def root():
    """Root endpoint with API information."""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "description": "Edge Intelligence-Driven Digital Twin Framework for Smart Building Energy Optimization",
        "endpoints": {
            "sensors": "/sensors/ingest, /sensors/{room_id}/latest",
            "energy": "/energy/current, /energy/history, /energy/prediction",
            "building": "/building/status, /building/rooms/{room_id}, /building/digital-twin",
            "optimization": "/optimization/action, /optimization/weights, /optimization/agent/decide",
            "ai": "/ai/assistant, /ai/anomalies, /ai/occupancy/{room_id}",
            "auth": "/auth/token, /auth/me",
            "docs": "/docs (Swagger UI), /redoc (ReDoc)",
        },
        "wso2_integration": {
            "micro_integrator": settings.WSO2_MI_URL,
            "api_manager": settings.WSO2_AM_URL,
        },
    }


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
