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

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

// ═══════════════════════════════════════════════════════════════
// CONFIGURATION
// ═══════════════════════════════════════════════════════════════

const CONFIG = {
    building: {
        width: 30,          // X-axis (meters)
        depth: 20,          // Y-axis
        floorHeight: 3.5,   // Height per floor
        slabThickness: 0.3, // Concrete slab
        floors: 5,
        wallThickness: 0.15,
        glassOpacity: 0.25,
    },
    camera: {
        fov: 45,
        near: 0.1,
        far: 500,
        position: [45, 35, 45],
        target: [0, 8, 0],
    },
    colors: {
        background: 0x0a0e17,
        ground: 0x1a1a2e,
        concrete: 0xb0b0b0,
        concreteFrame: 0x8a8a8a,
        glass: 0x88ccee,
        wallInterior: 0xe8e4df,
        floorTile: 0xc8c0b4,
        ceiling: 0xf0f0f0,
        carpet: {
            office: 0x5a6577,
            meeting: 0x6b7b6e,
            kitchen: 0x8b7b6b,
            corridor: 0x7a7a7a,
            lobby: 0x6b5e50,
            server: 0x3a3a4a,
            executive: 0x4a4a5a,
            lounge: 0x5a5050,
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
        gap: 2.5,        // Gap between floors in exploded view
        duration: 1200,  // Animation duration (ms)
    },
    api: {
        sseUrl: '/api/stream',
        stateUrl: '/api/rooms/current-state',
        pollInterval: 2000,
    }
};

// ═══════════════════════════════════════════════════════════════
// FLOOR LAYOUTS — 5 unique floors
// ═══════════════════════════════════════════════════════════════

const FLOOR_LAYOUTS = [
    // Floor 1 (Ground) — Lobby & Services
    {
        name: 'Lobby & Services',
        rooms: [
            { id: 'lobby',     name: 'Main Lobby',     type: 'lobby',    x: 0,  z: 0,  w: 15, d: 12, maxOcc: 15 },
            { id: 'reception', name: 'Reception',      type: 'office',   x: 15, z: 0,  w: 15, d: 6,  maxOcc: 3  },
            { id: 'security',  name: 'Security Room',  type: 'server',   x: 15, z: 6,  w: 8,  d: 6,  maxOcc: 2  },
            { id: 'mailroom',  name: 'Mail & Storage',type: 'corridor', x: 0,  z: 12, w: 15, d: 8,  maxOcc: 2  },
            { id: 'cafe',      name: 'Café',           type: 'kitchen',  x: 15, z: 12, w: 15, d: 8,  maxOcc: 10 },
            { id: 'corridor1', name: 'Main Corridor',  type: 'corridor', x: 23, z: 6,  w: 7,  d: 6,  maxOcc: 5  },
        ]
    },
    // Floor 2 — Administration
    {
        name: 'Administration',
        rooms: [
            { id: 'admin_office', name: 'Admin Office',    type: 'office',   x: 0,  z: 0,  w: 12, d: 10, maxOcc: 8  },
            { id: 'hr_office',    name: 'HR Department',   type: 'office',   x: 12, z: 0,  w: 10, d: 10, maxOcc: 6  },
            { id: 'finance',      name: 'Finance Office',  type: 'office',   x: 22, z: 0,  w: 8,  d: 10, maxOcc: 5  },
            { id: 'meeting_a',    name: 'Meeting Room A',  type: 'meeting',  x: 0,  z: 10, w: 10, d: 10, maxOcc: 12 },
            { id: 'breakroom2',   name: 'Break Room',      type: 'kitchen',  x: 10, z: 10, w: 10, d: 10, maxOcc: 6  },
            { id: 'corridor2',    name: 'Corridor',        type: 'corridor', x: 20, z: 10, w: 10, d: 10, maxOcc: 4  },
        ]
    },
    // Floor 3 — Operations (PRIMARY MONITORED FLOOR)
    {
        name: 'Operations (AI Monitored)',
        isMonitored: true,
        rooms: [
            { id: 'office_b',    name: 'Office B',        type: 'office',   x: 0,  z: 0,  w: 14, d: 12, maxOcc: 10, sensorId: 0 },
            { id: 'meeting_b',   name: 'Meeting Room B',  type: 'meeting',  x: 14, z: 0,  w: 10, d: 8,  maxOcc: 8,  sensorId: 1 },
            { id: 'kitchen3',    name: 'Kitchen',          type: 'kitchen',  x: 24, z: 0,  w: 6,  d: 8,  maxOcc: 4,  sensorId: 2 },
            { id: 'corridor3',   name: 'Main Corridor',   type: 'corridor', x: 14, z: 8,  w: 16, d: 4,  maxOcc: 5,  sensorId: 3 },
            { id: 'office_b2',   name: 'Office B2',       type: 'office',   x: 0,  z: 12, w: 14, d: 8,  maxOcc: 8  },
            { id: 'server_room', name: 'Server Room',     type: 'server',   x: 14, z: 12, w: 16, d: 8,  maxOcc: 2  },
        ]
    },
    // Floor 4 — Engineering
    {
        name: 'Engineering',
        rooms: [
            { id: 'eng_office',  name: 'Engineering Lab', type: 'office',   x: 0,  z: 0,  w: 18, d: 10, maxOcc: 12 },
            { id: 'testing_lab', name: 'Testing Lab',     type: 'server',   x: 18, z: 0,  w: 12, d: 10, maxOcc: 4  },
            { id: 'conference',  name: 'Conference Room', type: 'meeting',  x: 0,  z: 10, w: 12, d: 10, maxOcc: 15 },
            { id: 'workshop',    name: 'Workshop',        type: 'kitchen',  x: 12, z: 10, w: 10, d: 10, maxOcc: 6  },
            { id: 'corridor4',   name: 'Corridor',        type: 'corridor', x: 22, z: 10, w: 8,  d: 10, maxOcc: 4  },
        ]
    },
    // Floor 5 — Executive Suite
    {
        name: 'Executive Suite',
        rooms: [
            { id: 'exec_office', name: 'Executive Office', type: 'executive', x: 0,  z: 0,  w: 14, d: 12, maxOcc: 4  },
            { id: 'boardroom',   name: 'Board Room',       type: 'meeting',   x: 14, z: 0,  w: 16, d: 12, maxOcc: 16 },
            { id: 'lounge',      name: 'Executive Lounge', type: 'lounge',    x: 0,  z: 12, w: 15, d: 8,  maxOcc: 8  },
            { id: 'terrace',     name: 'Roof Terrace',     type: 'lobby',     x: 15, z: 12, w: 15, d: 8,  maxOcc: 10 },
        ]
    },
];

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

        // Live data
        this.liveData = {};
        this.connected = false;

        // Simulation data for non-monitored rooms
        this.simulatedData = {};

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
        this.initSimulatedData();
        this.connectToAPI();

        // Hide loading screen
        setTimeout(() => {
            document.getElementById('loading-screen').classList.add('hidden');
        }, 1500);

        this.animate();
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
        document.getElementById('canvas-container').appendChild(this.renderer.domElement);
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
        const ambient = new THREE.AmbientLight(0x404050, 0.6);
        this.scene.add(ambient);

        // Hemisphere light (sky/ground)
        const hemi = new THREE.HemisphereLight(0x87ceeb, 0x362d20, 0.4);
        this.scene.add(hemi);

        // Sun light with shadows
        this.sunLight = new THREE.DirectionalLight(0xfff5e6, 1.5);
        this.sunLight.position.set(30, 40, 20);
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
        const fill = new THREE.DirectionalLight(0xc4d4f0, 0.3);
        fill.position.set(-20, 15, -10);
        this.scene.add(fill);
    }

    // ─── GROUND ───

    buildGround() {
        this.groundGroup = new THREE.Group();

        // Main ground plane
        const groundGeo = new THREE.PlaneGeometry(200, 200);
        const groundMat = new THREE.MeshStandardMaterial({
            color: CONFIG.colors.ground,
            roughness: 0.9,
            metalness: 0.1,
        });
        const ground = new THREE.Mesh(groundGeo, groundMat);
        ground.rotation.x = -Math.PI / 2;
        ground.position.y = -0.01;
        ground.receiveShadow = true;
        this.groundGroup.add(ground);

        // Building footprint pad (lighter concrete)
        const padGeo = new THREE.PlaneGeometry(CONFIG.building.width + 6, CONFIG.building.depth + 6);
        const padMat = new THREE.MeshStandardMaterial({ color: 0x3a3a4a, roughness: 0.85 });
        const pad = new THREE.Mesh(padGeo, padMat);
        pad.rotation.x = -Math.PI / 2;
        pad.position.set(CONFIG.building.width / 2, 0, CONFIG.building.depth / 2);
        pad.receiveShadow = true;
        this.groundGroup.add(pad);

        // Grid lines for context
        const gridHelper = new THREE.GridHelper(200, 40, 0x1e2840, 0x141a2a);
        gridHelper.position.y = 0.01;
        this.groundGroup.add(gridHelper);

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
        const carpetColor = CONFIG.colors.carpet[floorType] || CONFIG.colors.carpet.office;
        const floorGeo = new THREE.PlaneGeometry(roomDef.w - wt * 2, roomDef.d - wt * 2);
        const floorMat = new THREE.MeshStandardMaterial({
            color: carpetColor,
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

        // Interior walls
        const wallMat = new THREE.MeshStandardMaterial({
            color: CONFIG.colors.wallInterior,
            roughness: 0.75,
            metalness: 0.02,
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

        // Store room data
        this.roomData.set(`${floorIndex}_${roomDef.id}`, {
            def: roomDef,
            floorIndex,
            group: roomGroup,
            sensors: {
                temperature: 22 + Math.random() * 4,
                humidity: 40 + Math.random() * 20,
                light: 200 + Math.random() * 400,
                co2: 400 + Math.random() * 200,
                occupancy: 0,
            },
            control: { light: 'OFF', hvac: 'ECO', energy: 0 },
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
            for (let i = 0; i < numDesks; i++) {
                const dx = roomDef.x + 1.5 + i * (roomDef.w - 3) / Math.max(numDesks - 1, 1);
                // Desk
                const desk = new THREE.Mesh(new THREE.BoxGeometry(1.4, 0.74, 0.7), deskMat);
                desk.position.set(dx, y0 + 0.37, cz - 1);
                desk.castShadow = true;
                group.add(desk);
                // Chair
                const chair = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.9, 0.5), chairMat);
                chair.position.set(dx, y0 + 0.45, cz - 1.8);
                group.add(chair);

                if (roomDef.d > 8) {
                    // Second row
                    const desk2 = new THREE.Mesh(new THREE.BoxGeometry(1.4, 0.74, 0.7), deskMat);
                    desk2.position.set(dx, y0 + 0.37, cz + 1.5);
                    desk2.castShadow = true;
                    group.add(desk2);
                }
            }
        } else if (type === 'meeting') {
            // Conference table
            const tw = Math.min(roomDef.w * 0.5, 4);
            const td = Math.min(roomDef.d * 0.4, 3);
            const table = new THREE.Mesh(new THREE.BoxGeometry(tw, 0.74, td), tableMat);
            table.position.set(cx, y0 + 0.37, cz);
            table.castShadow = true;
            group.add(table);

            // Chairs around table
            for (let i = 0; i < 3; i++) {
                const offset = (i - 1) * (tw * 0.35);
                // Top chairs
                const c1 = new THREE.Mesh(new THREE.BoxGeometry(0.45, 0.85, 0.45), chairMat);
                c1.position.set(cx + offset, y0 + 0.42, cz - td / 2 - 0.5);
                group.add(c1);
                // Bottom chairs
                const c2 = new THREE.Mesh(new THREE.BoxGeometry(0.45, 0.85, 0.45), chairMat);
                c2.position.set(cx + offset, y0 + 0.42, cz + td / 2 + 0.5);
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
        }
    }

    // ─── OCCUPANT INDICATORS ───

    addOccupantIndicators(group, floorIndex, roomDef, y0) {
        const indicators = [];
        const maxVisible = Math.min(roomDef.maxOcc, 6);

        for (let i = 0; i < maxVisible; i++) {
            // Simple cylindrical occupant
            const bodyGeo = new THREE.CylinderGeometry(0.15, 0.15, 1.2, 8);
            const headGeo = new THREE.SphereGeometry(0.18, 8, 6);

            const mat = new THREE.MeshStandardMaterial({
                color: CONFIG.colors.occupancy.empty,
                roughness: 0.6,
                transparent: true,
                opacity: 0.3,
            });

            const body = new THREE.Mesh(bodyGeo, mat);
            const head = new THREE.Mesh(headGeo, mat.clone());

            const personGroup = new THREE.Group();
            body.position.y = 0.6;
            head.position.y = 1.35;
            personGroup.add(body);
            personGroup.add(head);

            // Position occupants spread around the room
            const angle = (i / maxVisible) * Math.PI * 1.5 + 0.3;
            const radius = Math.min(roomDef.w, roomDef.d) * 0.25;
            personGroup.position.set(
                roomDef.x + roomDef.w / 2 + Math.cos(angle) * radius,
                y0,
                roomDef.z + roomDef.d / 2 + Math.sin(angle) * radius
            );
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
            opacity: CONFIG.building.glassOpacity,
            roughness: 0.05,
            metalness: 0.1,
            side: THREE.DoubleSide,
            envMapIntensity: 1.0,
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

    // ─── SIMULATED DATA FOR NON-MONITORED ROOMS ───

    initSimulatedData() {
        FLOOR_LAYOUTS.forEach((floor, fi) => {
            floor.rooms.forEach(room => {
                const key = `${fi}_${room.id}`;
                this.simulatedData[key] = {
                    temperature: 22 + Math.random() * 4,
                    humidity: 40 + Math.random() * 20,
                    light: 100 + Math.random() * 500,
                    co2: 380 + Math.random() * 250,
                    occupancy: Math.floor(Math.random() * room.maxOcc * 0.6),
                    lightState: Math.random() > 0.4 ? 'ON' : 'OFF',
                    hvacState: Math.random() > 0.3 ? 'COOLING' : 'ECO',
                    energy: Math.random() * 2.5,
                };
            });
        });
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

    applyCutaway(progress) {
        // Hide geometry in one quadrant to reveal interior
        const bw = CONFIG.building.width;
        const bd = CONFIG.building.depth;
        const cutX = bw * 0.55;
        const cutZ = bd * 0.55;

        this.floorGroups.forEach(group => {
            group.traverse(child => {
                if (child.isMesh && child.userData.isRoom) return; // Keep room floors visible

                if (child.isMesh && child.position) {
                    const worldPos = new THREE.Vector3();
                    child.getWorldPosition(worldPos);

                    // Hide meshes in the cut quadrant (front-right)
                    if (worldPos.x > cutX && worldPos.z < bd - cutZ) {
                        child.material = child.material.clone ? child.material.clone() : child.material;
                        if (child.material.transparent !== undefined) {
                            child.material.transparent = true;
                            child.material.opacity = Math.max(0, 1 - progress);
                            child.material.needsUpdate = true;
                        }
                    }
                }
            });
        });
    }

    removeCutaway(progress) {
        this.floorGroups.forEach(group => {
            group.traverse(child => {
                if (child.isMesh && child.material && child.material.opacity < 1) {
                    child.material.opacity = Math.min(1, child.material.opacity + progress * 0.05);
                    if (child.material.opacity >= 0.99) {
                        child.material.opacity = 1;
                        child.material.transparent = false;
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

    // ─── TIME OF DAY LIGHTING ───

    updateTimeOfDay(hour) {
        this.timeOfDay = hour;

        // Sun position
        const sunAngle = ((hour - 6) / 12) * Math.PI;
        const sunHeight = Math.sin(sunAngle) * 40;
        const sunX = Math.cos(sunAngle) * 30;

        if (hour >= 6 && hour <= 18) {
            this.sunLight.intensity = 1.0 + Math.sin(sunAngle) * 0.8;
            this.sunLight.position.set(sunX, Math.max(5, sunHeight), 20);

            // Warm sunrise/sunset colors
            if (hour < 8 || hour > 16) {
                this.sunLight.color.setHex(0xffaa44);
            } else {
                this.sunLight.color.setHex(0xfff5e6);
            }
        } else {
            // Night
            this.sunLight.intensity = 0.1;
            this.sunLight.color.setHex(0x334466);
        }

        // Update scene background for time of day
        const nightColor = new THREE.Color(0x0a0e17);
        const dayColor = new THREE.Color(0x1a2030);
        const sunsetColor = new THREE.Color(0x1a1020);

        if (hour >= 6 && hour <= 18) {
            const dayProgress = Math.sin(sunAngle);
            this.scene.background.copy(nightColor).lerp(dayColor, dayProgress);
        } else {
            this.scene.background.copy(nightColor);
        }

        // Window glows — brighter at night, dimmer during day
        const isNight = hour < 7 || hour > 18;
        this.windowGlows.forEach(glow => {
            const targetOpacity = isNight ? 0.6 : 0.05;
            glow.material.opacity += (targetOpacity - glow.material.opacity) * 0.1;
        });

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

    // ─── UPDATE ROOM VISUALS ───

    updateRoomVisuals() {
        this.roomData.forEach((data, key) => {
            const occupancy = data.sensors.occupancy;
            const isOccupied = occupancy > 0;
            const maxOcc = data.def.maxOcc;

            // Update occupant indicators
            const indicators = this.occupantMeshes.get(key);
            if (indicators) {
                indicators.forEach((person, i) => {
                    const shouldShow = i < occupancy;
                    person.visible = shouldShow;
                    if (shouldShow) {
                        person.traverse(child => {
                            if (child.isMesh) {
                                child.material.color.setHex(CONFIG.colors.occupancy.occupied);
                                child.material.opacity = 0.85;
                            }
                        });
                    }
                });
            }

            // Update ceiling lights
            const lightMesh = this.lightMeshes.get(key);
            if (lightMesh) {
                const lightOn = data.control.light === 'ON' || data.control.light === 'FULL';
                const lightDim = data.control.light === 'DIM';

                if (lightOn) {
                    lightMesh.material.emissive.setHex(0xffffcc);
                    lightMesh.material.emissiveIntensity = 1.0;
                    lightMesh.material.color.setHex(0xfffff0);
                } else if (lightDim) {
                    lightMesh.material.emissive.setHex(0xffeeaa);
                    lightMesh.material.emissiveIntensity = 0.4;
                    lightMesh.material.color.setHex(0xeeeecc);
                } else {
                    lightMesh.material.emissive.setHex(0x000000);
                    lightMesh.material.emissiveIntensity = 0;
                    lightMesh.material.color.setHex(0xcccccc);
                }
            }

            // Update window glows for occupied rooms
            this.windowGlows.forEach(glow => {
                if (glow.userData.floorIndex === data.floorIndex) {
                    const brightness = isOccupied ? 0.4 : 0.05;
                    glow.material.opacity += (brightness - glow.material.opacity) * 0.05;
                }
            });
        });
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
            if (data) {
                document.getElementById('tooltip-info').textContent =
                    `${data.sensors.temperature.toFixed(1)}°C | ${data.sensors.occupancy}/${room.maxOcc} people`;
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
    }

    updateRoomPanel(data, roomUserData) {
        const s = data.sensors;
        document.getElementById('room-temp').textContent = `${s.temperature.toFixed(1)}°C`;
        document.getElementById('room-humidity').textContent = `${s.humidity.toFixed(0)}%`;
        document.getElementById('room-light').textContent = `${s.light.toFixed(0)} lux`;
        document.getElementById('room-co2').textContent = `${s.co2.toFixed(0)} ppm`;

        // Progress bars
        document.getElementById('temp-bar').style.width = `${((s.temperature - 15) / 20) * 100}%`;
        document.getElementById('humidity-bar').style.width = `${s.humidity}%`;
        document.getElementById('light-bar').style.width = `${Math.min(s.light / 800, 1) * 100}%`;
        document.getElementById('co2-bar').style.width = `${Math.min(s.co2 / 1500, 1) * 100}%`;

        // Occupancy
        document.getElementById('room-occupancy').textContent = s.occupancy;
        document.getElementById('room-max-occ').textContent = `/ ${roomUserData.maxOcc || data.def.maxOcc}`;

        const statusEl = document.getElementById('room-occ-status');
        if (s.occupancy > (data.def.maxOcc * 0.6)) {
            statusEl.textContent = 'OCCUPIED';
            statusEl.className = 'occ-status';
        } else if (s.occupancy > 0) {
            statusEl.textContent = 'STANDBY';
            statusEl.className = 'occ-status standby';
        } else {
            statusEl.textContent = 'EMPTY';
            statusEl.className = 'occ-status empty';
        }

        // Control states
        const lightState = document.getElementById('room-light-state');
        lightState.textContent = data.control.light || 'OFF';
        lightState.className = 'control-state' + (data.control.light === 'ON' || data.control.light === 'FULL' ? ' on' : '');

        document.getElementById('room-hvac-state').textContent = data.control.hvac || 'ECO';
        document.getElementById('room-energy').textContent = `${(data.control.energy || 0).toFixed(1)} kW`;
    }

    // ─── API CONNECTION ───

    connectToAPI() {
        // Try SSE first
        try {
            const evtSource = new EventSource(CONFIG.api.sseUrl);

            evtSource.onopen = () => {
                this.connected = true;
                this.updateConnectionStatus(true);
            };

            evtSource.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    this.processLiveData(data);
                } catch (e) { /* ignore parse errors */ }
            };

            evtSource.onerror = () => {
                this.connected = false;
                this.updateConnectionStatus(false);
                evtSource.close();
                // Fallback to polling
                setTimeout(() => this.startPolling(), 3000);
            };
        } catch (e) {
            this.startPolling();
        }

        // Also start simulation data updates for non-monitored rooms
        this.startSimulationUpdates();
    }

    startPolling() {
        const poll = async () => {
            try {
                const res = await fetch(CONFIG.api.stateUrl);
                if (res.ok) {
                    const data = await res.json();
                    this.processLiveData(data);
                    this.updateConnectionStatus(true);
                }
            } catch (e) {
                this.updateConnectionStatus(false);
            }
        };

        setInterval(poll, CONFIG.api.pollInterval);
        poll(); // Initial fetch
    }

    processLiveData(data) {
        // Map API room data to floor 3 (monitored floor)
        const rooms = data.rooms || data;

        if (Array.isArray(rooms)) {
            rooms.forEach((room, i) => {
                const layout = FLOOR_LAYOUTS[2]; // Floor 3
                if (i < layout.rooms.length) {
                    const roomDef = layout.rooms[i];
                    const key = `2_${roomDef.id}`;
                    const rd = this.roomData.get(key);
                    if (rd) {
                        rd.sensors.temperature = room.temperature || room.sensors?.temperature || rd.sensors.temperature;
                        rd.sensors.humidity = room.humidity || room.sensors?.humidity || rd.sensors.humidity;
                        rd.sensors.light = room.light_level || room.sensors?.light_level || rd.sensors.light;
                        rd.sensors.co2 = room.co2 || room.sensors?.co2 || rd.sensors.co2;
                        rd.sensors.occupancy = room.occupancy || room.sensors?.occupancy || 0;
                        rd.control.light = room.light_state || room.actuators?.light_on ? 'ON' : 'OFF';
                        rd.control.hvac = room.hvac_state || room.actuators?.hvac_mode || 'ECO';
                        rd.control.energy = room.energy_use || room.sensors?.energy_use || 0;
                    }
                }
            });
        }
    }

    startSimulationUpdates() {
        // Update simulated (non-monitored) rooms every 3 seconds
        setInterval(() => {
            FLOOR_LAYOUTS.forEach((floor, fi) => {
                if (fi === 2) return; // Skip monitored floor

                floor.rooms.forEach(room => {
                    const key = `${fi}_${room.id}`;
                    const sd = this.simulatedData[key];
                    const rd = this.roomData.get(key);
                    if (!sd || !rd) return;

                    // Gentle random walk
                    sd.temperature += (Math.random() - 0.5) * 0.3;
                    sd.temperature = Math.max(18, Math.min(30, sd.temperature));
                    sd.humidity += (Math.random() - 0.5) * 1;
                    sd.humidity = Math.max(30, Math.min(75, sd.humidity));
                    sd.co2 += (Math.random() - 0.5) * 10;
                    sd.co2 = Math.max(350, Math.min(800, sd.co2));

                    // Occupancy based on time of day
                    const hour = this.timeOfDay;
                    const isWorkHour = hour >= 8 && hour <= 18;
                    const isLunch = hour >= 12 && hour <= 13;

                    if (isWorkHour && !isLunch) {
                        sd.occupancy = Math.floor(Math.random() * room.maxOcc * 0.8);
                    } else if (isLunch && room.type === 'kitchen') {
                        sd.occupancy = Math.floor(Math.random() * room.maxOcc);
                    } else if (isWorkHour) {
                        sd.occupancy = Math.floor(Math.random() * room.maxOcc * 0.3);
                    } else {
                        sd.occupancy = Math.random() > 0.9 ? 1 : 0;
                    }

                    sd.lightState = sd.occupancy > 0 ? 'ON' : 'OFF';
                    sd.light = sd.occupancy > 0 ? 300 + Math.random() * 200 : 20 + Math.random() * 50;
                    sd.hvacState = sd.occupancy > 0 ? 'COOLING' : 'ECO';
                    sd.energy = sd.occupancy > 0 ? 0.5 + Math.random() * 2 : 0.1 + Math.random() * 0.3;

                    // Update room data
                    rd.sensors.temperature = sd.temperature;
                    rd.sensors.humidity = sd.humidity;
                    rd.sensors.light = sd.light;
                    rd.sensors.co2 = sd.co2;
                    rd.sensors.occupancy = sd.occupancy;
                    rd.control.light = sd.lightState;
                    rd.control.hvac = sd.hvacState;
                    rd.control.energy = sd.energy;
                });
            });

            this.updateBuildingStats();
        }, 3000);
    }

    updateConnectionStatus(connected) {
        this.connected = connected;
        const dot = document.getElementById('conn-dot');
        const text = document.getElementById('conn-text');
        if (connected) {
            dot.classList.add('connected');
            text.textContent = 'Live';
        } else {
            dot.classList.remove('connected');
            text.textContent = 'Simulated';
        }
    }

    updateBuildingStats() {
        let totalOccupied = 0;
        let totalTemp = 0;
        let totalPower = 0;
        let roomCount = 0;

        this.roomData.forEach(data => {
            if (data.sensors.occupancy > 0) totalOccupied++;
            totalTemp += data.sensors.temperature;
            totalPower += data.control.energy || 0;
            roomCount++;
        });

        document.getElementById('stat-occupied').textContent = totalOccupied;
        document.getElementById('stat-avg-temp').textContent = `${(totalTemp / Math.max(roomCount, 1)).toFixed(1)}°C`;
        document.getElementById('stat-power').textContent = `${totalPower.toFixed(1)} kW`;
        document.getElementById('stat-energy-today').textContent = `${(totalPower * this.timeOfDay / 4).toFixed(1)} kWh`;
        document.getElementById('stat-comfort').textContent = `${(85 + Math.random() * 10).toFixed(0)}%`;
        document.getElementById('outdoor-temp').textContent = `${(26 + Math.sin(this.timeOfDay / 3) * 4).toFixed(0)}°C`;

        // Update selected room panel if open
        if (this.selectedRoom) {
            const data = this.roomData.get(this.selectedRoom);
            if (data) {
                this.updateRoomPanel(data, data.def);
            }
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

        // Time slider
        document.getElementById('time-slider').addEventListener('input', (e) => {
            this.updateTimeOfDay(parseFloat(e.target.value));
        });

        // Close room panel
        document.getElementById('close-room-panel').addEventListener('click', () => {
            document.getElementById('room-panel').style.display = 'none';
            this.selectedRoom = null;
        });
    }

    // ─── ANIMATION LOOP ───

    animate() {
        requestAnimationFrame(() => this.animate());

        this.controls.update();

        // Subtle building rotation/breathing effect
        const time = performance.now() * 0.001;

        // Update room visuals
        this.updateRoomVisuals();

        // Slowly advance time of day if not manually controlled
        // (commented out — user controls via slider)
        // this.updateTimeOfDay(this.timeOfDay + 0.0005);

        this.renderer.render(this.scene, this.camera);
    }
}

// ─── LAUNCH ───
const app = new SmartBuildingTwin();
