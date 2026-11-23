#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string>

class BLECharacteristic;

class BLECharacteristicCallbacks {
 public:
  virtual ~BLECharacteristicCallbacks() = default;
  typedef enum {
    SUCCESS_INDICATE,
    SUCCESS_NOTIFY,
    ERROR_INDICATE_DISABLED,
    ERROR_NOTIFY_DISABLED,
    ERROR_GATT,
    ERROR_NO_CLIENT,
    ERROR_NO_SUBSCRIBER,
    ERROR_INDICATE_TIMEOUT,
    ERROR_INDICATE_FAILURE
  } Status;
  virtual void onWrite(BLECharacteristic*) {}
  virtual void onStatus(BLECharacteristic*, Status, uint32_t) {}
};

class BLECharacteristic {
 public:
  static const uint32_t PROPERTY_READ = 1;
  static const uint32_t PROPERTY_WRITE = 2;
  static const uint32_t PROPERTY_NOTIFY = 4;
  void setAccessPermissions(uint16_t) {}
  void setCallbacks(BLECharacteristicCallbacks*) {}
  void addDescriptor(void*) {}
  void setValue(uint8_t*, size_t) {}
  std::string getValue() const { return {}; }
  void notify() {}
};
