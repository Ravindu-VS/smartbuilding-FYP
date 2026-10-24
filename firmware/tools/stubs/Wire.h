#pragma once
#include "Arduino.h"
class TwoWire : public Stream {
 public:
  bool begin(int sda = -1, int scl = -1, uint32_t freq = 0) { return true; }
  void setClock(uint32_t) {}
  void beginTransmission(uint8_t) {}
  uint8_t endTransmission(bool = true) { return 0; }
  uint8_t requestFrom(uint8_t, uint8_t, bool = true) { return 0; }
  size_t write(uint8_t) override { return 1; }
  size_t write(const uint8_t*, size_t n) { return n; }
};
extern TwoWire Wire;
