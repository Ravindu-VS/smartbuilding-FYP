#include <Wire.h>
#include <WiFi.h>
#include <esp_coexist.h>
#include <WiFiClient.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BME280.h>
#include <BH1750.h>
#include <Adafruit_INA219.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLE2902.h>
#include <BLESecurity.h>
#include <Preferences.h>
#include <freertos/FreeRTOS.h>

#if __has_include("secrets.h")
#include "secrets.h"
#endif

#ifndef WIFI_SSID
#define WIFI_SSID ""
#endif
#ifndef WIFI_PASSWORD
#define WIFI_PASSWORD ""
#endif
#ifndef MQTT_BROKER_IP
#define MQTT_BROKER_IP ""
#endif
#ifndef MQTT_PORT
#define MQTT_PORT 1883
#endif
#ifndef MQTT_USERNAME
#define MQTT_USERNAME ""
#endif
#ifndef MQTT_PASSWORD
#define MQTT_PASSWORD ""
#endif

// ===================================================================================================
// ROOM 101 WIRING (ESP32-S3-DevKitC-1 v1.0). Full circuit: docs/wiring/room101-wiring.html
//   GPIO   header  connects to
//   9      J1-15   I2C SDA  -> INA219 SDA, BME280 SDA, BH1750 SDA, OLED SDA
//   8      J1-12   I2C SCL  -> INA219 SCL, BME280 SCL, BH1750 SCL, OLED SCL
//   1      J3-4    MQ-135 AO through R1 10k; R2 15k from GPIO1 to GND (AO x 15/25, max 3.0 V)
//   2      J3-5    MQ-135 DO through R3 10k; R4 22k from GPIO2 to GND (DO swings to 5 V on the module)
//   4      J1-4    HC-SR501 PIR OUT (3.3 V output, no resistor)
//   10     J1-16   R5 1k -> Q1 BC547 base; R6 10k base -> GND; Q1 collector -> relay IN, emitter -> GND
//                  (GPIO10 HIGH = Q1 on = relay IN low = fan ON)
//   6/7/5  J1-6/7/5     light LED HW-478 R/G/B through 150/68/68 ohm, common (-) to GND
//   11/12/13 J1-17/18/19 AC indicator LED R/G/B through 150/68/68 ohm, long leg (-) to GND
//   14/15/16 J1-20/8/9   status LED R/G/B through 150/68/68 ohm, long leg (-) to GND
//   48     J3-16         onboard RGB LED of the DevKitC-1 v1.0 (no wire): Wi-Fi/MQTT link state
// I2C addresses: INA219 0x40, BME280 0x76, BH1750 0x23 (ADDR to GND), OLED SSD1306 0x3C (JMD0.96A-2: GND VCC SCL SDA)
// Power: 12 V in -> F1 1 A -> D1 1N5822 -> C1 470 uF -> LM2596 (5.0 V) -> C2 470 uF = +5 V rail
//        +5 V rail -> relay VCC, PIR VCC, MQ-135 VCC, and D3 1N5819 -> ESP32 5V pin (J1-21, C3 100 nF to GND)
//        ESP32 3V3 (J1-1) -> INA219, BME280, BH1750, OLED VCC
// Raspberry Pi 4B: no wire to this board (Wi-Fi/MQTT + Bluetooth LE), own 5.1 V 3 A USB-C supply
// Fan branch: +12 V (after D1) -> INA219 VIN+ -> VIN- -> relay COM -> NO -> fan + ; fan - -> GND; D2 1N4007 across the fan
// ===================================================================================================
#define PIN_SDA 9
#define INA219_SAMPLES 16
#define INA219_SHUNT_OHMS 0.1f   // R100 shunt on the INA219 module
#define PIN_SCL 8
#define PIN_MQ135_AO 1
#define PIN_MQ135_DO 2
#define PIN_PIR 4
#define PIN_RELAY 10
#define PIN_RGB_B 5
#define PIN_RGB_R 6
#define PIN_RGB_G 7
// Indicator RGB LEDs (on/off per colour, no PWM: the S3 has 8 LEDC channels and the light LED uses 3).
// "AC" LED: what the AC would be doing (the room has no AC actuator). "Status" LED: controller state.
#define PIN_AC_R 11
#define PIN_AC_G 12
#define PIN_AC_B 13
#define PIN_ST_R 14
#define PIN_ST_G 15
#define PIN_ST_B 16
#ifndef RGB_BUILTIN
#define RGB_BUILTIN 48   // ESP32-S3-DevKitC-1 v1.0: onboard addressable RGB LED on GPIO48 (v1.1 boards use 38)
#endif

#define ROOM_ID "f2_office_a"
#define TELEMETRY_TOPIC "sb/v1/room/f2_office_a/telemetry"
#define COMMAND_TOPIC "sb/v1/room/f2_office_a/command"
#define ACK_TOPIC "sb/v1/room/f2_office_a/ack"
#define STATUS_TOPIC "sb/v1/room/f2_office_a/status"
#define EDGE_STATUS_TOPIC "sb/v1/edge/status"
#define BLE_DEVICE_NAME "SB-Room101"
#define BLE_SERVICE_UUID "7c6f0001-4f3b-4c1a-9b2d-8a8b2f010101"
#define BLE_FRAME_UUID "7c6f0002-4f3b-4c1a-9b2d-8a8b2f010101"
#define FW_VERSION "room101-2026.11.25"

// The relay module (5 V coil, low-level trigger) is driven through NPN transistor Q1 (BC547, R5 1k to the base,
// R6 10k base to GND; docs/wiring/room101-wiring.html): GPIO10 HIGH turns Q1 on, pulls IN low and closes the relay.
// So the pin is active-HIGH, and the fan stays off while the board boots (GPIO10 floats, R6 holds Q1 off).
const bool RELAY_ACTIVE_LOW = false;
const bool RGB_COMMON_ANODE = false;
const bool INDICATOR_COMMON_ANODE = false;   // the two indicator LEDs: common cathode, COM to GND
const unsigned long SENSOR_INTERVAL_MS = 3000;
const unsigned long MQTT_RETRY_MS = 5000;
const unsigned long MQTT_COMMAND_TIMEOUT_MS = 30000;
const unsigned long MQTT_RETRY_WITH_BLE_MS = 15000;   // retry less often while BLE carries the data
const unsigned long MQTT_CONNECT_TIMEOUT_MS = 3000;   // a missing broker must not stall the loop for long
const uint16_t MQTT_KEEPALIVE_S = 60;                 // tolerant of short radio-sharing pauses
const unsigned long SENSOR_RETRY_MS = 30000;          // re-probe I2C sensors that were not found
const unsigned long BENCH_HOLD_MS = 120000;           // serial bench commands hold for 2 minutes
const uint16_t MAX_COMMAND_HOLD_S = 600;
const uint16_t MIN_MQTT_PAUSE_S = 10;
const uint16_t MAX_MQTT_PAUSE_S = 300;
// BLE frames: 4-byte header + data. 16 data bytes fit the 23-byte default ATT MTU; after the
// Pi negotiates a larger MTU each frame carries up to 240 bytes, so a telemetry message needs
// three or four notifications instead of forty-four.
const size_t BLE_FRAME_DATA_SIZE = 16;
const size_t BLE_MAX_FRAME_DATA = 240;
const uint16_t BLE_PREFERRED_MTU = 247;
const size_t BLE_MAX_MESSAGE_SIZE = 1024;
const uint8_t BLE_MAX_FRAMES = BLE_MAX_MESSAGE_SIZE / BLE_FRAME_DATA_SIZE;

Adafruit_BME280 bme;
BH1750 lightMeter;
Adafruit_INA219 ina219;
// JMD0.96A-2: 0.96" 128x64 SSD1306 OLED on the same I2C bus (0x3C), used as the room's energy meter.
const uint8_t OLED_ADDRESS = 0x3C;
const unsigned long OLED_REFRESH_MS = 1000;
Adafruit_SSD1306 oled(128, 64, &Wire, -1);
bool oledAvailable = false;
unsigned long lastOledDraw = 0;
double energyWh = 0.0;                 // fan-branch energy since boot, integrated from INA219 power
unsigned long lastEnergySample = 0;
WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);
BLEServer* bleServer = nullptr;
BLECharacteristic* bleFrameCharacteristic = nullptr;
Preferences blePreferences;
portMUX_TYPE bleCommandMux = portMUX_INITIALIZER_UNLOCKED;

