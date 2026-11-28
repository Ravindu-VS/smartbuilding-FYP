"""
Backup of the edge brain's SQLite store while it is being written (scripts/backup/sqlite_backup.py).
PostgreSQL backup/restore is exercised against the running stack by scripts/backup/test_restore.sh.
"""
import os
import sqlite3
import threading
import time

from scripts.backup.sqlite_backup import backup


def test_online_backup_is_consistent_and_retention_keeps_n(tmp_path):
    src = str(tmp_path / "edge_store.sqlite3")
    con = sqlite3.connect(src, check_same_thread=False)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE readings (id INTEGER PRIMARY KEY, v REAL)")
    con.executemany("INSERT INTO readings (v) VALUES (?)", [(i,) for i in range(5000)])
    con.commit()
    stop = threading.Event()

    def writer():                       # the edge brain keeps writing during the backup
        i = 0
        while not stop.is_set():
            con.execute("INSERT INTO readings (v) VALUES (?)", (i,))
            con.commit()
            i += 1

    th = threading.Thread(target=writer)
    th.start()
    try:
        paths = []
        for _ in range(4):
            paths.append(backup(src, str(tmp_path / "backups"), keep=3))
            time.sleep(1.1)              # backups are named by the second
    finally:
        stop.set()
        th.join()
    kept = sorted(os.listdir(tmp_path / "backups"))
    assert len(kept) == 3 and os.path.basename(paths[-1]) in kept
    with sqlite3.connect(paths[-1]) as b:
        assert b.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert b.execute("SELECT count(*) FROM readings").fetchone()[0] >= 5000
