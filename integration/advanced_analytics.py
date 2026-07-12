"""
Advanced Analytics Module

Tracks and analyzes:
- Occupancy prediction accuracy vs ground truth
- Energy baseline and usage comparison
- Anomaly detection (unexpected occupancy/energy patterns)
- Control effectiveness measures

Thread-safe for concurrent access.
"""

import logging
from datetime import datetime
from typing import Dict, List, Any, Optional
from collections import deque
from threading import Lock
from dataclasses import dataclass, asdict
import math

logger = logging.getLogger(__name__)


@dataclass
class OccupancyRecord:
    """Record of occupancy prediction vs ground truth."""
    timestamp: str
    room_id: str
    predicted_occupancy: int  # 0 or 1
    true_occupancy: int  # 0 or 1
    occupancy_probability: float  # 0-1
    confidence: float  # 0-1
    control_mode: str


@dataclass
class EnergyRecord:
    """Record of energy consumption."""
    timestamp: str
    room_id: str
    power_watts: float
    cumulative_wh: float
    occupancy_predicted: int
    control_mode: str


class AdvancedAnalytics:
    """Advanced analytics for the smart building system."""

    def __init__(self, max_history: int = 500):
        """Initialize analytics."""
        self._lock = Lock()
        self._occupancy_records: deque = deque(maxlen=max_history)
        self._energy_records: deque = deque(maxlen=max_history)
        self._anomalies: deque = deque(maxlen=100)

        # Baseline calculations
        self._energy_baselines: Dict[str, Dict[str, float]] = {}  # room -> mode -> avg power
        self._occupancy_baselines: Dict[str, float] = {}  # room -> avg occupancy 0-1

        logger.info("AdvancedAnalytics initialized")

    def record_occupancy(
        self,
        room_id: str,
        predicted: int,
        true: int,
        probability: float,
        confidence: float,
        control_mode: str,
    ):
        """Record an occupancy prediction."""
        record = OccupancyRecord(
            timestamp=datetime.now().isoformat(),
            room_id=room_id,
            predicted_occupancy=predicted,
            true_occupancy=true,
            occupancy_probability=probability,
            confidence=confidence,
            control_mode=control_mode,
        )
        with self._lock:
            self._occupancy_records.append(record)

    def record_energy(
        self,
        room_id: str,
        power_watts: float,
        cumulative_wh: float,
        occupancy_predicted: int,
        control_mode: str,
    ):
        """Record energy consumption."""
        record = EnergyRecord(
            timestamp=datetime.now().isoformat(),
            room_id=room_id,
            power_watts=power_watts,
            cumulative_wh=cumulative_wh,
            occupancy_predicted=occupancy_predicted,
            control_mode=control_mode,
        )
        with self._lock:
            self._energy_records.append(record)

    def get_occupancy_accuracy(self, room_id: Optional[str] = None) -> Dict[str, Any]:
        """Calculate occupancy prediction accuracy."""
        with self._lock:
            records = list(self._occupancy_records)

        if not records:
            return {
                "accuracy": 0,
                "precision": 0,
                "recall": 0,
                "f1_score": 0,
                "total_samples": 0,
                "true_positives": 0,
                "true_negatives": 0,
                "false_positives": 0,
                "false_negatives": 0,
            }

        # Filter by room if specified
        if room_id:
            records = [r for r in records if r.room_id == room_id]

        if not records:
            return {
                "accuracy": 0,
                "precision": 0,
                "recall": 0,
                "f1_score": 0,
                "total_samples": 0,
                "true_positives": 0,
                "true_negatives": 0,
                "false_positives": 0,
                "false_negatives": 0,
            }

        # Calculate confusion matrix
        tp = sum(
            1
            for r in records
            if r.predicted_occupancy == 1 and r.true_occupancy == 1
        )
        tn = sum(
            1
            for r in records
            if r.predicted_occupancy == 0 and r.true_occupancy == 0
        )
        fp = sum(
            1
            for r in records
            if r.predicted_occupancy == 1 and r.true_occupancy == 0
        )
        fn = sum(
            1
            for r in records
            if r.predicted_occupancy == 0 and r.true_occupancy == 1
        )

        total = len(records)
        accuracy = (tp + tn) / total if total > 0 else 0
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = (
            2 * (precision * recall) / (precision + recall)
            if (precision + recall) > 0
            else 0
        )

        return {
            "accuracy_pct": round(accuracy * 100, 2),
            "precision_pct": round(precision * 100, 2),
            "recall_pct": round(recall * 100, 2),
            "f1_score": round(f1, 3),
            "total_samples": total,
            "true_positives": tp,
            "true_negatives": tn,
            "false_positives": fp,
            "false_negatives": fn,
        }

    def get_energy_analysis(self, room_id: Optional[str] = None) -> Dict[str, Any]:
        """Analyze energy consumption patterns."""
        with self._lock:
            records = list(self._energy_records)

        if not records:
            return {"avg_power_watts": 0, "total_energy_wh": 0, "samples": 0}

        # Filter by room if specified
        if room_id:
            records = [r for r in records if r.room_id == room_id]

        if not records:
            return {"avg_power_watts": 0, "total_energy_wh": 0, "samples": 0}

        # Analyze by control mode
        modes = {}
        for record in records:
            mode = record.control_mode
            if mode not in modes:
                modes[mode] = []
            modes[mode].append(record.power_watts)

        mode_analysis = {}
        for mode, powers in modes.items():
            avg_power = sum(powers) / len(powers)
            mode_analysis[mode] = {
                "avg_power_watts": round(avg_power, 1),
                "samples": len(powers),
            }

        total_energy = records[-1].cumulative_wh if records else 0
        avg_power_overall = sum(r.power_watts for r in records) / len(
            records
        )

        return {
            "avg_power_watts": round(avg_power_overall, 1),
            "total_energy_wh": round(total_energy, 2),
            "by_control_mode": mode_analysis,
            "samples": len(records),
        }

    def detect_anomalies(self) -> List[Dict[str, Any]]:
        """Detect occupancy and energy anomalies."""
        anomalies = []

        with self._lock:
            occ_records = list(self._occupancy_records)
            energy_records = list(self._energy_records)

        # Anomaly 1: False shutdown (predicted empty but actually occupied)
        false_shutdowns = [
            r for r in occ_records
            if r.predicted_occupancy == 0 and r.true_occupancy == 1
        ]
        if false_shutdowns and len(false_shutdowns) > len(occ_records) * 0.1:
            anomalies.append({
                "type": "false_shutdowns",
                "severity": "high",
                "description": "High false shutdown rate detected",
                "count": len(false_shutdowns),
                "percentage": round(
                    len(false_shutdowns) / len(occ_records) * 100, 1
                ),
                "recommendation": "Increase occupied threshold or improve sensor calibration",
            })

        # Anomaly 2: False occupancy (predicted occupied but empty)
        false_occupancies = [
            r for r in occ_records
            if r.predicted_occupancy == 1 and r.true_occupancy == 0
        ]
        if false_occupancies and len(false_occupancies) > len(occ_records) * 0.15:
            anomalies.append({
                "type": "false_occupancies",
                "severity": "medium",
                "description": "High false occupancy detection rate",
                "count": len(false_occupancies),
                "percentage": round(
                    len(false_occupancies) / len(occ_records) * 100, 1
                ),
                "recommendation": "Decrease occupied threshold or add additional sensors",
            })

        # Anomaly 3: Unusually high energy for control mode
        if energy_records:
            for control_mode in set(r.control_mode for r in energy_records):
                mode_records = [
                    r for r in energy_records if r.control_mode == control_mode
                ]
                powers = [r.power_watts for r in mode_records]
                avg_power = sum(powers) / len(powers)
                high_power = [p for p in powers if p > avg_power * 1.5]

                if high_power and len(high_power) > len(powers) * 0.1:
                    anomalies.append({
                        "type": "high_energy",
                        "severity": "medium",
                        "control_mode": control_mode,
                        "description": f"Unusually high power in {control_mode} mode",
                        "count": len(high_power),
                        "avg_power_watts": round(avg_power, 1),
                        "high_power_readings": round(max(high_power), 1),
                    })

        with self._lock:
            for anomaly in anomalies:
                self._anomalies.append(anomaly)

        return anomalies

    def get_anomaly_report(self) -> List[Dict[str, Any]]:
        """Get recent anomalies."""
        with self._lock:
            return list(self._anomalies)

    def get_full_report(self) -> Dict[str, Any]:
        """Get comprehensive analytics report."""
        return {
            "timestamp": datetime.now().isoformat(),
            "occupancy_accuracy": self.get_occupancy_accuracy(),
            "energy_analysis": self.get_energy_analysis(),
            "anomalies": self.detect_anomalies(),
            "occupancy_by_room": {
                room_id: self.get_occupancy_accuracy(room_id)
                for room_id in set(r.room_id for r in list(self._occupancy_records))
            },
        }