bool bmeAvailable = false;
bool bh1750Available = false;
bool ina219Available = false;
volatile bool bleClientConnected = false;
volatile uint16_t bleConnHandle = 0;
volatile uint16_t blePeerMtu = 23;
volatile bool bleNotifyFailed = false;
uint32_t bleNotifyRetries = 0;
uint32_t bleNotifyDrops = 0;
uint32_t blePairingPasskey = 0;
uint8_t bleTxSequence = 0;
char bleCommandBuffer[BLE_MAX_MESSAGE_SIZE];
size_t bleCommandLength = 0;
bool bleCommandPending = false;
uint8_t bleAssembly[BLE_MAX_FRAMES][BLE_MAX_FRAME_DATA];
uint8_t bleAssemblyLengths[BLE_MAX_FRAMES];
uint8_t bleAssemblySequence = 0;
uint8_t bleAssemblyCount = 0;
uint64_t bleAssemblyMask = 0;
const char* rgbState = "OFF";
char acLedState[8] = "OFF";          // ac_led from the edge: OFF ECO LOW COOL MAX
char statusFromEdge[10] = "OFF";     // status_led from the edge: AI RULE MANUAL WARNING TEST
const char* statusShown = "OFF";     // what the status LED shows (edge state, or LOST / BENCH locally)
char lastStatusDetail[48] = "";
char commandHistory[8][65] = {};
uint8_t commandHistoryNext = 0;

bool fanState = false;
uint8_t lightLevel = 0;
unsigned long lastSensorRead = 0;
unsigned long lastMqttAttempt = 0;
// The edge answers every reading with a command, so a connected MQTT link that has delivered nothing
// for 12 s has stalled (seen on the factory guest Wi-Fi). Writing into a stalled TCP socket blocks the
// loop for up to 10 s per write once the send buffer is full, so the socket is dropped instead.
unsigned long lastMqttRx = 0;
const unsigned long MQTT_STALL_MS = 12000;
unsigned long lastCommandReceived = 0;
unsigned long lastWifiAttempt = 0;
bool wifiBeginStarted = false;
uint32_t telemetrySequence = 0;
bool edgeOnline = false;
unsigned long mqttPausedUntil = 0;     // diagnostic MQTT pause (BLE fallback test)
bool mqttPaused = false;
unsigned long rgbHoldUntil = 0;        // manual/test hold: automatic commands keep off the LED
unsigned long fanHoldUntil = 0;        // manual/test hold: automatic commands keep off the relay
unsigned long benchUntil = 0;          // serial bench session: the operator is at the board
bool failSafeActive = false;
unsigned long lastSensorRetry = 0;
uint32_t bmeRejected = 0;

struct Readings {
  bool bmeOk = false;
  float temperature = NAN;
  float humidity = NAN;
  float pressure = NAN;
  bool luxOk = false;
  float lux = NAN;
  int mqRaw = 0;
  int mqMilliVolts = 0;
  bool mqDigitalHigh = false;
  bool motion = false;
  bool inaOk = false;
  float busVoltage = NAN;
  float shuntMilliVolts = NAN;
  float currentMA = NAN;
  float powerMW = NAN;
};
Readings latest;

bool queueBleCommand(const uint8_t* payload, size_t length);
void writeRgbPwm(uint8_t red, uint8_t green, uint8_t blue);
void handleCommandPayload(byte* payload, unsigned int length);
bool parseActuatorState(const char* value, bool currentState, bool& nextState);
bool rememberCommand(const char* commandId);

class RoomBleServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer*) override {
    bleClientConnected = true;
    blePeerMtu = 23;
  }

  void onDisconnect(BLEServer*) override {
    bleClientConnected = false;
    blePeerMtu = 23;
    BLEDevice::startAdvertising();
  }

#if defined(CONFIG_NIMBLE_ENABLED)
  void onConnect(BLEServer* server, ble_gap_conn_desc* desc) override {
    bleConnHandle = desc->conn_handle;
    onConnect(server);
    // Ask for a relaxed 50-100 ms connection interval (units of 1.25 ms, supervision timeout 6 s).
    // BlueZ connects at ~7.5-30 ms, which leaves the shared 2.4 GHz radio almost no time for Wi-Fi:
    // in the 23 Nov 2026 run the board answered only 1 of 20 pings and MQTT could not connect.
    server->updateConnParams(desc->conn_handle, 40, 80, 0, 600);
  }

  void onMtuChanged(BLEServer*, ble_gap_conn_desc* desc, uint16_t mtu) override {
    bleConnHandle = desc->conn_handle;
    blePeerMtu = mtu;
    Serial.printf("BLE MTU negotiated: %u\n", (unsigned)mtu);
  }
#elif defined(CONFIG_BLUEDROID_ENABLED)
  void onMtuChanged(BLEServer*, esp_ble_gatts_cb_param_t* param) override {
    bleConnHandle = param->mtu.conn_id;
    blePeerMtu = param->mtu.mtu;
    Serial.printf("BLE MTU negotiated: %u\n", (unsigned)param->mtu.mtu);
  }
#endif
};

class RoomBleSecurityCallbacks : public BLESecurityCallbacks {
  uint32_t onPassKeyRequest() override {
    return blePairingPasskey;
  }

  void onPassKeyNotify(uint32_t passKey) override {
    Serial.printf("BLE pairing passkey: %06lu\n", (unsigned long)passKey);
  }

  bool onSecurityRequest() override {
    return true;
  }

#if defined(CONFIG_NIMBLE_ENABLED)
  void onAuthenticationComplete(ble_gap_conn_desc*, int status) override {
    Serial.println(status == 0 ? "BLE peer paired" : "BLE pairing failed");
  }
#elif defined(CONFIG_BLUEDROID_ENABLED)
  void onAuthenticationComplete(esp_ble_auth_cmpl_t result) override {
    Serial.println(result.success ? "BLE peer paired" : "BLE pairing failed");
  }
#endif

  bool onConfirmPIN(uint32_t) override {
    return true;
  }
};

class RoomBleFrameCallbacks : public BLECharacteristicCallbacks {
  void onStatus(BLECharacteristic*, Status status, uint32_t) override {
    if (status == Status::ERROR_GATT) {
      bleNotifyFailed = true;   // the host stack had no buffer for this notification
    }
  }

  void onWrite(BLECharacteristic* characteristic) override {
    const String frame = characteristic->getValue();
    const uint8_t* frameData = reinterpret_cast<const uint8_t*>(frame.c_str());
    const size_t frameLength = frame.length();
    if (frameLength < 5 || frameLength > 4 + BLE_MAX_FRAME_DATA || frameData[0] != 'C') {
      return;
    }

    const uint8_t sequence = frameData[1];
    const uint8_t index = frameData[2];
    const uint8_t count = frameData[3];
    const size_t payloadLength = frameLength - 4;
    if (count == 0 || count > BLE_MAX_FRAMES || index >= count ||
        payloadLength > BLE_MAX_FRAME_DATA) {
      return;
    }

    if (sequence != bleAssemblySequence || count != bleAssemblyCount) {
      if (index != 0) {
        return;
      }
      bleAssemblySequence = sequence;
      bleAssemblyCount = count;
      bleAssemblyMask = 0;
      memset(bleAssemblyLengths, 0, sizeof(bleAssemblyLengths));
    }

    memcpy(bleAssembly[index], frameData + 4, payloadLength);
    bleAssemblyLengths[index] = static_cast<uint8_t>(payloadLength);
    bleAssemblyMask |= (uint64_t)1 << index;
    const uint64_t expectedMask = count == 64 ? UINT64_MAX : (((uint64_t)1 << count) - 1);
    if (bleAssemblyMask != expectedMask) {
      return;
    }

    uint8_t complete[BLE_MAX_MESSAGE_SIZE];
    size_t completeLength = 0;
    for (uint8_t part = 0; part < count; part++) {
      if (completeLength + bleAssemblyLengths[part] > sizeof(complete)) {
        bleAssemblyMask = 0;
        bleAssemblyCount = 0;
        return;
      }
      memcpy(complete + completeLength, bleAssembly[part], bleAssemblyLengths[part]);
      completeLength += bleAssemblyLengths[part];
    }
    bleAssemblyMask = 0;
    bleAssemblyCount = 0;
    if (!queueBleCommand(complete, completeLength)) {
      Serial.println("BLE command rejected: command queue is full or payload size is invalid");
    }
  }
};

void setFan(bool on) {
  fanState = on;
  digitalWrite(PIN_RELAY, RELAY_ACTIVE_LOW ? (on ? LOW : HIGH) : (on ? HIGH : LOW));
}

bool holdActive(unsigned long until) {
  return until != 0 && (long)(until - millis()) > 0;
}

uint16_t holdSecondsLeft(unsigned long until) {
  return holdActive(until) ? (uint16_t)((until - millis() + 999UL) / 1000UL) : 0;
}

bool benchActive() {
  return holdActive(benchUntil);
}

