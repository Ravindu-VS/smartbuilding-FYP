#pragma once
// Host-side stub of Adafruit GFX for the firmware syntax check.
#include <stdint.h>
class Adafruit_GFX {
 public:
  void setTextSize(uint8_t) {}
  void setTextColor(uint16_t) {}
  void setCursor(int16_t, int16_t) {}
  void drawFastHLine(int16_t, int16_t, int16_t, uint16_t) {}
  template <typename T> void print(T) {}
};
