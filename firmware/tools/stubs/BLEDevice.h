#pragma once
#include <stdint.h>
#include <string>
#include "BLEServer.h"
#include "BLESecurity.h"

class BLEAdvertising {
 public:
  void addServiceUUID(const char*) {}
  void setScanResponse(bool) {}
  void start() {}
};

class BLEDevice {
 public:
  static void init(const std::string&) {}
  static void setMTU(uint16_t) {}
  static void setSecurityCallbacks(BLESecurityCallbacks*) {}
  static void startAdvertising() {}
  static BLEServer* createServer() {
    static BLEServer server;
    return &server;
  }
  static BLEAdvertising* getAdvertising() {
    static BLEAdvertising advertising;
    return &advertising;
  }
};
