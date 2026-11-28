#!/usr/bin/env python3
"""
Consistent online backup of the edge brain's SQLite store (WAL mode, written while running).

    python scripts/backup/sqlite_backup.py output/edge_store.sqlite3 backups/        # on the Pi (cron / timer)
    docker compose exec edge-brain python scripts/backup/sqlite_backup.py /app/output/edge_store.sqlite3 /app/output/backups

Uses SQLite's backup API (a copy of the files could be torn mid-transaction), then checks the copy with
PRAGMA integrity_check and keeps the newest N copies.
"""
import argparse
import os
import sqlite3
import sys
import time


def backup(src: str, dest_dir: str, keep: int = 7) -> str:
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, f"edge_store-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.sqlite3")
    s, d = sqlite3.connect(f"file:{src}?mode=ro", uri=True), sqlite3.connect(dest)
    try:
        s.backup(d)
        d.execute("PRAGMA journal_mode=DELETE")          # one self-contained file, no -wal/-shm beside it
        ok = d.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        s.close()
        d.close()
    if ok != "ok":
        os.remove(dest)
        raise RuntimeError(f"integrity check failed on the copy: {ok}")
    old = sorted(f for f in os.listdir(dest_dir) if f.startswith("edge_store-") and f.endswith(".sqlite3"))
    for f in old[:-keep] if keep > 0 else []:
        os.remove(os.path.join(dest_dir, f))
    return dest


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("db")
    p.add_argument("dest_dir")
    p.add_argument("--keep", type=int, default=7)
    a = p.parse_args()
    path = backup(a.db, a.dest_dir, a.keep)
    print(f"backup written: {path} ({os.path.getsize(path)} bytes, integrity ok)")
    sys.exit(0)
