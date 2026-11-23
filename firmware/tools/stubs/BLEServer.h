#pragma once
#include "BLEService.h"

class BLEServer;

class BLEServerCallbacks {
 public:
  virtual ~BLEServerCallbacks() = default;
  virtual void onConnect(BLEServer*) {}
  virtual void onDisconnect(BLEServer*) {}
};

class BLEServer {
 public:
  BLEService* createService(const char*) {
    static BLEService service;
    return &service;
  }
  void setCallbacks(BLEServerCallbacks*) {}
};
