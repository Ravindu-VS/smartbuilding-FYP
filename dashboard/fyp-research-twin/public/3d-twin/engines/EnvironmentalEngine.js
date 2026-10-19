// ═══════════════════════════════════════════════════════════════
// EnvironmentalEngine.js — Nature, Lighting, & Ambient Life
// ═══════════════════════════════════════════════════════════════
// Drives the sun position, sky color, window glows, moving cars,
// and procedural trees based on the global SimulationClock.

import * as THREE from 'three';
import { SimulationClock } from '../core/SimulationClock.js';

class EnvironmentalEngineImpl {
    constructor() {
        this._app = null;
        this._trees = [];
        this._cars = [];
    }

    init(app) {
        this._app = app;
        this._buildTrees();
        
        // Grab cars from app if they were built there
        this._cars = app.cars || [];
    }

    _buildTrees() {
        if (!this._app || !this._app.groundGroup) return;

        const treeCount = 40;
        const cx = 100; // Assuming CONFIG.building.width / 2 is roughly 100 or relative
        // We'll place trees randomly around the plaza/grass area

        const trunkGeo = new THREE.CylinderGeometry(0.3, 0.5, 3, 6);
        const trunkMat = new THREE.MeshStandardMaterial({ color: 0x4a3a2a, roughness: 1.0 });

        const leavesGeo = new THREE.DodecahedronGeometry(2.5, 1);
        const leavesMat = new THREE.MeshStandardMaterial({ 
            color: 0x3a5a2a, roughness: 0.9, flatShading: true
        });

        for (let i = 0; i < treeCount; i++) {
            const treeGroup = new THREE.Group();
            
            const trunk = new THREE.Mesh(trunkGeo, trunkMat);
            trunk.position.y = 1.5;
            trunk.castShadow = true;
            treeGroup.add(trunk);

            const leaves = new THREE.Mesh(leavesGeo, leavesMat);
            leaves.position.y = 3.5;
            leaves.castShadow = true;
            
            // Randomize shape slightly
            leaves.scale.set(1 + Math.random()*0.5, 1 + Math.random()*0.5, 1 + Math.random()*0.5);
            leaves.rotation.set(Math.random()*Math.PI, Math.random()*Math.PI, 0);
            treeGroup.add(leaves);

            // Store original rotation for wind animation
            treeGroup.userData.baseRotX = treeGroup.rotation.x;
            treeGroup.userData.baseRotZ = treeGroup.rotation.z;
            treeGroup.userData.windPhase = Math.random() * Math.PI * 2;

            // Placement (avoid building center)
            const angle = Math.random() * Math.PI * 2;
            const radius = 60 + Math.random() * 40;
            // Assuming building center is around x: 50, z: 20
            // Since we don't have exact CONFIG.building in scope easily, we use local offsets
            treeGroup.position.set(50 + Math.cos(angle)*radius, 0, 20 + Math.sin(angle)*radius);
            
            this._app.groundGroup.add(treeGroup);
            this._trees.push(treeGroup);
        }
    }

    onRoomStateChanged({ roomId, backendState, visualState }) {
        // We handle thermal mapping interpolation in tick, but we can track the target temperature here
    }

    tick(delta) {
        if (!this._app) return;

        const time = SimulationClock.elapsed;
        const hour = SimulationClock.hour;
        
        // (Room floors are coloured by temperature only when the Temp. Heatmap button is on:
        //  see ResearchEngine. An always-on copy here referenced VisualStateStore without
        //  importing it, threw on every frame and stopped the sky, sun and cars from updating.)

        // --- Wind Animation (Trees) ---
        const windStrength = 0.05;
        this._trees.forEach(tree => {
            const phase = time * 0.5 + tree.userData.windPhase;
            tree.rotation.x = tree.userData.baseRotX + Math.sin(phase) * windStrength;
            tree.rotation.z = tree.userData.baseRotZ + Math.cos(phase * 1.3) * windStrength;
        });

        // --- Sun & Sky Update ---
        this._updateLighting(hour);

        // --- Cars Update ---
        this._updateCars(hour, delta, time);
    }

