"""
Smart Building Digital Twin — Unified Orchestrator

This script is the single entry point to launch the complete system.
It runs the integration backend API (+ ML pipeline + dashboard) on a
background thread, and the Panda3D simulation engine on the main thread.

The bridge between them operates via two-way IPC:
- Panda3D writes `.sim_state.json`
- Backend runs ML logic and writes `.control_actions.json`
- Dashboard reads from backend API and displays the full state
"""

import os
import sys
import threading
import time
import signal
import webbrowser
import logging

from integration.config import (
    API_PORT, API_HOST, AUTO_OPEN_BROWSER, DASHBOARD_URL,
    LOG_DIR, OUTPUT_DIR
)

# Ensure project root is in path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("Launcher")

# Global flags
stop_event = threading.Event()

def ensure_directories():
    """Ensure required directories exist for IPC and logging."""
    for dir_path in [OUTPUT_DIR, LOG_DIR]:
        path = os.path.join(PROJECT_ROOT, dir_path)
        os.makedirs(path, exist_ok=True)
        # Create .placeholder to ensure directory persists in git
        with open(os.path.join(path, ".placeholder"), "w") as f:
            f.write("Directory created by unified launcher\n")

def run_backend_server(is_demo: bool = False):
    """Run the Flask API and LiveUpdateService in a background thread."""
    logger.info("Initializing Backend Integration Layer (Service + API)...")
    
    try:
        # Import dynamically so we don't crash if environment isn't fully set up yet
        import integration.config as cfg
        if is_demo:
            cfg.DEMO_MODE = True
            cfg.SIMULATION_SPEED_FACTOR = 720.0
            cfg.DEFAULT_UPDATE_INTERVAL = 0.5
            
        from integration.state_manager import StateManager
        from integration.simulation_bridge import SimulationBridge
        from integration.live_update_service import LiveUpdateService
        from smart_building_api_flask import app, set_live_service

        # 1. Create Core Components
        # We explicitly configure the bridge config (headless uses these params if Panda3D dies)
        bridge_config = {"speed_factor": cfg.SIMULATION_SPEED_FACTOR}
        bridge = SimulationBridge(config=bridge_config)
        state_manager = StateManager()

        # 2. Create and start Live Update Service
        live_service = LiveUpdateService(
            state_manager=state_manager,
            simulation_bridge=bridge,
            update_interval=cfg.DEFAULT_UPDATE_INTERVAL,
            enable_csv_logging=True
        )
        
        # 3. Register service with Flask and start
        set_live_service(live_service)
        live_service.start()
        
        # 3b. Start MQTT client for ESP32 hardware integration
        try:
            from hardware.mqtt_client import mqtt_client
            mqtt_client.start()
            logger.info("✓ MQTT Client started for ESP32 hardware integration")
        except Exception as mqtt_err:
            logger.warning(f"MQTT Client not started (non-fatal): {mqtt_err}")

        
        # 4. Open browser if configured
        if AUTO_OPEN_BROWSER:
            def open_browser():
                time.sleep(2.0)
                logger.info(f"Opening dashboard in browser: {DASHBOARD_URL}")
                webbrowser.open(DASHBOARD_URL)
            threading.Thread(target=open_browser, daemon=True).start()

        # 5. Run Flask server (blocks this thread)
        logger.info(f"Starting API Server on {API_HOST}:{API_PORT}")
        # Disable Werkzeug's default startup banner for cleaner logs
        logging.getLogger('werkzeug').setLevel(logging.ERROR)
        app.run(host=API_HOST, port=API_PORT, debug=False, use_reloader=False, threaded=True)

    except Exception as e:
        logger.error(f"Backend Server failed: {e}", exc_info=True)
        stop_event.set()

def run_panda3d_simulation(is_demo: bool = False):
    """Run the Panda3D simulation engine on the main thread."""
    logger.info("Initializing Panda3D Simulation Engine...")
    
    try:
        from panda3d_simulation.app import SmartBuildingSimApp
        
        sim_config = {}
        if is_demo:
            sim_config["speed_factor"] = 720.0
            logger.info("DEMO MODE ACTIVED: Simulation running at 720x speed")
            
        # Start application
        app = SmartBuildingSimApp(config=sim_config)
        
        # Run blocks here until window is closed
        app.run()
        
    except Exception as e:
        logger.error(f"Panda3D Simulation failed: {e}", exc_info=True)
        # If the 3D window fails, the whole system should shut down gracefully
        stop_event.set()

def signal_handler(sig, frame):
    """Handle Ctrl+C gracefully."""
    logger.info("\nCaught shutdown signal (Ctrl+C). Shutting down system...")
    stop_event.set()
    sys.exit(0)

def main():
    """Entry point for the unified system."""
    logger.info("==================================================")
    logger.info("Smart Building Digital Twin — Unified Orchestrator")
    logger.info("==================================================")

    # Register signal handler for Ctrl+C
    signal.signal(signal.SIGINT, signal_handler)

    # Prepare file system for IPC
    ensure_directories()

    # Create cleanup hook for IPC files to avoid stale state on next run
    try:
        from integration.simulation_ipc import cleanup_ipc_files
        cleanup_ipc_files()
    except Exception:
        pass

    # Check for demo mode argument
    is_demo = "--demo" in sys.argv
    if is_demo:
        logger.info("Starting in DEMO MODE")

    # Start the backend API on a background daemon thread
    api_thread = threading.Thread(
        target=run_backend_server, 
        args=(is_demo,),
        name="BackendAPIThread", 
        daemon=True
    )
    api_thread.start()

    # Give the backend a small head start so the API is up when the sim starts
    time.sleep(1.0)

    # Run in pure headless mode (powering the Three.js dashboard)
    logger.info("Running in Headless Simulation Mode (Three.js Dashboard Active)...")
    try:
        while not stop_event.is_set():
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    logger.info("Main simulation thread ended. Cleaning up...")
    stop_event.set()
    try:
        cleanup_ipc_files()
    except Exception:
        pass
    
    time.sleep(1.0) # Give background threads a moment to notice
    sys.exit(0)

if __name__ == "__main__":
    main()