void setRGB(uint8_t red, uint8_t green, uint8_t blue) {
  const bool active = red || green || blue;
  if (!active) {
    rgbState = "OFF";
  } else if (red == 255 && green == 0 && blue == 0) {
    rgbState = "RED";
  } else if (red == 0 && green == 255 && blue == 0) {
    rgbState = "GREEN";
  } else if (red == 0 && green == 0 && blue == 255) {
    rgbState = "BLUE";
  } else if (red == 255 && green == 255 && blue == 255) {
    rgbState = "WHITE";
  } else {
    rgbState = "CUSTOM";
  }

  if (RGB_COMMON_ANODE) {
    red = 255 - red;
    green = 255 - green;
    blue = 255 - blue;
  }
  writeRgbPwm(red, green, blue);
  lightLevel = active ? 255 : 0;
}

void writeRgbPwm(uint8_t red, uint8_t green, uint8_t blue) {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcWrite(PIN_RGB_R, red);
  ledcWrite(PIN_RGB_G, green);
  ledcWrite(PIN_RGB_B, blue);
#else
  ledcWrite(0, red);
  ledcWrite(1, green);
  ledcWrite(2, blue);
#endif
}

void attachRgbPwm() {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  const bool r = ledcAttach(PIN_RGB_R, 5000, 8);
  const bool g = ledcAttach(PIN_RGB_G, 5000, 8);
  const bool b = ledcAttach(PIN_RGB_B, 5000, 8);
#else
  ledcSetup(0, 5000, 8);
  ledcSetup(1, 5000, 8);
  ledcSetup(2, 5000, 8);
  ledcAttachPin(PIN_RGB_R, 0);
  ledcAttachPin(PIN_RGB_G, 1);
  ledcAttachPin(PIN_RGB_B, 2);
  const bool r = true;
  const bool g = true;
  const bool b = true;
#endif
  Serial.printf("RGB PWM on GPIO R%d/G%d/B%d: %s\n", PIN_RGB_R, PIN_RGB_G, PIN_RGB_B,
                (r && g && b) ? "ready" : "FAILED");
}

void detachRgbPwm() {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcDetach(PIN_RGB_R);
  ledcDetach(PIN_RGB_G);
  ledcDetach(PIN_RGB_B);
#else
  ledcDetachPin(PIN_RGB_R);
  ledcDetachPin(PIN_RGB_G);
  ledcDetachPin(PIN_RGB_B);
#endif
}

// Bench check of the HW-478 wiring without PWM: each colour pin is driven as a plain GPIO HIGH
// for four seconds. Measure GPIO-to-GND with a multimeter (about 3.3 V when driven) and watch
// the module: if the voltage is there but the LED stays dark, the fault is the module, its
// series resistor or the common-pin connection, not the firmware.
void rgbChannelDiagnostic() {
  struct Channel { const char* name; int pin; };
  const Channel channels[] = {{"RED", PIN_RGB_R}, {"GREEN", PIN_RGB_G}, {"BLUE", PIN_RGB_B}};
  Serial.println("RGB channel diagnostic (plain GPIO, no PWM). Common pin must go to GND.");
  detachRgbPwm();
  for (const Channel& channel : channels) {
    pinMode(channel.pin, OUTPUT);
    digitalWrite(channel.pin, LOW);
  }
  for (const Channel& channel : channels) {
    const int level = RGB_COMMON_ANODE ? LOW : HIGH;
    digitalWrite(channel.pin, level);
    Serial.printf("  %s: GPIO %d driven %s for 4 s - expect ~%s V between GPIO %d and GND\n",
                  channel.name, channel.pin, level == HIGH ? "HIGH" : "LOW",
                  level == HIGH ? "3.3" : "0.0", channel.pin);
    delay(4000);
    digitalWrite(channel.pin, RGB_COMMON_ANODE ? HIGH : LOW);
  }
  attachRgbPwm();
  setRGB(0, 0, 0);
  Serial.println("RGB channel diagnostic finished; LED OFF.");
}

void writeIndicator(uint8_t pr, uint8_t pg, uint8_t pb, bool r, bool g, bool b) {
  const bool on = !INDICATOR_COMMON_ANODE;
  digitalWrite(pr, r ? on : !on);
  digitalWrite(pg, g ? on : !on);
  digitalWrite(pb, b ? on : !on);
}

// colours: ECO green, LOW cyan, COOL blue, MAX magenta, OFF dark
bool acLedColour(const char* s, bool& r, bool& g, bool& b) {
  r = g = b = false;
  if (strcmp(s, "OFF") == 0) return true;
  if (strcmp(s, "ECO") == 0) { g = true; return true; }
  if (strcmp(s, "LOW") == 0) { g = b = true; return true; }
  if (strcmp(s, "COOL") == 0) { b = true; return true; }
  if (strcmp(s, "MAX") == 0) { r = b = true; return true; }
  return false;
}

// colours: AI blue, RULE green, MANUAL yellow, WARNING red, TEST white; locally LOST red (blinking), BENCH white
bool statusLedColour(const char* s, bool& r, bool& g, bool& b) {
  r = g = b = false;
  if (strcmp(s, "OFF") == 0) return true;
  if (strcmp(s, "AI") == 0) { b = true; return true; }
  if (strcmp(s, "RULE") == 0) { g = true; return true; }
  if (strcmp(s, "MANUAL") == 0) { r = g = true; return true; }
  if (strcmp(s, "WARNING") == 0 || strcmp(s, "LOST") == 0) { r = true; return true; }
  if (strcmp(s, "TEST") == 0 || strcmp(s, "BENCH") == 0) { r = g = b = true; return true; }
  return false;
}

void setAcLed(const char* s) {
  bool r, g, b;
  if (!acLedColour(s, r, g, b)) return;
  strncpy(acLedState, s, sizeof(acLedState) - 1);
  acLedState[sizeof(acLedState) - 1] = '\0';
  writeIndicator(PIN_AC_R, PIN_AC_G, PIN_AC_B, r, g, b);
}

// Called every loop: the status LED shows the edge's state unless the board itself knows better.
void serviceStatusLed(bool edgeLost, bool bench) {
  const char* shown = bench ? "BENCH" : (edgeLost ? "LOST" : statusFromEdge);
  bool r, g, b;
  statusLedColour(shown, r, g, b);
  if (strcmp(shown, "LOST") == 0 && (millis() / 500) % 2 == 1) {
    r = false;    // blink 1 Hz: no controller reachable
  }
  statusShown = shown;
  writeIndicator(PIN_ST_R, PIN_ST_G, PIN_ST_B, r, g, b);
}

void setOnboardStatus(bool wifiConnected) {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  rgbLedWrite(RGB_BUILTIN, 0, wifiConnected ? 64 : 0, 0);
#else
  pinMode(RGB_BUILTIN, OUTPUT);
  digitalWrite(RGB_BUILTIN, wifiConnected ? HIGH : LOW);
#endif
}

size_t bleFrameDataSize() {
  const uint16_t mtu = blePeerMtu;
  if (mtu <= 3 + 4 + BLE_FRAME_DATA_SIZE) {
    return BLE_FRAME_DATA_SIZE;
  }
  return min(BLE_MAX_FRAME_DATA, (size_t)(mtu - 3 - 4));
}

bool sendBleMessage(char kind, const uint8_t* payload, size_t length) {
  if (!bleClientConnected || bleFrameCharacteristic == nullptr ||
      length == 0 || length > BLE_MAX_MESSAGE_SIZE) {
    return false;
  }

  const size_t chunk = bleFrameDataSize();
  const uint8_t count = (length + chunk - 1) / chunk;
  const uint8_t sequence = ++bleTxSequence;
  // Small frames (default MTU) need more air time per message, so pace them further apart.
  const unsigned long pacingMs = chunk > BLE_FRAME_DATA_SIZE ? 12 : 40;
  for (uint8_t index = 0; index < count; index++) {
    const size_t offset = index * chunk;
    const size_t chunkLength = min(chunk, length - offset);
    uint8_t frame[4 + BLE_MAX_FRAME_DATA];
    frame[0] = static_cast<uint8_t>(kind);
    frame[1] = sequence;
    frame[2] = index;
    frame[3] = count;
    memcpy(frame + 4, payload + offset, chunkLength);
    bool delivered = false;
    for (uint8_t attempt = 0; attempt < 4 && bleClientConnected; attempt++) {
      bleNotifyFailed = false;
      bleFrameCharacteristic->setValue(frame, chunkLength + 4);
      bleFrameCharacteristic->notify();
      if (!bleNotifyFailed) {
        delivered = true;
        break;
      }
      bleNotifyRetries++;
      delay(25 + 25 * attempt);   // let the controller drain its buffers, then resend this frame
    }
    if (!delivered) {
      bleNotifyDrops++;
      return false;
    }
    delay(pacingMs);
  }
  return true;
}

