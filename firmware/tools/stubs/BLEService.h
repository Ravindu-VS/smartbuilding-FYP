#pragma once
#include <stdint.h>
#include "BLECharacteristic.h"

class BLEService {
 public:
  BLECharacteristic* createCharacteristic(const char*, uint32_t) {
    static BLECharacteristic characteristic;
    return &characteristic;
  }
  void start() {}
};
