// ═══════════════════════════════════════════════════════════════
// ResearchEngine.js — Heatmaps, PMV, & Energy Flow Visualizations
// ═══════════════════════════════════════════════════════════════
// Provides research-focused overlays over the 3D twin:
// 1. PMV Heatmap (Blue/Green/Red floor coloring based on thermal comfort)
// 2. Energy Flow (Particles flowing from electrical riser to active rooms)

import * as THREE from 'three';
import { VisualStateStore } from '../core/VisualStateStore.js';
import { SIM_CONFIG } from '../core/SimConfig.js';
import { dampedLerp } from '../animation/Tween.js';

class ResearchEngineImpl {
    constructor() {
        this._app = null;
        this.mode = 'NONE'; // 'NONE', 'PMV', 'ENERGY'
        
        // Energy Flow Particles
        this._particleSystem = null;
        this._particleCount = 500;
        this._particles = []; // { position, target, speed, active, ... }
        
        // Original floor colors to restore
        this._originalMaterials = new Map();
    }

    init(app) {
        this._app = app;
        this._initParticles();
        this._cacheOriginalMaterials();

        // Listen for UI commands to toggle mode
        window.addEventListener('message', (event) => {
            if (event.data?.type === 'UI_COMMAND' && event.data?.action === 'setResearchMode') {
                this.setMode(event.data.payload);
            }
        });
        
        // Keyboard shortcuts
        window.addEventListener('keydown', (e) => {
            if (e.key === 'p' || e.key === 'P') {
                this.setMode(this.mode === 'PMV' ? 'NONE' : 'PMV');
                console.log(`[ResearchEngine] Mode: ${this.mode}`);
            }
            if (e.key === 'e' || e.key === 'E') {
                this.setMode(this.mode === 'ENERGY' ? 'NONE' : 'ENERGY');
                console.log(`[ResearchEngine] Mode: ${this.mode}`);
            }
        });
    }
    
    _cacheOriginalMaterials() {
        if (!this._app || !this._app.roomMeshes) return;
        this._app.roomMeshes.forEach(mesh => {
            if (mesh.material) {
                // Clone material so we can mutate it freely without affecting shared materials
                mesh.material = mesh.material.clone();
                this._originalMaterials.set(mesh.uuid, {
                    color: mesh.material.color.clone(),
                    emissive: mesh.material.emissive.clone(),
                    emissiveIntensity: mesh.material.emissiveIntensity
                });
            }
        });
    }

    _initParticles() {
        if (!this._app) return;
        
        const geo = new THREE.SphereGeometry(0.15, 4, 4);
        const mat = new THREE.MeshBasicMaterial({ 
            color: 0xffd700, 
            transparent: true,
            opacity: 0.8
        });
        
        // Using InstancedMesh for performance
        this._particleSystem = new THREE.InstancedMesh(geo, mat, this._particleCount);
        this._particleSystem.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
        this._particleSystem.visible = false;
        
        this._app.scene.add(this._particleSystem);
        
        // Initialize particle data
        for (let i = 0; i < this._particleCount; i++) {
            this._particles.push({
                active: false,
                progress: 0,
                speed: 0,
                startX: 0, startY: 0, startZ: 0,
                endX: 0, endY: 0, endZ: 0,
                roomId: null
            });
            // Hide initially
            const dummy = new THREE.Object3D();
            dummy.scale.set(0, 0, 0);
            dummy.updateMatrix();
            this._particleSystem.setMatrixAt(i, dummy.matrix);
        }
        this._particleSystem.instanceMatrix.needsUpdate = true;
    }

    setMode(mode) {
        this.mode = mode;
        if (this._particleSystem) {
            this._particleSystem.visible = (mode === 'ENERGY');
        }
        
        if (mode !== 'PMV') {
            this._restoreOriginalColors();
        }
    }
    
    _restoreOriginalColors() {
        if (!this._app || !this._app.roomMeshes) return;
        this._app.roomMeshes.forEach(mesh => {
            const orig = this._originalMaterials.get(mesh.uuid);
            if (orig) {
                mesh.material.color.copy(orig.color);
                mesh.material.emissive.copy(orig.emissive);
                mesh.material.emissiveIntensity = orig.emissiveIntensity;
            }
        });
    }

    onRoomStateChanged() {
        // We use tick() to smoothly animate changes instead of reacting instantly
    }

    tick(delta) {
        if (!this._app) return;

        if (this.mode === 'PMV') {
            this._updatePMV(delta);
        } else if (this.mode === 'ENERGY') {
            this._updateEnergyFlow(delta);
        }
    }