bool queueBleCommand(const uint8_t* payload, size_t length) {
  if (length == 0 || length > sizeof(bleCommandBuffer)) {
    return false;
  }

  bool queued = false;
  portENTER_CRITICAL(&bleCommandMux);
  if (!bleCommandPending) {
    memcpy(bleCommandBuffer, payload, length);
    bleCommandLength = length;
    bleCommandPending = true;
    queued = true;
  }
  portEXIT_CRITICAL(&bleCommandMux);
  return queued;
}

void processBleCommand() {
  uint8_t command[BLE_MAX_MESSAGE_SIZE];
  size_t length = 0;
  portENTER_CRITICAL(&bleCommandMux);
  if (bleCommandPending) {
    length = bleCommandLength;
    memcpy(command, bleCommandBuffer, length);
    bleCommandPending = false;
    bleCommandLength = 0;
  }
  portEXIT_CRITICAL(&bleCommandMux);
  if (length > 0) {
    handleCommandPayload(command, length);
  }
}

void initBleTransport() {
  blePreferences.begin("sb_ble", false);
  blePairingPasskey = blePreferences.getUInt("passkey", 0);
  if (blePairingPasskey < 100000 || blePairingPasskey > 999999) {
    blePairingPasskey = static_cast<uint32_t>(random(100000, 1000000));
    blePreferences.putUInt("passkey", blePairingPasskey);
  }
  blePreferences.end();

  BLEDevice::init(BLE_DEVICE_NAME);
  BLEDevice::setMTU(BLE_PREFERRED_MTU);
  BLEDevice::setSecurityCallbacks(new RoomBleSecurityCallbacks());
  BLESecurity* security = new BLESecurity();
  security->setAuthenticationMode(ESP_LE_AUTH_REQ_SC_BOND);
  security->setCapability(ESP_IO_CAP_OUT);
  BLESecurity::setPassKey(true, blePairingPasskey);

  bleServer = BLEDevice::createServer();
  bleServer->setCallbacks(new RoomBleServerCallbacks());
  BLEService* service = bleServer->createService(BLE_SERVICE_UUID);
  bleFrameCharacteristic = service->createCharacteristic(
      BLE_FRAME_UUID,
      BLECharacteristic::PROPERTY_READ |
      BLECharacteristic::PROPERTY_WRITE |
      BLECharacteristic::PROPERTY_NOTIFY);
  bleFrameCharacteristic->setAccessPermissions(
      ESP_GATT_PERM_READ_ENC_MITM | ESP_GATT_PERM_WRITE_ENC_MITM);
  bleFrameCharacteristic->setCallbacks(new RoomBleFrameCallbacks());
#if defined(CONFIG_BLUEDROID_ENABLED)
  bleFrameCharacteristic->addDescriptor(new BLE2902());
#endif
  service->start();

  BLEAdvertising* advertising = BLEDevice::getAdvertising();
  advertising->addServiceUUID(BLE_SERVICE_UUID);
  advertising->setScanResponse(true);
  BLEDevice::startAdvertising();
  Serial.printf("BLE fallback ready: %s, pairing passkey %06lu\n",
                BLE_DEVICE_NAME, (unsigned long)blePairingPasskey);
}

char lastAckedCommand[65] = "";
unsigned long lastAckedAt = 0;

void publishAck(const char* commandId, const char* status, bool appliedFan, uint8_t appliedLight) {
  strncpy(lastAckedCommand, commandId, sizeof(lastAckedCommand) - 1);
  lastAckedCommand[sizeof(lastAckedCommand) - 1] = '\0';
  lastAckedAt = millis();
  StaticJsonDocument<384> doc;
  doc["schema"] = "sb.ack/1";
  doc["msg_id"] = commandId;
  doc["status"] = status;
  JsonObject applied = doc.createNestedObject("applied");
  applied["fan"] = appliedFan ? 255 : 0;
  applied["relay"] = appliedFan;
  applied["led"] = appliedLight;
  applied["rgb"] = rgbState;
  applied["ac_led"] = acLedState;
  applied["status_led"] = statusFromEdge;
  applied["servo"] = 0;
  doc["rgb_hold_s"] = holdSecondsLeft(rgbHoldUntil);
  doc["fan_hold_s"] = holdSecondsLeft(fanHoldUntil);

  char payload[384];
  size_t length = serializeJson(doc, payload, sizeof(payload));
  // Redundant delivery: over MQTT and, while the gateway is connected, over BLE as well. The edge
  // matches ACKs by msg_id, so a second copy is harmless; a stalled Wi-Fi link is not.
  bool sent = false;
  if (mqtt.connected() && !mqttPaused) {
    sent = mqtt.publish(ACK_TOPIC, reinterpret_cast<const uint8_t*>(payload), length);
  }
  if (bleClientConnected) {
    sent = sendBleMessage('A', reinterpret_cast<const uint8_t*>(payload), length) || sent;
  }
  if (!sent) {
    Serial.printf("Acknowledgement unavailable: MQTT state=%d, BLE peer=%d\n",
                  mqtt.state(), bleClientConnected);
  }
}

bool parseActuatorState(const char* value, bool currentState, bool& nextState) {
  if (strcmp(value, "ON") == 0) {
    nextState = true;
  } else if (strcmp(value, "OFF") == 0) {
    nextState = false;
  } else if (strcmp(value, "TOGGLE") == 0) {
    nextState = !currentState;
  } else {
    return false;
  }
  return true;
}

bool rememberCommand(const char* commandId) {
  for (size_t i = 0; i < sizeof(commandHistory) / sizeof(commandHistory[0]); i++) {
    if (strcmp(commandHistory[i], commandId) == 0) {
      return false;
    }
  }
  strncpy(commandHistory[commandHistoryNext], commandId, sizeof(commandHistory[0]) - 1);
  commandHistory[commandHistoryNext][sizeof(commandHistory[0]) - 1] = '\0';
  commandHistoryNext = (commandHistoryNext + 1) %
                       (sizeof(commandHistory) / sizeof(commandHistory[0]));
  return true;
}

