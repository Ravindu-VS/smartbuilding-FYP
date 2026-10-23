#!/usr/bin/env python3
"""
Export data collected by the edge brain (SQLite store) for offline analysis or retraining.

    python scripts/export_store.py --table readings --provenance room101_measured --out data/collected/room101.csv
    python scripts/export_store.py --table predictions --out data/collected/predictions.csv

Each export keeps the provenance column and refuses to mix classes in one file unless --allow-mixed is
given: measurements, synthetic rows and model predictions must stay distinguishable, and predictions
are never labels.  A sidecar .meta.json records the source database, query, row count and SHA-256.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TABLES = ("readings", "decisions", "predictions", "room_snapshots", "events", "commands")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=os.environ.get("EDGE_DB", os.path.join(ROOT, "output", "edge_store.sqlite3")))
    ap.add_argument("--table", choices=TABLES, required=True)
    ap.add_argument("--provenance", help="keep only this provenance class")
    ap.add_argument("--room", help="keep only this room id")
    ap.add_argument("--since")
    ap.add_argument("--until")
    ap.add_argument("--out", required=True)
    ap.add_argument("--allow-mixed", action="store_true")
    args = ap.parse_args(argv)
    if not os.path.exists(args.db):
        print(f"no store at {args.db}")
        return 1
    db = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    cols = [r[1] for r in db.execute(f"PRAGMA table_info({args.table})")]
    q, params = f"SELECT * FROM {args.table} WHERE 1=1", []
    if args.provenance:
        if "provenance" not in cols:
            print(f"{args.table} has no provenance column")
            return 1
        q += " AND provenance = ?"
        params.append(args.provenance)
    if args.room and "room_id" in cols:
        q += " AND room_id = ?"
        params.append(args.room)
    if args.since:
        q += " AND ts >= ?"
        params.append(args.since)
    if args.until:
        q += " AND ts <= ?"
        params.append(args.until)
    q += " ORDER BY ts, id"
    rows = [dict(r) for r in db.execute(q, params)]
    if "provenance" in cols:
        classes = sorted({r["provenance"] for r in rows})
        if len(classes) > 1 and not args.allow_mixed:
            print(f"rows of several provenance classes {classes}: choose one with --provenance (or --allow-mixed)")
            return 2
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    sha = hashlib.sha256(open(args.out, "rb").read()).hexdigest()
    meta = {"source_db": os.path.abspath(args.db), "table": args.table, "query": q, "params": params,
            "rows": len(rows), "sha256": sha, "exported_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    with open(args.out + ".meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    print(f"{len(rows)} rows -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
