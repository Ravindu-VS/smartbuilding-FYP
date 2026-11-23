#pragma once
#include "Wire.h"
class BH1750 {
 public:
  static const int CONTINUOUS_HIGH_RES_MODE = 0x10;
  bool begin(int = CONTINUOUS_HIGH_RES_MODE, uint8_t = 0x23, TwoWire* = &Wire) { return true; }
  float readLightLevel() { return 0.0F; }
};