void handleCommandPayload(byte* payload, unsigned int length) {
  StaticJsonDocument<512> doc;
  DeserializationError err = deserializeJson(doc, payload, length);
  if (err) {
    Serial.print("Command JSON error: ");
    Serial.println(err.c_str());
    return;
  }

  if (!doc["msg_id"].is<const char*>()) {
    Serial.println("Command rejected: msg_id must be a string");
    return;
  }
  const char* commandId = doc["msg_id"].as<const char*>();
  if (commandId == nullptr || strlen(commandId) == 0 || strlen(commandId) > 64) {
    Serial.println("Command rejected: missing or invalid msg_id");
    return;
  }

  const char* error = nullptr;
  if (!doc["schema"].is<const char*>() ||
      strcmp(doc["schema"].as<const char*>(), "sb.command/1") != 0) {
    error = "unsupported schema";
  }

  const bool hasFanSpeed = !doc["fan_speed"].isNull();
  const bool hasFan = !doc["fan"].isNull();
  const bool hasRelay = !doc["relay"].isNull();
  const bool hasLightLevel = !doc["light_level"].isNull();
  const bool hasRgb = !doc["rgb"].isNull();
  const bool hasAcLed = !doc["ac_led"].isNull();
  const bool hasStatusLed = !doc["status_led"].isNull();
  // "hold_s" marks a manual/test command: the actuators it sets are kept for that many seconds and
  // automatic (Edge Brain) commands do not change them meanwhile. "hold_s": 0 releases a hold.
  const bool hasHold = !doc["hold_s"].isNull();
  // "test": "mqtt_pause" disconnects MQTT for "seconds" so the BLE fallback can be commissioned.
  const bool hasTest = !doc["test"].isNull();
  bool nextFanState = fanState;
  uint16_t holdSeconds = 0;
  uint16_t pauseSeconds = 0;

  if (!error && hasFanSpeed &&
      (!doc["fan_speed"].is<int>() || doc["fan_speed"].as<int>() < 0 ||
       doc["fan_speed"].as<int>() > 255)) {
    error = "fan_speed must be an integer from 0 to 255";
  }
  if (!error && hasLightLevel &&
      (!doc["light_level"].is<int>() || doc["light_level"].as<int>() < 0 ||
       doc["light_level"].as<int>() > 255)) {
    error = "light_level must be an integer from 0 to 255";
  }
  if (!error && hasHold) {
    if (!doc["hold_s"].is<int>() || doc["hold_s"].as<int>() < 0 ||
        doc["hold_s"].as<int>() > MAX_COMMAND_HOLD_S) {
      error = "hold_s must be an integer from 0 to 600";
    } else {
      holdSeconds = static_cast<uint16_t>(doc["hold_s"].as<int>());
    }
  }
  if (!error && hasTest) {
    if (!doc["test"].is<const char*>() || strcmp(doc["test"].as<const char*>(), "mqtt_pause") != 0) {
      error = "test must be \"mqtt_pause\"";
    } else if (!doc["seconds"].is<int>() || doc["seconds"].as<int>() < MIN_MQTT_PAUSE_S ||
               doc["seconds"].as<int>() > MAX_MQTT_PAUSE_S) {
      error = "mqtt_pause needs seconds from 10 to 300";
    } else if (!bleClientConnected) {
      error = "mqtt_pause refused: no BLE gateway connected";
    } else {
      pauseSeconds = static_cast<uint16_t>(doc["seconds"].as<int>());
    }
  }
  if (!error && ((hasFanSpeed && (hasFan || hasRelay)) || (hasFan && hasRelay))) {
    error = "use only one of fan_speed, fan, or relay";
  }
  if (!error && hasRgb && hasLightLevel) {
    error = "use either rgb or light_level, not both";
  }
  if (!error && hasAcLed) {
    bool r, g, b;
    if (!doc["ac_led"].is<const char*>() || !acLedColour(doc["ac_led"].as<const char*>(), r, g, b)) {
      error = "ac_led must be OFF, ECO, LOW, COOL or MAX";
    }
  }
  if (!error && hasStatusLed) {
    bool r, g, b;
    const char* st = doc["status_led"].is<const char*>() ? doc["status_led"].as<const char*>() : nullptr;
    if (st == nullptr || !statusLedColour(st, r, g, b) || strcmp(st, "LOST") == 0 || strcmp(st, "BENCH") == 0) {
      error = "status_led must be OFF, AI, RULE, MANUAL, WARNING or TEST";
    }
  }
  if (!error && !hasFanSpeed && !hasFan && !hasRelay && !hasLightLevel && !hasRgb && !hasTest &&
      !hasAcLed && !hasStatusLed) {
    error = "command has no supported actuator field";
  }
  if (!error && hasFanSpeed) {
    nextFanState = doc["fan_speed"].as<int>() > 0;
  }
  if (!error && (hasFan || hasRelay)) {
    const bool stateIsString = hasFan ? doc["fan"].is<const char*>() :
                                        doc["relay"].is<const char*>();
    const char* requestedState = hasFan ? doc["fan"].as<const char*>() :
                                          doc["relay"].as<const char*>();
    if (!stateIsString || requestedState == nullptr) {
      error = "fan/relay command must be a string";
    } else if (!parseActuatorState(requestedState, fanState, nextFanState)) {
      error = "fan/relay must be ON, OFF, or TOGGLE";
    }
  }
  if (!error && hasRgb) {
    if (!doc["rgb"].is<const char*>()) {
      error = "rgb command must be a string";
    } else {
      const char* color = doc["rgb"].as<const char*>();
      if (strcmp(color, "RED") != 0 && strcmp(color, "GREEN") != 0 &&
          strcmp(color, "BLUE") != 0 && strcmp(color, "WHITE") != 0 &&
          strcmp(color, "OFF") != 0) {
        error = "rgb must be RED, GREEN, BLUE, WHITE, or OFF";
      }
    }
  }
  if (error) {
    Serial.printf("Command rejected: %s\n", error);
    publishAck(commandId, "rejected", fanState, lightLevel);
    return;
  }
  edgeOnline = true;
  lastCommandReceived = millis();
  if (!rememberCommand(commandId)) {
    // The same command arrives twice when the gateway forwards it over BLE as well as MQTT. Re-ACK
    // only a late repeat (a QoS 1 redelivery whose first ACK may have been lost).
    if (strcmp(lastAckedCommand, commandId) != 0 || millis() - lastAckedAt > 10000UL) {
      publishAck(commandId, "applied", fanState, lightLevel);
    }
    return;
  }

  // A serial bench session has priority: the operator is at the board.
  const bool bench = benchActive();
  const bool manual = hasHold;
  const unsigned long holdUntil = holdSeconds > 0 ? millis() + holdSeconds * 1000UL : 0;
  bool fanSkipped = false;
  bool ledSkipped = false;

  if (hasFanSpeed || hasFan || hasRelay) {
    if (bench || (!manual && holdActive(fanHoldUntil))) {
      fanSkipped = true;
    } else {
      setFan(nextFanState);
      if (manual) {
        fanHoldUntil = holdUntil;
      }
    }
  }
  if (hasRgb || hasLightLevel) {
    if (bench || (!manual && holdActive(rgbHoldUntil))) {
      ledSkipped = true;
    } else {
      if (hasRgb) {
        const char* color = doc["rgb"].as<const char*>();
        if (strcmp(color, "RED") == 0) {
          setRGB(255, 0, 0);
        } else if (strcmp(color, "GREEN") == 0) {
          setRGB(0, 255, 0);
        } else if (strcmp(color, "BLUE") == 0) {
          setRGB(0, 0, 255);
        } else if (strcmp(color, "WHITE") == 0) {
          setRGB(255, 255, 255);
        } else {
          setRGB(0, 0, 0);
        }
      } else {
        const uint8_t ledLevel = static_cast<uint8_t>(doc["light_level"].as<int>());
        setRGB(ledLevel, ledLevel, ledLevel);
        lightLevel = ledLevel;
      }
      if (manual) {
        rgbHoldUntil = holdUntil;
      }
    }
  }

  // indicators show the edge's view; holds and bench sessions do not apply to them
  if (hasAcLed) {
    setAcLed(doc["ac_led"].as<const char*>());
  }
  if (hasStatusLed) {
    strncpy(statusFromEdge, doc["status_led"].as<const char*>(), sizeof(statusFromEdge) - 1);
    statusFromEdge[sizeof(statusFromEdge) - 1] = '\0';
  }

  publishAck(commandId, "applied", fanState, lightLevel);

  if (pauseSeconds > 0) {
    mqttPausedUntil = millis() + pauseSeconds * 1000UL;
    Serial.printf("MQTT paused for %u s by test command; BLE carries telemetry and commands\n",
                  (unsigned)pauseSeconds);
  }
  Serial.printf("Command applied: fan=%s, rgb=%s, light=%u, ac=%s, status=%s%s%s%s\n",
                fanState ? "ON" : "OFF", rgbState, (unsigned)lightLevel, acLedState, statusFromEdge,
                manual ? " (manual hold)" : "", fanSkipped ? " [fan held]" : "",
                ledSkipped ? " [LED held]" : "");
}

void mqttCallback(char* topic, byte* payload, unsigned int length) {
  lastMqttRx = millis();
  if (strcmp(topic, EDGE_STATUS_TOPIC) == 0) {
    StaticJsonDocument<128> doc;
    DeserializationError err = deserializeJson(doc, payload, length);
    if (!err && doc["state"] == "online") {
      edgeOnline = true;
      lastCommandReceived = millis();
    } else if (!err && doc["state"] == "offline") {
      edgeOnline = false;
      if (!benchActive()) {
        setFan(false);
        setRGB(0, 0, 0);
        rgbHoldUntil = 0;
        fanHoldUntil = 0;
      }
      Serial.println("MQTT edge reports offline: fail-safe actuators OFF");
    }
    return;
  }

  if (strcmp(topic, COMMAND_TOPIC) == 0) {
    handleCommandPayload(payload, length);
  }
}

void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) {
    setOnboardStatus(true);
    return;
  }
  setOnboardStatus(false);

  if (strlen(WIFI_SSID) == 0) {
    Serial.println("Wi-Fi configuration missing in secrets.h");
    return;
  }

  if (wifiBeginStarted) {
    if (millis() - lastWifiAttempt < 15000) {
      return; // Give 15 seconds for association, WPA3 handshake, and DHCP
    }
    Serial.println("Wi-Fi connection attempt timed out, retrying...");
    WiFi.disconnect(false, false, 1000);
    wifiBeginStarted = false;
  }

  lastWifiAttempt = millis();
  wifiBeginStarted = true;

  Serial.printf("Connecting to Wi-Fi SSID \"%s\" (password len: %d)...\n",
                WIFI_SSID, (int)strlen(WIFI_PASSWORD));
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(false);
  WiFi.setScanMethod(WIFI_ALL_CHANNEL_SCAN);
  WiFi.setSortMethod(WIFI_CONNECT_AP_BY_SIGNAL);
  // Wi-Fi and BLE share the ESP32-S3's single 2.4 GHz radio. ESP-IDF coexistence needs Wi-Fi modem
  // sleep; with sleep disabled, Wi-Fi was starved whenever BLE was busy (MQTT connect failures and
  // broker keepalive timeouts in the 23 Nov 2026 run).
  WiFi.setSleep(true);
  esp_coex_preference_set(ESP_COEX_PREFER_WIFI);   // BLE is the fallback link; Wi-Fi gets the radio first
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

bool mqttConnected() {
  return mqtt.connected();
}

