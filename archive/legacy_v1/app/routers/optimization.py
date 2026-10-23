"""
Optimization Router — Multi-objective weights and RL control actions.
"""
from fastapi import APIRouter, HTTPException
from datetime import datetime

from app.models.schemas import (
    OptimizationWeights,
    OptimizationResponse,
    AgentDecisionRequest,
    AgentDecisionResponse,
)

router = APIRouter(prefix="/optimization", tags=["Optimization"])

_rl_service = None


def get_rl_service():
    if _rl_service is None:
        raise HTTPException(status_code=503, detail="RL service not initialized")
    return _rl_service


@router.post("/action", response_model=OptimizationResponse,
             summary="Trigger AI optimization",
             description="Compute optimal HVAC and lighting actions using PPO RL controller")
async def trigger_optimization():
    """Trigger the PPO/rule-based controller to compute optimal actions for all zones."""
    service = get_rl_service()
    result = service.get_optimization_actions()
    return result


@router.get("/weights",
            summary="Get optimization weights",
            description="Retrieve current multi-objective cost weights (α=energy, β=comfort, γ=stability)")
async def get_weights():
    """Get current multi-objective optimization weights."""
    service = get_rl_service()
    weights = service.get_optimization_weights()
    return {"weights": weights}


@router.put("/weights",
            summary="Update optimization weights",
            description="Dynamically adjust the multi-objective cost weights")
async def update_weights(weights: OptimizationWeights):
    """Update the multi-objective optimization weights."""
    service = get_rl_service()
    updated = service.set_optimization_weights(
        alpha=weights.alpha,
        beta=weights.beta,
        gamma=weights.gamma,
    )
    return {
        "status": "success",
        "message": "Optimization weights updated",
        "weights": updated,
    }


@router.post("/agent/decide", response_model=AgentDecisionResponse,
             summary="Autonomous energy agent decision",
             description="AI agent that interprets building conditions and makes energy optimization decisions")
async def agent_decide(request: AgentDecisionRequest):
    """
    Autonomous Energy Agent — Makes intelligent energy decisions.

    Example:
        Input: temperature=29°C, occupancy=low, energy_price=high
        Output: Reduce HVAC by 20%, dim lights to 30%
    """
    service = get_rl_service()
    result = service.autonomous_agent_decide(
        temperature=request.temperature,
        occupancy=request.occupancy,
        energy_price=request.energy_price,
        time_of_day=request.time_of_day,
    )
    return result
