#pragma once
#include "Arduino.h"
#define WL_CONNECTED 3
#define WIFI_STA 1
#define WIFI_ALL_CHANNEL_SCAN 1
#define WIFI_CONNECT_AP_BY_SIGNAL 1
enum WiFiEvent_t {
  ARDUINO_EVENT_WIFI_READY,
  ARDUINO_EVENT_WIFI_STA_START,
  ARDUINO_EVENT_WIFI_STA_CONNECTED,
  ARDUINO_EVENT_WIFI_STA_GOT_IP,
  ARDUINO_EVENT_WIFI_STA_DISCONNECTED
};
struct WiFiEventInfo_t {
  struct {
    uint8_t reason;
  } wifi_sta_disconnected;
};
class IPAddress : public Printable { public: String toString() const { return String(); } };
class WiFiClass {
 public:
  void mode(int) {}
  void begin(const char*, const char*) {}
  int status() { return WL_CONNECTED; }
  IPAddress localIP() { return IPAddress(); }
  int32_t RSSI() { return 0; }
  bool disconnect(bool = false, bool = false, unsigned long = 100) { return true; }
  void reconnect() {}
  void setAutoReconnect(bool) {}
  void setSleep(bool) {}
  void setScanMethod(int) {}
  void setSortMethod(int) {}
  template <class Callback> void onEvent(Callback) {}
  String macAddress() { return String(); }
};
extern WiFiClass WiFi;
