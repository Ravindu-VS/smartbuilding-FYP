#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# Raspberry Pi 4B — Edge Intelligence Launch Script
# ═══════════════════════════════════════════════════════════════
#
# Usage:
#   chmod +x run_edge.sh
#   ./run_edge.sh
#
# Environment variables:
#   SPEED_FACTOR  — Simulation speed (default: 360, meaning 1 sec = 6 sim min)
#   API_PORT      — Flask API port (default: 8001)
#   API_HOST      — Listen address (default: 0.0.0.0 for all interfaces)
#
# The Digital Twin dashboard on your laptop connects to:
#   http://<pi_ip>:8001/api/stream
#

echo "═══════════════════════════════════════════════════"
echo "  RASPBERRY PI 4B — EDGE INTELLIGENCE BRAIN"
echo "  Smart Building Hybrid Cyber-Physical System"
echo "═══════════════════════════════════════════════════"
echo ""

# Navigate to project root
cd "$(dirname "$0")/.."

# Activate virtual environment if it exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
    echo "✓ Virtual environment activated"
elif [ -d "venv" ]; then
    source venv/bin/activate
    echo "✓ Virtual environment activated"
fi

# Set defaults
export SPEED_FACTOR=${SPEED_FACTOR:-360}
export API_PORT=${API_PORT:-8001}
export API_HOST=${API_HOST:-0.0.0.0}
export MQTT_ENABLED=${MQTT_ENABLED:-1}
export BLE_ENABLED=${BLE_ENABLED:-1}

echo "  Speed Factor: ${SPEED_FACTOR}x"
echo "  API Port: ${API_PORT}"
echo "  Host: ${API_HOST}"
echo "  MQTT: ${MQTT_ENABLED}"
echo "  BLE fallback: ${BLE_ENABLED}"
echo ""

# Get Pi's IP address for display
PI_IP=$(hostname -I | awk '{print $1}')
echo "  Pi IP Address: ${PI_IP}"
echo ""
echo "  ESP32 should POST to:"
echo "    http://${PI_IP}:${API_PORT}/api/hardware/sensor-data"
echo ""
echo "  Digital Twin dashboard connects to:"
echo "    http://${PI_IP}:${API_PORT}/api/stream"
echo ""
echo "═══════════════════════════════════════════════════"
echo ""

# Launch the edge brain
python3 raspberry_pi/edge_brain.py
