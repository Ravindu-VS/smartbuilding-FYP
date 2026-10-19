/**
 * Smart Building 3D Digital Twin
 * ─────────────────────────────────────────────
 * Three.js WebGL visualization of a 5-floor smart building.
 * Connects to Flask API via SSE for live sensor data.
 *
 * Features:
 *  - Realistic multi-floor building with glass exterior
 *  - Exploded view / Cutaway view / Solid view
 *  - Click rooms for detailed sensor data
 *  - Dynamic lighting based on time of day
 *  - Occupancy indicators & HVAC particles
 *  - Real-time data from Flask API (SSE)
 */
console.log("SMART BUILDING TWIN ENGINE LOADED: public/3d-twin/app.js");

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

// ─── New Decoupled Architecture ───
import { eventBus, Events } from './core/EventBus.js';
import { EngineManager } from './core/EngineManager.js';
import { VisualStateStore } from './core/VisualStateStore.js';
import { SimulationClock } from './core/SimulationClock.js';
import { SIM_CONFIG } from './core/SimConfig.js';

// Engines (uniform API: init, onRoomStateChanged, tick, dispose)
import { OccupancyEngine } from './engines/occupancyEngine.js';
import { LightingEngine } from './engines/lightingEngine.js';
import { HVACEngine } from './engines/hvacEngine.js';
import { EnergyEngine } from './engines/energyEngine.js';
import { HeroEngine } from './engines/heroEngine.js';
import { EnvironmentalEngine } from './engines/EnvironmentalEngine.js';
import { ResearchEngine } from './engines/ResearchEngine.js';

// Controllers & Debug
import { RoomController } from './controllers/RoomController.js';
import { DebugOverlay } from './debug/DebugOverlay.js';

// ═══════════════════════════════════════════════════════════════
// CONFIGURATION
// ═══════════════════════════════════════════════════════════════

export const CONFIG = {
    building: {
        width: 30,          // X-axis (meters)
        depth: 20,          // Y-axis
        floorHeight: 3.5,   // Height per floor
        slabThickness: 0.3, // Concrete slab
        floors: 5,
        wallThickness: 0.15,
        glassOpacity: 0.45,
    },
    camera: {
        fov: 45,
        near: 0.1,
        far: 500,
        position: [45, 35, 45],
        target: [0, 8, 0],
    },
    colors: {
        background: 0x050510,
        ground: 0x020205,
        concrete: 0x11111a, // Dark sci-fi metal
        concreteFrame: 0x1a1a2a,
        glass: 0x00aaff, // Cyan-tinted glass
        wallInterior: 0x151525,
        floorTile: 0x10101c,
        ceiling: 0x11111a,
        carpet: {
            office: 0x5a6577,
            meeting: 0x6b7b6e,
            kitchen: 0x8b7b6b,
            corridor: 0x7a7a7a,
            lobby: 0x6b5e50,
            server: 0x3a3a4a,
            executive: 0x4a4a5a,
            lounge: 0x5a5050,
            gym: 0x4a5a5a,
            shop: 0x665544,
            residential: 0x8a7b6c,
            bathroom: 0xaaaaaa,
        },
        furniture: {
            desk: 0x8b6914,
            chair: 0x2a2a2a,
            table: 0x654321,
            sofa: 0x3a3a5a,
            cabinet: 0x6a6a6a,
        },
        occupancy: {
            occupied: 0x10b981,
            empty: 0x4a5568,
            standby: 0xf59e0b,
        },
        accent: 0x6366f1,
    },
    explode: {
        gap: 6.5,        // Gap between floors in exploded view
        duration: 1200,  // Animation duration (ms)
    },
};

// ═══════════════════════════════════════════════════════════════
// FLOOR LAYOUTS — 5 unique floors
// ═══════════════════════════════════════════════════════════════

const FLOOR_LAYOUTS = [
    // Floor 1 (Ground) — Retail & Lobby
    {
        name: 'Retail & Lobby',
        rooms: [
            { id: 'lobby',      name: 'Main Lobby',      type: 'lobby',    x: 0,  z: 0,  w: 15, d: 12, maxOcc: 15 },
            { id: 'cafe',       name: 'Coffee Shop',     type: 'shop',     x: 15, z: 0,  w: 15, d: 12, maxOcc: 15 },
            { id: 'retail_a',   name: 'Retail Store A',  type: 'shop',     x: 0,  z: 12, w: 10, d: 8,  maxOcc: 10 },
            { id: 'retail_b',   name: 'Retail Store B',  type: 'shop',     x: 10, z: 12, w: 10, d: 8,  maxOcc: 10 },
            { id: 'bathroom',   name: 'Public Restrooms',type: 'bathroom', x: 20, z: 12, w: 10, d: 8,  maxOcc: 5  },
        ]
    },
    // Floor 2 — Health & Recreation
    {
        name: 'Health & Recreation',
        rooms: [
            { id: 'gym',        name: 'Fitness Center',  type: 'gym',      x: 0,  z: 0,  w: 20, d: 12, maxOcc: 20 },
            { id: 'spa',        name: 'Spa & Wellness',  type: 'lounge',   x: 20, z: 0,  w: 10, d: 12, maxOcc: 10 },
            { id: 'studio',     name: 'Yoga Studio',     type: 'gym',      x: 0,  z: 12, w: 15, d: 8,  maxOcc: 12 },
            { id: 'lockers',    name: 'Locker Rooms',    type: 'bathroom', x: 15, z: 12, w: 15, d: 8,  maxOcc: 10 },
        ]
    },
    // Floor 3 — Operations (PRIMARY MONITORED FLOOR)
    {
        name: 'Operations (AI Monitored)',
        isMonitored: true,
        rooms: [
            { id: 'office_a',    name: 'Office A',        type: 'office',   x: 0,  z: 0,  w: 14, d: 12, maxOcc: 10, sensorId: 0 },
            { id: 'meeting_b',   name: 'Meeting Room B',  type: 'meeting',  x: 14, z: 0,  w: 10, d: 8,  maxOcc: 8,  sensorId: 1 },
            { id: 'kitchen',     name: 'Kitchen',          type: 'kitchen',  x: 24, z: 0,  w: 6,  d: 8,  maxOcc: 4,  sensorId: 2 },
            { id: 'corridor',    name: 'Main Corridor',   type: 'corridor', x: 14, z: 8,  w: 16, d: 4,  maxOcc: 5,  sensorId: 3 },
            { id: 'office_b2',   name: 'Office B2',       type: 'office',   x: 0,  z: 12, w: 14, d: 8,  maxOcc: 8  },
            { id: 'server',      name: 'Server Room',     type: 'server',   x: 14, z: 12, w: 16, d: 8,  maxOcc: 2  },
        ]
    },
    // Floor 4 — Residential Apartments
    {
        name: 'Residential Apartments',
        rooms: [
            { id: 'apt1_living', name: 'Apt 1 - Living',  type: 'residential', x: 0,  z: 0,  w: 10, d: 12, maxOcc: 4 },
            { id: 'apt1_bed',    name: 'Apt 1 - Bedroom', type: 'residential', x: 10, z: 0,  w: 5,  d: 12, maxOcc: 2 },
            { id: 'apt2_living', name: 'Apt 2 - Living',  type: 'residential', x: 15, z: 0,  w: 10, d: 12, maxOcc: 4 },
            { id: 'apt2_bed',    name: 'Apt 2 - Bedroom', type: 'residential', x: 25, z: 0,  w: 5,  d: 12, maxOcc: 2 },
            { id: 'apt1_bath',   name: 'Apt 1 - Bathroom',type: 'bathroom',    x: 0,  z: 12, w: 5,  d: 8,  maxOcc: 1 },
            { id: 'hallway',     name: 'Hallway',         type: 'corridor',    x: 5,  z: 12, w: 20, d: 8,  maxOcc: 3 },
            { id: 'apt2_bath',   name: 'Apt 2 - Bathroom',type: 'bathroom',    x: 25, z: 12, w: 5,  d: 8,  maxOcc: 1 },
        ]
    },
    // Floor 5 — Penthouse Suite
    {
        name: 'Penthouse Suite',
        rooms: [
            { id: 'lounge',       name: 'Penthouse Lounge',type: 'residential', x: 0,  z: 0,  w: 20, d: 12, maxOcc: 8 },
            { id: 'master',       name: 'Master Bedroom',  type: 'residential', x: 20, z: 0,  w: 10, d: 12, maxOcc: 2 },
            { id: 'terrace',      name: 'Roof Terrace',    type: 'lobby',       x: 0,  z: 12, w: 20, d: 8,  maxOcc: 15},
            { id: 'bath',         name: 'Luxury Bath',     type: 'bathroom',    x: 20, z: 12, w: 10, d: 8,  maxOcc: 2 },
        ]
    },
];

// Room badge above each room. The hardware room's badge follows the board status.
function drawRoomBadge(ctx, kind) {
    const styles = {
        live:    { fill: 'rgba(16, 185, 129, 0.85)', stroke: '#059669', text: '● LIVE ESP32' },
        test:    { fill: 'rgba(217, 119, 6, 0.85)',  stroke: '#b45309', text: 'TEST DATA' },
        offline: { fill: 'rgba(185, 28, 28, 0.85)',  stroke: '#7f1d1d', text: 'NO BOARD' },
        sim:     { fill: 'rgba(100, 116, 139, 0.5)', stroke: '#475569', text: 'SIMULATION' },
    };
    const st = styles[kind] || styles.sim;
    ctx.clearRect(0, 0, 256, 64);
    ctx.beginPath();
    ctx.fillStyle = st.fill;
    if (ctx.roundRect) ctx.roundRect(2, 2, 252, 60, 16); else ctx.rect(2, 2, 252, 60);
    ctx.fill();
    ctx.strokeStyle = st.stroke;
    ctx.lineWidth = 4;
    ctx.stroke();
    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold 30px Inter, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(st.text, 128, 32);
}

// ═══════════════════════════════════════════════════════════════
// MAIN APPLICATION CLASS
// ═══════════════════════════════════════════════════════════════

class SmartBuildingTwin {
    constructor() {
        this.scene = null;
        this.camera = null;
        this.renderer = null;
        this.controls = null;
        this.raycaster = new THREE.Raycaster();
        this.mouse = new THREE.Vector2();

        // Building structure
        this.floorGroups = [];        // THREE.Group per floor
        this.floorLayouts = FLOOR_LAYOUTS; // Exposed for engines
        this.exteriorGroup = null;
        this.roofGroup = null;
        this.groundGroup = null;
        this.roomMeshes = [];         // Clickable room floor meshes
        this.roomData = new Map();    // Room ID → data
        this.occupantMeshes = new Map(); // Room ID → occupant mesh array
        this.lightMeshes = new Map();    // Room ID → ceiling light meshes
        this.windowGlows = [];

        // State
        this.viewMode = 'solid';      // 'solid', 'explode', 'cutaway'
        this.selectedFloor = 2;       // Floor 3 (0-indexed)
        this.selectedRoom = null;
        this.timeOfDay = 10;          // 0-24
        this.animating = false;

        // Live data (pushed by the Next.js page; see applyBackendState)
        this.liveData = {};
        this.connected = false;
        this.liveBadge = null;        // { ctx, texture } of the hardware room's badge

        this.init();
    }

