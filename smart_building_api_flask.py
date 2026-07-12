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
        return jsonify({"error": "Integration service not running (use run_system.py)"}), 503

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