void serviceMqttPause() {
  if (mqttPausedUntil == 0) {
    return;
  }
  if (holdActive(mqttPausedUntil)) {
    if (!mqttPaused) {
      mqttPaused = true;
      if (mqtt.connected()) {
        // Tell the BLE gateway (retained) that the board left MQTT, then leave cleanly.
        mqtt.publish(STATUS_TOPIC, "{\"state\":\"offline\",\"reason\":\"test_mqtt_pause\"}", true);
        mqtt.loop();
        delay(50);
        mqtt.disconnect();
      }
    }
    return;
  }
  mqttPausedUntil = 0;
  mqttPaused = false;
  lastMqttAttempt = 0;   // reconnect right away
  Serial.println("MQTT pause ended; reconnecting");
}

// Retained board status: state online/offline (offline is the MQTT last will) plus a detail:
// booting (first 60 s), running, or error with the sensors that are not responding.
void publishStatusDetail(bool force) {
  if (!mqtt.connected() || mqttPaused) {
    return;
  }
  char failed[32];
  snprintf(failed, sizeof(failed), "%s%s%s", latest.bmeOk ? "" : "bme280,", latest.luxOk ? "" : "bh1750,",
           latest.inaOk ? "" : "ina219,");
  const size_t failedLen = strlen(failed);
  if (failedLen > 0) failed[failedLen - 1] = '\0';   // drop the trailing comma
  const char* detail = millis() < 60000UL ? "booting" : (failed[0] ? "error" : "running");
  char key[48];
  snprintf(key, sizeof(key), "%s|%s", detail, failed);
  if (!force && strcmp(key, lastStatusDetail) == 0) {
    return;
  }
  snprintf(lastStatusDetail, sizeof(lastStatusDetail), "%s", key);
  StaticJsonDocument<192> doc;
  doc["state"] = "online";
  doc["detail"] = detail;
  if (failed[0]) {
    doc["failed"] = failed;
  }
  doc["fw_version"] = FW_VERSION;
  char out[192];
  size_t n = serializeJson(doc, out, sizeof(out));
  mqtt.publish(STATUS_TOPIC, reinterpret_cast<const uint8_t*>(out), n, true);
}

void connectMqtt() {
  if (WiFi.status() != WL_CONNECTED || mqtt.connected() || mqttPaused) {
    return;
  }
  if (strlen(MQTT_BROKER_IP) == 0) {
    return;
  }
  const unsigned long retryMs = bleClientConnected ? MQTT_RETRY_WITH_BLE_MS : MQTT_RETRY_MS;
  if (lastMqttAttempt != 0 && millis() - lastMqttAttempt < retryMs) {
    return;
  }
  lastMqttAttempt = millis();

  String clientId = "room101-esp32-";
  clientId += String((uint32_t)ESP.getEfuseMac(), HEX);

  bool connected;
  if (strlen(MQTT_USERNAME) > 0) {
    connected = mqtt.connect(clientId.c_str(), MQTT_USERNAME, MQTT_PASSWORD,
                             STATUS_TOPIC, 1, true, "{\"state\":\"offline\"}");
  } else {
    connected = mqtt.connect(clientId.c_str(), STATUS_TOPIC, 1, true,
                             "{\"state\":\"offline\"}");
  }

  if (connected) {
    lastStatusDetail[0] = '\0';
    publishStatusDetail(true);
    mqtt.subscribe(COMMAND_TOPIC, 1);
    mqtt.subscribe(EDGE_STATUS_TOPIC, 1);
    edgeOnline = true;
    lastCommandReceived = millis();
    lastMqttRx = millis();
    Serial.printf("MQTT connected to %s:%d\n", MQTT_BROKER_IP, MQTT_PORT);
  } else {
    Serial.printf("MQTT connection failed, state=%d\n", mqtt.state());
  }
}

void scanI2C() {
  int found = 0;
  Serial.println("Scanning I2C bus...");
  for (byte address = 1; address < 127; address++) {
    Wire.beginTransmission(address);
    if (Wire.endTransmission() == 0) {
      Serial.printf("I2C device at 0x%02X\n", address);
      found++;
    }
  }
  Serial.printf("I2C devices found: %d\n", found);
}

void initActuators() {
  setFan(false);                 // set the OFF level first, so switching the pin to output never pulses the relay
  pinMode(PIN_RELAY, OUTPUT);
  setFan(false);
  setOnboardStatus(false);

  attachRgbPwm();
  setRGB(0, 0, 0);
  const uint8_t indicatorPins[] = {PIN_AC_R, PIN_AC_G, PIN_AC_B, PIN_ST_R, PIN_ST_G, PIN_ST_B};
  for (uint8_t pinNo : indicatorPins) {
    pinMode(pinNo, OUTPUT);
  }
  setAcLed("OFF");
  writeIndicator(PIN_ST_R, PIN_ST_G, PIN_ST_B, false, false, false);

  pinMode(PIN_PIR, INPUT);
  pinMode(PIN_MQ135_DO, INPUT);
  analogReadResolution(12);
  analogSetPinAttenuation(PIN_MQ135_AO, ADC_11db);
}

bool probeBme() {
  if (bme.begin(0x76, &Wire) || bme.begin(0x77, &Wire)) {
    return true;
  }
  return false;
}

bool probeBh1750() {
  return lightMeter.begin(BH1750::CONTINUOUS_HIGH_RES_MODE, 0x23, &Wire) ||
         lightMeter.begin(BH1750::CONTINUOUS_HIGH_RES_MODE, 0x5C, &Wire);
}

void initSensors() {
  Wire.begin(PIN_SDA, PIN_SCL);
  Wire.setClock(100000);
  delay(200);
  scanI2C();

  bmeAvailable = probeBme();
  Serial.println(bmeAvailable ? "BME280: connected" : "BME280: NOT FOUND");
  bh1750Available = probeBh1750();
  Serial.println(bh1750Available ? "BH1750: connected" : "BH1750: NOT FOUND");
  ina219Available = ina219.begin(&Wire);
  Serial.println(ina219Available ? "INA219: connected" : "INA219: NOT FOUND");
  oledAvailable = probeOled();
  Serial.println(oledAvailable ? "OLED: connected (energy display)" : "OLED: NOT FOUND");
  lastSensorRetry = millis();
}

// A sensor that did not answer at power-up (slow supply, loose jumper) is probed again every
// 30 s instead of staying unavailable until the next reboot.
bool probeOled() {
  Wire.beginTransmission(OLED_ADDRESS);
  if (Wire.endTransmission() != 0) {
    return false;
  }
  if (!oled.begin(SSD1306_SWITCHCAPVCC, OLED_ADDRESS)) {
    return false;
  }
  oled.clearDisplay();
  oled.setTextColor(SSD1306_WHITE);
  oled.display();
  return true;
}

void integrateEnergy(const Readings& r) {
  const unsigned long now = millis();
  if (r.inaOk && !isnan(r.powerMW) && lastEnergySample != 0) {
    const double watts = r.powerMW > 0 ? r.powerMW / 1000.0 : 0.0;
    energyWh += watts * (now - lastEnergySample) / 3600000.0;
  }
  lastEnergySample = now;
}

// Energy meter page: power big, then volts and milliamps, energy since boot, and fan / mode / temperature.
void drawOled() {
  if (!oledAvailable || millis() - lastOledDraw < OLED_REFRESH_MS) {
    return;
  }
  lastOledDraw = millis();
  const Readings& r = latest;
  char buf[32];
  oled.clearDisplay();
  oled.setTextSize(1);
  oled.setCursor(0, 0);
  oled.print("ROOM 101 ENERGY");
  const char* link = (mqtt.connected() && !mqttPaused) ? "WiFi" : (bleClientConnected ? " BLE" : "  --");
  oled.setCursor(104, 0);
  oled.print(link);
  oled.drawFastHLine(0, 10, 128, SSD1306_WHITE);
  if (r.inaOk) {
    const float watts = r.powerMW > 0 ? r.powerMW / 1000.0f : 0.0f;
    snprintf(buf, sizeof(buf), watts < 10 ? "%.2f" : "%.1f", watts);
  } else {
    snprintf(buf, sizeof(buf), "--");
  }
  oled.setTextSize(3);
  oled.setCursor(0, 15);
  oled.print(buf);
  oled.setTextSize(2);
  oled.print(" W");
  oled.setTextSize(1);
  oled.setCursor(0, 41);
  if (r.inaOk) {
    snprintf(buf, sizeof(buf), "%.1f V   %d mA", r.busVoltage, (int)lroundf(r.currentMA > 0 ? r.currentMA : 0));
  } else {
    snprintf(buf, sizeof(buf), "INA219 not found");
  }
  oled.print(buf);
  oled.setCursor(0, 49);
  snprintf(buf, sizeof(buf), energyWh < 100 ? "Energy %.2f Wh" : "Energy %.0f Wh", energyWh);
  oled.print(buf);
  oled.setCursor(0, 57);
  const char* mode = statusShown;
  if (strcmp(mode, "RULE") == 0) mode = "SCHED";
  if (strcmp(mode, "WARNING") == 0) mode = "WARN";
  if (r.bmeOk) {
    snprintf(buf, sizeof(buf), "FAN %s %s %.1fC", fanState ? "ON " : "OFF", mode, r.temperature);
  } else {
    snprintf(buf, sizeof(buf), "FAN %s %s", fanState ? "ON " : "OFF", mode);
  }
  oled.print(buf);
  oled.display();
}