    // ─── INITIALIZATION ───

    init() {
        this.setupScene();
        this.setupCamera();
        this.setupRenderer();
        this.setupControls();
        this.setupLighting();
        this.buildGround();
        this.buildBuilding();
        this.buildExterior();
        this.buildRoof();
        this.setupEventListeners();

        // Hide loading screen
        setTimeout(() => {
            document.getElementById('loading-screen').classList.add('hidden');
        }, 1500);

        this.animate();
    }

    // ─── PROCEDURAL TEXTURES ───
    createNoiseTexture(width = 256, height = 256, scale = 1, intensity = 50) {
        const canvas = document.createElement('canvas');
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext('2d');
        const imgData = ctx.createImageData(width, height);
        const data = imgData.data;

        for (let i = 0; i < data.length; i += 4) {
            const val = 128 + (Math.random() - 0.5) * intensity;
            data[i] = val;
            data[i+1] = val;
            data[i+2] = val;
            data[i+3] = 255;
        }
        ctx.putImageData(imgData, 0, 0);

        const tex = new THREE.CanvasTexture(canvas);
        tex.wrapS = THREE.RepeatWrapping;
        tex.wrapT = THREE.RepeatWrapping;
        tex.repeat.set(scale, scale);
        tex.colorSpace = THREE.SRGBColorSpace;
        tex.needsUpdate = true;
        return tex;
    }

    createWindowTexture() {
        const canvas = document.createElement('canvas');
        canvas.width = 512;
        canvas.height = 512;
        const ctx = canvas.getContext('2d');
        
        ctx.fillStyle = '#0a0d18'; // Base very dark
        ctx.fillRect(0, 0, 512, 512);

        const cols = 8;
        const rows = 12;
        const padX = 6;
        const padY = 8;
        const cellW = 512 / cols;
        const cellH = 512 / rows;

        for (let r = 0; r < rows; r++) {
            for (let c = 0; c < cols; c++) {
                const isLit = Math.random() > 0.8;
                ctx.fillStyle = isLit ? '#ffffff' : '#05070a';
                ctx.fillRect(c * cellW + padX, r * cellH + padY, cellW - padX*2, cellH - padY*2);
            }
        }

        const tex = new THREE.CanvasTexture(canvas);
        tex.wrapS = THREE.RepeatWrapping;
        tex.wrapT = THREE.RepeatWrapping;
        tex.colorSpace = THREE.SRGBColorSpace;
        tex.needsUpdate = true;
        return tex;
    }

    createRoadTexture() {
        const canvas = document.createElement('canvas');
        canvas.width = 1024;
        canvas.height = 1024;
        const ctx = canvas.getContext('2d');
        
        // Base dark gray noise for asphalt
        const imgData = ctx.createImageData(1024, 1024);
        const data = imgData.data;
        for (let i = 0; i < data.length; i += 4) {
            const val = 30 + Math.random() * 20; 
            data[i] = val;
            data[i+1] = val;
            data[i+2] = val;
            data[i+3] = 255;
        }
        ctx.putImageData(imgData, 0, 0);

        // Draw dashed lane lines
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 4;
        ctx.setLineDash([30, 30]);
        
        const center = 512;
        // Radius of roads in pixels (plane is 160 units, texture is 1024)
        // Ratio = 1024 / 160 = 6.4 pixels per unit
        // Road at radius 45 units -> 288 pixels
        ctx.beginPath();
        ctx.arc(center, center, 45 * 6.4, 0, Math.PI * 2);
        ctx.stroke();

        // Road at radius 55 units -> 352 pixels
        ctx.beginPath();
        ctx.arc(center, center, 55 * 6.4, 0, Math.PI * 2);
        ctx.stroke();

        const tex = new THREE.CanvasTexture(canvas);
        tex.colorSpace = THREE.SRGBColorSpace;
        tex.needsUpdate = true;
        return tex;
    }

    setupScene() {
        this.scene = new THREE.Scene();
        this.scene.background = new THREE.Color(CONFIG.colors.background);
        this.scene.fog = new THREE.FogExp2(CONFIG.colors.background, 0.008);
    }

    setupCamera() {
        const aspect = window.innerWidth / window.innerHeight;
        this.camera = new THREE.PerspectiveCamera(CONFIG.camera.fov, aspect, CONFIG.camera.near, CONFIG.camera.far);
        this.camera.position.set(...CONFIG.camera.position);
    }

    setupRenderer() {
        this.renderer = new THREE.WebGLRenderer({
            antialias: true,
            alpha: false,
            powerPreference: 'high-performance'
        });
        this.renderer.setSize(window.innerWidth, window.innerHeight);
        this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        this.renderer.shadowMap.enabled = true;
        this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
        this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
        this.renderer.toneMappingExposure = 1.2;

        const pmremGenerator = new THREE.PMREMGenerator(this.renderer);
        this.scene.environment = pmremGenerator.fromScene(new RoomEnvironment(), 0.04).texture;

        const renderScene = new RenderPass(this.scene, this.camera);
        const bloomPass = new UnrealBloomPass(new THREE.Vector2(window.innerWidth, window.innerHeight), 1.5, 0.4, 0.85);
        bloomPass.threshold = 1.5;
        bloomPass.strength = 0.5;
        bloomPass.radius = 0.5;

        const outputPass = new OutputPass();

        this.composer = new EffectComposer(this.renderer);
        this.composer.addPass(renderScene);
        this.composer.addPass(bloomPass);
        this.composer.addPass(outputPass);

        document.getElementById('canvas-container').appendChild(this.renderer.domElement);
        
        window.addEventListener('resize', () => {
            this.camera.aspect = window.innerWidth / window.innerHeight;
            this.camera.updateProjectionMatrix();
            this.renderer.setSize(window.innerWidth, window.innerHeight);
            this.composer.setSize(window.innerWidth, window.innerHeight);
        });
    }

    setupControls() {
        this.controls = new OrbitControls(this.camera, this.renderer.domElement);
        this.controls.target.set(...CONFIG.camera.target);
        this.controls.enableDamping = true;
        this.controls.dampingFactor = 0.05;
        this.controls.maxPolarAngle = Math.PI / 2.1;
        this.controls.minDistance = 15;
        this.controls.maxDistance = 120;
        this.controls.update();
    }

    setupLighting() {
        // Ambient light
        this.ambientLight = new THREE.AmbientLight(0xffffff, 0.4);
        this.scene.add(this.ambientLight);

        // Hemisphere light (sky/ground)
        this.hemiLight = new THREE.HemisphereLight(0x87ceeb, 0x362d20, 0.8);
        this.scene.add(this.hemiLight);

        // Sun light with shadows
        this.sunLight = new THREE.DirectionalLight(0xfff5e6, 2.5);
        this.sunLight.position.set(30, 50, 30);
        this.sunLight.castShadow = true;
        this.sunLight.shadow.mapSize.width = 2048;
        this.sunLight.shadow.mapSize.height = 2048;
        this.sunLight.shadow.camera.near = 0.5;
        this.sunLight.shadow.camera.far = 120;
        this.sunLight.shadow.camera.left = -40;
        this.sunLight.shadow.camera.right = 40;
        this.sunLight.shadow.camera.top = 40;
        this.sunLight.shadow.camera.bottom = -40;
        this.sunLight.shadow.bias = -0.0005;
        this.scene.add(this.sunLight);

        // Fill light
        const fill = new THREE.DirectionalLight(0xc4d4f0, 1.0);
        fill.position.set(-20, 15, -10);
        this.scene.add(fill);
    }

    // ─── PROCEDURAL CAR ───

