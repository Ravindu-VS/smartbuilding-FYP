# Room 101 Master Hardware Implementation & Wiring Guide
## Smart Building Hybrid Cyber-Physical Node (ESP32-S3)

**Target Node:** Room 101 (Floor 1 Main Office / Physical Prototype Anchor)  
**Firmware Path:** `Project/firmware/esp32_smart_building/esp32_smart_building.ino`  
**Communication Protocol:** HTTP REST API over Wi-Fi (Post to `http://172.20.10.2:8001/api/hardware/sensor-data`)  

---

## 🛠️ Step 1: Component Function & Dedicated Actuator Roles

| Hardware Component | Dedicated Role in System | Actuation Logic / Hardware Output |
| :--- | :--- | :--- |
| **ESP32-S3 Microcontroller** | Edge AI & Hardware Orchestrator | Runs on-device ML probability inference & REST API |
| **HW-478 3-Color RGB LED** | **ROOM LIGHTING ACTUATOR ONLY** | **ON:** Full White (`R: 255, G: HIGH, B: HIGH`)<br/>**DIM:** 50% Warm (`R: 128, G: HIGH, B: LOW`)<br/>**OFF:** (`R: 0, G: LOW, B: LOW`) |
| **HW-416-B MOSFET Driver** | **HVAC DC MOTOR FAN ACTUATOR** | **NORMAL / LOW:** Gate `GPIO 10` = `HIGH` (Motor Spins)<br/>**ECO / OFF:** Gate `GPIO 10` = `LOW` (Motor Stopped) |
| **HW-416-B Motion Sensor** | Digital Occupancy Detector | Connected to `GPIO 4` (PULLDOWN / Standard Input) |
| **MQ-2 Gas / Smoke Sensor** | Air Quality & Gas Drift Sampler | Connected to `GPIO 1` (Analog ADC) |
| **GY-30 BH1750 Lux Meter** | Ambient Light Level Sampler | Connected to Shared I2C (`SDA: GPIO 17, SCL: GPIO 18`) |
| **GY-BME280 Sensor** | Temp / Humidity / Pressure | Connected to Shared I2C (`SDA: GPIO 17, SCL: GPIO 18`) |
| **Onboard ESP32 LED** | System / Wi-Fi Status Indicator | **Solid ON:** Wi-Fi & Backend API Synced (`GPIO 38`) |

---

## 🔌 Master Wiring Diagram & Schematic Mapping

```
                        ┌────────────────────────┐
                        │     ESP32-S3 MCU       │
                        └───────────┬────────────┘
                                    │
    ┌───────────────────────────────┼───────────────────────────────┐
    │                               │                               │
 [GY-BME280]                 [GY-30 BH1750]                  [MQ-2 Gas]
Temp / Hum / Press           Lux Sensor                      Air Quality Sampler
SDA -> GPIO 17 (Shared)      SDA -> GPIO 17 (Shared)         Analog Out -> GPIO 1
SCL -> GPIO 18 (Shared)      SCL -> GPIO 18 (Shared)
    │                               │                               │
    ├───────────────────────────────┼───────────────────────────────┤
    │                               │                               │
 [HW-416-B Motion]           [HW-416-B MOSFET Fan Driver]   [HW-478 RGB LED]
Occupancy Trigger            DC Motor Fan Speed Driver       Room Lighting ONLY
Signal -> GPIO 4             Signal -> GPIO 10 (Digital)     R -> 6, G -> 7, B -> 15
```

---

## 📋 Complete Pin Connection Matrix

| Device / Module | Pin Label | ESP32-S3 Target Pin | Power Rail | Wiring Function & Notes |
| :--- | :--- | :--- | :--- | :--- |
| **GY-BME280** | VIN / VCC | **3.3V** | 3.3V Power | Sensor Power (3.3V only) |
| | GND | **GND** | Ground | Common Ground |
| | SDA | **GPIO 17** | Shared I2C | **Shared I2C Data Line** |
| | SCL | **GPIO 18** | Shared I2C | **Shared I2C Clock Line** |
| **GY-30 BH1750** | VCC | **3.3V** | 3.3V Power | Sensor Power (3.3V only) |
| | GND | **GND** | Ground | Common Ground |
| | SDA | **GPIO 17** | Shared I2C | **Shared I2C Data Line (Connected to BME280 SDA)** |
| | SCL | **GPIO 18** | Shared I2C | **Shared I2C Clock Line (Connected to BME280 SCL)** |
| **MQ-2 Gas Sensor** | VCC | **5V (VIN)** | 5V Power | Sensor heater element power |
| | GND | **GND** | Ground | Common Ground |
| | AO (Analog) | **GPIO 1** | ADC1_CH0 | Analog Air Quality reading |
| **HW-416-B Motion** | VCC | **3.3V** | 3.3V Power | Logic power |
| | GND | **GND** | Ground | Common Ground |
| | S (Signal) | **GPIO 4** | Digital Input | Digital Motion trigger (`HIGH` = motion) |
| **HW-416-B MOSFET** | V+ / V- | **5V / GND** | 5V Power | High-current power rails for DC motor |
| | SIG (Signal) | **GPIO 10** | Digital Output | Controls Fan Motor Gate (`HIGH` = ON, `LOW` = OFF) |
| | **Out+ / Out-**| **DC Motor Wires** | -- | Screw terminals connected to DC Motor |
| **HW-478 RGB LED** | R (Red) | **GPIO 6** | PWM Channel 0 | Red lighting channel |
| | G (Green) | **GPIO 7** | Digital Output | Green lighting channel |
| | B (Blue) | **GPIO 15** | Digital Output | Blue lighting channel |
| | GND (-) | **GND** | Ground | Common Cathode ground |
| **Status LED** | Built-in | **GPIO 38** | Onboard | Solid ON when Wi-Fi & Backend synced |

---

## 🚀 Re-flashing & Testing Procedure

1. Open `Project/firmware/esp32_smart_building/esp32_smart_building.ino` in Arduino IDE.
2. Click **Upload (Ctrl + U)**.
3. Open **Serial Monitor** at `115200` baud.

You will see:
```text
✓ HTTP 200 OK | Temp: 24.5°C | Lux: 410.5 | Gas: 463ppm | Motion: YES | OccProb: 0.94
   -> HVAC Actuator: DC MOTOR FAN [ON]
   -> Lighting Actuator: HW-478 RGB LED [FULL ON]
```
