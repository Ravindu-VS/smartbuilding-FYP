#pragma once
// Host-side stub of Adafruit SSD1306 for the firmware syntax check.
#include "Adafruit_GFX.h"
#include "Wire.h"
#define SSD1306_SWITCHCAPVCC 0x02
#define SSD1306_WHITE 1
class Adafruit_SSD1306 : public Adafruit_GFX {
 public:
  Adafruit_SSD1306(uint8_t, uint8_t, TwoWire*, int8_t) {}
  bool begin(uint8_t = SSD1306_SWITCHCAPVCC, uint8_t = 0x3C) { return true; }
  void clearDisplay() {}
  void display() {}
};