    buildCar(bodyColor) {
        const carGroup = new THREE.Group();
        
        const chassisGeo = new THREE.BoxGeometry(2, 0.8, 4.5);
        const chassisMat = new THREE.MeshStandardMaterial({ color: bodyColor, roughness: 0.2, metalness: 0.8 });
        const chassis = new THREE.Mesh(chassisGeo, chassisMat);
        chassis.position.y = 0.6;
        chassis.castShadow = true;
        carGroup.add(chassis);

        const cabinGeo = new THREE.BoxGeometry(1.8, 0.7, 2.5);
        const cabinMat = new THREE.MeshStandardMaterial({ color: 0x111111, roughness: 0.1, metalness: 0.9 });
        const cabin = new THREE.Mesh(cabinGeo, cabinMat);
        cabin.position.set(0, 1.35, -0.2);
        cabin.castShadow = true;
        carGroup.add(cabin);

        const wheelGeo = new THREE.CylinderGeometry(0.35, 0.35, 0.2, 16);
        wheelGeo.rotateZ(Math.PI / 2);
        const wheelMat = new THREE.MeshStandardMaterial({ color: 0x222222, roughness: 0.9 });
        
        const wheelPositions = [
            [-1.1, 0.35, -1.5], [1.1, 0.35, -1.5],
            [-1.1, 0.35, 1.5], [1.1, 0.35, 1.5]
        ];
        wheelPositions.forEach(pos => {
            const wheel = new THREE.Mesh(wheelGeo, wheelMat);
            wheel.position.set(...pos);
            wheel.castShadow = true;
            carGroup.add(wheel);
        });

        const hlGeo = new THREE.BoxGeometry(0.4, 0.2, 0.1);
        const hlMat = new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xffffee, emissiveIntensity: 3.0 });
        const hl1 = new THREE.Mesh(hlGeo, hlMat);
        hl1.position.set(-0.7, 0.6, 2.26);
        const hl2 = new THREE.Mesh(hlGeo, hlMat);
        hl2.position.set(0.7, 0.6, 2.26);
        
        const tlMat = new THREE.MeshStandardMaterial({ color: 0xff0000, emissive: 0xff0000, emissiveIntensity: 1.5 });
        const tl1 = new THREE.Mesh(hlGeo, tlMat);
        tl1.position.set(-0.7, 0.6, -2.26);
        const tl2 = new THREE.Mesh(hlGeo, tlMat);
        tl2.position.set(0.7, 0.6, -2.26);
        
        // Save lights for animation logic
        carGroup.userData.headlights = [hl1, hl2];
        carGroup.userData.taillights = [tl1, tl2];
        this.cars = this.cars || [];
        this.cars.push(carGroup);

        carGroup.add(hl1, hl2, tl1, tl2);
        return carGroup;
    }

    // ─── GROUND ───

    buildGround() {
        this.groundGroup = new THREE.Group();

        const cx = CONFIG.building.width / 2;
        const cz = CONFIG.building.depth / 2;

        // Generate procedural textures once
        const groundNoise = this.createNoiseTexture(256, 256, 10, 40);
        const roadTex = this.createRoadTexture();
        const leafNoise = this.createNoiseTexture(128, 128, 4, 80);
        const windowTex = this.createWindowTexture();

        // Main ground plane (light concrete/pavement base)
        const groundGeo = new THREE.PlaneGeometry(400, 400);
        const groundMat = new THREE.MeshStandardMaterial({ 
            color: 0x909492, roughness: 0.9, metalness: 0.05,
            bumpMap: groundNoise, bumpScale: 0.2
        });
        const ground = new THREE.Mesh(groundGeo, groundMat);
        ground.rotation.x = -Math.PI / 2;
        ground.position.y = -0.1;
        ground.receiveShadow = true;
        this.groundGroup.add(ground);

        // Surrounding road network (dark asphalt with lines)
        const roadGeo = new THREE.PlaneGeometry(160, 160);
        const roadMat = new THREE.MeshStandardMaterial({ 
            color: 0xffffff, roughness: 0.95, map: roadTex, bumpMap: roadTex, bumpScale: 0.05 
        });
        const road = new THREE.Mesh(roadGeo, roadMat);
        road.rotation.x = -Math.PI / 2;
        road.position.set(cx, -0.05, cz);
        road.receiveShadow = true;
        this.groundGroup.add(road);

        // Central plaza block (light stone)
        const plazaGeo = new THREE.PlaneGeometry(CONFIG.building.width + 40, CONFIG.building.depth + 40);
        const plazaMat = new THREE.MeshStandardMaterial({ 
            color: 0xc8c0b4, roughness: 0.9, bumpMap: groundNoise, bumpScale: 0.1 
        });
        const plaza = new THREE.Mesh(plazaGeo, plazaMat);
        plaza.rotation.x = -Math.PI / 2;
        plaza.position.set(cx, -0.04, cz);
        plaza.receiveShadow = true;
        this.groundGroup.add(plaza);

        // Grassy lawns inside the plaza
        const grassGeo = new THREE.PlaneGeometry(CONFIG.building.width + 30, CONFIG.building.depth + 30);
        const grassMat = new THREE.MeshStandardMaterial({ 
            color: 0x4a6a2c, roughness: 1.0, bumpMap: groundNoise, bumpScale: 0.3 
        });
        const grass = new THREE.Mesh(grassGeo, grassMat);
        grass.rotation.x = -Math.PI / 2;
        grass.position.set(cx, -0.03, cz);
        grass.receiveShadow = true;
        this.groundGroup.add(grass);

        // Building footprint pad (dark concrete)
        const padGeo = new THREE.PlaneGeometry(CONFIG.building.width + 2, CONFIG.building.depth + 2);
        const padMat = new THREE.MeshStandardMaterial({ color: 0x4a4a5a, roughness: 0.85 });
        const pad = new THREE.Mesh(padGeo, padMat);
        pad.rotation.x = -Math.PI / 2;
        pad.position.set(cx, -0.02, cz);
        pad.receiveShadow = true;
        this.groundGroup.add(pad);

        // Parking Lot & Driveway (Asphalt)
        const parkGeo = new THREE.PlaneGeometry(CONFIG.building.width + 10, 18);
        const parkMat = new THREE.MeshStandardMaterial({ 
            color: 0x2a2b2e, roughness: 0.95, bumpMap: roadTex, bumpScale: 0.05 
        });
        const park = new THREE.Mesh(parkGeo, parkMat);
        park.rotation.x = -Math.PI / 2;
        park.position.set(cx, -0.01, cz + 24);
        park.receiveShadow = true;
        this.groundGroup.add(park);

        // Add parked cars to the lot
        const carColors = [0x990000, 0x003399, 0xcccccc, 0x111111, 0x999900, 0xffffff];
        for (let i = 0; i < 6; i++) {
            const car = this.buildCar(carColors[i % carColors.length]);
            car.position.set(cx - 10 + i * 4, 0, cz + 24);
            car.rotation.y = Math.PI; // facing the building
            this.groundGroup.add(car);
        }

        // Add moving cars on the road
        for (let i = 0; i < 12; i++) {
            const mCar = this.buildCar(carColors[Math.floor(Math.random()*carColors.length)]);
            const roadOffset = 55; // radius of road
            const angle = (i / 12) * Math.PI * 2;
            mCar.position.set(cx + Math.cos(angle) * roadOffset, 0, cz + Math.sin(angle) * roadOffset);
            mCar.rotation.y = -angle; // facing tangent
            this.groundGroup.add(mCar);
        }

        // Background City Context
        const cityMat = new THREE.MeshStandardMaterial({ color: 0xb0b3b8, roughness: 0.7, metalness: 0.1 });
        const windowMat = new THREE.MeshStandardMaterial({ 
            color: 0xffffff, 
            roughness: 0.2, 
            metalness: 0.8, 
            map: windowTex,
            emissive: 0xffffff,
            emissiveMap: windowTex,
            emissiveIntensity: 1.5
        });
        
        const cityGroup = new THREE.Group();
        for (let i = 0; i < 40; i++) {
            const w = 12 + Math.random() * 20;
            const d = 12 + Math.random() * 20;
            const h = 20 + Math.random() * 60;
            
            const bGroup = new THREE.Group();
            
            // Main block
            const b = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), cityMat);
            b.position.y = h/2;
            b.castShadow = true;
            b.receiveShadow = true;
            bGroup.add(b);

            // Windows (glass with texture)
            windowMat.map.repeat.set(w / 10, h / 10);
            const winGeo = new THREE.BoxGeometry(w + 0.2, h * 0.8, d + 0.2);
            const win = new THREE.Mesh(winGeo, windowMat);
            win.position.y = h/2;
            bGroup.add(win);
            
            // Roof AC unit
            const acGeo = new THREE.BoxGeometry(w*0.3, 1.5, d*0.3);
            const ac = new THREE.Mesh(acGeo, new THREE.MeshStandardMaterial({color: 0x555555}));
            ac.position.set(0, h + 0.75, 0);
            bGroup.add(ac);

            const angle = Math.random() * Math.PI * 2;
            const dist = 85 + Math.random() * 80;
            bGroup.position.set(cx + Math.cos(angle) * dist, 0, cz + Math.sin(angle) * dist);
            cityGroup.add(bGroup);
        }
        
        // Add Nature (Lush Organic Trees)
        const trunkMat = new THREE.MeshStandardMaterial({ color: 0x4a3422, roughness: 0.9, bumpMap: groundNoise, bumpScale: 0.5 });
        const leafMat = new THREE.MeshStandardMaterial({ color: 0x3d5c1e, roughness: 0.9, flatShading: true });
        
        // Create organic deformed tree geometry
        const leavesGeo = new THREE.IcosahedronGeometry(2.0, 3);
        const posAttribute = leavesGeo.attributes.position;
        for (let j = 0; j < posAttribute.count; j++) {
            const x = posAttribute.getX(j);
            const y = posAttribute.getY(j);
            const z = posAttribute.getZ(j);
            const noise = (Math.random() - 0.5) * 0.7; // organic bumpiness
            posAttribute.setXYZ(j, x + x*noise, y + y*noise, z + z*noise);
        }
        leavesGeo.computeVertexNormals();

        for (let i = 0; i < 150; i++) {
            const treeGroup = new THREE.Group();
            const trunk = new THREE.Mesh(new THREE.CylinderGeometry(0.2, 0.4, 1.5), trunkMat);
            trunk.position.y = 0.75;
            trunk.castShadow = true;
            treeGroup.add(trunk);
            
            const leaves = new THREE.Mesh(leavesGeo, leafMat);
            leaves.position.y = 2.5;
            leaves.castShadow = true;
            treeGroup.add(leaves);
            
            const angle = Math.random() * Math.PI * 2;
            let dist;
            if (i < 50) {
                // Inner plaza ring
                dist = 22 + Math.random() * 15; // 22 to 37 (inside road at 45)
            } else {
                // Outer forest
                dist = 65 + Math.random() * 40; // 65 to 105 (outside road at 55)
            }
            
            // Avoid building footprint (dist > 22 handles this) and intersections
            if (Math.abs(Math.cos(angle)*dist) > 18 || Math.abs(Math.sin(angle)*dist) > 18) {
                treeGroup.position.set(cx + Math.cos(angle) * dist, 0, cz + Math.sin(angle) * dist);
                
                // Add some size variance
                const scale = 0.6 + Math.random() * 0.8;
                treeGroup.scale.set(scale, scale, scale);
                cityGroup.add(treeGroup);
            }
        }
        
        this.groundGroup.add(cityGroup);
        this.scene.add(this.groundGroup);
    }

    // ─── BUILD ALL FLOORS ───

    buildBuilding() {
        const bw = CONFIG.building.width;
        const bd = CONFIG.building.depth;
        const fh = CONFIG.building.floorHeight;
        const st = CONFIG.building.slabThickness;

        for (let fi = 0; fi < CONFIG.building.floors; fi++) {
            const floorGroup = new THREE.Group();
            floorGroup.name = `floor_${fi}`;
            floorGroup.userData = { floorIndex: fi, originalY: fi * fh };
            floorGroup.position.y = fi * fh;

            // Concrete slab
            const slabGeo = new THREE.BoxGeometry(bw, st, bd);
            const slabMat = new THREE.MeshStandardMaterial({
                color: CONFIG.colors.concrete,
                roughness: 0.7,
                metalness: 0.05,
            });
            const slab = new THREE.Mesh(slabGeo, slabMat);
            slab.position.set(bw / 2, st / 2, bd / 2);
            slab.castShadow = true;
            slab.receiveShadow = true;
            floorGroup.add(slab);

            // Build rooms for this floor
            const layout = FLOOR_LAYOUTS[fi];
            layout.rooms.forEach(roomDef => {
                this.buildRoom(floorGroup, fi, roomDef, st);
            });

            this.floorGroups.push(floorGroup);
            this.scene.add(floorGroup);
        }
    }

    // ─── BUILD A SINGLE ROOM ───

    buildRoom(floorGroup, floorIndex, roomDef, slabTop) {
        const roomGroup = new THREE.Group();
        roomGroup.name = `room_${roomDef.id}`;
        const y0 = slabTop;
        const wallH = CONFIG.building.floorHeight - CONFIG.building.slabThickness;
        const wt = CONFIG.building.wallThickness;

        // Floor carpet/tile

        const floorType = roomDef.type || 'office';
        let carpetColor = CONFIG.colors.carpet[floorType] || CONFIG.colors.carpet.office;
        
        const isLiveRoom = roomDef.id === 'office_a';
        let emissiveColor = 0x000000;
        let emissiveIntensity = 0;

        if (isLiveRoom) {
            carpetColor = 0x06b6d4; // Cyan 500
            emissiveColor = 0x06b6d4;
            emissiveIntensity = 0.5;
        }

        const floorGeo = new THREE.PlaneGeometry(roomDef.w - wt * 2, roomDef.d - wt * 2);
        const floorMat = new THREE.MeshStandardMaterial({
            color: carpetColor,
            emissive: emissiveColor,
            emissiveIntensity: emissiveIntensity,
            roughness: 0.8,
            metalness: 0.02,
        });

        const floorMesh = new THREE.Mesh(floorGeo, floorMat);
        floorMesh.rotation.x = -Math.PI / 2;
        floorMesh.position.set(roomDef.x + roomDef.w / 2, y0 + 0.02, roomDef.z + roomDef.d / 2);
        floorMesh.receiveShadow = true;
        floorMesh.userData = {
            isRoom: true,
            roomId: roomDef.id,
            roomName: roomDef.name,
            roomType: roomDef.type,
            floorIndex: floorIndex,
            maxOcc: roomDef.maxOcc,
            sensorId: roomDef.sensorId,
        };
        this.roomMeshes.push(floorMesh);
        roomGroup.add(floorMesh);

        // Interior walls - GLASS
        const wallMat = new THREE.MeshPhysicalMaterial({
            color: CONFIG.colors.wallInterior,
            roughness: 0.1,
            metalness: 0.1,
            transparent: true,
            transmission: 0.8,
            opacity: 0.4,
            side: THREE.DoubleSide,
        });

        // 4 walls (simple box geometry for each)
        const walls = [
            // Back wall (along X at z=roomDef.z)
            { w: roomDef.w, h: wallH, d: wt, x: roomDef.x + roomDef.w / 2, z: roomDef.z + wt / 2 },
            // Front wall
            { w: roomDef.w, h: wallH, d: wt, x: roomDef.x + roomDef.w / 2, z: roomDef.z + roomDef.d - wt / 2 },
            // Left wall
            { w: wt, h: wallH, d: roomDef.d, x: roomDef.x + wt / 2, z: roomDef.z + roomDef.d / 2 },
            // Right wall
            { w: wt, h: wallH, d: roomDef.d, x: roomDef.x + roomDef.w - wt / 2, z: roomDef.z + roomDef.d / 2 },
        ];

        walls.forEach((w, i) => {
            const geo = new THREE.BoxGeometry(w.w, w.h, w.d);
            const mesh = new THREE.Mesh(geo, wallMat.clone());
            mesh.position.set(w.x, y0 + wallH / 2, w.z);
            mesh.castShadow = true;
            mesh.receiveShadow = true;
            roomGroup.add(mesh);
        });

        // Ceiling light fixture
        const lightGeo = new THREE.BoxGeometry(Math.min(roomDef.w * 0.4, 3), 0.08, Math.min(roomDef.d * 0.3, 2));
        const lightOffMat = new THREE.MeshStandardMaterial({
            color: 0xcccccc,
            roughness: 0.3,
            emissive: 0x000000,
            emissiveIntensity: 0,
        });
        const lightMesh = new THREE.Mesh(lightGeo, lightOffMat);
        lightMesh.position.set(
            roomDef.x + roomDef.w / 2,
            y0 + wallH - 0.1,
            roomDef.z + roomDef.d / 2
        );
        roomGroup.add(lightMesh);
        this.lightMeshes.set(`${floorIndex}_${roomDef.id}`, lightMesh);

        // Add furniture based on room type
        this.addFurniture(roomGroup, roomDef, y0);

        // Add occupant indicators
        this.addOccupantIndicators(roomGroup, floorIndex, roomDef, y0);

        floorGroup.add(roomGroup);

        // --- HYBRID DIGITAL TWIN BADGES ---
        const badgeCanvas = document.createElement('canvas');
        badgeCanvas.width = 256;
        badgeCanvas.height = 64;
        const bCtx = badgeCanvas.getContext('2d');
        
        drawRoomBadge(bCtx, isLiveRoom ? 'offline' : 'sim');

        const badgeTex = new THREE.CanvasTexture(badgeCanvas);
        if (isLiveRoom) this.liveBadge = { ctx: bCtx, texture: badgeTex, kind: 'offline' };
        const badgeMat = new THREE.SpriteMaterial({ map: badgeTex, transparent: true });
        const badgeSprite = new THREE.Sprite(badgeMat);
        badgeSprite.scale.set(4, 1, 1);
        badgeSprite.position.set(roomDef.x + roomDef.w / 2, y0 + 3.5, roomDef.z + roomDef.d / 2);
        
        roomGroup.add(badgeSprite);


        // Store room data
        this.roomData.set(`${floorIndex}_${roomDef.id}`, {
            def: roomDef,
            floorIndex,
            group: roomGroup,
            source: isLiveRoom ? 'hardware' : 'simulated',
            hardware: null,
            hasData: false,
            sensors: { temperature: null, humidity: null, light: null, co2: null },
            co2Source: null,
            occupancy: { truth: null, predicted: null, probability: null, presence: null },
            control: { light: null, hvac: null, mode: null },
            power: { estimated: null, measured: null },
        });
    }

    // ─── FURNITURE ───

    addFurniture(group, roomDef, y0) {
        const type = roomDef.type;
        const cx = roomDef.x + roomDef.w / 2;
        const cz = roomDef.z + roomDef.d / 2;

        const deskMat = new THREE.MeshStandardMaterial({ color: CONFIG.colors.furniture.desk, roughness: 0.5 });
        const chairMat = new THREE.MeshStandardMaterial({ color: CONFIG.colors.furniture.chair, roughness: 0.6 });
        const tableMat = new THREE.MeshStandardMaterial({ color: CONFIG.colors.furniture.table, roughness: 0.4 });

        if (type === 'office' || type === 'executive') {
            // Desks in rows
            const numDesks = Math.min(Math.floor(roomDef.w / 3), 4);
            const monitorMat = new THREE.MeshStandardMaterial({ 
                color: 0x111111, roughness: 0.2, 
                emissive: 0x4488ff, emissiveIntensity: 0.5 
            });
            const standMat = new THREE.MeshStandardMaterial({color: 0x222222, roughness: 0.8});

            for (let i = 0; i < numDesks; i++) {
                const dx = roomDef.x + 1.5 + i * (roomDef.w - 3) / Math.max(numDesks - 1, 1);
                
                // Detailed Desk
                const deskGroup = new THREE.Group();
                const deskTop = new THREE.Mesh(new THREE.BoxGeometry(1.4, 0.05, 0.7), deskMat);
                deskTop.position.set(0, 0.74, 0);
                const deskLeg1 = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.74, 0.6), deskMat);
                deskLeg1.position.set(-0.65, 0.37, 0);
                const deskLeg2 = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.74, 0.6), deskMat);
                deskLeg2.position.set(0.65, 0.37, 0);
                deskGroup.add(deskTop, deskLeg1, deskLeg2);
                deskGroup.position.set(dx, y0, cz - 1);
                group.add(deskGroup);

                // Emissive Monitor
                const monitorGroup = new THREE.Group();
                const screen = new THREE.Mesh(new THREE.BoxGeometry(0.6, 0.35, 0.02), monitorMat);
                screen.position.set(0, 0.2, 0);
                const stand = new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.05, 0.15), standMat);
                stand.position.set(0, 0.075, -0.02);
                monitorGroup.add(screen, stand);
                monitorGroup.position.set(dx, y0 + 0.74, cz - 1.1);
                group.add(monitorGroup);

                // Office Chair
                const chairGroup = new THREE.Group();
                const seat = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.05, 0.5), chairMat);
                seat.position.set(0, 0.45, 0);
                const back = new THREE.Mesh(new THREE.BoxGeometry(0.4, 0.5, 0.05), chairMat);
                back.position.set(0, 0.7, -0.2);
                const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.04, 0.45), standMat);
                leg.position.set(0, 0.22, 0);
                chairGroup.add(seat, back, leg);
                chairGroup.position.set(dx, y0, cz - 1.6);
                group.add(chairGroup);
            }
        } else if (type === 'meeting') {
            // Detailed Conference table
            const tw = Math.min(roomDef.w * 0.5, 4);
            const td = Math.min(roomDef.d * 0.4, 3);
            const tableGroup = new THREE.Group();
            const top = new THREE.Mesh(new THREE.BoxGeometry(tw, 0.05, td), tableMat);
            top.position.set(0, 0.74, 0);
            const tleg = new THREE.Mesh(new THREE.BoxGeometry(tw * 0.6, 0.74, td * 0.4), new THREE.MeshStandardMaterial({color: 0x222222}));
            tleg.position.set(0, 0.37, 0);
            tableGroup.add(top, tleg);
            tableGroup.position.set(cx, y0, cz);
            group.add(tableGroup);

            // Glowing Presentation Screen
            const screenMat = new THREE.MeshStandardMaterial({
                color: 0x111111, emissive: 0x4488ff, emissiveIntensity: 0.8
            });
            const presScreen = new THREE.Mesh(new THREE.BoxGeometry(tw * 0.8, 1.5, 0.05), screenMat);
            presScreen.position.set(cx, y0 + 1.6, roomDef.z + 0.1);
            group.add(presScreen);

            // Detailed Chairs around table
            const standMat = new THREE.MeshStandardMaterial({color: 0x222222, roughness: 0.8});
            for (let i = 0; i < 3; i++) {
                const offset = (i - 1) * (tw * 0.35);
                
                // Top chair
                const c1 = new THREE.Group();
                const seat1 = new THREE.Mesh(new THREE.BoxGeometry(0.45, 0.05, 0.45), chairMat);
                seat1.position.set(0, 0.45, 0);
                const back1 = new THREE.Mesh(new THREE.BoxGeometry(0.4, 0.5, 0.05), chairMat);
                back1.position.set(0, 0.7, -0.2);
                const leg1 = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.04, 0.45), standMat);
                leg1.position.set(0, 0.22, 0);
                c1.add(seat1, back1, leg1);
                c1.position.set(cx + offset, y0, cz - td / 2 - 0.4);
                group.add(c1);

                // Bottom chair
                const c2 = new THREE.Group();
                const seat2 = new THREE.Mesh(new THREE.BoxGeometry(0.45, 0.05, 0.45), chairMat);
                seat2.position.set(0, 0.45, 0);
                const back2 = new THREE.Mesh(new THREE.BoxGeometry(0.4, 0.5, 0.05), chairMat);
                back2.position.set(0, 0.7, 0.2);
                const leg2 = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.04, 0.45), standMat);
                leg2.position.set(0, 0.22, 0);
                c2.add(seat2, back2, leg2);
                c2.position.set(cx + offset, y0, cz + td / 2 + 0.4);
                group.add(c2);
            }
        } else if (type === 'kitchen') {
            // Counter
            const counter = new THREE.Mesh(
                new THREE.BoxGeometry(Math.min(roomDef.w * 0.6, 3), 0.9, 0.6),
                new THREE.MeshStandardMaterial({ color: 0x909090, roughness: 0.3, metalness: 0.3 })
            );
            counter.position.set(cx, y0 + 0.45, roomDef.z + 0.8);
            counter.castShadow = true;
            group.add(counter);

            // Small table
            const smallTable = new THREE.Mesh(new THREE.BoxGeometry(1, 0.74, 1), tableMat);
            smallTable.position.set(cx, y0 + 0.37, cz + 1);
            group.add(smallTable);
        } else if (type === 'lobby') {
            // Seating arrangement
            const sofaMat = new THREE.MeshStandardMaterial({ color: CONFIG.colors.furniture.sofa, roughness: 0.7 });
            const sofa = new THREE.Mesh(new THREE.BoxGeometry(2.5, 0.6, 0.8), sofaMat);
            sofa.position.set(cx - 2, y0 + 0.3, cz);
            group.add(sofa);
            const sofa2 = new THREE.Mesh(new THREE.BoxGeometry(2.5, 0.6, 0.8), sofaMat);
            sofa2.position.set(cx + 2, y0 + 0.3, cz);
            group.add(sofa2);
        } else if (type === 'server') {
            // Server racks
            const rackMat = new THREE.MeshStandardMaterial({ color: 0x2a2a2a, roughness: 0.4, metalness: 0.5 });
            const numRacks = Math.min(Math.floor(roomDef.w / 2), 4);
            for (let i = 0; i < numRacks; i++) {
                const rack = new THREE.Mesh(new THREE.BoxGeometry(0.6, 2.0, 0.8), rackMat);
                rack.position.set(roomDef.x + 1 + i * 1.5, y0 + 1.0, cz);
                rack.castShadow = true;
                group.add(rack);
            }
        } else if (type === 'gym') {
            const tmMat = new THREE.MeshStandardMaterial({ color: 0x222222, roughness: 0.8 });
            const benchMat = new THREE.MeshStandardMaterial({ color: 0x882222, roughness: 0.5 });
            const matMat = new THREE.MeshStandardMaterial({ color: 0x2288aa, roughness: 0.9 });
            
            for(let i=0; i<3; i++) {
                const tm = new THREE.Mesh(new THREE.BoxGeometry(0.8, 1.2, 1.8), tmMat);
                tm.position.set(roomDef.x + 2 + i*2, y0 + 0.6, cz - 2);
                tm.castShadow = true;
                group.add(tm);
            }
            const bench = new THREE.Mesh(new THREE.BoxGeometry(0.6, 0.4, 1.5), benchMat);
            bench.position.set(cx, y0 + 0.2, cz + 1);
            group.add(bench);
            
            for(let i=0; i<3; i++) {
                const mat = new THREE.Mesh(new THREE.BoxGeometry(0.6, 0.02, 1.6), matMat);
                mat.position.set(roomDef.x + roomDef.w - 2 - i*2, y0 + 0.02, cz + 1.5);
                group.add(mat);
            }
        } else if (type === 'shop') {
            const shelfMat = new THREE.MeshStandardMaterial({ color: 0xdddddd, roughness: 0.4 });
            const box1 = new THREE.MeshStandardMaterial({ color: 0x4488cc, roughness: 0.6 });
            const box2 = new THREE.MeshStandardMaterial({ color: 0xcc4455, roughness: 0.6 });
            
            for (let i = 0; i < 2; i++) {
                const shelf = new THREE.Mesh(new THREE.BoxGeometry(roomDef.w * 0.4, 1.8, 0.6), shelfMat);
                shelf.position.set(cx, y0 + 0.9, cz - 1.5 + i*3);
                shelf.castShadow = true;
                group.add(shelf);
                
                const product1 = new THREE.Mesh(new THREE.BoxGeometry(0.4, 0.4, 0.4), box1);
                product1.position.set(cx - 1, y0 + 1.2, cz - 1.5 + i*3);
                group.add(product1);
                const product2 = new THREE.Mesh(new THREE.BoxGeometry(0.3, 0.6, 0.3), box2);
                product2.position.set(cx + 1, y0 + 0.5, cz - 1.5 + i*3);
                group.add(product2);
            }
            
            const counter = new THREE.Mesh(new THREE.BoxGeometry(2, 1, 0.8), deskMat);
            counter.position.set(roomDef.x + 2, y0 + 0.5, roomDef.z + 1.5);
            counter.castShadow = true;
            group.add(counter);
        } else if (type === 'residential') {
            const bedMat = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.9 });
            const blanketMat = new THREE.MeshStandardMaterial({ color: 0x446688, roughness: 0.9 });
            
            if (roomDef.w <= 10) { // Bedroom
                const bed = new THREE.Mesh(new THREE.BoxGeometry(2, 0.4, 2.2), deskMat);
                bed.position.set(cx, y0 + 0.2, cz);
                bed.castShadow = true;
                group.add(bed);
                const blanket = new THREE.Mesh(new THREE.BoxGeometry(2.05, 0.15, 1.2), blanketMat);
                blanket.position.set(cx, y0 + 0.45, cz + 0.5);
                group.add(blanket);
                const pillow = new THREE.Mesh(new THREE.BoxGeometry(1.6, 0.1, 0.4), bedMat);
                pillow.position.set(cx, y0 + 0.45, cz - 0.7);
                group.add(pillow);
            } else { // Living room
                const sofaMat = new THREE.MeshStandardMaterial({ color: 0x445566, roughness: 0.8 });
                const sofa = new THREE.Mesh(new THREE.BoxGeometry(2.5, 0.8, 1), sofaMat);
                sofa.position.set(cx, y0 + 0.4, cz + 2);
                sofa.castShadow = true;
                group.add(sofa);
                
                const tvMat = new THREE.MeshStandardMaterial({ color: 0x111111, roughness: 0.2 });
                const tv = new THREE.Mesh(new THREE.BoxGeometry(2.5, 1.2, 0.1), tvMat);
                tv.position.set(cx, y0 + 1, cz - 2);
                group.add(tv);
                
                const rugMat = new THREE.MeshStandardMaterial({ color: 0x883333, roughness: 0.9 });
                const rug = new THREE.Mesh(new THREE.BoxGeometry(3, 0.02, 3), rugMat);
                rug.position.set(cx, y0 + 0.02, cz);
                group.add(rug);
            }
        } else if (type === 'bathroom') {
            const porcelain = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.1 });
            const toilet = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.5, 0.7), porcelain);
            toilet.position.set(cx, y0 + 0.25, roomDef.z + 0.5);
            toilet.castShadow = true;
            group.add(toilet);
            const sink = new THREE.Mesh(new THREE.BoxGeometry(0.8, 0.8, 0.5), porcelain);
            sink.position.set(roomDef.x + 0.5, y0 + 0.4, cz);
            group.add(sink);
        }
    }

    // ─── PROCEDURAL HUMAN ───
    buildHuman() {
        const personGroup = new THREE.Group();
        
        const shirtColors = [0x3366cc, 0xcc3333, 0x33cc66, 0xcccccc, 0xeeaa22, 0x444444];
        const shirtColor = shirtColors[Math.floor(Math.random() * shirtColors.length)];
        const skinMat = new THREE.MeshStandardMaterial({ color: 0xffccaa, roughness: 0.6 });
        const shirtMat = new THREE.MeshStandardMaterial({ color: shirtColor, roughness: 0.8 });
        const pantsMat = new THREE.MeshStandardMaterial({ color: 0x112244, roughness: 0.9 });
        
        const torso = new THREE.Mesh(new THREE.BoxGeometry(0.4, 0.6, 0.2), shirtMat);
        torso.position.y = 1.0;
        torso.castShadow = true;
        personGroup.add(torso);
        
        const head = new THREE.Mesh(new THREE.BoxGeometry(0.25, 0.3, 0.25), skinMat);
        head.position.y = 1.45;
        head.castShadow = true;
        personGroup.add(head);
        
        const armGeo = new THREE.BoxGeometry(0.12, 0.5, 0.12);
        const leftArm = new THREE.Mesh(armGeo, skinMat);
        leftArm.position.set(-0.28, 1.0, 0);
        leftArm.castShadow = true;
        const rightArm = new THREE.Mesh(armGeo, skinMat);
        rightArm.position.set(0.28, 1.0, 0);
        rightArm.castShadow = true;
        
        personGroup.add(leftArm, rightArm);
        personGroup.userData.limbs = { leftArm, rightArm };
        
        const legGeo = new THREE.BoxGeometry(0.16, 0.7, 0.16);
        const leftLeg = new THREE.Mesh(legGeo, pantsMat);
        leftLeg.position.set(-0.1, 0.35, 0);
        leftLeg.castShadow = true;
        const rightLeg = new THREE.Mesh(legGeo, pantsMat);
        rightLeg.position.set(0.1, 0.35, 0);
        rightLeg.castShadow = true;
        
        personGroup.add(leftLeg, rightLeg);
        personGroup.userData.limbs.leftLeg = leftLeg;
        personGroup.userData.limbs.rightLeg = rightLeg;
        
        return personGroup;
    }

    // ─── OCCUPANT INDICATORS ───

    addOccupantIndicators(group, floorIndex, roomDef, y0) {
        const indicators = [];
        const maxVisible = Math.min(roomDef.maxOcc, 6);

        for (let i = 0; i < maxVisible; i++) {
            const personGroup = this.buildHuman();
            
            // Randomize slightly smaller/larger
            const scale = 0.85 + Math.random() * 0.2;
            personGroup.scale.set(scale, scale, scale);

            const angle = (i / maxVisible) * Math.PI * 1.5 + 0.3;
            const radius = Math.min(roomDef.w, roomDef.d) * 0.25;
            personGroup.position.set(
                roomDef.x + roomDef.w / 2 + Math.cos(angle) * radius,
                y0,
                roomDef.z + roomDef.d / 2 + Math.sin(angle) * radius
            );
            personGroup.rotation.y = Math.random() * Math.PI * 2;
            personGroup.userData.baseY = y0; 
            personGroup.userData.animOffset = Math.random() * 100;
            personGroup.visible = false;
            
            group.add(personGroup);
            indicators.push(personGroup);
        }

        this.occupantMeshes.set(`${floorIndex}_${roomDef.id}`, indicators);
    }

    // ─── EXTERIOR SHELL ───

    buildExterior() {
        this.exteriorGroup = new THREE.Group();
        const bw = CONFIG.building.width;
        const bd = CONFIG.building.depth;
        const totalH = CONFIG.building.floors * CONFIG.building.floorHeight;
        const fh = CONFIG.building.floorHeight;

        // Glass material
        const glassMat = new THREE.MeshPhysicalMaterial({
            color: CONFIG.colors.glass,
            transparent: true,
            opacity: 0.6,
            transmission: 0.4,
            roughness: 0.2,
            metalness: 0.5,
            ior: 1.5,
            thickness: 0.1,
            side: THREE.DoubleSide,
            envMapIntensity: 1.0,
            depthWrite: false, // Fix transparency ghosting
        });

        // Concrete frame material
        const frameMat = new THREE.MeshStandardMaterial({
            color: CONFIG.colors.concreteFrame,
            roughness: 0.6,
            metalness: 0.1,
        });

        // Build glass curtain walls per floor for individual control
        for (let fi = 0; fi < CONFIG.building.floors; fi++) {
            const floorY = fi * fh;
            const wallH = fh - CONFIG.building.slabThickness;
            const slabTop = CONFIG.building.slabThickness;

            // Front glass wall (Z = 0 face)
            this.addGlassPanel(this.floorGroups[fi], bw, wallH, bw / 2, slabTop + wallH / 2, -0.05, glassMat, 0);
            // Back glass wall
            this.addGlassPanel(this.floorGroups[fi], bw, wallH, bw / 2, slabTop + wallH / 2, bd + 0.05, glassMat, 0);
            // Left glass wall
            this.addGlassPanel(this.floorGroups[fi], bd, wallH, -0.05, slabTop + wallH / 2, bd / 2, glassMat, Math.PI / 2);
            // Right glass wall
            this.addGlassPanel(this.floorGroups[fi], bd, wallH, bw + 0.05, slabTop + wallH / 2, bd / 2, glassMat, Math.PI / 2);

            // Horizontal frame beams at each floor level
            const beamGeo = new THREE.BoxGeometry(bw + 0.4, 0.12, 0.15);
            const beamFront = new THREE.Mesh(beamGeo, frameMat);
            beamFront.position.set(bw / 2, slabTop, -0.1);
            beamFront.castShadow = true;
            this.floorGroups[fi].add(beamFront);

            const beamBack = new THREE.Mesh(beamGeo.clone(), frameMat);
            beamBack.position.set(bw / 2, slabTop, bd + 0.1);
            this.floorGroups[fi].add(beamBack);

            // Side beams
            const sideBeamGeo = new THREE.BoxGeometry(0.15, 0.12, bd + 0.4);
            const beamLeft = new THREE.Mesh(sideBeamGeo, frameMat);
            beamLeft.position.set(-0.1, slabTop, bd / 2);
            this.floorGroups[fi].add(beamLeft);

            const beamRight = new THREE.Mesh(sideBeamGeo.clone(), frameMat);
            beamRight.position.set(bw + 0.1, slabTop, bd / 2);
            this.floorGroups[fi].add(beamRight);

            // Vertical frame columns at corners and intervals
            const columnGeo = new THREE.BoxGeometry(0.25, wallH, 0.25);
            const colPositions = [
                [0, slabTop + wallH / 2, 0],
                [bw, slabTop + wallH / 2, 0],
                [0, slabTop + wallH / 2, bd],
                [bw, slabTop + wallH / 2, bd],
                [bw / 2, slabTop + wallH / 2, 0],
                [bw / 2, slabTop + wallH / 2, bd],
                [0, slabTop + wallH / 2, bd / 2],
                [bw, slabTop + wallH / 2, bd / 2],
            ];

            colPositions.forEach(pos => {
                const col = new THREE.Mesh(columnGeo, frameMat);
                col.position.set(...pos);
                col.castShadow = true;
                this.floorGroups[fi].add(col);
            });

            // Window glow planes (emissive, inside glass)
            this.addWindowGlows(this.floorGroups[fi], fi, bw, bd, wallH, slabTop);
        }

        this.scene.add(this.exteriorGroup);
    }

    addGlassPanel(parent, width, height, x, y, z, material, rotY) {
        const geo = new THREE.PlaneGeometry(width, height);
        const mesh = new THREE.Mesh(geo, material.clone());
        mesh.position.set(x, y, z);
        if (rotY) mesh.rotation.y = rotY;
        mesh.userData.isExteriorGlass = true;
        mesh.userData.originalOpacity = material.opacity;
        parent.add(mesh);
        return mesh;
    }

    addWindowGlows(floorGroup, floorIndex, bw, bd, wallH, slabTop) {
        // Create emissive planes behind glass to simulate lit windows
        const glowMat = new THREE.MeshBasicMaterial({
            color: 0xffeedd,
            transparent: true,
            opacity: 0,
            side: THREE.DoubleSide,
        });

        const numWindows = 6;
        const windowW = (bw - 2) / numWindows;
        for (let i = 0; i < numWindows; i++) {
            const geo = new THREE.PlaneGeometry(windowW * 0.7, wallH * 0.6);
            const glow = new THREE.Mesh(geo, glowMat.clone());
            glow.position.set(
                1 + i * windowW + windowW / 2,
                slabTop + wallH * 0.5,
                -0.02
            );
            glow.userData = { floorIndex, windowIndex: i };
            floorGroup.add(glow);
            this.windowGlows.push(glow);
        }
    }

    // ─── ROOF ───

    buildRoof() {
        this.roofGroup = new THREE.Group();
        const bw = CONFIG.building.width;
        const bd = CONFIG.building.depth;
        const totalH = CONFIG.building.floors * CONFIG.building.floorHeight;

        // Roof slab
        const roofGeo = new THREE.BoxGeometry(bw + 0.5, 0.3, bd + 0.5);
        const roofMat = new THREE.MeshStandardMaterial({ color: 0x606060, roughness: 0.8 });
        const roof = new THREE.Mesh(roofGeo, roofMat);
        roof.position.set(bw / 2, totalH + 0.15, bd / 2);
        roof.castShadow = true;
        roof.receiveShadow = true;
        this.roofGroup.add(roof);

        // Rooftop HVAC units
        const hvacMat = new THREE.MeshStandardMaterial({ color: 0x808080, roughness: 0.5, metalness: 0.3 });
        const hvacPositions = [
            [bw * 0.25, totalH + 0.8, bd * 0.3],
            [bw * 0.75, totalH + 0.8, bd * 0.3],
            [bw * 0.5, totalH + 0.8, bd * 0.7],
        ];
        hvacPositions.forEach(pos => {
            const hvac = new THREE.Mesh(new THREE.BoxGeometry(2.5, 1.2, 1.8), hvacMat);
            hvac.position.set(...pos);
            hvac.castShadow = true;
            this.roofGroup.add(hvac);

            // Fan on top
            const fan = new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.5, 0.3, 16), hvacMat);
            fan.position.set(pos[0], pos[1] + 0.75, pos[2]);
            this.roofGroup.add(fan);
        });

        // Roof parapet (low wall around edge)
        const parapetMat = new THREE.MeshStandardMaterial({ color: 0x707070, roughness: 0.7 });
        const parapetH = 0.8;
        const parapetT = 0.15;

        const parapets = [
            new THREE.BoxGeometry(bw + 0.5, parapetH, parapetT),
            new THREE.BoxGeometry(bw + 0.5, parapetH, parapetT),
            new THREE.BoxGeometry(parapetT, parapetH, bd + 0.5),
            new THREE.BoxGeometry(parapetT, parapetH, bd + 0.5),
        ];
        const parapetPositions = [
            [bw / 2, totalH + 0.3 + parapetH / 2, -0.15],
            [bw / 2, totalH + 0.3 + parapetH / 2, bd + 0.15],
            [-0.15, totalH + 0.3 + parapetH / 2, bd / 2],
            [bw + 0.15, totalH + 0.3 + parapetH / 2, bd / 2],
        ];
        parapets.forEach((geo, i) => {
            const mesh = new THREE.Mesh(geo, parapetMat);
            mesh.position.set(...parapetPositions[i]);
            this.roofGroup.add(mesh);
        });

        this.scene.add(this.roofGroup);
    }

    // ─── VIEW MODE TRANSITIONS ───

    setViewMode(mode) {
        if (this.animating || mode === this.viewMode) return;
        this.viewMode = mode;
        this.animating = true;

        // Update UI buttons
        document.querySelectorAll('.ctrl-btn').forEach(b => b.classList.remove('active'));
        document.getElementById(`btn-${mode === 'solid' ? 'solid' : mode === 'explode' ? 'explode' : 'cutaway'}`).classList.add('active');

        const duration = CONFIG.explode.duration;
        const startTime = performance.now();

        const startPositions = this.floorGroups.map(g => g.position.y);
        const startOpacities = this.floorGroups.map(() => 1);

        // Calculate target positions
        const fh = CONFIG.building.floorHeight;
        const gap = CONFIG.explode.gap;

        const targetPositions = this.floorGroups.map((g, i) => {
            if (mode === 'solid') return i * fh;
            if (mode === 'explode') return i * (fh + gap);
            // Cutaway: same as solid but we'll hide part of the building
            return i * fh;
        });

        const animateTransition = (now) => {
            const elapsed = now - startTime;
            const t = Math.min(elapsed / duration, 1);
            const ease = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2; // easeInOutQuad

            this.floorGroups.forEach((group, i) => {
                group.position.y = startPositions[i] + (targetPositions[i] - startPositions[i]) * ease;
            });

            // Roof follows top floor
            if (this.roofGroup) {
                const topFloorY = this.floorGroups[this.floorGroups.length - 1].position.y;
                this.roofGroup.position.y = topFloorY + fh - (CONFIG.building.floors - 1) * fh;
            }

            // Cutaway: clip one quarter of building
            if (mode === 'cutaway') {
                this.applyCutaway(ease);
            } else {
                this.removeCutaway(ease);
            }

            if (t < 1) {
                requestAnimationFrame(animateTransition);
            } else {
                this.animating = false;
            }
        };

        requestAnimationFrame(animateTransition);
    }

    applyCutaway(ease) {
        const bw = CONFIG.building.width;
        const bd = CONFIG.building.depth;
        
        this.floorGroups.forEach(group => {
            group.traverse(child => {
                if (!child.isMesh || !child.material) return;
                
                if (child.userData.isExteriorGlass) {
                    const isFront = Math.abs(child.position.z - 0) < 1;
                    const isRight = Math.abs(child.position.x - bw) < 1;
                    if (isFront || isRight) {
                        child.material.opacity = child.userData.originalOpacity * (1 - ease);
                        child.visible = child.material.opacity > 0.05;
                    }
                } else if (!child.userData.isRoom) {
                    const worldPos = new THREE.Vector3();
                    child.getWorldPosition(worldPos);
                    const isFrontRightCorner = worldPos.x > bw * 0.4 && worldPos.z < bd * 0.6;
                    if (isFrontRightCorner) {
                        if (!child.userData.originalOpacityInfo) {
                            child.userData.originalOpacityInfo = {
                                opacity: child.material.opacity !== undefined ? child.material.opacity : 1,
                                transparent: child.material.transparent || false
                            };
                            child.material = child.material.clone ? child.material.clone() : child.material;
                        }
                        child.material.transparent = true;
                        child.material.opacity = Math.max(0.05, child.userData.originalOpacityInfo.opacity * (1 - ease));
                        child.material.needsUpdate = true;
                    }
                }
            });
        });
    }

    removeCutaway(ease) {
        const bw = CONFIG.building.width;
        this.floorGroups.forEach(group => {
            group.traverse(child => {
                if (!child.isMesh || !child.material) return;
                
                if (child.userData.isExteriorGlass) {
                    const isFront = Math.abs(child.position.z - 0) < 1;
                    const isRight = Math.abs(child.position.x - bw) < 1;
                    if (isFront || isRight) {
                        child.material.opacity = child.userData.originalOpacity * ease;
                        child.visible = true;
                    }
                } else if (child.userData.originalOpacityInfo) {
                    child.material.opacity = Math.max(0.05, child.userData.originalOpacityInfo.opacity * ease);
                    if (ease >= 0.99) {
                        child.material.opacity = child.userData.originalOpacityInfo.opacity;
                        child.material.transparent = child.userData.originalOpacityInfo.transparent;
                    }
                }
            });
        });
    }

    selectFloor(index) {
        this.selectedFloor = index;

        // Update UI
        document.querySelectorAll('.floor-btn').forEach(btn => {
            btn.classList.toggle('active', parseInt(btn.dataset.floor) === index);
        });

        // Animate camera to focus on selected floor
        const fh = CONFIG.building.floorHeight;
        const targetY = this.floorGroups[index].position.y + fh / 2;
        const bw = CONFIG.building.width;
        const bd = CONFIG.building.depth;

        this.animateCamera(
            new THREE.Vector3(bw / 2 + 25, targetY + 12, bd / 2 + 25),
            new THREE.Vector3(bw / 2, targetY, bd / 2),
            800
        );
    }

    animateCamera(targetPos, targetLookAt, duration = 800) {
        const startPos = this.camera.position.clone();
        const startTarget = this.controls.target.clone();
        const startTime = performance.now();

        const animStep = (now) => {
            const t = Math.min((now - startTime) / duration, 1);
            const ease = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;

            this.camera.position.lerpVectors(startPos, targetPos, ease);
            this.controls.target.lerpVectors(startTarget, targetLookAt, ease);
            this.controls.update();

            if (t < 1) requestAnimationFrame(animStep);
        };
        requestAnimationFrame(animStep);
    }

    highlightRoom(room) {
        const roomGroup = this.roomData.get(`${room.floorIndex}_${room.roomId}`).group;
        const worldPos = new THREE.Vector3();
        roomGroup.children[0].getWorldPosition(worldPos); 
        
        const targetPos = worldPos.clone();
        const camPos = targetPos.clone().add(new THREE.Vector3(15, 15, 15));
        
        this.animateCamera(camPos, targetPos, 1000);

        this.floorGroups.forEach((floor, fi) => {
            floor.traverse(child => {
                if (child.isMesh && child.material) {
                    if (!child.userData.originalOpacityInfo) {
                        child.userData.originalOpacityInfo = {
                            transparent: child.material.transparent,
                            opacity: child.material.opacity
                        };
                    }

                    let isSelectedRoom = false;
                    let parent = child;
                    while(parent) {
                        if (parent.name === `room_${room.roomId}` && fi === room.floorIndex) {
                            isSelectedRoom = true;
                            break;
                        }
                        parent = parent.parent;
                    }

                    child.material = child.material.clone ? child.material.clone() : child.material;
                    child.material.transparent = true;
                    
                    if (isSelectedRoom) {
                        child.material.opacity = child.userData.originalOpacityInfo.opacity;
                    } else {
                        child.material.opacity = 0.05; // Ghost mode
                    }
                    child.material.needsUpdate = true;
                }
            });
        });

        if (this.roofGroup) {
            this.roofGroup.traverse(child => {
                if (child.isMesh && child.material) {
                    if (!child.userData.originalOpacityInfo) {
                        child.userData.originalOpacityInfo = {
                            transparent: child.material.transparent,
                            opacity: child.material.opacity
                        };
                    }
                    child.material = child.material.clone ? child.material.clone() : child.material;
                    child.material.transparent = true;
                    child.material.opacity = 0.05;
                    child.material.needsUpdate = true;
                }
            });
        }
    }

    resetHighlight() {
        this.floorGroups.forEach(floor => {
            floor.traverse(child => {
                if (child.isMesh && child.material && child.userData.originalOpacityInfo) {
                    child.material.transparent = child.userData.originalOpacityInfo.transparent;
                    child.material.opacity = child.userData.originalOpacityInfo.opacity;
                    child.material.needsUpdate = true;
                }
            });
        });
        
        if (this.roofGroup) {
            this.roofGroup.traverse(child => {
                if (child.isMesh && child.material && child.userData.originalOpacityInfo) {
                    child.material.transparent = child.userData.originalOpacityInfo.transparent;
                    child.material.opacity = child.userData.originalOpacityInfo.opacity;
                    child.material.needsUpdate = true;
                }
            });
        }
        
        const fh = CONFIG.building.floorHeight;
        const targetY = this.floorGroups[this.selectedFloor].position.y + fh / 2;
        const bw = CONFIG.building.width;
        const bd = CONFIG.building.depth;
        
        const targetPos = new THREE.Vector3(bw / 2 + 25, targetY + 12, bd / 2 + 25);
        const targetLookAt = new THREE.Vector3(bw / 2, targetY, bd / 2);
        this.animateCamera(targetPos, targetLookAt, 1000);
    }

    // ─── TIME OF DAY LIGHTING ───

    updateTimeOfDay(hour) {
        this.timeOfDay = hour;

        // NOTE: Sun position, sky color, and window glows are now managed by EnvironmentalEngine.
        
        // Update time display
        const displayHour = Math.floor(hour);
        const displayMin = Math.floor((hour % 1) * 60);
        const ampm = displayHour >= 12 ? 'PM' : 'AM';
        const h12 = displayHour % 12 || 12;
        document.getElementById('sim-time').textContent =
            `${h12}:${displayMin.toString().padStart(2, '0')} ${ampm}`;
        document.getElementById('time-label').textContent =
            `${displayHour.toString().padStart(2, '0')}:${displayMin.toString().padStart(2, '0')}`;

        // Weather icon
        const weatherEl = document.getElementById('weather-icon');
        if (hour >= 6 && hour < 18) {
            weatherEl.textContent = hour > 7 && hour < 16 ? '☀️' : '🌅';
        } else {
            weatherEl.textContent = '🌙';
        }
    }

    // ─── CLICK / HOVER INTERACTION ───

    onMouseMove(event) {
        this.mouse.x = (event.clientX / window.innerWidth) * 2 - 1;
        this.mouse.y = -(event.clientY / window.innerHeight) * 2 + 1;

        this.raycaster.setFromCamera(this.mouse, this.camera);
        const intersects = this.raycaster.intersectObjects(this.roomMeshes);

        const tooltip = document.getElementById('tooltip');
        const canvas = this.renderer.domElement;

        if (intersects.length > 0) {
            const room = intersects[0].object.userData;
            tooltip.style.display = 'block';
            tooltip.style.left = (event.clientX + 15) + 'px';
            tooltip.style.top = (event.clientY - 10) + 'px';
            document.getElementById('tooltip-title').textContent = room.roomName;

            const key = `${room.floorIndex}_${room.roomId}`;
            const data = this.roomData.get(key);
            if (data && data.hasData) {
                const t = data.sensors.temperature;
                const occ = data.source === 'hardware'
                    ? (data.occupancy.presence === null ? 'presence —' : (data.occupancy.presence ? 'presence detected' : 'no presence'))
                    : `${data.occupancy.truth ?? '—'}/${room.maxOcc} people (simulated)`;
                document.getElementById('tooltip-info').textContent =
                    `${t === null ? '—' : t.toFixed(1) + '°C'} | ${occ}`;
            } else if (data && data.source === 'hardware') {
                document.getElementById('tooltip-info').textContent = 'Board not connected — no live data';
            } else {
                document.getElementById('tooltip-info').textContent = `Floor ${room.floorIndex + 1}`;
            }

            canvas.style.cursor = 'pointer';
        } else {
            tooltip.style.display = 'none';
            canvas.style.cursor = 'default';
        }
    }

    onMouseClick(event) {
        this.raycaster.setFromCamera(this.mouse, this.camera);
        const intersects = this.raycaster.intersectObjects(this.roomMeshes);

        if (intersects.length > 0) {
            const room = intersects[0].object.userData;
            this.showRoomPanel(room);
        }
    }

    showRoomPanel(roomUserData) {
        const key = `${roomUserData.floorIndex}_${roomUserData.roomId}`;
        const data = this.roomData.get(key);
        if (!data) return;

        this.selectedRoom = key;

        const panel = document.getElementById('room-panel');
        panel.style.display = 'block';

        document.getElementById('room-title').textContent = roomUserData.roomName;
        document.getElementById('room-floor-tag').textContent = `Floor ${roomUserData.floorIndex + 1}`;

        this.updateRoomPanel(data, roomUserData);

        this.highlightRoom(roomUserData);
    }

    updateRoomPanel(data, roomUserData) {
        const s = data.sensors;
        const fmt = (v, digits, unit) => (v === null || v === undefined) ? '—' : `${v.toFixed(digits)}${unit}`;
        const bar = (id, v, toPct) => {
            document.getElementById(id).style.width = (v === null || v === undefined) ? '0%' : `${Math.max(0, Math.min(100, toPct(v)))}%`;
        };
        document.getElementById('room-temp').textContent = fmt(s.temperature, 1, '°C');
        document.getElementById('room-humidity').textContent = fmt(s.humidity, 0, '%');
        document.getElementById('room-light').textContent = fmt(s.light, 0, ' lux');
        document.getElementById('room-co2').textContent = fmt(s.co2, 0, ' ppm');
        bar('temp-bar', s.temperature, v => ((v - 15) / 20) * 100);
        bar('humidity-bar', s.humidity, v => v);
        bar('light-bar', s.light, v => (v / 800) * 100);
        bar('co2-bar', s.co2, v => (v / 1500) * 100);

        const co2Label = document.querySelector('#room-panel .sensor-card.co2 .sensor-label');
        if (co2Label) {
            co2Label.textContent = data.co2Source === 'mq2_estimate' ? 'CO₂ (MQ-2 estimate, uncalibrated)'
                : data.co2Source === 'scd41_ndir' ? 'CO₂ (SCD41)' : 'CO₂ Level';
        }

        const sourceBadge = document.getElementById('room-source-badge');
        sourceBadge.style.display = 'inline-block';
        if (data.source === 'hardware') {
            const hw = data.hardware;
            if (hw && hw.connected && hw.real_board) {
                sourceBadge.textContent = '🟢 LIVE — ESP32 board';
                sourceBadge.style.background = '#10b981';
            } else if (hw && hw.connected) {
                sourceBadge.textContent = '🟡 TEST SENDER — not the real board';
                sourceBadge.style.background = '#d97706';
            } else {
                const seen = hw && hw.last_seen ? ` (last data ${new Date(hw.last_seen).toLocaleTimeString()})` : '';
                sourceBadge.textContent = '🔴 BOARD NOT CONNECTED' + seen;
                sourceBadge.style.background = '#dc2626';
            }
        } else {
            sourceBadge.textContent = '🔵 SIMULATED ROOM';
            sourceBadge.style.background = '#3b82f6';
        }

        // Occupancy: simulated rooms have the simulator's true count; the real room has a presence sensor
        const occ = data.occupancy;
        const occEl = document.getElementById('room-occupancy');
        const maxEl = document.getElementById('room-max-occ');
        const statusEl = document.getElementById('room-occ-status');
        const aiLine = document.getElementById('room-ai-line');
        if (data.source === 'hardware') {
            occEl.textContent = occ.presence === null ? '—' : (occ.presence ? 'Yes' : 'No');
            maxEl.textContent = ' presence sensor';
        } else {
            occEl.textContent = occ.truth === null ? '—' : String(occ.truth);
            maxEl.textContent = `/ ${roomUserData.maxOcc || data.def.maxOcc} (simulated)`;
        }
        if (occ.predicted === null) {
            statusEl.textContent = 'NO DATA';
            statusEl.className = 'occ-status empty';
        } else if (data.control.mode === 'OCCUPIED') {
            statusEl.textContent = 'OCCUPIED';
            statusEl.className = 'occ-status';
        } else if (data.control.mode === 'STANDBY') {
            statusEl.textContent = 'STANDBY';
            statusEl.className = 'occ-status standby';
        } else {
            statusEl.textContent = 'EMPTY';
            statusEl.className = 'occ-status empty';
        }
        if (aiLine) {
            aiLine.textContent = occ.probability === null ? 'AI: no prediction (no data)'
                : `AI occupancy probability ${(occ.probability * 100).toFixed(0)}% → ${occ.predicted ? 'occupied' : 'empty'}`;
        }

        // Control states (null when there is no decision)
        const lightState = document.getElementById('room-light-state');
        lightState.textContent = data.control.light ?? '—';
        lightState.className = 'control-state' + (data.control.light === 'ON' ? ' on' : '');
        document.getElementById('room-hvac-state').textContent = data.control.hvac ?? '—';
        const energyEl = document.getElementById('room-energy');
        if (data.source === 'hardware') {
            energyEl.textContent = data.power.measured === null ? 'not measured' : `${data.power.measured.toFixed(2)} W (measured)`;
        } else {
            energyEl.textContent = data.power.estimated === null ? '—' : `${(data.power.estimated / 1000).toFixed(2)} kW (estimated)`;
        }
    }

    // ─── LIVE DATA (pushed by the Next.js page over postMessage) ───

    /**
     * Apply one backend state (the edge brain's SSE payload, forwarded by the page).
     * Every value shown comes from this payload; nothing is generated here.
     */
    applyBackendState(msg) {
        const rooms = Array.isArray(msg.rooms) ? msg.rooms : [];
        this.liveData = { system: msg.system || null, hardware: msg.hardware || null };
        if (msg.system && msg.system.simulation_time) {
            SimulationClock.parseBackendTime(msg.system.simulation_time);
            this.updateTimeOfDay(SimulationClock.hour);
            const timeSlider = document.getElementById('time-slider');
            if (timeSlider) {
                timeSlider.value = SimulationClock.hour;
                document.getElementById('time-label').textContent = msg.system.simulation_time.slice(0, 5);
            }
        }

        const num = (v) => (typeof v === 'number' && isFinite(v)) ? v : null;
        let matched = 0;
        const unmatched = [];
        for (const room of rooms) {
            const key = String(room.room_id || '').replace(/^f/, '');
            const rd = this.roomData.get(key);
            if (!rd) { unmatched.push(room.room_id); continue; }
            matched++;
            const s = room.sensors || {};
            rd.source = room.source;
            rd.hardware = room.hardware || null;
            rd.hasData = !!room.ai;
            rd.sensors = { temperature: num(s.Temperature), humidity: num(s.Humidity), light: num(s.Light), co2: num(s.CO2) };
            rd.co2Source = s.CO2_source || null;
            rd.occupancy = {
                truth: num(room.ground_truth?.true_occupancy),
                predicted: room.ai ? room.ai.predicted_occupancy : null,
                probability: room.ai ? num(room.ai.occupancy_probability) : null,
                presence: room.presence ? (room.presence.fused_presence ?? null) : null,
            };
            rd.control = {
                light: room.control?.light_action ?? null,
                hvac: room.control?.hvac_action ?? null,
                mode: room.control?.control_mode ?? null,
            };
            rd.power = { estimated: num(room.energy?.estimated_power_watts), measured: num(room.energy?.measured_power_watts) };

            const visualState = VisualStateStore.get(key);
            if (VisualStateStore.processBackendUpdate(key, room, null)) {
                eventBus.emit(Events.ROOM_STATE_CHANGED, { roomId: key, backendState: room, visualState });
            }
            if (room.source === 'hardware') this.updateLiveBadge(room.hardware);
        }
        this.updateBuildingStats();
        // Tell the page how many backend rooms were found in the 3D model (a real sync check)
        if (window.parent && window.parent !== window) {
            window.parent.postMessage({
                type: 'TWIN_SYNC_REPORT', matched, received: rooms.length,
                modelRooms: this.roomData.size, unmatched, seq: msg.seq ?? null,
            }, '*');
        }
    }

    updateLiveBadge(hw) {
        if (!this.liveBadge) return;
        const kind = hw && hw.connected ? (hw.real_board ? 'live' : 'test') : 'offline';
        if (kind === this.liveBadge.kind) return;
        this.liveBadge.kind = kind;
        drawRoomBadge(this.liveBadge.ctx, kind);
        this.liveBadge.texture.needsUpdate = true;
    }

    setLinkStatus(ok, detail) {
        this.connected = ok;
        let banner = document.getElementById('link-banner');
        if (!banner) {
            banner = document.createElement('div');
            banner.id = 'link-banner';
            banner.style.cssText = 'position:fixed;top:12px;left:50%;transform:translateX(-50%);z-index:50;' +
                'background:rgba(127,29,29,0.92);color:#fff;padding:8px 14px;border-radius:8px;' +
                'font:600 13px Inter,sans-serif;border:1px solid #ef4444;display:none;';
            document.body.appendChild(banner);
        }
        banner.textContent = `Edge brain not connected${detail ? ' — ' + detail : ''}. The 3D view is not live.`;
        banner.style.display = ok ? 'none' : 'block';
    }

    updateBuildingStats() {
        const sys = this.liveData && this.liveData.system;
        const set = (id, text) => { const el = document.getElementById(id); if (el) el.textContent = text; };
        if (sys) {
            set('stat-total-rooms', String(sys.total_rooms ?? '—'));
            set('stat-occupied', `${sys.occupied_rooms ?? '—'} / ${sys.rooms_with_data ?? '—'}`);
            set('stat-power', `${((sys.sim_estimated_power_watts ?? 0) / 1000).toFixed(1)} kW (est.)`);
            set('stat-energy-saved', '—');
            set('stat-decisions', sys.model_loaded ? 'RF model' : 'heuristic');
            set('total-energy', `${((sys.sim_cumulative_energy_wh ?? 0) / 1000).toFixed(1)} kWh (sim)`);
            if (typeof sys.outdoor_temp_c === 'number') set('outdoor-temp', `${sys.outdoor_temp_c.toFixed(0)}°C`);
        }
        const temps = [];
        this.roomData.forEach(d => { if (d.sensors && typeof d.sensors.temperature === 'number') temps.push(d.sensors.temperature); });
        set('stat-avg-temp', temps.length ? `${(temps.reduce((a, b) => a + b, 0) / temps.length).toFixed(1)}°C` : '—');
        set('stat-comfort', '—');

        if (this.selectedRoom) {
            const data = this.roomData.get(this.selectedRoom);
            if (data) this.updateRoomPanel(data, data.def);
        }
    }

    // ─── EVENT LISTENERS ───

    setupEventListeners() {
        // Window resize
        window.addEventListener('resize', () => {
            this.camera.aspect = window.innerWidth / window.innerHeight;
            this.camera.updateProjectionMatrix();
            this.renderer.setSize(window.innerWidth, window.innerHeight);
        });

        // Mouse interaction
        window.addEventListener('mousemove', (e) => this.onMouseMove(e));
        window.addEventListener('click', (e) => this.onMouseClick(e));

        // Floor buttons
        document.querySelectorAll('.floor-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const fi = parseInt(btn.dataset.floor);
                this.selectFloor(fi);
            });
        });

        // View mode buttons
        document.getElementById('btn-solid').addEventListener('click', () => this.setViewMode('solid'));
        document.getElementById('btn-explode').addEventListener('click', () => this.setViewMode('explode'));
        document.getElementById('btn-cutaway').addEventListener('click', () => this.setViewMode('cutaway'));

        // Research mode buttons
        const btnPmv = document.getElementById('btn-pmv');
        const btnEnergy = document.getElementById('btn-energy');
        
        btnPmv.addEventListener('click', () => {
            const isActive = btnPmv.classList.contains('active');
            ResearchEngine.setMode(isActive ? 'NONE' : 'PMV');
            btnPmv.classList.toggle('active', !isActive);
            btnEnergy.classList.remove('active');
        });
        
        btnEnergy.addEventListener('click', () => {
            const isActive = btnEnergy.classList.contains('active');
            ResearchEngine.setMode(isActive ? 'NONE' : 'ENERGY');
            btnEnergy.classList.toggle('active', !isActive);
            btnPmv.classList.remove('active');
        });

        // Toggle UI
        const btnToggleUI = document.getElementById('btn-toggle-ui');
        if (btnToggleUI) {
            let uiVisible = true;
            btnToggleUI.addEventListener('click', () => {
                uiVisible = !uiVisible;
                const displayStyle = uiVisible ? '' : 'none';
                document.getElementById('bottom-bar').style.display = displayStyle;
                const roomPanel = document.getElementById('room-panel');
                if (this.selectedRoom && uiVisible) {
                    roomPanel.style.display = 'block';
                } else {
                    roomPanel.style.display = 'none';
                }
                const header = document.querySelector('.header');
                if (header) header.style.display = displayStyle;
                btnToggleUI.innerHTML = uiVisible ? 
                    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/></svg> Hide UI' :
                    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h4"/><polyline points="14 17 9 12 14 7"/><line x1="9" y1="12" x2="21" y2="12"/></svg> Show UI';
            });
        }

        // Time slider
        document.getElementById('time-slider').addEventListener('input', (e) => {
            this.updateTimeOfDay(parseFloat(e.target.value));
        });

        // Close room panel
        document.getElementById('close-room-panel').addEventListener('click', () => {
            document.getElementById('room-panel').style.display = 'none';
            this.selectedRoom = null;
            this.resetHighlight();
        });
    }

    // ─── ANIMATION LOOP ───

    animate() {
        requestAnimationFrame(() => this.animate());

        const now = performance.now();
        const delta = SimulationClock.tick(now);

        this.controls.update();

        // Tick all registered engines (occupancy, lighting, HVAC, energy, environment, etc.)
        EngineManager.tick(delta);

        if (this.composer) {
            this.composer.render();
        } else {
            this.renderer.render(this.scene, this.camera);
        }
    }
}

