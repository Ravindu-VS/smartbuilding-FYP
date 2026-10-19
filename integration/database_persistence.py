import sqlite3
import logging
import os
from datetime import datetime
from typing import List, Dict, Any, Optional
from threading import Lock

logger = logging.getLogger(__name__)

# Try importing psycopg2 for Postgres support
try:
    import psycopg2
    import psycopg2.extras
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False


class DatabasePersistence:
    """
    Manage persistent storage, supporting both local SQLite and containerized PostgreSQL.
    Automatically switches to PostgreSQL if POSTGRES_HOST environment variable is defined.
    """

    def __init__(self, db_path: str = "output/smart_building.db"):
        """Initialize database connection config."""
        self._db_path = db_path
        self._lock = Lock()
        
        self.pg_host = os.environ.get("POSTGRES_HOST")
        self.pg_db = os.environ.get("POSTGRES_DB", "smartbuilding")
        self.pg_user = os.environ.get("POSTGRES_USER", "admin")
        self.pg_password = os.environ.get("POSTGRES_PASSWORD", "adminpassword")
        self.pg_port = os.environ.get("POSTGRES_PORT", "5432")
        
        self.use_postgres = self.pg_host is not None and POSTGRES_AVAILABLE
        
        if self.use_postgres:
            logger.info(f"Connecting to PostgreSQL database at {self.pg_host}:{self.pg_port}...")
        else:
            if self.pg_host and not POSTGRES_AVAILABLE:
                logger.warning("POSTGRES_HOST set but psycopg2 not installed. Falling back to SQLite.")
            os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
            logger.info(f"Connecting to local SQLite database at {db_path}...")
            
        # Initialize database tables
        self._init_database()

    def _get_connection(self):
        """Get database connection context manager."""
        if self.use_postgres:
            return psycopg2.connect(
                host=self.pg_host,
                database=self.pg_db,
                user=self.pg_user,
                password=self.pg_password,
                port=self.pg_port
            )
        else:
            return sqlite3.connect(self._db_path)

    def _format_sql(self, sql: str) -> str:
        """Translate SQL queries and placeholders between SQLite and PostgreSQL dialects."""
        if self.use_postgres:
            # Replace SQLite auto-increment syntax with PG Serial type
            sql = sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
            sql = sql.replace("REAL", "DOUBLE PRECISION")
            # Replace placeholder ? with %s
            sql = sql.replace("?", "%s")
        return sql

    def _init_database(self):
        """Create tables if they don't exist."""
        queries = [
            # Metrics table
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
            """,
            # Occupancy records table
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
            """,
            # Energy records table
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
            """,
            # System events table
            """
            CREATE TABLE IF NOT EXISTS system_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                severity TEXT,
                message TEXT,
                details TEXT
            )
            """,
            # Anomalies table
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
        ]

        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                for query in queries:
                    cursor.execute(self._format_sql(query))
                conn.commit()
            except Exception as e:
                logger.error(f"Failed to initialize database: {e}")
                raise
            finally:
                conn.close()

    def save_metric(self, metric: Dict[str, Any]):
        """Save a metrics record."""
        sql = """
        INSERT INTO metrics (
            timestamp, tick_number, total_time_ms,
            simulation_step_ms, inference_ms, control_ms,
            energy_ms, api_response_ms, rooms_processed,
            occupancy_accuracy, energy_consumed_wh
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        values = (
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
        )
        self._execute_write(sql, values)

    def save_occupancy_record(self, record: Dict[str, Any]):
        """Save occupancy prediction record."""
        sql = """
        INSERT INTO occupancy_records (
            timestamp, room_id, predicted_occupancy,
            true_occupancy, occupancy_probability,
            confidence, control_mode
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        values = (
            record.get("timestamp"),
            record.get("room_id"),
            record.get("predicted_occupancy"),
            record.get("true_occupancy"),
            record.get("occupancy_probability"),
            record.get("confidence"),
            record.get("control_mode"),
        )
        self._execute_write(sql, values)

    def save_energy_record(self, record: Dict[str, Any]):
        """Save energy record."""
        sql = """
        INSERT INTO energy_records (
            timestamp, room_id, power_watts,
            cumulative_wh, occupancy_predicted,
            control_mode
        ) VALUES (?, ?, ?, ?, ?, ?)
        """
        values = (
            record.get("timestamp"),
            record.get("room_id"),
            record.get("power_watts"),
            record.get("cumulative_wh"),
            record.get("occupancy_predicted"),
            record.get("control_mode"),
        )
        self._execute_write(sql, values)

    def save_event(self, event_type: str, message: str, severity: str = "info", details: Optional[str] = None):
        """Save system event."""
        sql = """
        INSERT INTO system_events (
            timestamp, event_type, message, severity, details
        ) VALUES (?, ?, ?, ?, ?)
        """
        values = (
            datetime.now().isoformat(),
            event_type,
            message,
            severity,
            details,
        )
        self._execute_write(sql, values)

    def save_anomaly(self, anomaly: Dict[str, Any]):
        """Save detected anomaly."""
        sql = """
        INSERT INTO anomalies (
            timestamp, anomaly_type, severity,
            description, details
        ) VALUES (?, ?, ?, ?, ?)
        """
        values = (
            datetime.now().isoformat(),
            anomaly.get("type"),
            anomaly.get("severity"),
            anomaly.get("description"),
            str(anomaly),
        )
        self._execute_write(sql, values)

    def _execute_write(self, sql: str, values: tuple):
        """Helper to run insert transactions thread-safely."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(self._format_sql(sql), values)
                conn.commit()
            except Exception as e:
                logger.warning(f"Database write execution error: {e}")
            finally:
                conn.close()

    def query_metrics(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Query recent metrics."""
        sql = "SELECT * FROM metrics ORDER BY timestamp DESC LIMIT ?"
        with self._lock:
            conn = self._get_connection()
            try:
                if self.use_postgres:
                    # Using RealDictCursor for Postgres
                    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                    cursor.execute(self._format_sql(sql), (limit,))
                    return [dict(row) for row in cursor.fetchall()]
                else:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()
                    cursor.execute(self._format_sql(sql), (limit,))
                    return [dict(row) for row in cursor.fetchall()]
            except Exception as e:
                logger.warning(f"Failed to query metrics: {e}")
                return []
            finally:
                conn.close()

    def get_database_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                stats = {}
                for table in ["metrics", "occupancy_records", "energy_records", "system_events", "anomalies"]:
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    count = cursor.fetchone()[0]
                    stats[table] = count
                
                size_mb = 0.0
                if not self.use_postgres:
                    size_mb = round(os.path.getsize(self._db_path) / 1024 / 1024, 2)
                    
                return {
                    "database_type": "PostgreSQL" if self.use_postgres else "SQLite",
                    "database_path": self.pg_host if self.use_postgres else self._db_path,
                    "file_size_mb": size_mb,
                    "table_counts": stats,
                }
            except Exception as e:
                logger.warning(f"Failed to get database stats: {e}")
                return {"error": str(e)}
            finally:
                conn.close()

    def export_occupancy_csv(self, output_path: str, room_id: Optional[str] = None):
        """Export occupancy records to CSV."""
        import csv
        with self._lock:
            conn = self._get_connection()
            try:
                if self.use_postgres:
                    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                else:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()

                if room_id:
                    sql = "SELECT * FROM occupancy_records WHERE room_id = ? ORDER BY timestamp"
                    cursor.execute(self._format_sql(sql), (room_id,))
                else:
                    sql = "SELECT * FROM occupancy_records ORDER BY timestamp"
                    cursor.execute(self._format_sql(sql))

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
            finally:
                conn.close()
