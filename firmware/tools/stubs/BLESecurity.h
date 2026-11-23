#pragma once
#include <stdint.h>

struct esp_ble_auth_cmpl_t {
  bool success;
};

static const uint8_t ESP_LE_AUTH_REQ_SC_BOND = 1;
static const uint8_t ESP_IO_CAP_OUT = 2;
static const uint16_t ESP_GATT_PERM_READ_ENC_MITM = 1;
static const uint16_t ESP_GATT_PERM_WRITE_ENC_MITM = 2;

class BLESecurityCallbacks {
 public:
  virtual ~BLESecurityCallbacks() = default;
  virtual uint32_t onPassKeyRequest() { return 0; }
  virtual void onPassKeyNotify(uint32_t) {}
  virtual bool onConfirmPIN(uint32_t) { return false; }
  virtual bool onSecurityRequest() { return false; }
  virtual void onAuthenticationComplete(esp_ble_auth_cmpl_t) {}
};

class BLESecurity {
 public:
  void setAuthenticationMode(uint8_t) {}
  void setCapability(uint8_t) {}
  void setStaticPIN(uint32_t) {}
  static void setPassKey(bool, uint32_t) {}
};