// ─── LAUNCH ───
const app = new SmartBuildingTwin();
window.twinApp = app;   // for inspection in the browser console and the end-to-end test

// Register all engines with the EngineManager
EngineManager.register('occupancy', OccupancyEngine);
EngineManager.register('lighting', LightingEngine);
EngineManager.register('hvac', HVACEngine);
EngineManager.register('energy', EnergyEngine);
EngineManager.register('hero', HeroEngine);
EngineManager.register('environment', EnvironmentalEngine);
EngineManager.register('research', ResearchEngine);
EngineManager.register('roomController', RoomController);
EngineManager.register('debugOverlay', DebugOverlay);

// Initialize all engines (gives them access to the app/scene)
EngineManager.initAll(app);

console.log('[Architecture] Phase 2: EventBus + EngineManager + SceneRegistry + RoomController + HeroEngine + DebugOverlay active.');

// Data comes only from the Next.js page (one SSE connection there, forwarded here)
window.addEventListener('message', (event) => {
    if (!event.data || event.source !== window.parent) return;

    if (event.data.type === 'UI_COMMAND') {
        const { action, payload } = event.data;
        if (action === 'setViewMode') app.setViewMode(payload);
        if (action === 'selectFloor') app.selectFloor(payload);
        if (action === 'toggleDebug') SIM_CONFIG.debug = !SIM_CONFIG.debug;
    }

    if (event.data.type === 'SYNC_STATE' && Array.isArray(event.data.rooms)) {
        app.applyBackendState(event.data);
    }

    if (event.data.type === 'LINK_STATUS') {
        app.setLinkStatus(!!event.data.ok, event.data.detail || '');
    }
});

// Ask the page for the current state once this view has loaded
if (window.parent && window.parent !== window) {
    window.parent.postMessage({ type: 'TWIN_READY' }, '*');
}

// Debug mode toggle via keyboard
window.addEventListener('keydown', (e) => {
    if (e.key === 'd' || e.key === 'D') {
        SIM_CONFIG.debug = !SIM_CONFIG.debug;
        console.log(`[Debug] Debug mode: ${SIM_CONFIG.debug ? 'ON' : 'OFF'}`);
    }
});
