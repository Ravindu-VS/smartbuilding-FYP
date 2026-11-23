#pragma once
// Minimal stand-in exposing the ArduinoJson v6/v7-compatible calls the firmware uses.
#include "Arduino.h"
struct JsonVariant {
  template <class T> JsonVariant& operator=(const T&) { return *this; }
  JsonVariant operator[](const char*) { return JsonVariant(); }
  template <class T> T as() const { return T(); }
  template <class T> bool is() const { return false; }
  const char* operator|(const char* d) const { return d; }
  int operator|(int d) const { return d; }
  float operator|(float d) const { return d; }
  double operator|(double d) const { return d; }
  bool operator|(bool d) const { return d; }
  bool isNull() const { return true; }
  bool operator==(const char*) const { return false; }
};
struct JsonObject : JsonVariant {};
template <size_t N> struct StaticJsonDocument {
  JsonVariant operator[](const char*) { return JsonVariant(); }
  JsonObject createNestedObject(const char*) { return JsonObject(); }
  bool containsKey(const char*) const { return false; }
};
struct DeserializationError {
  enum Code { Ok, InvalidInput, NoMemory };
  Code c = Ok;
  DeserializationError(Code x = Ok) : c(x) {}
  bool operator==(Code x) const { return c == x; }
  bool operator!=(Code x) const { return c != x; }
  explicit operator bool() const { return c != Ok; }
  const char* c_str() const { return ""; }
};
template <size_t N> size_t serializeJson(const StaticJsonDocument<N>&, String&) { return 0; }
template <size_t N> size_t serializeJson(const StaticJsonDocument<N>&, char*, size_t) { return 0; }
template <size_t N> DeserializationError deserializeJson(StaticJsonDocument<N>&, const String&) { return DeserializationError(); }
template <size_t N, class T> DeserializationError deserializeJson(StaticJsonDocument<N>&, const T*, size_t) { return DeserializationError(); }
