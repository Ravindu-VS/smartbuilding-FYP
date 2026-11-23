#pragma once
#include "Arduino.h"
class WiFiClient;
class PubSubClient {
 public:
  PubSubClient(WiFiClient&) {}
  void setServer(const char*, uint16_t) {}
  void setCallback(void (*)(char*, byte*, unsigned int)) {}
  void setKeepAlive(uint16_t) {}
  bool setBufferSize(uint16_t) { return true; }
  bool connect(const char*, const char*, const char*, const char*, int, bool, const char*) { return true; }
  bool connect(const char*, const char*, int, bool, const char*) { return true; }
  bool connected() { return true; }
  void disconnect() {}
  PubSubClient& setSocketTimeout(uint16_t) { return *this; }
  bool publish(const char*, const char*, bool = false) { return true; }
  bool publish(const char*, const byte*, unsigned int) { return true; }
  bool publish(const char*, const byte*, unsigned int, bool) { return true; }
  bool subscribe(const char*, int = 0) { return true; }
  bool loop() { return true; }
  int state() { return 0; }
};
