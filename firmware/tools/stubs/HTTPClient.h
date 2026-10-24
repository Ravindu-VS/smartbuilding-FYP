#pragma once
#include "WiFi.h"
class HTTPClient {
 public:
  bool begin(const char*) { return true; }
  bool begin(const String&) { return true; }
  void addHeader(const char*, const char*) {}
  void setTimeout(uint16_t) {}
  void setConnectTimeout(int32_t) {}
  int POST(const String&) { return 200; }
  int POST(const char*) { return 200; }
  String getString() { return String(); }
  static String errorToString(int) { return String(); }
  void setReuse(bool) {}
  void end() {}
};
