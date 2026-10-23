import unittest
import os
import sys
import yaml
import sqlite3

# Ensure project root is on path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from integration.database_persistence import DatabasePersistence
from integration.state_manager import StateManager

class TestDbRedis(unittest.TestCase):
    
    def setUp(self):
        # Clean local test DB path
        self.test_sqlite_path = "output/test_smart_building.db"
        if os.path.exists(self.test_sqlite_path):
            os.remove(self.test_sqlite_path)

    def tearDown(self):
        if os.path.exists(self.test_sqlite_path):
            try:
                os.remove(self.test_sqlite_path)
            except OSError:
                pass

    def test_database_persistence_sqlite_fallback(self):
        print("Testing local SQLite database persistence...")
        # Clear env variables to force SQLite mode
        if "POSTGRES_HOST" in os.environ:
            del os.environ["POSTGRES_HOST"]
            
        db = DatabasePersistence(db_path=self.test_sqlite_path)
        self.assertFalse(db.use_postgres)
        
        # Test saving and retrieving event
        db.save_event("TEST_EVENT", "This is a local SQLite test message", "INFO", "test-details")
        stats = db.get_database_stats()
        self.assertEqual(stats["database_type"], "SQLite")
        self.assertEqual(stats["table_counts"]["system_events"], 1)

    def test_postgres_sql_formatting(self):
        print("Testing SQL dialect conversion...")
        db = DatabasePersistence(db_path=self.test_sqlite_path)
        
        # Force PostgreSQL mode locally for formatting tests
        db.use_postgres = True
        
        raw_sqlite_query = "INSERT INTO table VALUES (?, ?, ?)"
        formatted_pg_query = db._format_sql(raw_sqlite_query)
        self.assertIn("%s", formatted_pg_query)
        self.assertNotIn("?", formatted_pg_query)
        
        raw_sqlite_create = "id INTEGER PRIMARY KEY AUTOINCREMENT"
        formatted_pg_create = db._format_sql(raw_sqlite_create)
        self.assertIn("SERIAL PRIMARY KEY", formatted_pg_create)
        self.assertNotIn("AUTOINCREMENT", formatted_pg_create)

    def test_state_manager_redis_mock_vars(self):
        print("Testing StateManager Redis connection logic...")
        # Set environment variable to trigger Redis initialization block
        os.environ["REDIS_HOST"] = "localhost"
        
        state_mgr = StateManager()
        # Even if connection fails because Redis is not running locally,
        # it should initialize self.redis_client = None or Redis instance
        # and not raise a crash/exception.
        self.assertHasAttr(state_mgr, "redis_client")
        
    def assertHasAttr(self, obj, attr):
        self.assertTrue(hasattr(obj, attr), f"Object missing attribute {attr}")

if __name__ == '__main__':
    unittest.main()
