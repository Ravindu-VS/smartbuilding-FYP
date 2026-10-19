// ═══════════════════════════════════════════════════════════════
// HeroEngine.js — Room 101 Research Visualization Engine
// ═══════════════════════════════════════════════════════════════
// Uniform API: init(), onRoomStateChanged(), tick(delta), dispose()
//
// Manages ONLY Room 101 (the hardware-connected room):
//   - Green synchronization pulse on occupancy change
//   - LIVE badge glow animation
//   - Latency tracking (PIR → ESP32 → MQTT → Backend → Twin)
//   - Edge AI inference time display
//   - Hardware connection status ring
//
// Keeps research-specific logic isolated from general simulation.

import * as THREE from 'three';
import { eventBus, Events } from '../core/EventBus.js';
import { SIM_CONFIG } from '../core/SimConfig.js';
import { SimulationClock } from '../core/SimulationClock.js';
import { VisualStateStore } from '../core/VisualStateStore.js';
import { SceneRegistry, EntityType } from '../core/SceneRegistry.js';

class HeroEngineImpl {
    constructor() {
        this._app = null;
        this._heroRoomId = null;      // Legacy format: '2_office_a'
        this._syncRing = null;        // Glowing ring mesh around Room 101
        this._pulseIntensity = 0;     // Current pulse brightness (0–1)
        this._pulseActive = false;
        this._latencyMs = 0;
        this._lastOccupancy = 0;
        this._syncCount = 0;          // Total sync events (for research metrics)
        this._unsubscribers = [];
    }

    init(app) {
        this._app = app;
        this._heroRoomId = SIM_CONFIG.hero.ROOM_ID;

        // Create the synchronization ring around Room 101
        this._createSyncRing();

        // Listen for hero sync events
        const unsub = eventBus.on(Events.HERO_ROOM_SYNC, (data) => {
            this._onHeroSync(data);
        });
        this._unsubscribers.push(unsub);
    }

    /**
     * Create a glowing ring mesh that surrounds Room 101 on the floor.
     */
    _createSyncRing() {
        if (!this._app) return;

        // Find the Room 101 definition from FLOOR_LAYOUTS
        // Room 101 = Floor 3 (index 2), office_a
        const floorGroup = this._app.floorGroups?.[2];
        if (!floorGroup) return;

        // Room 101 position from FLOOR_LAYOUTS: x:0, z:0, w:14, d:12
        const roomDef = { x: 0, z: 0, w: 14, d: 12 };
        const cx = roomDef.x + roomDef.w / 2;
        const cz = roomDef.z + roomDef.d / 2;
        const y = 2 * 3.8 + 0.05; // Floor 3 base Y + tiny offset

        // Create ring geometry
        const ringGeometry = new THREE.RingGeometry(
            Math.max(roomDef.w, roomDef.d) * 0.52,
            Math.max(roomDef.w, roomDef.d) * 0.55,
            32
        );
        const ringMaterial = new THREE.MeshBasicMaterial({
            color: SIM_CONFIG.hero.PULSE_COLOR,
            transparent: true,
            opacity: 0,
            side: THREE.DoubleSide,
            depthWrite: false,
        });

        this._syncRing = new THREE.Mesh(ringGeometry, ringMaterial);
        this._syncRing.rotation.x = -Math.PI / 2; // Lay flat
        this._syncRing.position.set(cx, y, cz);

        floorGroup.add(this._syncRing);

        // Register in SceneRegistry
        SceneRegistry.register(
            `${EntityType.HERO_RING}_${this._heroRoomId}`,
            this._syncRing,
            { roomId: this._heroRoomId, floorId: 2, type: EntityType.HERO_RING }
        );
    }

    /**
     * Triggered when Room 101 receives a hardware sync event.
     */
    _onHeroSync({ roomId, latencyMs, occupancy }) {
        if (roomId !== this._heroRoomId) return;

        this._pulseActive = true;
        this._pulseIntensity = 1.0;
        this._latencyMs = latencyMs || 0;
        this._syncCount++;

        console.log(
            `[HeroEngine] 🔴 LIVE SYNC #${this._syncCount} | ` +
            `Occupancy: ${this._lastOccupancy} → ${occupancy} | ` +
            `Latency: ${this._latencyMs}ms`
        );

        this._lastOccupancy = occupancy;
    }

    onRoomStateChanged({ roomId, backendState, visualState }) {
        // Only care about Room 101
        if (roomId !== this._heroRoomId) return;

        // Track latency from backend timestamp
        if (backendState.timestamp) {
            try {
                this._latencyMs = Date.now() - new Date(backendState.timestamp).getTime();
            } catch { /* ignore parse errors */ }
        }
    }

    tick(delta) {
        // Animate the sync ring pulse
        if (this._pulseActive && this._syncRing) {
            this._pulseIntensity -= delta / (SIM_CONFIG.hero.PULSE_DURATION_MS / 1000);

            if (this._pulseIntensity <= 0) {
                this._pulseIntensity = 0;
                this._pulseActive = false;
            }

            // Pulsing opacity and scale
            this._syncRing.material.opacity = this._pulseIntensity * 0.8;
            const scale = 1.0 + (1.0 - this._pulseIntensity) * 0.3; // Ring expands as it fades
            this._syncRing.scale.set(scale, scale, 1);
        } else if (this._syncRing) {
            // Subtle idle glow to show Room 101 is always LIVE
            const idleGlow = 0.08 + Math.sin(SimulationClock.elapsed * 2) * 0.04;
            this._syncRing.material.opacity = idleGlow;
            this._syncRing.scale.set(1, 1, 1);
        }
    }

    /**
     * Get hero room metrics for debug/dashboard.
     */
    getMetrics() {
        return {
            roomId: this._heroRoomId,
            latencyMs: this._latencyMs,
            syncCount: this._syncCount,
            pulseActive: this._pulseActive,
            lastOccupancy: this._lastOccupancy,
        };
    }

    dispose() {
        this._unsubscribers.forEach(fn => fn());
        this._unsubscribers = [];

        if (this._syncRing) {
            this._syncRing.parent?.remove(this._syncRing);
            this._syncRing.geometry.dispose();
            this._syncRing.material.dispose();
            this._syncRing = null;
        }
        this._app = null;
    }
}

export const HeroEngine = new HeroEngineImpl();
