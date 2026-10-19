// ═══════════════════════════════════════════════════════════════
// RoomController.js — Per-Room Visual Entity Coordinator
// ═══════════════════════════════════════════════════════════════
// Encapsulates ALL visual elements belonging to a single room:
//   Door, Window, Avatars, Fan, Lights, Monitors, Furniture
//
// OccupancyEngine says "Room 2_office_a: occupancy = 3"
// RoomController handles EVERYTHING visual for that room.

import { SceneRegistry, EntityType } from '../core/SceneRegistry.js';
import { VisualStateStore } from '../core/VisualStateStore.js';
import { eventBus, Events } from '../core/EventBus.js';
import { SIM_CONFIG } from '../core/SimConfig.js';
import { dampedLerp } from '../animation/Tween.js';

class RoomControllerImpl {
    constructor() {
        this._app = null;
        this._rooms = new Map();          // roomId → RoomVisuals
        this._unsubscribers = [];
    }

    /**
     * Internal per-room visual state tracker.
     */
    _createRoomVisuals(roomId) {
        return {
            roomId,
            // Door
            doorMesh: null,
            doorAngle: 0,
            doorTarget: 0,
            doorTimer: 0,
            previousOccupancy: 0,
            // Window
            windowMeshes: [],
            windowAngle: 0,
            windowTarget: 0,
            // Fan
            fanMesh: null,
            fanRotation: 0,
            fanSpeed: 0,
            // Monitors
            monitorMeshes: [],
            monitorGlow: 0,
            monitorTarget: 0,
            // Hero ring (Room 101 only)
            heroRing: null,
            heroPulse: 0,
            heroPulseActive: false,
            // Initialized
            registered: false,
        };
    }

    init(app) {
        this._app = app;

        // Subscribe to state changes
        const unsub1 = eventBus.on(Events.ROOM_STATE_CHANGED, (data) => {
            this._onRoomUpdate(data);
        });

        // Subscribe to hero events
        const unsub2 = eventBus.on(Events.HERO_ROOM_SYNC, (data) => {
            this._onHeroSync(data);
        });

        this._unsubscribers.push(unsub1, unsub2);

        // Register existing room meshes from app into SceneRegistry
        this._registerExistingMeshes();
    }

    /**
     * Scan the app's existing mesh maps and register them into SceneRegistry.
     */
    _registerExistingMeshes() {
        if (!this._app) return;

        // Register light meshes
        this._app.lightMeshes?.forEach((mesh, roomId) => {
            const entityId = `${EntityType.LIGHT}_${roomId}`;
            const floorId = parseInt(roomId.split('_')[0], 10);
            SceneRegistry.register(entityId, mesh, {
                roomId, floorId, type: EntityType.LIGHT,
            });
        });

        // Register occupant meshes (avatars)
        this._app.occupantMeshes?.forEach((meshArray, roomId) => {
            meshArray.forEach((mesh, idx) => {
                const entityId = `${EntityType.AVATAR}_${roomId}_${idx}`;
                const floorId = parseInt(roomId.split('_')[0], 10);
                SceneRegistry.register(entityId, mesh, {
                    roomId, floorId, type: EntityType.AVATAR, index: idx,
                });
            });
        });

        // Register window glow meshes
        this._app.windowGlows?.forEach((mesh, idx) => {
            const floorId = mesh.userData?.floorIndex ?? 0;
            const entityId = `${EntityType.WINDOW}_glow_${floorId}_${idx}`;
            SceneRegistry.register(entityId, mesh, {
                roomId: null, floorId, type: EntityType.WINDOW, subType: 'glow',
            });
        });

        console.log(`[RoomController] Registered ${SceneRegistry.size} entities in SceneRegistry.`);
    }

