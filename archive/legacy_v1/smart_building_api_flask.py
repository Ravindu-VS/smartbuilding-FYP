"""
Smart Building ML API - Flask Version (Extended)

REST API that serves both the original ML inference endpoints AND the new
real-time integration endpoints for the dashboard.

Original Endpoints (preserved):
    POST /predict-occupancy   - Single sensor reading → occupancy probability
    POST /control-decision    - Single sensor reading → control actions
    POST /batch-occupancy     - Batch occupancy predictions
    POST /batch-control       - Batch control decisions
    GET  /health              - Health check

New Integration Endpoints:
    GET  /api/rooms/current-state  - All 4 rooms with full state
    GET  /api/rooms/history        - Per-room history buffers
    GET  /api/system/summary       - Building-wide summary
    GET  /api/system/live          - Current state + system health
    GET  /api/stream               - Server-Sent Events live stream
    POST /api/simulation/control   - Pause/resume/set-interval/reset-energy
    GET  /dashboard                - Serve web dashboard

Usage:
    python run_integration.py
    Dashboard: http://localhost:8001/dashboard
"""

from flask import Flask, request, jsonify, send_from_directory, Response
import logging
import json
import os
import sys
import time
import threading
from datetime import datetime

# Ensure project root is on path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from smart_building_controller import SmartBuildingController
from occupancy_inference_service import OccupancyInferenceService
from integration.logger import SystemLogger

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)

# Enable CORS manually
@app.after_request
def after_request(response):
    """Add CORS headers."""
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

# Global controller and service instances (loaded once on startup)
controller = None
inference_service = None

# Integration layer reference (set by run_integration.py)
_live_service = None


def set_live_service(service):
    """
    Register the LiveUpdateService instance with the API.
    Called by run_integration.py after creating the service.
    """
    global _live_service
    _live_service = service
    logger.info("✓ LiveUpdateService registered with Flask API")


def _get_waiting_response():
    """
    Return a proper 'waiting for simulation' response.
    Used when the LiveUpdateService is not yet registered.
    Dashboard uses this to show the waiting state clearly.
    """
    return {
        "timestamp": datetime.now().isoformat(),
        "rooms": [],
        "system": {
            "total_rooms": 0,
            "occupied_rooms": 0,
            "empty_rooms": 0,
            "total_power_watts": 0,
            "total_cumulative_energy_wh": 0,
            "model_loaded": False,
            "api_online": True,
            "simulation_running": False,
            "simulation_connected": False,
            "simulation_time": None,
            "data_stale": True,
            "last_update": None,
            "update_interval": 2.0,
            "simulation_paused": False,
        },
        "message": "Waiting for simulation connection",
    }


@app.before_request
def initialize_models():
    """Initialize models on first request."""
    global controller, inference_service
    if controller is None or inference_service is None:
        try:
            logger.info("Initializing models on first request...")
            inference_service = OccupancyInferenceService(
                "models/final_unified_occupancy_pipeline.pkl",
                threshold=0.20
            )
            controller = SmartBuildingController(
                "models/final_unified_occupancy_pipeline.pkl",
                empty_threshold=0.20,
                occupied_threshold=0.60
            )
            logger.info("[OK] Models initialized successfully")
        except Exception as e:
            logger.error(f"Model initialization failed: {e}")
            return jsonify({"error": str(e)}), 503


# =============================================================================
# ORIGINAL ENDPOINTS (PRESERVED)
# =============================================================================

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    model_ok = controller is not None and inference_service is not None
    sim_ok = _live_service is not None and _live_service.is_running()

    return jsonify({
        "status": "healthy" if model_ok else "initializing",
        "message": "Smart Building ML API is running",
        "model_loaded": model_ok,
        "simulation_active": sim_ok,
    })


