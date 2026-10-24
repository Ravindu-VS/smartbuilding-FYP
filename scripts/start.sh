#!/usr/bin/env bash
# One-command start-up.  Usage:
#   scripts/start.sh dev        edge brain (simulation + store) and the dashboard on this machine
#   scripts/start.sh edge       edge brain only (what runs on the Raspberry Pi; boards post over HTTP)
#   scripts/start.sh live       edge brain with the MQTT bridge (needs a broker: MQTT_HOST/MQTT_PORT)
#   scripts/start.sh harness    local MQTT broker + simulated board + edge brain + dashboard (no hardware)
#   scripts/start.sh virtual    edge brain + dashboard + virtual board replaying the UCI office data (HTTP, like the firmware)
#   scripts/start.sh virtual-twin   the same with Office A simulated by the digital twin (closed loop)
# Offline training is never started here (see scripts/train_all.sh).
set -euo pipefail
cd "$(dirname "$0")/.."
MODE="${1:-dev}"
PY="${PYTHON:-python3}"
LOG=output/logs; mkdir -p "$LOG"
pids=()
cleanup() { for p in "${pids[@]:-}"; do kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT INT TERM

need() { "$PY" -c "import $1" 2>/dev/null || { echo "missing Python package '$1': $PY -m pip install -r requirements/$2.txt"; exit 1; }; }
need flask edge; need numpy edge

wait_http() {   # url, name
  for _ in $(seq 1 120); do
    if curl -fsS "$1" >/dev/null 2>&1; then echo "  ok: $2 ($1)"; return 0; fi; sleep 1
  done
  echo "  FAILED: $2 did not answer at $1 (see $LOG)"; exit 1
}

start_edge() {
  echo "starting edge brain (log: $LOG/edge.log)"
  "$PY" raspberry_pi/edge_brain.py >"$LOG/edge.log" 2>&1 & pids+=($!)
  wait_http "http://127.0.0.1:${API_PORT:-8001}/health" "edge brain API"
}

start_dashboard() {
  command -v npm >/dev/null || { echo "npm not found: install Node.js 20+ for the dashboard"; exit 1; }
  ( cd dashboard/fyp-research-twin && [ -d node_modules ] || npm ci )
  echo "starting dashboard (log: $LOG/dashboard.log)"
  ( cd dashboard/fyp-research-twin && npm run dev ) >"$LOG/dashboard.log" 2>&1 & pids+=($!)
  wait_http "http://127.0.0.1:3000" "dashboard"
}

case "$MODE" in
  dev)  start_edge; start_dashboard ;;
  edge) start_edge ;;
  live) need paho.mqtt edge; export MQTT_ENABLED=1; start_edge ;;
  harness)
    need amqtt dev; need paho.mqtt edge
    export MQTT_ENABLED=1 MQTT_HOST=127.0.0.1 MQTT_PORT="${MQTT_PORT:-1883}"
    echo "starting local MQTT broker on :$MQTT_PORT (log: $LOG/broker.log)"
    "$PY" -c "
import asyncio
from amqtt.broker import Broker
cfg={'listeners':{'default':{'type':'tcp','bind':'127.0.0.1:$MQTT_PORT'}},'sys_interval':0,
     'auth':{'allow-anonymous':True,'plugins':['auth_anonymous']},'topic-check':{'enabled':False}}
async def main():
    b=Broker(cfg); await b.start(); await asyncio.Event().wait()
asyncio.run(main())" >"$LOG/broker.log" 2>&1 & pids+=($!)
    sleep 2
    start_edge
    echo "starting simulated board (log: $LOG/device.log) - its data is labelled synthetic"
    "$PY" raspberry_pi/mqtt_device_sim.py --interval 3 >"$LOG/device.log" 2>&1 & pids+=($!)
    start_dashboard ;;
  virtual|virtual-twin)
    start_edge
    SRC=uci; [ "$MODE" = virtual-twin ] && SRC=twin
    echo "starting the virtual board ($SRC; log: $LOG/virtual_board.log) - labelled virtual_board, stored as synthetic"
    "$PY" raspberry_pi/virtual_board.py --source "$SRC" >"$LOG/virtual_board.log" 2>&1 & pids+=($!)
    start_dashboard ;;
  *) echo "unknown mode '$MODE' (dev | edge | live | harness | virtual | virtual-twin)"; exit 2 ;;
esac
echo
echo "running ($MODE). Dashboard: http://localhost:3000  API: http://localhost:${API_PORT:-8001}/api/rooms/current-state"
echo "Ctrl+C stops everything."
wait