void retryMissingSensors() {
  if (bmeAvailable && bh1750Available && ina219Available && oledAvailable) {
    return;
  }
  if (millis() - lastSensorRetry < SENSOR_RETRY_MS) {
    return;
  }
  lastSensorRetry = millis();
  if (!bmeAvailable && probeBme()) {
    bmeAvailable = true;
    Serial.println("BME280: connected (retry)");
  }
  if (!bh1750Available && probeBh1750()) {
    bh1750Available = true;
    Serial.println("BH1750: connected (retry)");
  }
  if (!ina219Available && ina219.begin(&Wire)) {
    ina219Available = true;
    Serial.println("INA219: connected (retry)");
  }
  if (!oledAvailable && probeOled()) {
    oledAvailable = true;
    Serial.println("OLED: connected (retry)");
  }
}

float median3(float a, float b, float c) {
  if (isnan(a) || isnan(b) || isnan(c)) {
    return NAN;
  }
  return max(min(a, b), min(max(a, b), c));
}

// Three BME280 reads 40 ms apart, median per channel, then a physical range check. A corrupted
// I2C transfer shows up as one outlier and is discarded instead of being published.
bool readBme(float& temperature, float& humidity, float& pressure) {
  float t[3], h[3], p[3];
  for (int i = 0; i < 3; i++) {
    t[i] = bme.readTemperature();
    h[i] = bme.readHumidity();
    p[i] = bme.readPressure() / 100.0F;
    if (i < 2) {
      delay(40);
    }
  }
  temperature = median3(t[0], t[1], t[2]);
  humidity = median3(h[0], h[1], h[2]);
  pressure = median3(p[0], p[1], p[2]);
  const bool valid = !isnan(temperature) && !isnan(humidity) && !isnan(pressure) &&
                     temperature > -40.0F && temperature < 85.0F &&
                     humidity >= 0.0F && humidity <= 100.0F &&
                     pressure > 800.0F && pressure < 1100.0F;
  if (!valid) {
    bmeRejected++;
    Serial.printf("BME280 reading rejected (T=%.2f H=%.2f P=%.2f); total rejected %lu\n",
                  temperature, humidity, pressure, (unsigned long)bmeRejected);
    if (bmeRejected % 3 == 0) {
      bmeAvailable = probeBme();   // re-initialise after repeated bad reads
    }
  }
  return valid;
}

void readSensors(Readings& r) {
  r = Readings();
  if (bmeAvailable) {
    r.bmeOk = readBme(r.temperature, r.humidity, r.pressure);
  }
  if (bh1750Available) {
    const float lux = lightMeter.readLightLevel();
    r.luxOk = lux >= 0;
    r.lux = r.luxOk ? lux : NAN;
  }
  // MQ-135: mean of 8 ADC samples (the ESP32-S3 ADC has a few mV of noise per sample)
  long mqRawSum = 0, mqMvSum = 0;
  for (int i = 0; i < 8; i++) {
    mqRawSum += analogRead(PIN_MQ135_AO);
    mqMvSum += analogReadMilliVolts(PIN_MQ135_AO);
  }
  r.mqRaw = (int)(mqRawSum / 8);
  r.mqMilliVolts = (int)(mqMvSum / 8);
  r.mqDigitalHigh = digitalRead(PIN_MQ135_DO) == HIGH;
  r.motion = digitalRead(PIN_PIR) == HIGH;
  if (ina219Available) {
    // The fan's motor draws a pulsing current, and the chip's own current and power registers come from
    // different conversions, so they disagree (e.g. 79.7 mA x 11.69 V reported as 1174 mW). Average 16 pairs of
    // bus and shunt voltage over ~20 ms, take the current from the shunt voltage (R100 = 0.1 ohm) and the power
    // as volts x amps, so V, I and P always agree.
    float busSum = 0, shuntSum = 0;
    for (int i = 0; i < INA219_SAMPLES; i++) {
      busSum += ina219.getBusVoltage_V();
      shuntSum += ina219.getShuntVoltage_mV();
      delayMicroseconds(1200);
    }
    r.busVoltage = busSum / INA219_SAMPLES;
    r.shuntMilliVolts = shuntSum / INA219_SAMPLES;
    r.currentMA = r.shuntMilliVolts / INA219_SHUNT_OHMS;          // mV / ohm = mA
    r.powerMW = r.busVoltage * r.currentMA;                       // V x mA = mW
    r.inaOk = !isnan(r.busVoltage) && !isnan(r.currentMA);
  }
}

void printSensorReadings(const Readings& r) {
  Serial.printf("T=%.2f C  H=%.2f %%  P=%.2f hPa  Lux=%.2f  MQ=%d (%dmV)  PIR=%s\n",
                r.bmeOk ? r.temperature : 0.0, r.bmeOk ? r.humidity : 0.0,
                r.bmeOk ? r.pressure : 0.0, r.luxOk ? r.lux : 0.0,
                r.mqRaw, r.mqMilliVolts, r.motion ? "DETECTED" : "CLEAR");
  if (r.inaOk) {
    Serial.printf("INA219: bus %.3f V, shunt %.3f mV, %.2f mA, %.2f mW\n",
                  r.busVoltage, r.shuntMilliVolts, r.currentMA, r.powerMW);
  }
}

// `stamp` (millis() when the reading is published) makes msg_id identical on both links, so the
// edge keeps exactly one copy of each reading.
size_t buildTelemetry(const Readings& r, const char* transport, unsigned long stamp, char* payload,
                      size_t capacity) {
  StaticJsonDocument<1280> doc;
  doc["schema"] = "sb.telemetry/1";
  doc["room_id"] = ROOM_ID;
  char msgId[24];
  snprintf(msgId, sizeof(msgId), "%08lX%04lX", stamp, (unsigned long)telemetrySequence);
  doc["msg_id"] = msgId;
  doc["source"] = "esp32_room101";
  doc["device_id"] = "room101-esp32";
  doc["firmware"] = "esp32_smart_building";
  doc["fw_version"] = FW_VERSION;
  doc["transport"] = transport;
  doc["ts"] = stamp;
  doc["uptime_s"] = stamp / 1000UL;

  if (r.bmeOk) {
    doc["temperature"] = r.temperature;
    doc["humidity"] = r.humidity;
    doc["pressure_hpa"] = r.pressure;
  }
  if (r.luxOk) {
    doc["lux"] = r.lux;
  }
  doc["motion_detected"] = r.motion;
  doc["presence"] = r.motion;
  doc["presence_source"] = "pir";
  doc["mq135_raw"] = r.mqRaw;
  doc["mq135_adc_mv"] = r.mqMilliVolts;
  doc["mq135_do_high"] = r.mqDigitalHigh;
  doc["fan_on"] = fanState;
  doc["relay_on"] = fanState;
  doc["actuator_rgb"] = rgbState;
  doc["actuator_ac_led"] = acLedState;
  doc["actuator_status_led"] = statusShown;
  if (WiFi.status() == WL_CONNECTED) {
    doc["wifi_rssi_dbm"] = WiFi.RSSI();
  }
  if (r.inaOk) {
    doc["measured_voltage_v"] = r.busVoltage;
    doc["ina219_shunt_voltage_mV"] = r.shuntMilliVolts;
    doc["measured_current_mA"] = r.currentMA;
    doc["measured_power_mW"] = r.powerMW;
  }
  doc["actuator_fan_speed"] = fanState ? 255 : 0;
  doc["actuator_light_level"] = lightLevel;
  doc["actuator_servo_angle"] = 0;
  doc["rgb_hold_s"] = holdSecondsLeft(rgbHoldUntil);
  doc["fan_hold_s"] = holdSecondsLeft(fanHoldUntil);
  doc["bench_mode"] = benchActive();
  doc["ble_mtu"] = blePeerMtu;

  JsonObject health = doc.createNestedObject("sensor_health");
  health["bme280"] = r.bmeOk;
  health["bh1750"] = r.luxOk;
  health["mq135"] = true;
  health["pir"] = true;
  health["ina219"] = r.inaOk;
  health["relay"] = true;
  health["rgb"] = true;

  return serializeJson(doc, payload, capacity);
}

