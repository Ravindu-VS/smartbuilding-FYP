#pragma once
#include "Arduino.h"
class Servo {   // signatures from ESP32Servo.h
 public:
  int attach(int pin);
  int attach(int pin, int min, int max);
  void detach();
  void write(int value);
  bool attached();
};
class ESP32PWM { public: static void allocateTimer(int) {} };
