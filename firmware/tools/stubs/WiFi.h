#pragma once
#include "Arduino.h"
#define WL_CONNECTED 3
#define WIFI_STA 1
class IPAddress : public Printable { public: String toString() const { return String(); } };
class WiFiClass {
 public:
  void mode(int) {}
  void begin(const char*, const char*) {}
  int status() { return WL_CONNECTED; }
  IPAddress localIP() { return IPAddress(); }
  int32_t RSSI() { return 0; }
  void disconnect(bool = false) {}
  void reconnect() {}
  void setAutoReconnect(bool) {}
  void setSleep(bool) {}
  String macAddress() { return String(); }
};
extern WiFiClass WiFi;