    _updatePMV(delta) {
        if (!this._app.roomMeshes) return;
        
        const colors = SIM_CONFIG.research.PMV_COLORS;
        const colCold = new THREE.Color(colors.COLD);
        const colNeutral = new THREE.Color(colors.NEUTRAL);
        const colHot = new THREE.Color(colors.HOT);
        const targetColor = new THREE.Color();

        this._app.roomMeshes.forEach(mesh => {
            const ud = mesh.userData;
            const key = `${ud.floorIndex}_${ud.roomId}`;
            const vs = VisualStateStore.get(key);
            
            // PMV ranges from -3 (cold) to +3 (hot)
            const pmv = vs.pmv || 0;
            
            if (pmv < 0) {
                targetColor.copy(colNeutral).lerp(colCold, Math.min(1, Math.abs(pmv) / 3));
            } else {
                targetColor.copy(colNeutral).lerp(colHot, Math.min(1, pmv / 3));
            }
            
            // Smoothly tint the floor mesh emissive
            mesh.material.emissive.lerp(targetColor, 0.05);
            mesh.material.emissiveIntensity = dampedLerp(mesh.material.emissiveIntensity, 0.7, 0.05, delta);
            mesh.material.color.lerp(new THREE.Color(0x000000), 0.05); // Darken base to let emissive pop
        });
    }

    _updateEnergyFlow(delta) {
        if (!this._app.roomMeshes || !this._particleSystem) return;
        
        const dummy = new THREE.Object3D();
        let matrixUpdated = false;
        
        // Find total building power to scale spawning probability
        let totalPower = 0;
        this._app.roomMeshes.forEach(mesh => {
            const vs = VisualStateStore.get(`${mesh.userData.floorIndex}_${mesh.userData.roomId}`);
            totalPower += vs.powerWatts || 0;
        });
        
        // Spawn new particles based on room power consumption
        this._app.roomMeshes.forEach(mesh => {
            const ud = mesh.userData;
            const key = `${ud.floorIndex}_${ud.roomId}`;
            const vs = VisualStateStore.get(key);
            const power = vs.powerWatts || 0;
            
            if (power > 50) { // Only spawn if using significant power
                // Spawn probability proportional to power
                const spawnProb = (power / (SIM_CONFIG.research.ENERGY_MAX_WATTS || 5000)) * 0.1;
                
                if (Math.random() < spawnProb) {
                    this._spawnParticle(mesh);
                }
            }
        });
        
        // Update existing particles
        for (let i = 0; i < this._particleCount; i++) {
            const p = this._particles[i];
            if (!p.active) continue;
            
            p.progress += delta * p.speed;
            
            if (p.progress >= 1.0) {
                p.active = false;
                dummy.scale.set(0, 0, 0);
            } else {
                // Parabolic trajectory (arc up slightly)
                const arcY = Math.sin(p.progress * Math.PI) * 1.5;
                
                dummy.position.set(
                    p.startX + (p.endX - p.startX) * p.progress,
                    p.startY + (p.endY - p.startY) * p.progress + arcY,
                    p.startZ + (p.endZ - p.startZ) * p.progress
                );
                
                // Pulse size
                const pulse = Math.sin(p.progress * Math.PI * 4) * 0.2 + 0.8;
                dummy.scale.set(pulse, pulse, pulse);
            }
            
            dummy.updateMatrix();
            this._particleSystem.setMatrixAt(i, dummy.matrix);
            matrixUpdated = true;
        }
        
        if (matrixUpdated) {
            this._particleSystem.instanceMatrix.needsUpdate = true;
        }
    }
    
    _spawnParticle(targetMesh) {
        // Find inactive particle
        const idx = this._particles.findIndex(p => !p.active);
        if (idx === -1) return;
        
        const p = this._particles[idx];
        const ud = targetMesh.userData;
        
        // Central electrical shaft (assumed near x: 15, z: 10 on all floors)
        const shaftX = 15;
        const shaftZ = 10;
        const floorY = ud.floorIndex * 3.8;
        
        // Target is center of the room floor mesh
        targetMesh.geometry.computeBoundingBox();
        const bbox = targetMesh.geometry.boundingBox;
        const centerX = targetMesh.position.x;
        const centerZ = targetMesh.position.z;
        
        p.active = true;
        p.progress = 0;
        p.speed = SIM_CONFIG.research.PARTICLE_SPEED + Math.random();
        p.roomId = `${ud.floorIndex}_${ud.roomId}`;
        
        // Start from electrical shaft on ground floor
        p.startX = shaftX;
        p.startY = 0;
        p.startZ = shaftZ;
        
        // End at room center
        p.endX = centerX;
        p.endY = floorY + 0.1;
        p.endZ = centerZ;
    }

    dispose() {
        if (this._particleSystem) {
            this._app.scene.remove(this._particleSystem);
            this._particleSystem.geometry.dispose();
            this._particleSystem.material.dispose();
        }
        this._restoreOriginalColors();
        this._app = null;
    }
}

export const ResearchEngine = new ResearchEngineImpl();