    /**
     * Handle a room state update.
     */
    _onRoomUpdate({ roomId, backendState, visualState }) {
        let rv = this._rooms.get(roomId);
        if (!rv) {
            rv = this._createRoomVisuals(roomId);
            this._rooms.set(roomId, rv);
        }

        const vs = visualState;
        const currentOcc = vs.targetAvatarCount;
        const prevOcc = rv.previousOccupancy;

        // --- Door Logic: only on 0→N or N→0 ---
        if ((prevOcc === 0 && currentOcc > 0) || (prevOcc > 0 && currentOcc === 0)) {
            rv.doorTarget = 1.2; // ~70 degrees open
            rv.doorTimer = SIM_CONFIG.animation.DOOR_CLOSE_DELAY_MS / 1000;
        }
        rv.previousOccupancy = currentOcc;

        // --- Window: AI ventilation decision ---
        rv.windowTarget = vs.windowTarget;

        // --- Fan speed: from HVAC ---
        rv.fanSpeed = vs.fanSpeed;

        // --- Monitor glow: based on occupancy ---
        rv.monitorTarget = currentOcc > 0 ? 1.0 : 0.0;
    }

    /**
     * Handle Room 101 hero sync pulse.
     */
    _onHeroSync({ roomId, latencyMs, occupancy }) {
        const rv = this._rooms.get(roomId);
        if (!rv) return;
        rv.heroPulseActive = true;
        rv.heroPulse = 1.0; // Start full intensity
    }

    /**
     * Called every frame — interpolate all room visuals smoothly.
     */
    tick(delta) {
        this._rooms.forEach((rv, roomId) => {

            // --- Door interpolation ---
            rv.doorAngle = dampedLerp(rv.doorAngle, rv.doorTarget, 0.06, delta);
            if (rv.doorTimer > 0) {
                rv.doorTimer -= delta;
                if (rv.doorTimer <= 0) {
                    rv.doorTarget = 0; // Auto-close
                }
            }
            // Apply to door mesh if registered
            const doorEntity = SceneRegistry.getMesh(`${EntityType.DOOR}_${roomId}`);
            if (doorEntity) {
                doorEntity.rotation.y = rv.doorAngle;
            }

            // --- Window interpolation ---
            rv.windowAngle = dampedLerp(rv.windowAngle, rv.windowTarget, 0.08, delta);
            // Apply to window meshes if registered
            const windowEntities = SceneRegistry.getByRoomAndType(roomId, EntityType.WINDOW);
            windowEntities.forEach(e => {
                if (e.mesh) e.mesh.rotation.y = rv.windowAngle;
            });

            // --- Fan rotation ---
            if (rv.fanSpeed > 0.01) {
                rv.fanRotation += rv.fanSpeed * delta * 10;
                const fanEntity = SceneRegistry.getMesh(`${EntityType.FAN}_${roomId}`);
                if (fanEntity) {
                    fanEntity.rotation.y = rv.fanRotation;
                }
            }

            // --- Monitor glow interpolation ---
            rv.monitorGlow = dampedLerp(rv.monitorGlow, rv.monitorTarget, 0.1, delta);
            const monitors = SceneRegistry.getByRoomAndType(roomId, EntityType.MONITOR);
            monitors.forEach(e => {
                if (e.mesh?.material) {
                    e.mesh.material.emissiveIntensity = rv.monitorGlow * 0.8;
                }
            });

            // --- Hero pulse decay ---
            if (rv.heroPulseActive && rv.heroPulse > 0) {
                rv.heroPulse -= delta / (SIM_CONFIG.hero.PULSE_DURATION_MS / 1000);
                if (rv.heroPulse <= 0) {
                    rv.heroPulse = 0;
                    rv.heroPulseActive = false;
                }
            }
        });
    }

    /**
     * Get room visual state (for debug overlay).
     */
    getRoomVisuals(roomId) {
        return this._rooms.get(roomId) || null;
    }

    /**
     * Get all room IDs being tracked.
     */
    getRoomIds() {
        return Array.from(this._rooms.keys());
    }

    onRoomStateChanged(data) {
        // Already handled via EventBus subscription in init()
        // This satisfies the EngineManager uniform API
    }

    dispose() {
        this._unsubscribers.forEach(fn => fn());
        this._unsubscribers = [];
        this._rooms.clear();
        this._app = null;
    }
}

export const RoomController = new RoomControllerImpl();
