"""
Metrics & Observability Tracker

Tracks performance metrics, timing, and system health:
- Per-tick execution time
- Inference latency
- Control decision latency
- Energy calculation time
- API response times
- Occupancy accuracy (actual vs predicted)
- Anomalies detected

Thread-safe for concurrent access.
"""

import time
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional
from collections import deque
from threading import Lock
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class TickMetrics:
    """Metrics for a single tick/update cycle."""
    timestamp: str
    tick_number: int
    total_time_ms: float
    simulation_step_ms: float
    inference_ms: float
    control_ms: float
    energy_ms: float
    api_response_ms: float
    rooms_processed: int
    occupancy_accuracy: float  # percentage correct 0-100
    energy_consumed_wh: float


class MetricsTracker:
    """Track and report system performance metrics."""

    def __init__(self, max_history: int = 500):
        """Initialize metrics tracker."""
        self._lock = Lock()
        self._tick_metrics: deque = deque(maxlen=max_history)
        self._tick_count = 0
        self._start_time = datetime.now()
        self._accuracy_history: deque = deque(maxlen=100)

        # Current tick timing
        self._current_tick_start = None
        self._current_tick_times: Dict[str, float] = {}

        logger.info("MetricsTracker initialized")

    def start_tick(self):
        """Mark the start of a tick cycle."""
        self._current_tick_start = time.time()
        self._current_tick_times = {}

    def record_phase_time(self, phase_name: str):
        """Record execution time for a phase."""
        if self._current_tick_start is not None:
            elapsed = (time.time() - self._current_tick_start) * 1000
            self._current_tick_times[phase_name] = elapsed

    def end_tick(self, rooms_processed: int = 0, energy_consumed: float = 0.0):
        """Mark the end of a tick and compute metrics."""
        if self._current_tick_start is None:
            return

        total_ms = (time.time() - self._current_tick_start) * 1000
        self._tick_count += 1

        # Extract phase times
        metrics = TickMetrics(
            timestamp=datetime.now().isoformat(),
            tick_number=self._tick_count,
            total_time_ms=round(total_ms, 2),
            simulation_step_ms=round(
                self._current_tick_times.get("simulation", 0), 2
            ),
            inference_ms=round(
                self._current_tick_times.get("inference", 0), 2
            ),
            control_ms=round(
                self._current_tick_times.get("control", 0), 2
            ),
            energy_ms=round(
                self._current_tick_times.get("energy", 0), 2
            ),
            api_response_ms=round(
                self._current_tick_times.get("api", 0), 2
            ),
            rooms_processed=rooms_processed,
            occupancy_accuracy=0.0,  # Updated separately
            energy_consumed_wh=energy_consumed,
        )

        with self._lock:
            self._tick_metrics.append(metrics)

    def record_occupancy_accuracy(self, accuracy: float):
        """Record occupancy prediction accuracy (0-100)."""
        with self._lock:
            self._accuracy_history.append(accuracy)
            if self._tick_metrics:
                self._tick_metrics[-1].occupancy_accuracy = accuracy

    def get_summary(self) -> Dict[str, Any]:
        """Get current metrics summary."""
        with self._lock:
            if not self._tick_metrics:
                return {
                    "tick_count": 0,
                    "uptime_seconds": (
                        datetime.now() - self._start_time
                    ).total_seconds(),
                    "avg_tick_ms": 0,
                    "avg_occupancy_accuracy": 0,
                }

            metrics_list = list(self._tick_metrics)
            total_times = [m.total_time_ms for m in metrics_list]
            avg_total = sum(total_times) / len(total_times) if total_times else 0

            avg_phase_times = {
                "simulation_ms": sum(
                    m.simulation_step_ms for m in metrics_list
                ) / len(metrics_list),
                "inference_ms": sum(
                    m.inference_ms for m in metrics_list
                ) / len(metrics_list),
                "control_ms": sum(
                    m.control_ms for m in metrics_list
                ) / len(metrics_list),
                "energy_ms": sum(
                    m.energy_ms for m in metrics_list
                ) / len(metrics_list),
            }

            avg_accuracy = (
                sum(self._accuracy_history) / len(self._accuracy_history)
                if self._accuracy_history
                else 0
            )
            total_energy = sum(m.energy_consumed_wh for m in metrics_list)

            return {
                "tick_count": self._tick_count,
                "uptime_seconds": round(
                    (datetime.now() - self._start_time).total_seconds(), 1
                ),
                "avg_tick_ms": round(avg_total, 2),
                "min_tick_ms": round(min(total_times), 2) if total_times else 0,
                "max_tick_ms": round(max(total_times), 2) if total_times else 0,
                "avg_phase_times_ms": {
                    k: round(v, 2) for k, v in avg_phase_times.items()
                },
                "avg_occupancy_accuracy_pct": round(avg_accuracy, 2),
                "total_energy_consumed_wh": round(total_energy, 2),
                "rooms_processed_per_tick": (
                    metrics_list[-1].rooms_processed if metrics_list else 0
                ),
            }

    def get_detailed_metrics(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get detailed metrics history."""
        with self._lock:
            metrics_list = list(self._tick_metrics)[-limit:]
            return [asdict(m) for m in metrics_list]

    def get_health_check(self) -> Dict[str, Any]:
        """Get health status based on metrics."""
        summary = self.get_summary()

        # Simple health thresholds
        avg_tick_ms = summary.get("avg_tick_ms", 0)
        avg_accuracy = summary.get("avg_occupancy_accuracy_pct", 0)

        health = "healthy"
        if avg_tick_ms > 500:  # Ticks taking >500ms
            health = "degraded"
        if avg_tick_ms > 1000:  # Ticks taking >1s
            health = "poor"
        if avg_accuracy < 50:  # Very poor accuracy
            health = "poor"

        return {
            "health": health,
            "avg_tick_ms": avg_tick_ms,
            "avg_accuracy_pct": avg_accuracy,
            "tick_count": summary["tick_count"],
            "uptime_seconds": summary["uptime_seconds"],
        }
