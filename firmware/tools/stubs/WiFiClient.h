#pragma once
#include "Arduino.h"
class WiFiClient : public Stream {
 public:
  bool connected() const { return true; }
  void setConnectionTimeout(uint32_t) {}
  void stop() {}
};