void publishTelemetry(const Readings& r) {
  telemetrySequence++;
  char payload[1024];
  const bool mqttUp = mqtt.connected() && !mqttPaused;
  const unsigned long stamp = millis();
  size_t length = buildTelemetry(r, mqttUp ? "mqtt" : "ble", stamp, payload, sizeof(payload));
  if (length == 0 || length >= sizeof(payload)) {
    Serial.println("Telemetry too large for the buffer; not sent");
    return;
  }
  // Redundant delivery (same msg_id on both links; the edge keeps the first copy). On the factory
  // guest Wi-Fi the TCP link can stall for tens of seconds while still counting as connected.
  bool sentMqtt = false;
  bool sentBle = false;
  if (mqttUp) {
    sentMqtt = mqtt.publish(TELEMETRY_TOPIC, reinterpret_cast<const uint8_t*>(payload), length);
  }
  if (bleClientConnected) {
    if (mqttUp) {
      length = buildTelemetry(r, "ble", stamp, payload, sizeof(payload));
    }
    sentBle = sendBleMessage('T', reinterpret_cast<const uint8_t*>(payload), length);
  }
  const bool sent = sentMqtt || sentBle;
  const char* transport = sentMqtt && sentBle ? "MQTT+BLE" : (sentMqtt ? "MQTT" : "BLE");
  if (sent) {
    Serial.printf("Telemetry sent via %s: %u bytes\n", transport, (unsigned)length);
  } else {
    Serial.printf("Telemetry unavailable: %u bytes, MQTT state=%d, BLE peer=%d, BLE drops=%lu\n",
                  (unsigned)length, mqtt.state(), bleClientConnected, (unsigned long)bleNotifyDrops);
  }
}

void printHelp() {
  Serial.println("Bench commands (hold 2 min, fail-safe paused while the operator is at the board):");
  Serial.println("  1 / 0      relay+fan ON / OFF");
  Serial.println("  R G B W K  RGB red / green / blue / white / off (PWM)");
  Serial.println("  D          RGB channel diagnostic: each colour pin plain HIGH for 4 s");
  Serial.println("  S          read sensors      I  scan I2C      X  end bench session now");
  Serial.println("  H          this help");
}

void startBench(const char* what) {
  benchUntil = millis() + BENCH_HOLD_MS;
  Serial.printf("%s (bench session until +120 s; X ends it)\n", what);
}

void handleSerialCommands() {
  while (Serial.available()) {
    const char command = Serial.read();
    switch (command) {
      case '1': setFan(true); startBench("Fan relay ON"); break;
      case '0': setFan(false); startBench("Fan relay OFF"); break;
      case 'R': case 'r': setRGB(255, 0, 0); startBench("RGB RED"); break;
      case 'G': case 'g': setRGB(0, 255, 0); startBench("RGB GREEN"); break;
      case 'B': case 'b': setRGB(0, 0, 255); startBench("RGB BLUE"); break;
      case 'W': case 'w': setRGB(255, 255, 255); startBench("RGB WHITE"); break;
      case 'K': case 'k': setRGB(0, 0, 0); startBench("RGB OFF"); break;
      case 'D': case 'd': startBench("RGB channel diagnostic"); rgbChannelDiagnostic(); break;
      case 'S': case 's': { Readings r; readSensors(r); printSensorReadings(r); break; }
      case 'I': case 'i': scanI2C(); break;
      case 'X': case 'x':
        benchUntil = 0;
        setFan(false);
        setRGB(0, 0, 0);
        Serial.println("Bench session ended; relay and LED OFF");
        break;
      case 'H': case 'h': case '?': printHelp(); break;
      default: break;
    }
  }
}

void setup(void);
void loop(void);

void setup(void) {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\n==========================================");
  Serial.println("  SMART BUILDING ROOM 101 ESP32-S3");
  Serial.println("  firmware " FW_VERSION);
  Serial.println("==========================================");

  initActuators();
  initSensors();
  initBleTransport();

  wifiClient.setConnectionTimeout(MQTT_CONNECT_TIMEOUT_MS);
  mqtt.setServer(MQTT_BROKER_IP, MQTT_PORT);
  mqtt.setSocketTimeout(3);
  if (!mqtt.setBufferSize(1280)) {
    Serial.println("Failed to allocate MQTT packet buffer");
  }
  mqtt.setCallback(mqttCallback);
  mqtt.setKeepAlive(MQTT_KEEPALIVE_S);

  // Register Wi-Fi diagnostic event callbacks
  WiFi.onEvent([](WiFiEvent_t event, WiFiEventInfo_t info) {
    switch (event) {
      case ARDUINO_EVENT_WIFI_READY:
        Serial.println("[WiFi] Interface ready");
        break;
      case ARDUINO_EVENT_WIFI_STA_START:
        Serial.println("[WiFi] Station mode started");
        break;
      case ARDUINO_EVENT_WIFI_STA_CONNECTED:
        Serial.println("[WiFi] Connected to AP! Negotiating IP address...");
        break;
      case ARDUINO_EVENT_WIFI_STA_GOT_IP:
        wifiBeginStarted = false;
        Serial.printf("[WiFi] SUCCESS! Got IP: %s (RSSI: %d dBm)\n",
                      WiFi.localIP().toString().c_str(), WiFi.RSSI());
        setOnboardStatus(true);
        break;
      case ARDUINO_EVENT_WIFI_STA_DISCONNECTED:
        Serial.printf("[WiFi] Disconnected! Reason code: %d\n", info.wifi_sta_disconnected.reason);
        setOnboardStatus(false);
        break;
      default:
        break;
    }
  });

  connectWiFi();

  Serial.println("MQTT telemetry: " TELEMETRY_TOPIC);
  Serial.println("MQTT command:   " COMMAND_TOPIC);
  Serial.println("BLE fallback: paired GATT service, forwards telemetry and commands");
  printHelp();
}

void loop(void) {
  static bool previousBleConnected = false;
  if (bleClientConnected != previousBleConnected) {
    previousBleConnected = bleClientConnected;
    if (bleClientConnected) {
      edgeOnline = true;
      lastCommandReceived = millis();
      Serial.println("BLE gateway connected");
    } else if (!mqtt.connected()) {
      edgeOnline = false;
      Serial.println("BLE gateway disconnected");
    }
  }

  serviceMqttPause();
  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
  } else {
    static bool firstConnect = true;
    if (firstConnect) {
      firstConnect = false;
      Serial.printf("Wi-Fi CONNECTED! IP: %s, RSSI: %d dBm\n",
                    WiFi.localIP().toString().c_str(), WiFi.RSSI());
    }
    if (!mqtt.connected()) {
      if (!bleClientConnected) {
        edgeOnline = false;
      }
      connectMqtt();
    } else {
      mqtt.loop();
      if (mqtt.connected() && !mqttPaused && millis() - lastMqttRx > MQTT_STALL_MS) {
        Serial.printf("MQTT link stalled (nothing received for %lu s): dropping it, BLE carries the data\n",
                      (unsigned long)(MQTT_STALL_MS / 1000));
        wifiClient.stop();
        lastMqttAttempt = millis();
      }
    }
  }

  processBleCommand();
  handleSerialCommands();
  retryMissingSensors();

  if (millis() - lastSensorRead >= SENSOR_INTERVAL_MS) {
    lastSensorRead = millis();
    readSensors(latest);
    integrateEnergy(latest);
    printSensorReadings(latest);
    if ((mqtt.connected() && !mqttPaused) || bleClientConnected) {
      publishTelemetry(latest);
    }
  }

  const bool linkUp = (mqtt.connected() && !mqttPaused) || bleClientConnected;
  if (linkUp && lastCommandReceived > 0 &&
      millis() - lastCommandReceived > MQTT_COMMAND_TIMEOUT_MS) {
    edgeOnline = false;
  }

  // Fail-safe: no edge controller reachable -> relay and LED OFF, holds cleared. A serial bench
  // session is the exception: the operator is physically at the board and ends it with X or
  // after two minutes.
  const bool edgeLost = !linkUp || !edgeOnline;
  if (edgeLost && !benchActive()) {
    if (!failSafeActive || fanState || lightLevel != 0) {
      setFan(false);
      setRGB(0, 0, 0);
      setAcLed("OFF");
      rgbHoldUntil = 0;
      fanHoldUntil = 0;
    }
    if (!failSafeActive) {
      failSafeActive = true;
      Serial.println("Edge unavailable (no MQTT/BLE link or no command for 30 s): fail-safe actuators OFF");
    }
  } else if (!edgeLost && failSafeActive) {
    failSafeActive = false;
    Serial.println("Edge reachable again: actuators follow commands");
  }
  if (benchUntil != 0 && !benchActive()) {
    benchUntil = 0;
    Serial.println("Bench session expired");
  }
  serviceStatusLed(edgeLost, benchActive());
  drawOled();
  publishStatusDetail(false);

  delay(10);
}
