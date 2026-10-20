// Copy this file to secrets.h (same folder) and fill in your values.
// secrets.h is listed in .gitignore, so your Wi-Fi password is never committed.
#pragma once

#define WIFI_SSID        "your-wifi-name"
#define WIFI_PASSWORD    "your-wifi-password"

// The edge brain (Raspberry Pi or this PC). run_local.bat prints this PC's IP address.
#define EDGE_SERVER_URL  "http://192.168.1.20:8001/api/hardware/sensor-data"