@app.route('/predict-occupancy', methods=['POST'])
def predict_occupancy():
    """Predict occupancy probability from sensor readings."""
    if inference_service is None:
        return jsonify({"error": "Inference service not initialized"}), 503

    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Request body must be JSON"}), 400

        sensor_dict = {}
        for key in ['Temperature', 'Humidity', 'Light', 'CO2', 'HumidityRatio']:
            if key in data and data[key] is not None:
                try:
                    sensor_dict[key] = float(data[key])
                except (ValueError, TypeError):
                    return jsonify({"error": f"Invalid value for {key}"}), 400

        if not sensor_dict:
            return jsonify({"error": "At least one sensor value must be provided"}), 400

        result = inference_service.predict(sensor_dict)

        response = {
            "occupancy_probability": float(result.occupancy_probability),
            "occupancy_prediction": int(result.occupancy_prediction),
            "confidence": float(result.confidence),
            "missing_values_count": result.missing_count,
            "missing_values_detail": result.missing_values
        }

        return jsonify(response)

    except Exception as e:
        logger.error(f"Prediction error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/control-decision', methods=['POST'])
def get_control_decision():
    """Get building control recommendation from sensor readings."""
    if controller is None:
        return jsonify({"error": "Controller not initialized"}), 503

    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Request body must be JSON"}), 400

        sensor_dict = {}
        for key in ['Temperature', 'Humidity', 'Light', 'CO2', 'HumidityRatio']:
            if key in data and data[key] is not None:
                try:
                    sensor_dict[key] = float(data[key])
                except (ValueError, TypeError):
                    return jsonify({"error": f"Invalid value for {key}"}), 400

        if not sensor_dict:
            return jsonify({"error": "At least one sensor value must be provided"}), 400

        decision = controller.get_control_decision(sensor_dict)

        response = {
            "occupancy_probability": float(decision.occupancy_probability),
            "occupancy_prediction": int(decision.occupancy_prediction),
            "control_mode": decision.control_mode,
            "light_action": decision.light_action,
            "hvac_action": decision.hvac_action,
            "energy_mode": decision.energy_mode,
            "confidence": float(decision.confidence),
            "missing_values_count": decision.missing_values_count
        }

        return jsonify(response)

    except Exception as e:
        logger.error(f"Control decision error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/batch-occupancy', methods=['POST'])
def batch_predict_occupancy():
    """Predict occupancy for multiple sensor readings."""
    if inference_service is None:
        return jsonify({"error": "Inference service not initialized"}), 503

    try:
        data = request.get_json()
        if not isinstance(data, list) or len(data) == 0:
            return jsonify({"error": "Request body must be non-empty JSON array"}), 400

        results = []
        for sensor_data in data:
            sensor_dict = {}
            for key in ['Temperature', 'Humidity', 'Light', 'CO2', 'HumidityRatio']:
                if key in sensor_data and sensor_data[key] is not None:
                    try:
                        sensor_dict[key] = float(sensor_data[key])
                    except (ValueError, TypeError):
                        continue

            result = inference_service.predict(sensor_dict)
            response = {
                "occupancy_probability": float(result.occupancy_probability),
                "occupancy_prediction": int(result.occupancy_prediction),
                "confidence": float(result.confidence),
                "missing_values_count": result.missing_count
            }
            results.append(response)

        return jsonify(results)

    except Exception as e:
        logger.error(f"Batch prediction error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/batch-control', methods=['POST'])
def batch_control_decisions():
    """Get building control recommendations for multiple sensor readings."""
    if controller is None:
        return jsonify({"error": "Controller not initialized"}), 503

    try:
        data = request.get_json()
        if not isinstance(data, list) or len(data) == 0:
            return jsonify({"error": "Request body must be non-empty JSON array"}), 400

        results = []
        for sensor_data in data:
            sensor_dict = {}
            for key in ['Temperature', 'Humidity', 'Light', 'CO2', 'HumidityRatio']:
                if key in sensor_data and sensor_data[key] is not None:
                    try:
                        sensor_dict[key] = float(sensor_data[key])
                    except (ValueError, TypeError):
                        continue

            decision = controller.get_control_decision(sensor_dict)
            response = {
                "control_mode": decision.control_mode,
                "light_action": decision.light_action,
                "hvac_action": decision.hvac_action,
                "energy_mode": decision.energy_mode,
                "confidence": float(decision.confidence),
                "occupancy_probability": float(decision.occupancy_probability)
            }
            results.append(response)

        return jsonify(results)

    except Exception as e:
        logger.error(f"Batch control error: {e}")
        return jsonify({"error": str(e)}), 500


# =============================================================================
# NEW INTEGRATION ENDPOINTS
# =============================================================================

@app.route('/api/rooms/current-state', methods=['GET'])
def api_rooms_current_state():
    """
    Get current state of all 4 rooms.
    Returns full JSON schema with sensors, AI, control, energy, status.
    """
    if _live_service is None:
        return jsonify(_get_waiting_response())

    try:
        state = _live_service.state_manager.get_current_state()
        return jsonify(state)
    except Exception as e:
        logger.error(f"Current state error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/rooms/history', methods=['GET'])
def api_rooms_history():
    """
    Get history buffers for all rooms (or a specific room via ?room_id=...).
    """
    if _live_service is None:
        return jsonify({"history": {}, "message": "Waiting for simulation"})

    try:
        room_id = request.args.get("room_id")
        if room_id:
            history = _live_service.state_manager.get_room_history(room_id)
            return jsonify({"room_id": room_id, "history": history})
        else:
            all_history = _live_service.state_manager.get_all_history()
            return jsonify(all_history)
    except Exception as e:
        logger.error(f"History error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/system/summary', methods=['GET'])
def api_system_summary():
    """
    Get building-wide system summary.
    Includes total rooms, occupied/empty, power, energy, health.

    NOTE: ALL data comes from StateManager ONLY. We never call bridge directly.
    StateManager is the single source of truth.
    """
    if _live_service is None:
        return jsonify(_get_waiting_response()["system"])

    try:
        summary = _live_service.state_manager.get_system_summary()
        # Add operational metadata (from service, not from bridge)
        summary["update_interval"] = _live_service.get_update_interval()
        summary["simulation_paused"] = _live_service.is_paused()
        # NOTE: simulation_time is ALREADY in summary from StateManager
        return jsonify(summary)
    except Exception as e:
        logger.error(f"Summary error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/system/live', methods=['GET'])
def api_system_live():
    """
    Combined endpoint: current room states + system summary.
    Optimized for the dashboard's polling loop (one request instead of two).

    CRITICAL: ALL data comes from StateManager. Never call bridge directly.
    StateManager is the authoritative source for all live state.
    """
    if _live_service is None:
        return jsonify(_get_waiting_response())

    try:
        state = _live_service.state_manager.get_current_state()
        state["system"]["update_interval"] = _live_service.get_update_interval()
        state["system"]["simulation_paused"] = _live_service.is_paused()
        # NOTE: simulation_time is ALREADY in state["system"] from StateManager
        return jsonify(state)
    except Exception as e:
        logger.error(f"Live state error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/simulation/control', methods=['POST'])
def api_simulation_control():
    """
    Control the simulation.

    Request body:
    {
        "action": "pause" | "resume" | "set_interval" | "reset_energy",
        "value": <optional, used for set_interval>
    }
    """
    if _live_service is None:
        return jsonify({"error": "Integration service not running"}), 503

    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Request body must be JSON"}), 400

        action = data.get("action", "").lower()

        if action == "pause":
            _live_service.pause()
            return jsonify({"status": "paused"})

        elif action == "resume":
            _live_service.resume()
            return jsonify({"status": "resumed"})

        elif action == "set_interval":
            value = data.get("value", 2.0)
            _live_service.set_update_interval(float(value))
            return jsonify({
                "status": "interval_updated",
                "interval": _live_service.get_update_interval()
            })

        elif action == "reset_energy":
            _live_service.state_manager.reset_energy()
            return jsonify({"status": "energy_reset"})

        else:
            return jsonify({"error": f"Unknown action: {action}"}), 400

    except Exception as e:
        logger.error(f"Simulation control error: {e}")
        return jsonify({"error": str(e)}), 500


# =============================================================================
# SERVER-SENT EVENTS (SSE) ENDPOINT
# =============================================================================

@app.route('/api/stream')
def api_sse_stream():
    """
    Server-Sent Events endpoint for real-time dashboard updates.
    Streams the full live state every update_interval seconds.

    CRITICAL: ALL data comes from StateManager. Never call bridge directly.
    StateManager is the authoritative source for all live state.
    """
    def generate():
        """SSE generator that yields live state data."""
        while True:
            try:
                if _live_service is not None:
                    state = _live_service.state_manager.get_current_state()
                    state["system"]["update_interval"] = _live_service.get_update_interval()
                    state["system"]["simulation_paused"] = _live_service.is_paused()
                    # NOTE: simulation_time is ALREADY in state["system"] from StateManager
                    data = json.dumps(state)
                    yield f"data: {data}\n\n"
                else:
                    waiting = _get_waiting_response()
                    data = json.dumps(waiting)
                    yield f"data: {data}\n\n"

                # Sleep for the configured interval
                interval = 2.0
                if _live_service is not None:
                    interval = _live_service.get_update_interval()
                time.sleep(interval)

            except GeneratorExit:
                break
            except Exception as e:
                logger.warning(f"SSE stream error: {e}")
                yield f"data: {{\"error\": \"{str(e)}\"}}\n\n"
                time.sleep(5.0)

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',
        }
    )


# =============================================================================
# HARDWARE SENSOR ENDPOINTS (ESP32 Integration)
# =============================================================================
# ESP32 → POST /api/hardware/sensor-data → sensor_gateway
#       → hardware_room_manager → state_manager → SSE → Dashboard → Three.js

@app.route('/api/hardware/sensor-data', methods=['POST'])
def receive_hardware_sensor_data():
    """
    Receive sensor data from ESP32 hardware.
    
    Expected JSON payload:
    {
        "room_id": "f2_office_a",
        "temperature": 26.4,
        "humidity": 62,
        "co2": 520,
        "lux": 340,
        "occupancy_probability": 0.94,
        "edge_inference_time_ms": 12,
        "pir_motion": 1
    }
    """
    try:
        from hardware.sensor_gateway import process_incoming_sensor_data
        
        payload = request.get_json(force=True)
        if not payload:
            return jsonify({"error": "No JSON payload"}), 400
        
        success = process_incoming_sensor_data(payload)
        
        if success:
            logger.info(f"LIVE HARDWARE DATA received: room={payload.get('room_id')} "
                       f"temp={payload.get('temperature')} "
                       f"prob={payload.get('occupancy_probability')}")
            
            # If the payload came from edge AI, it already contains the actuation decisions!
            if payload.get("source") == "edge_ai":
                hvac_act = payload.get("hvac_action", "ECO")
                light_act = payload.get("light_action", "OFF")
                dimming = 1.0 if light_act == "ON" else (0.5 if light_act == "DIM" else 0.0)
            else:
                # Compute closed-loop AI control actions for physical actuators (Cloud Fallback)
                occ_prob = float(payload.get('occupancy_probability', 0.1))
                if occ_prob >= 0.60:
                    hvac_act = "NORMAL"
                    light_act = "ON"
                    dimming = 1.0
                elif occ_prob >= 0.20:
                    hvac_act = "LOW"
                    light_act = "DIM"
                    dimming = 0.5
                else:
                    hvac_act = "ECO"
                    light_act = "OFF"
                    dimming = 0.0

            return jsonify({
                "status": "ok",
                "message": "Sensor data accepted",
                "room_id": payload.get("room_id"),
                "source": payload.get("source", "hardware"),
                "hvac_action": hvac_act,
                "light_action": light_act,
                "dimming_level": dimming,
                "timestamp": datetime.now().isoformat()
            }), 200
        else:
            return jsonify({"error": "Invalid sensor data"}), 400
            
    except Exception as e:
        logger.error(f"Hardware sensor endpoint error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/hardware/status', methods=['GET'])
def get_hardware_status():
    """
    Get the current status of all hardware-connected rooms.
    Used by the dashboard Hardware Debug Panel.
    """
    try:
        from hardware.hardware_room_manager import hardware_manager
        
        hw_states = hardware_manager.get_all_hardware_states()
        mqtt_connected = False
        try:
            from hardware.mqtt_client import mqtt_client
            mqtt_connected = mqtt_client.connected
        except Exception:
            pass
        
        rooms_status = {}
        for room_id, hw_state in hw_states.items():
            room_data = {}
            if _live_service:
                full_state = _live_service.state_manager.get_current_state()
                for room in full_state.get("rooms", []):
                    if room.get("room_id") == room_id:
                        room_data = room
                        break
            
            last_update = hw_state.get("last_update", 0)
            staleness = time.time() - last_update if last_update > 0 else -1
            
            rooms_status[room_id] = {
                "source": "hardware",
                "is_live": True,
                "staleness_seconds": round(staleness, 1),
                "is_stale": staleness > 30,
                "raw_sensors": {
                    "temperature": hw_state.get("temperature"),
                    "humidity": hw_state.get("humidity"),
                    "co2": hw_state.get("co2"),
                    "lux": hw_state.get("lux"),
                },
                "edge_ai": {
                    "occupancy_probability": hw_state.get("occupancy_probability"),
                    "source": "ESP32_EDGE",
                },
                "ai_decision": room_data.get("control", {}),
                "energy": room_data.get("energy", {}),
                "last_update_iso": (
                    datetime.fromtimestamp(last_update).isoformat()
                    if last_update > 0 else None
                ),
            }
        
        return jsonify({
            "hardware_rooms": rooms_status,
            "mqtt_connected": mqtt_connected,
            "total_hardware_rooms": len(hw_states),
            "timestamp": datetime.now().isoformat(),
        }), 200
        
    except Exception as e:
        logger.error(f"Hardware status endpoint error: {e}")
        return jsonify({"error": str(e)}), 500


# =============================================================================
# DASHBOARD SERVING
# =============================================================================

DASHBOARD_DIR = os.path.join(PROJECT_ROOT, "dashboard")

@app.route('/dashboard')
@app.route('/dashboard/')
def serve_dashboard():
    """Serve the web dashboard."""
    return send_from_directory(DASHBOARD_DIR, 'index.html')


@app.route('/dashboard/<path:filename>')
def serve_dashboard_static(filename):
    """Serve dashboard static files (CSS, JS, images)."""
    return send_from_directory(DASHBOARD_DIR, filename)


# =============================================================================
# API ENDPOINT ALIASES (User-requested paths)
# =============================================================================

@app.route('/api/predict-occupancy', methods=['POST'])
def api_predict_occupancy():
    """Alias for /predict-occupancy at /api/ path."""
    return predict_occupancy()


@app.route('/api/control-decision', methods=['POST'])
def api_control_decision():
    """Alias for /control-decision at /api/ path."""
    return get_control_decision()


@app.route('/api/system/reset-energy', methods=['POST'])
def api_reset_energy():
    """Dedicated reset energy endpoint."""
    if _live_service is None:
        return jsonify({"error": "Integration service not running"}), 503

    try:
        _live_service.state_manager.reset_energy()
        return jsonify({"status": "energy_reset", "message": "All energy counters have been reset"})
    except Exception as e:
        logger.error(f"Energy reset error: {e}")
        return jsonify({"error": str(e)}), 500


# =============================================================================
# API INDEX
# =============================================================================

@app.route('/', methods=['GET'])
def index():
    """API documentation."""
    return jsonify({
        "name": "Smart Building ML API",
        "version": "2.1.0",
        "dashboard": "/dashboard",
        "endpoints": {
            "GET /health": "Health check",
            "POST /predict-occupancy": "Get occupancy probability",
            "POST /control-decision": "Get building control recommendation",
            "POST /batch-occupancy": "Batch occupancy predictions",
            "POST /batch-control": "Batch control decisions",
            "GET /api/rooms/current-state": "All rooms current state",
            "GET /api/rooms/history": "Room history buffers",
            "GET /api/system/summary": "Building-wide summary",
            "GET /api/system/live": "Combined live state + summary",
            "GET /api/stream": "SSE live data stream",
            "POST /api/simulation/control": "Pause/resume/configure simulation",
            "POST /api/predict-occupancy": "Alias: occupancy prediction",
            "POST /api/control-decision": "Alias: control recommendation",
            "POST /api/system/reset-energy": "Reset energy counters",
        },
        "documentation": {
            "example_sensor_data": {
                "Temperature": 21.5,
                "Humidity": 35.0,
                "Light": 450.0,
                "CO2": 700.0,
                "HumidityRatio": 0.0045
            },
            "control_zones": {
                "EMPTY": "probability < 0.20",
                "STANDBY": "0.20 <= probability < 0.60",
                "OCCUPIED": "probability >= 0.60"
            }
        }
    })


# =============================================================================
# EVENT LOG & MANUAL OVERRIDE ENDPOINTS
# =============================================================================

@app.route('/api/events', methods=['GET'])
def api_events():
    """Get recent system events for the dashboard event log panel."""
    try:
        limit = request.args.get('limit', 50, type=int)
        sys_logger = SystemLogger.get_instance()
        events = sys_logger.get_recent_events(limit=limit)
        return jsonify({
            "events": events,
            "total_logged": sys_logger.get_event_count(),
        })
    except Exception as e:
        logger.error(f"Events error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/rooms/<room_id>/override', methods=['POST'])
def api_room_override(room_id):
    """
    Manual override for room controls (lights/HVAC).

    Request body:
    {
        "light_action": "ON" | "OFF" | "DIM",
        "hvac_action": "NORMAL" | "LOW" | "ECO" | "OFF"
    }
    """
    if _live_service is None:
        return jsonify({"error": "Integration service not running"}), 503

    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Request body must be JSON"}), 400

        light_action = data.get("light_action")
        hvac_action = data.get("hvac_action")

        if not light_action and not hvac_action:
            return jsonify({"error": "Specify light_action and/or hvac_action"}), 400

        # Build override actions and write to IPC
        override = {}
        if light_action:
            override["light_action"] = light_action
        if hvac_action:
            override["hvac_action"] = hvac_action
        override["control_mode"] = "OVERRIDE"
        override["energy_mode"] = "MANUAL"

        _live_service.bridge.write_control_actions({room_id: override})

        sys_logger = SystemLogger.get_instance()
        current_sim_time = _live_service.state_manager._health.get("simulation_time") if _live_service.state_manager else None
        sys_logger.log_control(
            room_id, "OVERRIDE",
            f"Manual: Lights={light_action or '-'}, HVAC={hvac_action or '-'}",
            sim_time=current_sim_time
        )

        return jsonify({
            "status": "override_applied",
            "room_id": room_id,
            "actions": override,
        })
    except Exception as e:
        logger.error(f"Override error: {e}")
        return jsonify({"error": str(e)}), 500


# =============================================================================
# METRICS & OBSERVABILITY ENDPOINTS
# =============================================================================

@app.route('/api/metrics', methods=['GET'])
def api_metrics():
    """Get system performance metrics."""
    if _live_service is None:
        return jsonify({"error": "Integration service not running"}), 503

    try:
        metrics_tracker = getattr(_live_service, '_metrics_tracker', None)
        if metrics_tracker is None:
            return jsonify({"error": "Metrics tracking not enabled"}), 503

        return jsonify({
            "summary": metrics_tracker.get_summary(),
            "health": metrics_tracker.get_health_check(),
        })
    except Exception as e:
        logger.error(f"Metrics error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/analytics', methods=['GET'])
def api_analytics():
    """Get advanced analytics report."""
    if _live_service is None:
        return jsonify({"error": "Integration service not running"}), 503

    try:
        analytics = getattr(_live_service, '_analytics', None)
        if analytics is None:
            return jsonify({"error": "Analytics not enabled"}), 503

        room_id = request.args.get("room_id")

        return jsonify({
            "occupancy_accuracy": analytics.get_occupancy_accuracy(room_id),
            "energy_analysis": analytics.get_energy_analysis(room_id),
            "anomalies": analytics.get_anomaly_report(),
            "timestamp": datetime.now().isoformat(),
        })
    except Exception as e:
        logger.error(f"Analytics error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/anomalies', methods=['GET'])
def api_anomalies():
    """Get detected anomalies."""
    if _live_service is None:
        return jsonify({"error": "Integration service not running"}), 503

    try:
        analytics = getattr(_live_service, '_analytics', None)
        if analytics is None:
            return jsonify({"error": "Analytics not enabled"}), 503

        anomalies = analytics.detect_anomalies()

        return jsonify({
            "count": len(anomalies),
            "anomalies": anomalies,
            "timestamp": datetime.now().isoformat(),
        })
    except Exception as e:
        logger.error(f"Anomalies error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/data/export', methods=['POST'])
def api_data_export():
    """Export data to CSV."""
    if _live_service is None:
        return jsonify({"error": "Integration service not running"}), 503

    try:
        data = request.get_json() or {}
        export_type = data.get("type", "occupancy")  # occupancy, energy, full
        room_id = data.get("room_id")

        db = getattr(_live_service, '_database', None)
        if db is None:
            return jsonify({"error": "Database not available"}), 503

        # Generate export based on type
        import tempfile
        fd, export_path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)

        if export_type == "occupancy":
            db.export_occupancy_csv(export_path, room_id)
        else:
            return jsonify({"error": f"Export type '{export_type}' not supported"}), 400

        # Read and return file
        with open(export_path, 'r') as f:
            content = f.read()

        os.remove(export_path)

        return jsonify({
            "status": "exported",
            "export_type": export_type,
            "room_id": room_id,
            "rows": len(content.split('\\n')) - 1,
            "data": content,
        })
    except Exception as e:
        logger.error(f"Export error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/database/stats', methods=['GET'])
def api_database_stats():
    """Get database statistics."""
    if _live_service is None:
        return jsonify({"error": "Integration service not running"}), 503

    try:
        db = getattr(_live_service, '_database', None)
        if db is None:
            return jsonify({"error": "Database not available"}), 503

        return jsonify(db.get_database_stats())
    except Exception as e:
        logger.error(f"Database stats error: {e}")
        return jsonify({"error": str(e)}), 500



# =============================================================================
# HARDWARE-IN-THE-LOOP (HITL) ENDPOINTS
# =============================================================================

@app.route('/api/hardware/sensors', methods=['POST'])
def api_hardware_sensors():
    """Receive raw sensor data from physical IoT hardware (ESP32)."""
    try:
        from hardware.sensor_gateway import process_incoming_sensor_data
        
        payload = request.get_json()
        if not payload:
            return jsonify({"error": "No JSON payload provided"}), 400
            
        success = process_incoming_sensor_data(payload)
        
        if success:
            return jsonify({"status": "ok", "message": "Sensor data ingested successfully"}), 200
        else:
            return jsonify({"error": "Failed to process sensor data"}), 400
            
    except ImportError as e:
        logger.error(f"Hardware module not available: {e}")
        return jsonify({"error": "Hardware-in-the-Loop module not installed"}), 501
    except Exception as e:
        logger.error(f"Hardware sensor error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/hardware/actuators/<room_id>', methods=['GET'])
def api_hardware_actuators(room_id):
    """Allow physical hardware to poll its latest actuator decisions."""
    if _live_service is None:
        return jsonify({"error": "Integration service not running"}), 503
        
    try:
        state_mgr = _live_service._state_manager
        full_state = state_mgr.get_full_state()
        
        for room in full_state.get("rooms", []):
            if room.get("room_id") == room_id:
                # Return the device state decisions
                return jsonify({
                    "status": "ok",
                    "room_id": room_id,
                    "timestamp": full_state.get("timestamp"),
                    "actuators": room.get("device_state", {})
                })
                
        return jsonify({"error": f"Room {room_id} not found in state manager"}), 404
        
    except Exception as e:
        logger.error(f"Hardware actuator error: {e}")
        return jsonify({"error": str(e)}), 500


# =============================================================================
# WEB DASHBOARDS
# =============================================================================

@app.route('/3d-twin')
def serve_3d_twin():
    """Serve the 3D Digital Twin dashboard."""
    return send_from_directory('dashboard/3d-twin', 'index.html')

@app.route('/3d-twin/<path:path>')
def serve_3d_twin_static(path):
    """Serve static files for the 3D Digital Twin."""
    return send_from_directory('dashboard/3d-twin', path)
# =============================================================================
# WSO2 ENTERPRISE API GATEWAY v1 ENDPOINTS
# =============================================================================

@app.route('/api/v1/sensors', methods=['POST'])
def api_v1_sensors():
    """Ingest sensor telemetry from WSO2 Micro Integrator (MQTT to REST)."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON payload provided"}), 400

        # Extract topic from header/payload
        topic = data.get("topic", "")
        telemetry = data.get("telemetry", {})

        # Topic format: building/{b_id}/floor/{f_id}/room/{r_id}/sensor
        # e.g., smartbuilding/sensors/f2_office_a or building/A/floor/2/room/office_a/sensor
        room_id = data.get("room_id")
        if not room_id and topic:
            parts = topic.split("/")
            # Handle standard MQTT topic format: building/A/floor/2/room/office_a/sensor
            if len(parts) >= 6:
                room_id = f"f{parts[3]}_{parts[5]}"  # Standardize to f2_office_a format
            elif len(parts) >= 3:
                room_id = parts[-1]  # Standardize smartbuilding/sensors/f2_office_a

        if not room_id:
            return jsonify({"error": "Missing room identifier"}), 400

        # Prepare normalized payload
        payload = {
            "room_id": room_id,
            "temperature": telemetry.get("temperature", 24.0),
            "humidity": telemetry.get("humidity", 50.0),
            "co2": telemetry.get("co2", 400.0),
            "lux": telemetry.get("lux", 0.0)
        }

        from hardware.sensor_gateway import process_incoming_sensor_data
        success = process_incoming_sensor_data(payload)

        if success:
            return jsonify({"status": "success", "room_id": room_id, "message": "Telemetry ingested via WSO2 successfully"}), 200
        else:
            return jsonify({"error": "Failed to process telemetry payload"}), 500

    except Exception as e:
        logger.error(f"WSO2 Telemetry ingestion error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/v1/buildings', methods=['GET'])
def api_v1_buildings():
    """Retrieve room layouts and building structural metadata."""
    try:
        config_path = os.path.join(PROJECT_ROOT, "room_config.json")
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                config_data = json.load(f)
            return jsonify(config_data), 200
        else:
            # Fallback mock configuration if file is missing
            return jsonify({
                "building": {"name": "Smart Office Building", "version": "v2.0"},
                "rooms": []
            }), 200
    except Exception as e:
        logger.error(f"WSO2 get buildings error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/v1/energy', methods=['GET'])
def api_v1_energy():
    """Retrieve building energy meters and optimization summaries."""
    if _live_service is None:
        return jsonify({"error": "Integration service not running"}), 503

    try:
        summary = _live_service.state_manager.get_system_summary()
        return jsonify({
            "timestamp": datetime.now().isoformat(),
            "total_power_watts": summary.get("total_power_watts", 0.0),
            "total_cumulative_energy_wh": summary.get("total_cumulative_energy_wh", 0.0),
            "baseline_energy_wh": summary.get("baseline_energy_wh", 0.0),
            "ai_energy_wh": summary.get("ai_energy_wh", 0.0),
            "energy_saved_wh": summary.get("energy_saved_wh", 0.0),
            "percentage_saved": summary.get("percentage_saved", 0.0),
            "hvac_power_watts": summary.get("hvac_power_watts", 0.0),
            "lighting_power_watts": summary.get("lighting_power_watts", 0.0),
            "plug_power_watts": summary.get("plug_power_watts", 0.0),
            "comfort_score": summary.get("comfort_score", 0.0)
        }), 200
    except Exception as e:
        logger.error(f"WSO2 get energy metrics error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/v1/optimization', methods=['GET', 'POST'])
def api_v1_optimization():
    """Get or update multi-objective optimization cost weights (alpha, beta, gamma)."""
    if _live_service is None:
        return jsonify({"error": "Integration service not running"}), 503

    try:
        state_mgr = _live_service.state_manager
        if request.method == 'POST':
            data = request.get_json()
            if not data:
                return jsonify({"error": "No JSON payload provided"}), 400

            alpha = data.get("alpha")
            beta = data.get("beta")
            gamma = data.get("gamma")

            state_mgr.set_optimization_weights(alpha, beta, gamma)
            weights = state_mgr.get_optimization_weights()

            return jsonify({
                "status": "success",
                "message": "Optimization weights adapted successfully",
                "weights": weights
            }), 200
        else:
            weights = state_mgr.get_optimization_weights()
            return jsonify({"weights": weights}), 200

    except Exception as e:
        logger.error(f"WSO2 optimization weighting error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/v1/assistant', methods=['POST'])
def api_v1_assistant():
    """Smart Building Assistant chatbot endpoint."""
    try:
        data = request.get_json()
        if not data or "message" not in data:
            return jsonify({"error": "Missing 'message' in request body"}), 400

        user_message = data["message"]

        state_mgr = None
        db = None
        if _live_service is not None:
            state_mgr = _live_service.state_manager
            db = _live_service.db_persistence

        from ai.assistant.llm_engine import BuildingAssistant
        assistant = BuildingAssistant(state_manager=state_mgr, database=db)
        result = assistant.generate_response(user_message)

        return jsonify(result), 200

    except Exception as e:
        logger.error(f"AI Assistant endpoint error: {e}")
        return jsonify({"error": str(e)}), 500


# =============================================================================
# STARTUP & MAIN
# =============================================================================

if __name__ == "__main__":
    logger.info("="*70)
    logger.info("Smart Building ML API - Flask Version (Enhanced)")
    logger.info("="*70)
    logger.info("Starting server on http://localhost:8001")
    logger.info("API documentation available at http://localhost:8001/")
    logger.info("New endpoints:")
    logger.info("  GET  /api/metrics        - System performance metrics")
    logger.info("  GET  /api/analytics      - Advanced analytics report")
    logger.info("  GET  /api/anomalies      - Detected system anomalies")
    logger.info("  POST /api/data/export    - Export data to CSV")
    logger.info("  GET  /api/database/stats - Database statistics")
    logger.info("="*70)

    try:
        app.run(host='127.0.0.1', port=8001, debug=False, use_reloader=False)
    except Exception as e:
        logger.error(f"Failed to start server: {e}")
