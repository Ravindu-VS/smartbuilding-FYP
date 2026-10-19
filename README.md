# Design and Implementation of an Edge Intelligence Based Energy Management and Optimization System for Smart Buildings
## A Hybrid Cyber-Physical Digital Twin Approach

**Author:** Vinusha Rathnayaka  
**Degree:** BSc (Hons) Computer Engineering | Final Year Research Project  
**Repository Location:** `G:/projects/Final Year Project Smart Building/Project`  

---

## 📋 Table of Contents

1. [Executive Summary & Core Paradigm](#1-executive-summary--core-paradigm)
2. [Key System Features](#2-key-system-features)
3. [System Architecture & Data Pipeline](#3-system-architecture--data-pipeline)
4. [Physical Prototype Hardware (Room 101)](#4-physical-prototype-hardware-room-101)
5. [Edge Intelligence & Machine Learning Pipeline](#5-edge-intelligence--machine-learning-pipeline)
6. [Backend, Middleware & Enterprise Layer](#6-backend-middleware--enterprise-layer)
7. [3D WebGL Digital Twin Architecture](#7-3d-webgl-digital-twin-architecture)
8. [Intelligent Control & Optimization Framework](#8-intelligent-control--optimization-framework)
9. [Verified Experimental Evaluation & Results](#9-verified-experimental-evaluation--results)
10. [Repository Directory Structure](#10-repository-directory-structure)
11. [Installation & Quickstart Guide](#11-installation--quickstart-guide)
12. [API Reference & Telemetry Payloads](#12-api-reference--telemetry-payloads)
13. [Academic Defense & Viva Guidance](#13-academic-defense--viva-guidance)

---

## 1. Executive Summary & Core Paradigm

Commercial and residential buildings account for over 40% of global electricity usage, with HVAC and artificial lighting representing the vast majority of that consumption. Traditional Building Management Systems (BMS) operate on static, rule-based schedules (e.g., turning on cooling and lights from 8 AM to 6 PM), causing massive energy waste during low or zero occupancy periods. Furthermore, centralized cloud-based IoT analytics suffer from network latency, single-point-of-failure risks, and privacy concerns when streaming raw occupancy sensor telemetry.

This project introduces a **Hybrid Cyber-Physical Smart Building Platform** that combines **Edge Intelligence** on low-cost microcontrollers with a **5-Floor, 26-Room WebGL 3D Digital Twin**.

### 🌟 The Core Cyber-Physical Principle
> **Room 101** operates as a **Live Physical Hardware Prototype Anchor** (ESP32-S3 Dual-Core MCU, DHT22, BH1750, MQ135, PIR sensor, Relay, and LED PWM dimmer), while the remaining **25 rooms** form a **Simulated Digital Twin Environment** to demonstrate building-scale multi-zone optimization.

```
┌───────────────────────────────┐
│     REAL PHYSICAL WORLD       │
│                               │
│  Room 101 Hardware Node       │
│  (ESP32-S3 + Sensors + Relay) │
└───────────────┬───────────────┘
                │
                ▼
┌───────────────────────────────┐
│       EDGE INTELLIGENCE       │
│                               │
│  Logistic Regression MCU ML   │
│  P(Occupied) Inference <5ms   │
└───────────────┬───────────────┘
                │  MQTT JSON
                ▼
┌───────────────────────────────┐
│      BACKEND CONTROL LAYER    │
│                               │
│  Flask State Manager          │
│  Demand-Driven HVAC / Dimming │
└───────────────┬───────────────┘
                │  Server-Sent Events (SSE)
                ▼
┌───────────────────────────────┐
│    3D DIGITAL TWIN ENGINE     │
│                               │
│  Next.js 16 + Three.js 0.185  │
│  5 Floors / 26 Rooms Rendering│
└───────────────┴───────────────┘
```

---

## 2. Key System Features

- **On-Device Edge ML Inference:** Deploys trained Logistic Regression and domain-adapted occupancy models directly on ESP32-S3 microcontrollers (<15 KB SRAM footprint, <5 ms MCU execution time).
- **Sub-150ms Synchronization Latency:** Real-time data pipeline streaming physical sensor motion triggers to virtual 3D avatar rendering via MQTT, Flask, and Server-Sent Events (SSE).
- **Quantified Energy Savings:** Achieves a **38.2% total energy reduction** (0.52 kWh saved per hour vs. baseline static schedules) while maintaining a **0.0% comfort violation rate** (Fanger PMV index boundaries).
- **Modular 3D WebGL Digital Twin:** Built with Three.js, featuring instanced particle rendering (`InstancedMesh`), $O(1)$ scene graph lookups (`SceneRegistry`), dynamic floor thermal heatmaps (PMV), and power riser particle pulses (`ResearchEngine.js`).
- **Enterprise Security & Integration:** WSO2 Micro Integrator sequences and JWT token validation layer (`auth/jwt_validator.py`) for enterprise API deployment.
- **RL/PPO Optimization Readiness:** Fully formulated state-action MDP environment (`control/ppo_controller.py` using `stable-baselines3`), pre-trained and saved in `models/ppo_building_controller.zip`.

---

## 3. System Architecture & Data Pipeline

The system operates across four decoupled layers:

```mermaid
graph TD
    subgraph "1. PHYSICAL HARDWARE LAYER (Room 101 Anchor)"
        A[ESP32-S3 Microcontroller<br/>240 MHz Dual-Core | 512 KB SRAM]
        S1[DHT22: Temp & Hum] --> A
        S2[BH1750: Ambient Lux] --> A
        S3[MQ135: Air Quality / CO2] --> A
        S4[PIR Sensor: Physical Motion] --> A
        A -->|On-Device ML| B[Edge Inference Engine<br/>P Occupied Calculation]
    end

    subgraph "2. COMMUNICATION & BACKEND LAYER"
        B -->|MQTT / Wi-Fi| C[MQTT Broker<br/>Topic: building/A/floor/1/room/101/sensor]
        C -->|JSON Telemetry| D[Flask / FastAPI Backend<br/>smart_building_api_flask.py]
        D -->|Actuator Callback| E[Relay Fan ON/OFF & LED PWM Dimming]
        E -->|GPIO 5 & 6| A
    end

    subgraph "3. STREAMING & UI LAYER"
        D -->|Server-Sent Events| F[Next.js Dashboard<br/>useSSE.ts Hook]
        F -->|postMessage| G[Three.js Vanilla Wrapper<br/>public/3d-twin/app.js]
    end

    subgraph "4. 3D DIGITAL TWIN ENGINE LAYER"
        G --> H[EngineManager<br/>60 FPS Rendering Loop]
        H --> I[OccupancyEngine - Avatars]
        H --> J[LightingEngine - Illumination]
        H --> K[HVACEngine - Airflow]
        H --> L[ResearchEngine - PMV Heatmaps & Energy Flow]
        H --> M[HeroEngine - Room 101 Green Sync Ring]
    end

    style A fill:#0d2d1e,stroke:#2e7d32,color:#fff
    style B fill:#311b92,stroke:#673ab7,color:#fff
    style D fill:#263238,stroke:#546e7a,color:#fff
    style G fill:#0d47a1,stroke:#1976d2,color:#fff
```

---

## 4. Physical Prototype Hardware (Room 101)

The physical prototype is deployed on an **ESP32-S3** microcontroller board representing **Room 101 (Floor 1 Main Office/Lobby)**.

### Hardware Bill of Materials (BOM) & Pinout

| Component | Function / Description | Interface / Pin Assignment | Operating Voltage |
| :--- | :--- | :--- | :--- |
| **ESP32-S3** | Main MCU Processing & Wi-Fi Node | System Core | 3.3V / 5V USB |
| **DHT22** | Digital Temperature & Humidity Sensor | Single-Bus Data -> `GPIO 4` | 3.3V |
| **BH1750** | Digital Ambient Light Lux Sensor | I2C (SDA -> `GPIO 8`, SCL -> `GPIO 9`) | 3.3V |
| **MQ135** | Air Quality / CO2 ppm Estimator | Analog Output -> `GPIO 1` (ADC) | 5.0V |
| **PIR Sensor** | Physical Infrared Motion Detector | Digital Input -> `GPIO 2` | 3.3V |
| **Relay Module** | HVAC Cooling Fan High-Power Actuator | Control Pin -> `GPIO 5` | 5.0V |
| **LED Module** | Lighting Actuator with PWM Dimming | PWM Channel 0 -> `GPIO 6` | 3.3V |

### Firmware Logic (`firmware/esp32_smart_building.ino`)
- Samples sensor array every 10 seconds.
- Computes derived feature values (`HumidityRatio`).
- Constructs JSON telemetry payload.
- Publishes to `building/A/floor/1/room/101/sensor`.
- Subscribes to `building/A/floor/1/room/101/control` for incoming actuator commands (`light_action`: OFF/DIM/ON, `hvac_action`: ECO/NORMAL).

---

## 5. Edge Intelligence & Machine Learning Pipeline

### On-Device Inference Logic
To avoid raw telemetry overhead, the ESP32 calculates occupancy probability locally using standardized feature vectors:

$$\mathbf{x} = \left[ \text{Temperature (°C)}, \text{Humidity (\%)} , \text{Light (Lux)}, \text{CO}_2 \text{ (ppm)}, \text{HumidityRatio} \right]$$

$$P(y=1 | \mathbf{x}) = \sigma(\mathbf{w}^T \mathbf{x} + b) = \frac{1}{1 + e^{-(\mathbf{w}^T \mathbf{x} + b)}}$$

### Model Performance Benchmarks

Experiments were conducted across the **UCI Benchmark Dataset** and empirical smart building test runs (`output/metrics/`):

| Evaluation Metric | Logistic Regression (Edge MCU) | Random Forest | Final Unified Model |
| :--- | :--- | :--- | :--- |
| **Accuracy** | **98.34%** | 97.26% | **99.88%** |
| **Precision** | **96.50%** | 93.62% | **99.71%** |
| **Recall** | **96.69%** | 95.23% | **99.80%** |
| **F1-Score** | **96.59%** | 94.42% | **99.75%** |
| **ROC-AUC** | **0.9948** | 0.9927 | **0.9999** |
| **MCU Memory Footprint** | **< 15 KB SRAM** | > 2.3 MB | 3.7 MB (Backend) |
| **MCU Inference Time** | **< 5 ms** | ~45 ms | N/A (Server-side) |

---

## 6. Backend, Middleware & Enterprise Layer

### Flask / FastAPI System Server (`smart_building_api_flask.py`)
- Running on port `8001` (or `8002` for FastAPI).
- Main-thread event loop coordinating MQTT ingestion, simulation clock tick, and control policy evaluation.
- Serves the `/api/stream` Server-Sent Events (SSE) endpoint broadcasting building-wide JSON state changes to web subscribers.

### Enterprise Security & Integration (WSO2 MI)
- `auth/jwt_validator.py` enforces RS256/HS256 JWT validation on API routes.
- `wso2/mi/synapse-configs/sequences/SensorIngestionSequence.xml` provides enterprise service bus routing for industrial IoT gateways.

---

## 7. 3D WebGL Digital Twin Architecture

The frontend is a **Next.js 16 (Turbopack) App** located in `dashboard/fyp-research-twin/`. The 3D Digital Twin is embedded inside an `iframe` loading `public/3d-twin/index.html`.

### Decoupled Engine Architecture (`public/3d-twin/`)

```
public/3d-twin/
├── app.js                      # Master WebGL Controller & Engine Orchestrator
├── index.html                  # Canvas & ImportMap entry
├── core/
│   ├── EngineManager.js        # 60 FPS animation tick manager
│   ├── EventBus.js             # Asynchronous pub/sub event bus
│   ├── SceneRegistry.js        # O(1) Mesh lookup dictionary
│   ├── SimConfig.js            # Visual thresholds & palette constants
│   ├── SimulationClock.js      # Time-of-day clock (00:00 - 23:59)
│   └── VisualStateStore.js     # State hash diffing engine
├── engines/
│   ├── AvatarPool.js           # Pre-allocated 3D human mesh pool
│   ├── EnvironmentalEngine.js  # Dynamic sky, sun position, swaying trees & cars
│   ├── ResearchEngine.js       # PMV heatmaps & energy particle risers
│   ├── energyEngine.js         # Power consumption visualization
│   ├── heroEngine.js           # Room 101 glowing green sync ring & latency meter
│   ├── hvacEngine.js           # Directional cooling/heating airflow particles
│   ├── lightingEngine.js       # Room emissive ceiling light intensity
│   └── occupancyEngine.js      # Pathfinding avatars (door -> desk sitting/typing)
└── controllers/
    ├── DoorManager.js          # Physical hinged door opening/closing
    └── RoomController.js       # Room state coordinator
```

### Key Performance Optimizations
1. **$O(1)$ Scene Registry:** Eliminates runtime `scene.traverse()` calls by caching meshes in `SceneRegistry.js`.
2. **State Hash Diffing:** `VisualStateStore.js` computes a hash of room visual properties and skips 3D material updates if the incoming SSE payload hasn't changed.
3. **Instanced Mesh Particle Systems:** `ResearchEngine.js` renders hundreds of energy particles flowing along the building power shaft using `THREE.InstancedMesh`.

---

## 8. Intelligent Control & Optimization Framework

### Multi-Objective Formulation
The system optimizes building operation over a discrete time horizon $t$:

$$\min_{\mathbf{a}_t} J = w_e \cdot E_{\text{power}}(\mathbf{a}_t) + w_c \cdot \sum_{i=1}^{N} \max\left(0, |T_i - T_{\text{target}}| - \Delta_{\text{comfort}}\right) + w_s \cdot \|\mathbf{a}_t - \mathbf{a}_{t-1}\|$$

Where:
- $w_e = 1.0$ (Energy weight)
- $w_c = 5.0$ (Comfort penalty weight)
- $w_s = 0.5$ (Actuator switching wear penalty)

### Control Policies Implemented
1. **Baseline Rule Controller (`control/baseline_rule_controller.py`):** Runs static schedules (23°C target, 100% lights ON during work hours).
2. **Demand-Driven AI Controller (`smart_building_controller.py`):** Dynamically drops HVAC to ECO mode (26°C / fan OFF) and dims lights (0–30%) when rooms transition to `EMPTY`.
3. **Reinforcement Learning Adapter (`control/ppo_controller.py`):** Integrates Stable-Baselines3 PPO model (`models/ppo_building_controller.zip`) for multi-zone optimization.

---

## 9. Verified Experimental Evaluation & Results

Quantitative results recorded from 1-hour to 24-hour evaluation trials (`output/metrics/`):

### 📊 Energy & Comfort Benchmark Summary

| Evaluation Parameter | Baseline Control (Static Schedule) | Proposed AI Controller | Absolute Improvement |
| :--- | :--- | :--- | :--- |
| **Total Energy Consumption (1-Hour Trial)** | **1.35 kWh** | **0.83 kWh** | **0.52 kWh Saved** |
| **Energy Reduction Percentage** | 0.0% | **38.2%** | **38.2% Energy Saved** |
| **Comfort Boundary Violations (22–24°C)** | 0 Violations | **0 Violations** | **0.0% Violation Rate** |
| **Lighting Active Time** | 50.0% | **43.3%** | **6.7% Reduction** |
| **HVAC Active Cooling Time** | 50.0% | **43.3%** | **6.7% Reduction** |
| **End-to-End Cyber-Physical Sync Latency** | N/A | **< 150 ms** | **Real-Time Synchronized** |

```
1.35 kWh ┌───────────────────────────────────────────┐ (Baseline Static Schedule)
         │███████████████████████████████████████████│
0.83 kWh ├───────────────────────────────┐           │ (Proposed AI Controller)
         │███████████████████████████████│ 38.2% SAVED
         └───────────────────────────────┴───────────┘
```

---

## 10. Repository Directory Structure

```
G:/projects/Final Year Project Smart Building/Project/
├── config.yaml                         # Master simulation & thermal parameters
├── requirements.txt                    # Python dependencies
├── run_system.py                       # System orchestrator script
├── smart_building_api_flask.py         # Primary Flask SSE API server (Port 8001)
├── smart_building_controller.py        # Real-time AI control policy engine
├── occupancy_predictor.py              # On-demand ML occupancy inference script
├── room_config.json                    # 26-room spatial definitions
├── firmware/
│   └── esp32_smart_building.ino        # ESP32-S3 C++ Arduino firmware
├── hardware/
│   ├── hardware_room_manager.py        # Live Hardware state manager (Room 101)
│   └── sensor_gateway.py               # MQTT telemetry parsing & bounds checker
├── models/
│   ├── uci_occupancy_model.pkl         # Trained Logistic Regression model
│   ├── domain_adapted_occupancy_model.pkl # Domain-adapted ML model
│   └── ppo_building_controller.zip     # Trained Stable-Baselines3 PPO policy
├── control/
│   ├── baseline_rule_controller.py     # Static schedule baseline logic
│   ├── mpc_controller.py              # Model Predictive Control algorithm
│   ├── ppo_controller.py              # PPO RL controller adapter
│   └── optimizer.py                    # Multi-objective scoring loss
├── dashboard/fyp-research-twin/        # Next.js 16 WebGL Dashboard
│   ├── package.json
│   ├── src/
│   │   ├── app/page.tsx                # Dashboard UI Page
│   │   ├── components/
│   │   │   ├── 3d/VanillaTwinWrapper.tsx # Iframe Wrapper for 3D Twin
│   │   │   └── hardware/HardwareLivePanel.tsx # Room 101 Hardware HUD
│   │   └── hooks/useSSE.ts             # Server-Sent Events subscriber hook
│   └── public/3d-twin/                 # Three.js 3D Engine source code
├── experiments/                        # Experiment execution scripts (Exp A, B, C, D)
└── output/metrics/                     # Evaluation log files & CSV benchmarks
```

---

## 11. Installation & Quickstart Guide

### Prerequisites
- Python 3.10+ (Virtual environment recommended)
- Node.js 18+ & npm
- C++ Arduino IDE (For ESP32 firmware flashing)

### Step 1: Install Python Dependencies
```bash
cd "G:/projects/Final Year Project Smart Building/Project"
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

### Step 2: Install Dashboard Dependencies
```bash
cd dashboard/fyp-research-twin
npm install
```

### Step 3: Run System Backend (Flask API + Simulation Loop)
```bash
# In Project root
.\.venv\Scripts\python run_system.py --demo
```
*Backend starts on `http://127.0.0.1:8001`.*

### Step 4: Run Next.js WebGL Dashboard
```bash
# In dashboard/fyp-research-twin
npm run dev
```
*Open your browser at `http://localhost:3000`.*

---

## 12. API Reference & Telemetry Payloads

### 1. Ingest Physical Hardware Sensor Data
`POST /api/hardware/sensor-data`

**Request Payload:**
```json
{
  "room_id": "f1_room_101",
  "temperature": 24.5,
  "humidity": 52.3,
  "co2": 520.0,
  "lux": 380.0,
  "occupancy_probability": 0.94
}
```

**Response:**
```json
{
  "status": "success",
  "room_id": "f1_room_101",
  "updated_sensors": {
    "temperature": 24.5,
    "humidity": 52.3,
    "co2": 520.0,
    "lux": 380.0,
    "occupancy_probability": 0.94
  }
}
```

### 2. Stream Real-Time Building Telemetry (SSE)
`GET /api/stream`

**Event Stream Payload (data: JSON):**
```json
{
  "sim_time": "Day 1T14:30:00",
  "global_metrics": {
    "total_power_watts": 3450,
    "occupied_rooms": 8,
    "comfort_score": 98.5
  },
  "rooms": {
    "f1_room_101": {
      "temperature": 24.5,
      "humidity": 52.3,
      "occupancy": 1,
      "occupancy_probability": 0.94,
      "hvac_status": "ACTIVE",
      "light_status": "ON",
      "powerWatts": 320,
      "is_hardware": true
    }
  }
}
```

---

## 13. Academic Defense & Viva Guidance

### 🎯 Key Viva Positioning
When presenting to the viva panel, maintain the following exact statements to ensure 100% academic defensibility:

> 1. **On Hardware Boundaries:** "Room 101 is our live physical prototype anchor equipped with an ESP32-S3 and real physical sensors. The remaining 25 rooms operate within our 3D Digital Twin simulation environment to evaluate building-scale scalability."
> 2. **On Edge Intelligence:** "Occupancy inference runs directly on the ESP32-S3 using a lightweight Logistic Regression model (<15 KB SRAM footprint, <5 ms inference time), eliminating continuous cloud telemetry dependencies."
> 3. **On AI Optimization:** "The system currently executes a demand-driven algorithmic control state machine that achieved 38.2% energy savings in evaluation trials. `ppo_controller.py` provides the fully implemented Reinforcement Learning MDP framework for planned multi-agent training."
> 4. **On Digital Twin Role:** "The 3D Digital Twin is an explainable visual interface. It visualizes backend state changes—such as PMV thermal heatmaps and energy particle flows—in real time with <150 ms synchronization latency."

---

*For further details, consult `viva_presentation.md` for the 18-slide presentation deck and speaker notes.*
