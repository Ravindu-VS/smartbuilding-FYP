"""
Database Persistence Module

Lightweight SQLite persistence for historical data:
- Metrics snapshots
- Occupancy records
- Energy records
- System events
- Anomalies

Auto-creates database and tables on first use.
"""

import sqlite3
import logging
import os
from datetime import datetime
from typing import List, Dict, Any, Optional
from threading import Lock

logger = logging.getLogger(__name__)


class DatabasePersistence:
    """Manage persistent storage to SQLite."""

    def __init__(self, db_path: str = "output/smart_building.db"):
        """Initialize database."""
        self._db_path = db_path
        self._lock = Lock()

        # Create directory if needed
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

        # Initialize database
        self._init_database()
        logger.info(f"DatabasePersistence initialized: {db_path}")

    def _init_database(self):
        """Create tables if they don't exist."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()

            # Metrics table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    tick_number INTEGER,
                    total_time_ms REAL,
                    simulation_step_ms REAL,
                    inference_ms REAL,
                    control_ms REAL,
                    energy_ms REAL,
                    api_response_ms REAL,
                    rooms_processed INTEGER,
                    occupancy_accuracy REAL,
                    energy_consumed_wh REAL
                )
                """
            )

            # Occupancy records table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS occupancy_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    room_id TEXT NOT NULL,
                    predicted_occupancy INTEGER,
                    true_occupancy INTEGER,
                    occupancy_probability REAL,
                    confidence REAL,
                    control_mode TEXT
                )
                """
            )

            # Energy records table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS energy_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    room_id TEXT NOT NULL,
                    power_watts REAL,
                    cumulative_wh REAL,
                    occupancy_predicted INTEGER,
                    control_mode TEXT
                )
                """
            )

            # System events table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS system_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    severity TEXT,
                    message TEXT,
                    details TEXT
                )
                """
            )

            # Anomalies table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS anomalies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    anomaly_type TEXT NOT NULL,
                    severity TEXT,
                    description TEXT,
                    details TEXT
                )
                """
            )

            conn.commit()

    def save_metric(self, metric: Dict[str, Any]):
        """Save a metrics record."""
        with self._lock:
            try:
                with sqlite3.connect(self._db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        INSERT INTO metrics (
                            timestamp, tick_number, total_time_ms,
                            simulation_step_ms, inference_ms, control_ms,
                            energy_ms, api_response_ms, rooms_processed,
                            occupancy_accuracy, energy_consumed_wh
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            metric.get("timestamp"),
                            metric.get("tick_number"),
                            metric.get("total_time_ms"),
                            metric.get("simulation_step_ms"),
                            metric.get("inference_ms"),
                            metric.get("control_ms"),
                            metric.get("energy_ms"),
                            metric.get("api_response_ms"),
                            metric.get("rooms_processed"),
                            metric.get("occupancy_accuracy"),
                            metric.get("energy_consumed_wh"),
                        ),
                    )
                    conn.commit()
            except Exception as e:
                logger.warning(f"Failed to save metric: {e}")

    def save_occupancy_record(self, record: Dict[str, Any]):
        """Save occupancy prediction record."""
        with self._lock:
            try:
                with sqlite3.connect(self._db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        INSERT INTO occupancy_records (
                            timestamp, room_id, predicted_occupancy,
                            true_occupancy, occupancy_probability,
                            confidence, control_mode
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            record.get("timestamp"),
                            record.get("room_id"),
                            record.get("predicted_occupancy"),
                            record.get("true_occupancy"),
                            record.get("occupancy_probability"),
                            record.get("confidence"),
                            record.get("control_mode"),
                        ),
                    )
                    conn.commit()
            except Exception as e:
                logger.warning(f"Failed to save occupancy record: {e}")

    def save_energy_record(self, record: Dict[str, Any]):
        """Save energy record."""
        with self._lock:
            try:
                with sqlite3.connect(self._db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        INSERT INTO energy_records (
                            timestamp, room_id, power_watts,
                            cumulative_wh, occupancy_predicted,
                            control_mode
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            record.get("timestamp"),
                            record.get("room_id"),
                            record.get("power_watts"),
                            record.get("cumulative_wh"),
                            record.get("occupancy_predicted"),
                            record.get("control_mode"),
                        ),
                    )
                    conn.commit()
            except Exception as e:
                logger.warning(f"Failed to save energy record: {e}")

    def save_event(self, event_type: str, message: str, severity: str = "info", details: Optional[str] = None):
        """Save system event."""
        with self._lock:
            try:
                with sqlite3.connect(self._db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        INSERT INTO system_events (
                            timestamp, event_type, message, severity, details
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            datetime.now().isoformat(),
                            event_type,
                            message,
                            severity,
                            details,
                        ),
                    )
                    conn.commit()
            except Exception as e:
                logger.warning(f"Failed to save event: {e}")

    def save_anomaly(self, anomaly: Dict[str, Any]):
        """Save detected anomaly."""
        with self._lock:
            try:
                with sqlite3.connect(self._db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        INSERT INTO anomalies (
                            timestamp, anomaly_type, severity,
                            description, details
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            datetime.now().isoformat(),
                            anomaly.get("type"),
                            anomaly.get("severity"),
                            anomaly.get("description"),
                            str(anomaly),
                        ),
                    )
                    conn.commit()
            except Exception as e:
                logger.warning(f"Failed to save anomaly: {e}")

    def query_metrics(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Query recent metrics."""
        with self._lock:
            try:
                with sqlite3.connect(self._db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT * FROM metrics ORDER BY timestamp DESC LIMIT ?",
                        (limit,)
                    )
                    return [dict(row) for row in cursor.fetchall()]
            except Exception as e:
                logger.warning(f"Failed to query metrics: {e}")
                return []

    def get_database_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        with self._lock:
            try:
                with sqlite3.connect(self._db_path) as conn:
                    cursor = conn.cursor()

                    stats = {}
                    for table in ["metrics", "occupancy_records", "energy_records", "system_events", "anomalies"]:
                        cursor.execute(f"SELECT COUNT(*) FROM {table}")
                        count = cursor.fetchone()[0]
                        stats[table] = count

                    return {
                        "database_path": self._db_path,
                        "file_size_mb": round(
                            os.path.getsize(self._db_path) / 1024 / 1024, 2
                        ),
                        "table_counts": stats,
                    }
            except Exception as e:
                logger.warning(f"Failed to get database stats: {e}")
                return {"error": str(e)}

    def export_occupancy_csv(self, output_path: str, room_id: Optional[str] = None):
        """Export occupancy records to CSV."""
        import csv

        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                if room_id:
                    cursor.execute(
                        "SELECT * FROM occupancy_records WHERE room_id = ? ORDER BY timestamp",
                        (room_id,)
                    )
                else:
                    cursor.execute("SELECT * FROM occupancy_records ORDER BY timestamp")

                rows = cursor.fetchall()

                if rows:
                    keys = rows[0].keys()
                    with open(output_path, "w", newline="") as f:
                        writer = csv.DictWriter(f, fieldnames=keys)
                        writer.writeheader()
                        for row in rows:
                            writer.writerow(dict(row))
                    logger.info(f"Exported {len(rows)} records to {output_path}")
                    return True
        except Exception as e:
            logger.warning(f"Failed to export CSV: {e}")
            return False