    _updateLighting(hour) {
        // Sun position
        const sunAngle = ((hour - 6) / 12) * Math.PI;
        const sunHeight = Math.sin(sunAngle) * 40;
        const sunX = Math.cos(sunAngle) * 30;

        if (this._app.sunLight) {
            if (hour >= 6 && hour <= 18) {
                this._app.sunLight.intensity = 1.0 + Math.sin(sunAngle) * 0.8;
                this._app.sunLight.position.set(sunX, Math.max(5, sunHeight), 20);

                if (this._app.ambientLight) this._app.ambientLight.intensity = 0.4 + Math.sin(sunAngle) * 0.2;
                if (this._app.hemiLight) this._app.hemiLight.intensity = 0.8 + Math.sin(sunAngle) * 0.2;

                // Warm sunrise/sunset colors
                if (hour < 8 || hour > 16) {
                    this._app.sunLight.color.setHex(0xffaa44);
                } else {
                    this._app.sunLight.color.setHex(0xfff5e6);
                }
            } else {
                // Night (Deep dark for clear emissives)
                this._app.sunLight.intensity = 0.0;
                this._app.sunLight.color.setHex(0x111122);
                if (this._app.ambientLight) this._app.ambientLight.intensity = 0.05;
                if (this._app.hemiLight) this._app.hemiLight.intensity = 0.05;
            }
        }

        // Sky & Fog Color
        if (this._app.scene && this._app.scene.background) {
            const nightColor = new THREE.Color(0x050510);
            const dayColor = new THREE.Color(0x4a80ba); // Bright clear sky blue
            
            if (hour >= 6 && hour <= 18) {
                const dayProgress = Math.sin(sunAngle);
                this._app.scene.background.copy(nightColor).lerp(dayColor, dayProgress);
            } else {
                this._app.scene.background.copy(nightColor);
            }
            // Update fog to match sky background so the horizon blends nicely
            if (this._app.scene.fog) {
                this._app.scene.fog.color.copy(this._app.scene.background);
            }
        }

        // Window glows — brighter at night, dimmer during day
        const isNight = hour < 7 || hour > 18;
        if (this._app.windowGlows) {
            this._app.windowGlows.forEach(glow => {
                const targetOpacity = isNight ? 0.6 : 0.05;
                glow.material.opacity += (targetOpacity - glow.material.opacity) * 0.1;
            });
        }
    }

    _updateCars(hour, delta, time) {
        const isNight = hour < 7 || hour > 18;
        
        this._cars.forEach((car, index) => {
            // Headlights & Taillights
            if (car.userData.headlights) {
                car.userData.headlights.forEach(hl => { hl.material.emissiveIntensity = isNight ? 3.0 : 0.0; });
                car.userData.taillights.forEach(tl => { tl.material.emissiveIntensity = isNight ? 1.5 : 0.0; });
            }

            // Move the moving cars (first 6 are parked, rest are moving)
            // Wait, in app.js, parked cars don't have a special flag, but let's assume index > 5 are moving
            if (index > 5) {
                // Move in a circle
                const roadOffset = 55;
                const speed = 0.2; // radians per second
                const angle = -((index / 12) * Math.PI * 2) + (time * speed);
                // Center of the building is approx (cx, cz)
                const cx = 35; // Rough estimate of center from app.js buildGround
                const cz = 25; 
                
                car.position.set(cx + Math.cos(angle) * roadOffset, 0, cz + Math.sin(angle) * roadOffset);
                car.rotation.y = -angle; // facing tangent
            }
        });
    }

    dispose() {
        this._trees.forEach(tree => {
            tree.parent?.remove(tree);
        });
        this._trees = [];
        this._app = null;
    }
}

export const EnvironmentalEngine = new EnvironmentalEngineImpl();
