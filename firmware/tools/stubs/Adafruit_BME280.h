#pragma once
#include "Wire.h"
#define BME280_ADDRESS (0x77)
class Adafruit_BME280 {   // signatures copied from Adafruit_BME280.h (begin, read*)
 public:
  bool begin(uint8_t addr = BME280_ADDRESS, TwoWire *theWire = &Wire);
  float readTemperature(void);
  float readPressure(void);
  float readHumidity(void);
};
