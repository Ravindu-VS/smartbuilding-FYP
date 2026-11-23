#pragma once
#include "Wire.h"
class Adafruit_INA219 {
 public:
  bool begin(TwoWire* = &Wire) { return true; }
  float getBusVoltage_V() { return 0.0F; }
  float getShuntVoltage_mV() { return 0.0F; }
  float getCurrent_mA() { return 0.0F; }
  float getPower_mW() { return 0.0F; }
};
