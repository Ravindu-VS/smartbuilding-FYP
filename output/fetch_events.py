import urllib.request
import json

print("Checking port 5000...")
try:
    resp = urllib.request.urlopen("http://127.0.0.1:5000/api/events")
    data = json.loads(resp.read())
    print(json.dumps(data.get("events", [])[:5], indent=2))
except Exception as e:
    print(f"Error 5000: {e}")

print("Checking port 8001...")
try:
    resp = urllib.request.urlopen("http://127.0.0.1:8001/api/events")
    data = json.loads(resp.read())
    print(json.dumps(data.get("events", [])[:5], indent=2))
except Exception as e:
    print(f"Error 8001: {e}")
