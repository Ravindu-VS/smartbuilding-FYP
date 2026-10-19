// ═══════════════════════════════════════════════════════════════
// LightingEngine.js — Deterministic Lighting from Backend State
// ═══════════════════════════════════════════════════════════════
// Uniform API: init(), onRoomStateChanged(), tick(delta), dispose()

import { VisualStateStore } from '../core/VisualStateStore.js';
import { dampedLerp } from '../animation/Tween.js';

class LightingEngineImpl {
    constructor() {
        this._app = null;
        this._roomBrightness = new Map(); // roomId → current brightness (0–1)
    }

    init(app) {
        this._app = app;
    }

    onRoomStateChanged({ roomId, backendState, visualState }) {
        // Visual state already has lightTarget computed
        // We just ensure the room is tracked
        if (!this._roomBrightness.has(roomId)) {
            this._roomBrightness.set(roomId, 0);
        }
    }

    tick(delta) {
        if (!this._app) return;

        this._roomBrightness.forEach((currentBrightness, roomId) => {
            const vs = VisualStateStore.get(roomId);
            const lightMesh = this._app.lightMeshes.get(roomId);
            if (!lightMesh) return;

            // Initialize PointLight if not present
            if (!lightMesh.userData.pointLight) {
                const pLight = new THREE.PointLight(0xfffff0, 0, 15);
                pLight.position.set(0, -1, 0); // slightly below ceiling
                lightMesh.add(pLight);
                lightMesh.userData.pointLight = pLight;
            }

            // Smoothly interpolate brightness
            const newBrightness = dampedLerp(currentBrightness, vs.lightTarget, 0.08, delta);
            this._roomBrightness.set(roomId, newBrightness);
            
            const pLight = lightMesh.userData.pointLight;

            // Apply to mesh
            if (newBrightness > 0.6) {
                // ON
                lightMesh.material.emissive.setHex(0xffffff);
                lightMesh.material.emissiveIntensity = newBrightness * 3.0;
                lightMesh.material.color.setHex(0xffffff);
                pLight.intensity = newBrightness * 2.5;
                pLight.color.setHex(0xaaaaee); // Cool white/blue for sci-fi feel
            } else if (newBrightness > 0.2) {
                // DIM
                lightMesh.material.emissive.setHex(0xffeeaa);
                lightMesh.material.emissiveIntensity = newBrightness;
                lightMesh.material.color.setHex(0xeeeecc);
                pLight.intensity = newBrightness * 0.8;
                pLight.color.setHex(0xffeeaa); // Warm dim
            } else {
                // OFF
                lightMesh.material.emissive.setHex(0x000000);
                lightMesh.material.emissiveIntensity = 0;
                lightMesh.material.color.setHex(0x333333);
                pLight.intensity = 0;
            }
        });
    }

    dispose() {
        this._roomBrightness.clear();
        this._app = null;
    }
}

export const LightingEngine = new LightingEngineImpl();
