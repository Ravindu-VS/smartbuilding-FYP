/**
 * =============================================================================
 * FINAL YEAR PROJECT: SMART BUILDING — ESP32-S3 SENSOR ACQUISITION NODE v2.0
 * Author: Vinusha Rathnayaka
 * Node Target: Room 101 (Floor 1 Main Office / Physical Prototype Anchor)
 * Microcontroller: ESP32-S3 Dual-Core (240 MHz, Wi-Fi 4)
 * =============================================================================
 * 
 * ARCHITECTURE (v2.0 — Research-Grade Hardware):
 *   ESP32-S3 is a PURE SENSOR + ACTUATOR node.
 *   It does NOT run any ML inference locally.
 *   All intelligence resides on the Raspberry Pi 4B Edge Brain.
 *
 *   Flow:
 *     1. ESP32 reads physical sensors (BME280, BH1750, SCD41, LD2410C, INA226, PIR, MQ-2)
 *     2. ESP32 POSTs raw sensor data to Raspberry Pi via HTTP
 *     3. Raspberry Pi runs Random Forest ML + PPO RL inference
 *     4. Pi responds with control decisions (fan_speed, light_level, servo_angle, hvac_action)
 *     5. ESP32 actuates Room 101 hardware based on Pi's decision
 *
 * COMPLETE MASTER WIRING DIAGRAM (v2.0):
 * -----------------------------------------------------------------------------
 * 1. SHARED I2C SENSOR BUS (SDA: GPIO 17, SCL: GPIO 18):
 *    - GY-BME280     (0x76/0x77): Temperature / Humidity / Pressure
 *    - GY-30 BH1750  (0x23/0x5C): Ambient Illuminance (lux)
 *    - SCD41         (0x62):      CO2 (ppm) / Temperature / Humidity (NDIR)
 *    - INA226        (0x40):      Voltage / Current / Power (mW)
 * 
 * 2. UART SENSOR (Serial1):
 *    - LD2410C mmWave (TX->GPIO 16, RX->GPIO 15): 24GHz presence / distance
 *      NOTE: GPIO 15 is re-assigned from RGB Blue. RGB Blue moves to GPIO 5.
 *
 * 3. ANALOG & DIGITAL SENSORS:
 *    - MQ-2 Gas Sensor:          VCC->5V, GND->GND, AO->GPIO 1  (Analog ADC)
 *    - HW-416-B PIR Motion:      VCC->3.3V, GND->GND, S->GPIO 4 (Digital)
 * 
 * 4. PHYSICAL ACTUATORS (PWM-Controlled):
 *    - MOSFET->DC Fan:            SIG->GPIO 14  (PWM variable speed)
 *    - White LED (lighting):     Anode->GPIO 12 (PWM dimmable via MOSFET/transistor)
 *    - SG90 Servo (ventilation): SIG->GPIO 13  (50Hz PWM)
 *    - HW-478 RGB LED (status):  R->GPIO 6, G->GPIO 7, B->GPIO 5
 *    - ESP32-S3 Onboard LED:     GPIO 38 (connection status)
 * 
 * 5. NETWORK & SYSTEM:
 *    - Wi-Fi 2.4GHz STA Mode -> SSID: "YOUR_WIFI_NAME", Pass: "YOUR_WIFI_PASSWORD"
 *    - REST API Server -> http://<RASPBERRY_PI_IP>:8001/api/hardware/sensor-data
 *
 * SENSOR PRIORITY (graceful degradation — all optional):
 *    BME280    -> Core temperature/humidity
 *    BH1750    -> Core illuminance
 *    SCD41     -> CO2 for occupancy estimation & IAQ
 *    LD2410C   -> mmWave presence detection
 *    INA226    -> Electrical power measurement
 *    MQ-2      -> Secondary air quality
 *    PIR       -> Motion event trigger
 * =============================================================================
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <ArduinoJson.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BME280.h>
#include <BH1750.h>

// -------------------------------------------------------------------
// Optional sensor libraries — comment out if library not installed
// -------------------------------------------------------------------
// SCD41 CO2 Sensor (Sensirion I2C)
#if __has_include(<SensirionI2CScd4x.h>)
  #include <SensirionI2CScd4x.h>
  #define HAS_SCD41_LIB true
#else
  #define HAS_SCD41_LIB false
#endif

// INA226 Power Monitor
#if __has_include(<INA226.h>)
  #include <INA226.h>
  #define HAS_INA226_LIB true
#else
  #define HAS_INA226_LIB false
#endif

// LD2410 mmWave Presence Sensor
#if __has_include(<ld2410.h>)
  #include <ld2410.h>
  #define HAS_LD2410_LIB true
#else
  #define HAS_LD2410_LIB false
#endif

// ESP32 Servo Library
#if __has_include(<ESP32Servo.h>)
  #include <ESP32Servo.h>
  #define HAS_SERVO_LIB true
#else
  #define HAS_SERVO_LIB false
#endif

// Include ESP32 Version header for LEDC API compatibility
#if __has_include(<esp_arduino_version.h>)
  #include <esp_arduino_version.h>
#endif

// =============================================================================
// FEATURE FLAGS — set false to disable a sensor even if library exists
// =============================================================================
#define ENABLE_BME280     true
#define ENABLE_BH1750     true
#define ENABLE_SCD41      true
#define ENABLE_LD2410C    true
#define ENABLE_INA226     true
#define ENABLE_MQ2        true
#define ENABLE_PIR        true
#define ENABLE_SERVO      true
#define ENABLE_WHITE_LED  true

// =============================================================================
// MASTER CONFIGURATION
// =============================================================================
// Network & Server Config
const char* ssid = "YOUR_WIFI_NAME";                   // Your Wi-Fi Hotspot Name
const char* password = "YOUR_WIFI_PASSWORD";           // Your Wi-Fi Hotspot Password

// >>> CHANGE THIS to your Raspberry Pi's IP address <<<
const char* server_url = "http://172.20.10.2:8001/api/hardware/sensor-data";

// =============================================================================
// GPIO PIN ASSIGNMENTS (ESP32-S3)
// =============================================================================
// I2C Bus (shared by BME280, BH1750, SCD41, INA226)
#define I2C_SDA_PIN        17
#define I2C_SCL_PIN        18

// LD2410C UART (Serial1)
#define LD2410_TX_PIN      16    // ESP32 RX <- LD2410 TX
#define LD2410_RX_PIN      15    // ESP32 TX -> LD2410 RX  (reassigned from old RGB Blue)

// Analog & Digital Sensors
#define MQ2_PIN            1     // MQ-2 Analog Input
#define PIR_PIN            4     // HW-416-B Digital Motion Input

// Actuator Outputs (PWM)
#define FAN_PWM_PIN        14    // MOSFET -> DC Fan (PWM variable speed)
#define WHITE_LED_PIN      12    // White LED module (PWM dimmable)
#define SERVO_PIN          13    // SG90 Servo (ventilation damper)

// RGB Status LED (HW-478)
#define RGB_RED_PIN        6
#define RGB_GREEN_PIN      7
#define RGB_BLUE_PIN       5     // Moved from GPIO 15 (now used by LD2410C UART)

// System Status
#define ONBOARD_LED_PIN    38    // Built-in status indicator

// =============================================================================
// PWM CONFIGURATION
// =============================================================================
#define FAN_PWM_FREQ       25000   // 25 kHz for quiet fan operation
#define FAN_PWM_RES        8       // 8-bit resolution (0-255)
#define LED_PWM_FREQ       5000    // 5 kHz for LED dimming
#define LED_PWM_RES        8       // 8-bit resolution (0-255)

// LEDC channel assignments (ESP32-S3)
#define FAN_LEDC_CH        0
#define LED_LEDC_CH        1

// =============================================================================
// TIMING
// =============================================================================
unsigned long last_send_time = 0;
const unsigned long send_interval_ms = 3000;  // Telemetry loop: 3 seconds

unsigned long last_scd41_time = 0;
const unsigned long scd41_interval_ms = 5000; // SCD41 measurement interval: 5s

// =============================================================================
// GLOBAL SENSOR OBJECTS & STATE FLAGS
// =============================================================================
HTTPClient http;
Adafruit_BME280 bme;
BH1750 lightMeter;

bool bme_found = false;
bool bh1750_found = false;
bool scd41_found = false;
bool ina226_found = false;
bool ld2410_found = false;
bool servo_attached = false;

// SCD41 cached readings (it measures every ~5s)
float scd41_co2 = 0.0;
float scd41_temp = 0.0;
float scd41_hum = 0.0;
bool  scd41_data_ready = false;

// INA226 cached readings
float ina226_voltage = 0.0;
float ina226_current_mA = 0.0;
float ina226_power_mW = 0.0;

// LD2410C cached readings
bool  ld2410_presence = false;
bool  ld2410_moving = false;
bool  ld2410_stationary = false;
int   ld2410_distance_cm = 0;

// Conditional global objects
#if HAS_SCD41_LIB
  SensirionI2CScd4x scd41;
#endif

#if HAS_INA226_LIB
  INA226 ina226(0x40);
#endif

#if HAS_LD2410_LIB
  ld2410 radar;
#endif

#if HAS_SERVO_LIB
  Servo ventServo;
#endif

// Current actuator state (for telemetry feedback)
int current_fan_speed = 0;      // 0-255
int current_light_level = 0;    // 0-255
int current_servo_angle = 0;    // 0-180

// Forward Declarations
void apply_actuation(const char* hvac_action, const char* light_action,
                     int fan_speed, int light_level, int servo_angle);
void setup_wifi();
void send_telemetry();
void set_status_led(int r, int g, int b);
void init_scd41();
void init_ina226();
void init_ld2410();
void read_scd41();
void read_ina226();
void read_ld2410();

// =============================================================================
// SETUP
// =============================================================================
void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println("\n=======================================================");
  Serial.println("  ESP32-S3 SENSOR NODE v2.0 — ROOM 101");
  Serial.println("  Research-Grade Hardware-in-the-Loop Prototype");
  Serial.println("  Intelligence: Raspberry Pi 4B Edge Brain");
  Serial.println("=======================================================");

  // ---------------------------------------------------------------
  // 1. Initialize basic digital/analog sensor inputs
  // ---------------------------------------------------------------
  pinMode(MQ2_PIN, INPUT);
  pinMode(PIR_PIN, INPUT);

  // ---------------------------------------------------------------
  // 2. Initialize PWM actuator outputs
  // ---------------------------------------------------------------
  #if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
    // ESP32 Arduino Core v3.x — new ledcAttach() API
    ledcAttach(FAN_PWM_PIN, FAN_PWM_FREQ, FAN_PWM_RES);
    ledcAttach(WHITE_LED_PIN, LED_PWM_FREQ, LED_PWM_RES);
  #else
    // ESP32 Arduino Core v2.x — classic ledcSetup() API
    ledcSetup(FAN_LEDC_CH, FAN_PWM_FREQ, FAN_PWM_RES);
    ledcAttachPin(FAN_PWM_PIN, FAN_LEDC_CH);
    ledcSetup(LED_LEDC_CH, LED_PWM_FREQ, LED_PWM_RES);
    ledcAttachPin(WHITE_LED_PIN, LED_LEDC_CH);
  #endif

  // Set initial actuator states: OFF
  #if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
    ledcWrite(FAN_PWM_PIN, 0);
    ledcWrite(WHITE_LED_PIN, 0);
  #else
    ledcWrite(FAN_LEDC_CH, 0);
    ledcWrite(LED_LEDC_CH, 0);
  #endif

  // ---------------------------------------------------------------
  // 3. Initialize RGB Status LED (digital output)
  // ---------------------------------------------------------------
  pinMode(RGB_RED_PIN, OUTPUT);
  pinMode(RGB_GREEN_PIN, OUTPUT);
  pinMode(RGB_BLUE_PIN, OUTPUT);
  set_status_led(0, 0, 0);  // OFF initially

  // Onboard connection status LED
  pinMode(ONBOARD_LED_PIN, OUTPUT);
  digitalWrite(ONBOARD_LED_PIN, LOW);

  // ---------------------------------------------------------------
  // 4. Initialize Servo (SG90 ventilation actuator)
  // ---------------------------------------------------------------
  #if HAS_SERVO_LIB && ENABLE_SERVO
    ventServo.attach(SERVO_PIN, 500, 2400);  // SG90 typical pulse range
    ventServo.write(0);  // Closed position
    servo_attached = true;
    Serial.println("  + SG90 Servo attached on GPIO 13 (ventilation damper)");
  #else
    Serial.println("  i Servo library not available — ventilation actuator disabled");
  #endif

  // ---------------------------------------------------------------
  // 5. Shared I2C Bus Initialization
  // ---------------------------------------------------------------
  Serial.printf("\nInitializing I2C Bus (SDA: GPIO %d, SCL: GPIO %d)...\n", I2C_SDA_PIN, I2C_SCL_PIN);
  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
  Wire.setClock(100000);  // 100 kHz for sensor compatibility

  // --- BME280 ---
  #if ENABLE_BME280
    if (bme.begin(0x76, &Wire) || bme.begin(0x77, &Wire)) {
      bme_found = true;
      Serial.println("  + BME280 (Temp/Humidity/Pressure) ACTIVE");
    } else {
      Serial.println("  i BME280 not found — using thermal estimate fallback");
    }
  #endif

  // --- BH1750 ---
  #if ENABLE_BH1750
    if (lightMeter.begin(BH1750::CONTINUOUS_HIGH_RES_MODE, 0x23, &Wire) ||
        lightMeter.begin(BH1750::CONTINUOUS_HIGH_RES_MODE, 0x5C, &Wire)) {
      bh1750_found = true;
      Serial.println("  + BH1750 (Illuminance) ACTIVE");
    } else {
      Serial.println("  i BH1750 not found — using ambient light estimate");
    }
  #endif

  // --- SCD41 CO2 Sensor ---
  #if HAS_SCD41_LIB && ENABLE_SCD41
    init_scd41();
  #else
    Serial.println("  i SCD41 library not available — CO2 from MQ-2 estimate only");
  #endif

  // --- INA226 Power Monitor ---
  #if HAS_INA226_LIB && ENABLE_INA226
    init_ina226();
  #else
    Serial.println("  i INA226 library not available — power measurement disabled");
  #endif

  // ---------------------------------------------------------------
  // 6. LD2410C mmWave (UART — Serial1)
  // ---------------------------------------------------------------
  #if HAS_LD2410_LIB && ENABLE_LD2410C
    init_ld2410();
  #else
    Serial.println("  i LD2410 library not available — presence via PIR only");
  #endif

  // ---------------------------------------------------------------
  // 7. Wi-Fi Connection
  // ---------------------------------------------------------------
  WiFi.setAutoReconnect(true);
  setup_wifi();

  // ---------------------------------------------------------------
  // 8. HTTP Client Configuration
  // ---------------------------------------------------------------
  http.setReuse(true);
  http.setTimeout(8000);

  // Print sensor summary
  Serial.println("\n--- SENSOR STATUS SUMMARY ---");
  Serial.printf("  BME280:  %s\n", bme_found ? "ACTIVE" : "NOT FOUND");
  Serial.printf("  BH1750:  %s\n", bh1750_found ? "ACTIVE" : "NOT FOUND");
  Serial.printf("  SCD41:   %s\n", scd41_found ? "ACTIVE" : "NOT FOUND");
  Serial.printf("  INA226:  %s\n", ina226_found ? "ACTIVE" : "NOT FOUND");
  Serial.printf("  LD2410C: %s\n", ld2410_found ? "ACTIVE" : "NOT FOUND");
  Serial.printf("  PIR:     ENABLED\n");
  Serial.printf("  MQ-2:    ENABLED\n");
  Serial.printf("  Servo:   %s\n", servo_attached ? "ATTACHED" : "NOT AVAILABLE");
  Serial.println("-----------------------------\n");
}

// =============================================================================
// MAIN LOOP
// =============================================================================
void loop() {
  // Wi-Fi reconnection
  if (WiFi.status() != WL_CONNECTED) {
    digitalWrite(ONBOARD_LED_PIN, LOW);
    set_status_led(255, 0, 0);  // RED = disconnected
    setup_wifi();
  } else {
    digitalWrite(ONBOARD_LED_PIN, HIGH);
  }

  // Read LD2410C radar continuously (it needs frequent polling)
  #if HAS_LD2410_LIB && ENABLE_LD2410C
    if (ld2410_found) {
      read_ld2410();
    }
  #endif

  // Periodic telemetry cycle
  unsigned long now = millis();
  if (now - last_send_time >= send_interval_ms) {
    last_send_time = now;

    // Read SCD41 if measurement ready (it self-times at ~5s intervals)
    #if HAS_SCD41_LIB && ENABLE_SCD41
      if (scd41_found) {
        read_scd41();
      }
    #endif

    // Read INA226 power
    #if HAS_INA226_LIB && ENABLE_INA226
      if (ina226_found) {
        read_ina226();
      }
    #endif

    send_telemetry();
  }
}

// =============================================================================
// WIFI CONNECTION ROUTINE
// =============================================================================
void setup_wifi() {
  if (WiFi.status() == WL_CONNECTED) return;

  Serial.printf("Connecting to Wi-Fi SSID: %s ", ssid);
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);

  int retries = 0;
  while (WiFi.status() != WL_CONNECTED && retries < 20) {
    delay(500);
    Serial.print(".");
    retries++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n+ Wi-Fi Connected Successfully!");
    Serial.print("ESP32-S3 IP Address: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("\nx Wi-Fi Connection Timeout! Retrying in loop...");
  }
}

// =============================================================================
// SENSOR INITIALIZATION FUNCTIONS
// =============================================================================

void init_scd41() {
  #if HAS_SCD41_LIB
    scd41.begin(Wire);
    
    // Stop any previous measurement before reconfiguring
    uint16_t error = scd41.stopPeriodicMeasurement();
    delay(500);
    
    // Start periodic measurement (one measurement every ~5 seconds)
    error = scd41.startPeriodicMeasurement();
    if (error == 0) {
      scd41_found = true;
      Serial.println("  + SCD41 CO2/Temp/Humidity sensor ACTIVE (NDIR, I2C 0x62)");
    } else {
      Serial.printf("  x SCD41 start error: %d\n", error);
    }
  #endif
}

void init_ina226() {
  #if HAS_INA226_LIB
    if (ina226.begin()) {
      ina226.configure(INA226_AVERAGES_16,
                       INA226_BUS_CONV_TIME_1100US,
                       INA226_SHUNT_CONV_TIME_1100US,
                       INA226_MODE_SHUNT_BUS_CONT);
      ina226.calibrate(0.1, 1.0);  // 0.1 ohm shunt, max 1A — adjust for your hardware
      ina226_found = true;
      Serial.println("  + INA226 Power Monitor ACTIVE (I2C 0x40)");
    } else {
      Serial.println("  i INA226 not found at I2C 0x40");
    }
  #endif
}

void init_ld2410() {
  #if HAS_LD2410_LIB
    Serial1.begin(256000, SERIAL_8N1, LD2410_TX_PIN, LD2410_RX_PIN);
    delay(500);
    if (radar.begin(Serial1)) {
      ld2410_found = true;
      Serial.println("  + LD2410C mmWave Presence Sensor ACTIVE (UART Serial1)");
    } else {
      Serial.println("  i LD2410C not responding on Serial1");
    }
  #endif
}

// =============================================================================
// SENSOR READING FUNCTIONS
// =============================================================================

void read_scd41() {
  #if HAS_SCD41_LIB
    uint16_t co2_raw;
    float temp_raw, hum_raw;
    bool isDataReady = false;
    
    scd41.getDataReadyFlag(isDataReady);
    if (isDataReady) {
      uint16_t error = scd41.readMeasurement(co2_raw, temp_raw, hum_raw);
      if (error == 0 && co2_raw > 0) {
        scd41_co2 = (float)co2_raw;
        scd41_temp = temp_raw;
        scd41_hum = hum_raw;
        scd41_data_ready = true;
      }
    }
  #endif
}

void read_ina226() {
  #if HAS_INA226_LIB
    ina226_voltage = ina226.readBusVoltage();
    ina226_current_mA = ina226.readShuntCurrent() * 1000.0;  // A -> mA
    ina226_power_mW = ina226.readBusPower() * 1000.0;        // W -> mW
  #endif
}

void read_ld2410() {
  #if HAS_LD2410_LIB
    radar.read();
    if (radar.isConnected()) {
      ld2410_presence = radar.presenceDetected();
      ld2410_moving = radar.movingTargetDetected();
      ld2410_stationary = radar.stationaryTargetDetected();
      
      // Get closest detection distance
      if (ld2410_moving) {
        ld2410_distance_cm = radar.movingTargetDistance();
      } else if (ld2410_stationary) {
        ld2410_distance_cm = radar.stationaryTargetDistance();
      } else {
        ld2410_distance_cm = 0;
      }
    }
  #endif
}

// =============================================================================
// RGB STATUS LED (color-coded room/system state)
// =============================================================================
void set_status_led(int r, int g, int b) {
  digitalWrite(RGB_RED_PIN,   r > 0 ? HIGH : LOW);
  digitalWrite(RGB_GREEN_PIN, g > 0 ? HIGH : LOW);
  digitalWrite(RGB_BLUE_PIN,  b > 0 ? HIGH : LOW);
}

// =============================================================================
// TELEMETRY SAMPLING & REMOTE EDGE AI SYNC
// =============================================================================
void send_telemetry() {
  if (WiFi.status() != WL_CONNECTED) return;

  // ---------------------------------------------------------------
  // 1. Read all physical sensors
  // ---------------------------------------------------------------
  
  // BME280: Temperature + Humidity + Pressure
  float temp = 24.5;   // fallback
  float hum = 50.0;    // fallback
  float pressure = 1013.25;
  
  if (bme_found) {
    temp = bme.readTemperature();
    hum = bme.readHumidity();
    pressure = bme.readPressure() / 100.0;  // Pa -> hPa
  }

  // BH1750: Illuminance
  float lux = 350.0;   // fallback
  if (bh1750_found && lightMeter.measurementReady()) {
    lux = lightMeter.readLightLevel();
  }

  // MQ-2: Gas/Air Quality (analog, secondary)
  int raw_mq2 = analogRead(MQ2_PIN);
  float mq2_voltage = raw_mq2 * (3.3 / 4095.0);
  float mq2_ppm = 350.0 + (mq2_voltage * 400.0);

  // PIR: Motion event
  bool pir_motion = (digitalRead(PIR_PIN) == HIGH);

  // CO2: prefer SCD41 (NDIR) over MQ-2 estimate
  float co2_value = mq2_ppm;           // fallback: MQ-2 estimate
  String co2_source = "mq2_estimate";
  if (scd41_found && scd41_data_ready) {
    co2_value = scd41_co2;
    co2_source = "scd41_ndir";
  }

  // Presence: combine PIR + LD2410C
  bool presence = pir_motion;
  String presence_source = "pir";
  if (ld2410_found) {
    presence = ld2410_presence || pir_motion;  // OR fusion: either sensor triggers
    presence_source = "pir+mmwave";
  }

  // ---------------------------------------------------------------
  // 2. Construct expanded JSON payload
  // ---------------------------------------------------------------
  StaticJsonDocument<512> doc;
  
  // Core environmental data
  doc["room_id"]          = "f2_office_a";
  doc["temperature"]      = round(temp * 100.0) / 100.0;
  doc["humidity"]         = round(hum * 100.0) / 100.0;
  doc["pressure_hpa"]     = round(pressure * 10.0) / 10.0;
  doc["co2"]              = round(co2_value * 10.0) / 10.0;
  doc["co2_source"]       = co2_source;
  doc["lux"]              = round(lux * 10.0) / 10.0;
  doc["motion_detected"]  = pir_motion;
  doc["mq2_raw"]          = raw_mq2;
  doc["source"]           = "sensor_node";
  
  // SCD41 supplementary readings (if available)
  if (scd41_found && scd41_data_ready) {
    doc["scd41_temp"]     = round(scd41_temp * 100.0) / 100.0;
    doc["scd41_humidity"] = round(scd41_hum * 100.0) / 100.0;
  }
  
  // LD2410C mmWave presence (if available)
  if (ld2410_found) {
    doc["mmwave_presence"]   = ld2410_presence;
    doc["mmwave_moving"]     = ld2410_moving;
    doc["mmwave_stationary"] = ld2410_stationary;
    doc["mmwave_distance_cm"] = ld2410_distance_cm;
  }
  doc["presence"]         = presence;
  doc["presence_source"]  = presence_source;
  
  // INA226 power measurement (if available)
  if (ina226_found) {
    doc["measured_voltage_v"]  = round(ina226_voltage * 1000.0) / 1000.0;
    doc["measured_current_mA"] = round(ina226_current_mA * 10.0) / 10.0;
    doc["measured_power_mW"]   = round(ina226_power_mW * 10.0) / 10.0;
  }
  
  // Current actuator state (for Pi feedback loop)
  doc["actuator_fan_speed"]    = current_fan_speed;
  doc["actuator_light_level"]  = current_light_level;
  doc["actuator_servo_angle"]  = current_servo_angle;
  
  // Sensor health status
  JsonObject health = doc.createNestedObject("sensor_health");
  health["bme280"]  = bme_found;
  health["bh1750"]  = bh1750_found;
  health["scd41"]   = scd41_found;
  health["ina226"]  = ina226_found;
  health["ld2410c"] = ld2410_found;
  health["servo"]   = servo_attached;

  String requestBody;
  serializeJson(doc, requestBody);

  // ---------------------------------------------------------------
  // 3. POST to Raspberry Pi Edge Brain
  // ---------------------------------------------------------------
  http.begin(server_url);
  http.addHeader("Content-Type", "application/json");

  int httpCode = http.POST(requestBody);

  if (httpCode == 200) {
    String response = http.getString();
    
    // Compact status log
    Serial.printf("+ T=%.1fC RH=%.0f%% CO2=%.0f Lux=%.0f Pres=%s",
                  temp, hum, co2_value, lux, presence ? "YES" : "NO");
    if (ina226_found) {
      Serial.printf(" P=%.0fmW", ina226_power_mW);
    }
    Serial.println();

    // ---------------------------------------------------------------
    // 4. Parse Pi's expanded control decision
    // ---------------------------------------------------------------
    StaticJsonDocument<384> respDoc;
    if (deserializeJson(respDoc, response) == DeserializationError::Ok) {
      const char* hvac_action  = respDoc["hvac_action"]  | "ECO";
      const char* light_action = respDoc["light_action"] | "OFF";
      float occ_prob           = respDoc["occupancy_probability"] | 0.0;
      
      // New v2.0 control fields (with backward-compatible defaults)
      int fan_speed    = respDoc["fan_speed"]    | -1;    // 0-255, -1 = use hvac_action
      int light_level  = respDoc["light_level"]  | -1;    // 0-255, -1 = use light_action
      int servo_angle  = respDoc["servo_angle"]  | -1;    // 0-180, -1 = no change

      Serial.printf("   Pi -> Occ=%.2f HVAC=%s Light=%s Fan=%d LED=%d Servo=%d\n",
                    occ_prob, hvac_action, light_action, fan_speed, light_level, servo_angle);

      // 5. Actuate Room 101 hardware
      apply_actuation(hvac_action, light_action, fan_speed, light_level, servo_angle);
    }

  } else if (httpCode > 0) {
    Serial.printf("! Pi Response Code: %d\n", httpCode);
  } else {
    Serial.printf("x HTTP Error: %s\n", http.errorToString(httpCode).c_str());
    // Fail-safe: reduce actuators when Pi unreachable
    apply_actuation("ECO", "OFF", 0, 0, -1);
    set_status_led(255, 0, 0);  // RED = connection lost
  }

  http.end();
}

// =============================================================================
// CLOSED-LOOP ACTUATION (Driven by Raspberry Pi Edge AI decisions)
// =============================================================================
void apply_actuation(const char* hvac_action, const char* light_action,
                     int fan_speed, int light_level, int servo_angle) {

  // ---------------------------------------------------------------
  // 1. FAN CONTROL (PWM variable speed via MOSFET)
  // ---------------------------------------------------------------
  if (fan_speed >= 0) {
    // Direct PWM value from Pi (0-255)
    current_fan_speed = constrain(fan_speed, 0, 255);
  } else {
    // Backward compatible: use hvac_action string
    if (strcmp(hvac_action, "HIGH") == 0) {
      current_fan_speed = 255;
    } else if (strcmp(hvac_action, "NORMAL") == 0 || strcmp(hvac_action, "MEDIUM") == 0) {
      current_fan_speed = 180;
    } else if (strcmp(hvac_action, "LOW") == 0) {
      current_fan_speed = 100;
    } else {  // ECO / OFF
      current_fan_speed = 0;
    }
  }

  #if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
    ledcWrite(FAN_PWM_PIN, current_fan_speed);
  #else
    ledcWrite(FAN_LEDC_CH, current_fan_speed);
  #endif

  Serial.printf("   -> Fan: %d/255\n", current_fan_speed);

  // ---------------------------------------------------------------
  // 2. WHITE LED LIGHTING (PWM dimmable)
  // ---------------------------------------------------------------
  #if ENABLE_WHITE_LED
    if (light_level >= 0) {
      // Direct PWM value from Pi (0-255)
      current_light_level = constrain(light_level, 0, 255);
    } else {
      // Backward compatible: use light_action string
      if (strcmp(light_action, "OFF") == 0) {
        current_light_level = 0;
      } else if (strcmp(light_action, "LOW") == 0) {
        current_light_level = 64;
      } else if (strcmp(light_action, "MEDIUM") == 0) {
        current_light_level = 160;
      } else {  // ON / HIGH
        current_light_level = 255;
      }
    }

    #if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
      ledcWrite(WHITE_LED_PIN, current_light_level);
    #else
      ledcWrite(LED_LEDC_CH, current_light_level);
    #endif

    Serial.printf("   -> Light: %d/255\n", current_light_level);
  #endif

  // ---------------------------------------------------------------
  // 3. SERVO VENTILATION ACTUATOR (SG90)
  // ---------------------------------------------------------------
  #if HAS_SERVO_LIB && ENABLE_SERVO
    if (servo_attached && servo_angle >= 0) {
      current_servo_angle = constrain(servo_angle, 0, 180);
      ventServo.write(current_servo_angle);
      Serial.printf("   -> Servo: %d deg\n", current_servo_angle);
    }
  #endif

  // ---------------------------------------------------------------
  // 4. RGB STATUS LED — show system state color
  // ---------------------------------------------------------------
  if (current_fan_speed > 200) {
    set_status_led(0, 0, 255);    // BLUE = active cooling
  } else if (current_fan_speed > 0) {
    set_status_led(0, 255, 255);  // CYAN = ventilation/low cooling
  } else if (current_light_level > 0) {
    set_status_led(0, 255, 0);    // GREEN = occupied, lights on
  } else {
    set_status_led(0, 0, 0);      // OFF = vacant/eco
  }
}
