#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string>
#include <math.h>
#include <string.h>
#include <stdlib.h>
#include <stdio.h>
class Print;
class Printable { public: virtual size_t printTo(Print&) const { return 0; } };
typedef uint8_t byte;
typedef bool boolean;
#define HIGH 1
#define LOW 0
#define INPUT 0
#define OUTPUT 1
#define INPUT_PULLUP 2
#define INPUT_PULLDOWN 3
#define SERIAL_8N1 0x800001c
#define F(x) x
#define PI 3.14159265358979
class __FlashStringHelper;
class String {
 public:
  std::string s;
  String() {}
  String(const char* c) : s(c ? c : "") {}
  String(const std::string& x) : s(x) {}
  String(int v) : s(std::to_string(v)) {}
  String(unsigned int v) : s(std::to_string(v)) {}
  String(long v) : s(std::to_string(v)) {}
  String(unsigned long v) : s(std::to_string(v)) {}
  String(float v, unsigned d = 2) : s(std::to_string(v)) {}
  String(double v, unsigned d = 2) : s(std::to_string(v)) {}
  const char* c_str() const { return s.c_str(); }
  unsigned length() const { return s.size(); }
  String operator+(const String& o) const { return String(s + o.s); }
  String& operator+=(const String& o) { s += o.s; return *this; }
  bool operator==(const char* o) const { return s == o; }
  int indexOf(const char*) const { return -1; }
  String substring(unsigned a, unsigned b = 0) const { return String(); }
  int toInt() const { return 0; }
  void trim() {}
  bool startsWith(const char*) const { return false; }
};
inline String operator+(const char* a, const String& b) { return String(a) + b; }
class Print {
 public:
  size_t print(const String&) { return 0; }
  size_t print(const char*) { return 0; }
  size_t print(char) { return 0; }
  size_t print(int, int = 10) { return 0; }
  size_t print(unsigned int, int = 10) { return 0; }
  size_t print(long, int = 10) { return 0; }
  size_t print(unsigned long, int = 10) { return 0; }
  size_t print(double, int = 2) { return 0; }
  size_t print(const Printable&) { return 0; }
  size_t println(const Printable&) { return 0; }
  size_t println() { return 0; }
  size_t println(const String&) { return 0; }
  size_t println(const char*) { return 0; }
  size_t println(char) { return 0; }
  size_t println(int, int = 10) { return 0; }
  size_t println(unsigned int, int = 10) { return 0; }
  size_t println(long, int = 10) { return 0; }
  size_t println(unsigned long, int = 10) { return 0; }
  size_t println(double, int = 2) { return 0; }
  size_t printf(const char*, ...) __attribute__((format(printf, 2, 3))) { return 0; }
  virtual size_t write(uint8_t) { return 1; }
  size_t write(const uint8_t*, size_t n) { return n; }
};
class Stream : public Print {
 public:
  virtual int available() { return 0; }
  virtual int read() { return -1; }
  virtual int peek() { return -1; }
  virtual void flush() {}
  void setTimeout(unsigned long) {}
};
class HardwareSerial : public Stream {
 public:
  void begin(unsigned long, uint32_t = SERIAL_8N1, int8_t = -1, int8_t = -1) {}
  operator bool() const { return true; }
};
extern HardwareSerial Serial;
extern HardwareSerial Serial1;
unsigned long millis();
unsigned long micros();
void delay(unsigned long);
void delayMicroseconds(unsigned int);
void pinMode(uint8_t, uint8_t);
void digitalWrite(uint8_t, uint8_t);
int digitalRead(uint8_t);
uint16_t analogRead(uint8_t);
void analogReadResolution(uint8_t);
void analogSetAttenuation(int);
#define ADC_11db 3
long random(long);
long random(long, long);
long map(long, long, long, long, long);
void yield();
#ifndef ESP_ARDUINO_VERSION_MAJOR
#include <esp_arduino_version.h>
#endif
#if ESP_ARDUINO_VERSION_MAJOR >= 3
bool ledcAttach(uint8_t pin, uint32_t freq, uint8_t resolution);
bool ledcWrite(uint8_t pin, uint32_t duty);
#else
double ledcSetup(uint8_t channel, double freq, uint8_t resolution_bits);
void ledcAttachPin(uint8_t pin, uint8_t channel);
void ledcWrite(uint8_t channel, uint32_t duty);
#endif
template <class T, class L, class H> auto constrain(T x, L l, H h) -> decltype(x + l + h) { return x < l ? l : (x > h ? h : x); }
template <class A, class B> auto min(A a, B b) -> decltype(a + b) { return a < b ? a : b; }
template <class A, class B> auto max(A a, B b) -> decltype(a + b) { return a > b ? a : b; }
class EspClass { public: uint32_t getFreeHeap() { return 0; } void restart() {} uint64_t getEfuseMac() { return 0; } };
extern EspClass ESP;
