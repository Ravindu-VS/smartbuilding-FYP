#pragma once
#include <stddef.h>
#include <stdint.h>

class Preferences {
 public:
  bool begin(const char*, bool) { return true; }
  uint32_t getUInt(const char*, uint32_t defaultValue) { return defaultValue; }
  size_t putUInt(const char*, uint32_t) { return sizeof(uint32_t); }
  void end() {}
};
