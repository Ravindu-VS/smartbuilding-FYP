#!/usr/bin/env python3
"""
Runs every Prometheus query of the Grafana dashboards against a live Prometheus and reports per panel:
OK (returns data), EMPTY (valid query, no data yet / target not present) or ERROR (the query is broken).

    python scripts/check_dashboards.py --prometheus http://localhost:9090      # exit 1 on any ERROR
    python scripts/check_dashboards.py --require-data "sb-ml,sb-application"   # also fail on EMPTY there

Also checks the dashboards themselves: valid JSON, unique uids, every panel's datasource uid is provisioned.
"""
import argparse
import glob
import json
import os
import sys
import urllib.parse
import urllib.request

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DASH = os.path.join(ROOT, "monitoring", "grafana", "dashboards")
DS = os.path.join(ROOT, "monitoring", "grafana", "provisioning", "datasources", "datasources.yml")


def query(prom: str, expr: str):
    expr = expr.replace("$__rate_interval", "1m").replace("$__interval", "1m")
    url = f"{prom}/api/v1/query?" + urllib.parse.urlencode({"query": expr})
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            body = json.loads(r.read())
    except urllib.error.HTTPError as e:
        return "ERROR", json.loads(e.read() or b"{}").get("error", str(e))
    res = body["data"]["result"]
    return ("OK", len(res)) if res else ("EMPTY", 0)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--prometheus", default="http://localhost:9090")
    p.add_argument("--require-data", default="", help="dashboard uids where EMPTY counts as a failure")
    p.add_argument("--allow-empty", default="sb_ble_connected,edge-brain-pi,sb_room_power_watts{source=~\"physical",
                   help="substrings of queries allowed to be EMPTY even in --require-data dashboards")
    a = p.parse_args()
    provisioned = {d["uid"] for d in yaml.safe_load(open(DS))["datasources"]}
    must = {u for u in a.require_data.split(",") if u}
    allow = [x for x in a.allow_empty.split(",") if x]
    uids, errors, empties, total = set(), 0, 0, 0
    for path in sorted(glob.glob(os.path.join(DASH, "*.json"))):
        d = json.load(open(path))
        assert d["uid"] not in uids, f"duplicate uid {d['uid']}"
        uids.add(d["uid"])
        print(f"\n{d['uid']} · {d['title']}")
        for panel in d["panels"]:
            if panel["type"] == "row":
                continue
            ds = panel.get("datasource", {}).get("uid")
            if ds not in provisioned:
                print(f"  ERROR  {panel['title']}: datasource {ds!r} not provisioned")
                errors += 1
            for t in panel.get("targets", []):
                if t.get("datasource", {}).get("uid", ds) != "prometheus":
                    print(f"  SKIP   {panel['title']}: SQL panel (checked against PostgreSQL by the stack test)")
                    continue
                total += 1
                state, info = query(a.prometheus, t["expr"])
                if state == "ERROR":
                    errors += 1
                elif state == "EMPTY":
                    empties += 1
                    if d["uid"] in must and not any(x in t["expr"] for x in allow):
                        errors += 1
                        state = "EMPTY!"
                print(f"  {state:6s} {panel['title']}" + (f"  [{t.get('legendFormat') or ''}]" if t.get("legendFormat") else "")
                      + (f"  -> {info}" if state.startswith("ERROR") else f"  ({info} series)" if state == "OK" else ""))
    print(f"\n{total} queries: {total - errors - empties} with data, {empties} empty, {errors} failures")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
