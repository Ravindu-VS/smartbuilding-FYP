// ═══════════════════════════════════════════════════════════════
// OccupancyEngine.js — AI-Driven Avatar Lifecycle Engine
// ═══════════════════════════════════════════════════════════════
// Uniform API: init(), onRoomStateChanged(), tick(delta), dispose()
//
// Uses AvatarPool for efficient mesh management.
// Uses DoorManager for entrance positions.
//
// Lifecycle:   AI probability rises → door opens → avatar walks
//              from entrance to desk → sits → idle animations.
//              AI probability falls → avatar stands → walks to
//              door → door closes → avatar released to pool.

import { VisualStateStore } from '../core/VisualStateStore.js';
import { eventBus, Events } from '../core/EventBus.js';
import { SIM_CONFIG } from '../core/SimConfig.js';
import { SimulationClock } from '../core/SimulationClock.js';
import { dampedLerp, seededRandom, hashString } from '../animation/Tween.js';
import { AvatarPool } from './AvatarPool.js';
import { DoorManager } from '../controllers/DoorManager.js';

// Per-room occupancy animation state
class RoomOccupancyState {
    constructor(roomId) {
        this.roomId = roomId;
        this.targetAvatars = 0;       // Target from backend
        this.previousAvatars = 0;     // For door transition detection
        this.doorAngle = 0;           // Current door angle (radians)
        this.doorTarget = 0;          // Target door angle
        this.doorTimer = 0;           // Timer for auto-close
        this.delayTimer = 0;          // AI decision delay timer
        this.pendingTarget = null;    // Target after delay expires
        this.currentCount = 0;        // Currently managed avatar count
        this.rng = seededRandom(hashString(roomId));

        // Room geometry (filled on first use)
        this.roomDef = null;
        this.floorY = 0;
        this.deskPositions = [];      // Pre-computed desk spots
    }
}

class OccupancyEngineImpl {
    constructor() {
        this._app = null;
        this._roomStates = new Map();
        this._poolInitialized = false;
    }

    init(app) {
        this._app = app;

        // Initialize AvatarPool
        if (!this._poolInitialized && app.scene) {
            AvatarPool.init(app.scene);
            this._poolInitialized = true;
        }

        // Create doors for all floors
        const FLOOR_HEIGHT = 3.8;
        app.floorGroups?.forEach((floorGroup, floorIndex) => {
            const layout = app.floorLayouts?.[floorIndex];
            if (layout?.rooms) {
                const y0 = floorIndex * FLOOR_HEIGHT;
                DoorManager.createDoorsForFloor(floorGroup, floorIndex, layout.rooms, y0);
            }
        });

        console.log(`[OccupancyEngine] Doors created. AvatarPool ready (${AvatarPool.getStats().total} avatars).`);
    }

    /**
     * Compute desk positions within a room for avatar seating.
     */
    _computeDeskPositions(roomDef, floorY, maxPositions = 6) {
        const positions = [];
        const cx = roomDef.x + roomDef.w / 2;
        const cz = roomDef.z + roomDef.d / 2;
        const radiusX = roomDef.w * 0.3;
        const radiusZ = roomDef.d * 0.3;

        for (let i = 0; i < maxPositions; i++) {
            const angle = (i / maxPositions) * Math.PI * 1.5 + 0.3;
            positions.push({
                x: cx + Math.cos(angle) * radiusX,
                z: cz + Math.sin(angle) * radiusZ,
                rotation: angle + Math.PI, // Face inward
            });
        }
        return positions;
    }

    onRoomStateChanged({ roomId, backendState, visualState }) {
        if (!this._app) return;

        const vs = visualState;
        let rs = this._roomStates.get(roomId);
        if (!rs) {
            rs = new RoomOccupancyState(roomId);
            this._roomStates.set(roomId, rs);

            // Find room definition for desk positions
            const floorIndex = parseInt(roomId.split('_')[0], 10);
            const roomName = roomId.substring(roomId.indexOf('_') + 1);
            const layout = this._app.floorLayouts?.[floorIndex];
            if (layout?.rooms) {
                rs.roomDef = layout.rooms.find(r => r.id === roomName);
                rs.floorY = 0.32;   // positions are local to the floor group
                if (rs.roomDef) {
                    rs.deskPositions = this._computeDeskPositions(rs.roomDef, rs.floorY);
                }
            }
        }

        const newTarget = vs.targetAvatarCount;

        // Set pending with AI decision delay
        rs.pendingTarget = newTarget;
        rs.delayTimer = SIM_CONFIG.animation.DECISION_DELAY_MS / 1000;

        // Door logic: only animate on 0→N or N→0
        const wasEmpty = rs.targetAvatars === 0;
        const willBeOccupied = newTarget > 0;
        const wasOccupied = rs.targetAvatars > 0;
        const willBeEmpty = newTarget === 0;

        if ((wasEmpty && willBeOccupied) || (wasOccupied && willBeEmpty)) {
            rs.doorTarget = 1.2; // ~70 degrees
            rs.doorTimer = SIM_CONFIG.animation.DOOR_CLOSE_DELAY_MS / 1000;
        }

        rs.previousAvatars = rs.targetAvatars;
        rs.targetAvatars = newTarget;

        // Hero room pulse
        if (roomId === SIM_CONFIG.hero.ROOM_ID && newTarget !== rs.previousAvatars) {
            eventBus.emit(Events.HERO_ROOM_SYNC, {
                roomId,
                latencyMs: vs.heroSyncLatencyMs,
                occupancy: newTarget,
            });
        }
    }

    tick(delta) {
        if (!this._app) return;

        this._roomStates.forEach((rs, roomId) => {
            // --- Process AI decision delay ---
            if (rs.delayTimer > 0) {
                rs.delayTimer -= delta;
                if (rs.delayTimer <= 0 && rs.pendingTarget !== null) {
                    this._applyTargetChange(rs, rs.pendingTarget);
                    rs.pendingTarget = null;
                }
            }

            // --- Door interpolation ---
            const doorEntity = DoorManager.getDoor(roomId);
            if (doorEntity) {
                rs.doorAngle = dampedLerp(rs.doorAngle, rs.doorTarget, 0.06, delta);
                doorEntity.pivot.rotation.y = rs.doorAngle;
            }

            // Door auto-close timer
            if (rs.doorTimer > 0) {
                rs.doorTimer -= delta;
                if (rs.doorTimer <= 0) {
                    rs.doorTarget = 0;
                }
            }

            // --- Avatar animations ---
            const avatars = AvatarPool.getActiveInRoom(roomId);
            avatars.forEach(avatar => {
                const ud = avatar.userData;
                const time = SimulationClock.elapsed + (ud.animOffset || 0);

                if (ud.state === 'walking') {
                    // Walk from entrance to desk
                    ud.walkProgress += delta * SIM_CONFIG.animation.WALK_SPEED * 0.3;

                    if (ud.walkProgress >= 1.0) {
                        ud.walkProgress = 1.0;
                        ud.state = 'seated';
                        // Snap to final position
                        avatar.position.x = ud.walkTarget.x;
                        avatar.position.z = ud.walkTarget.z;
                    } else {
                        // Interpolate position
                        const t = this._easeInOutQuad(ud.walkProgress);
                        avatar.position.x = ud.walkStart.x + (ud.walkTarget.x - ud.walkStart.x) * t;
                        avatar.position.z = ud.walkStart.z + (ud.walkTarget.z - ud.walkStart.z) * t;

                        // Face walking direction
                        const dx = ud.walkTarget.x - ud.walkStart.x;
                        const dz = ud.walkTarget.z - ud.walkStart.z;
                        avatar.rotation.y = Math.atan2(dx, dz);

                        // Walking leg animation
                        if (ud.limbs) {
                            const walkCycle = ud.walkProgress * 20;
                            ud.limbs.leftLeg.rotation.x = Math.sin(walkCycle) * 0.6;
                            ud.limbs.rightLeg.rotation.x = -Math.sin(walkCycle) * 0.6;
                            ud.limbs.leftArm.rotation.x = -Math.sin(walkCycle) * 0.4;
                            ud.limbs.rightArm.rotation.x = Math.sin(walkCycle) * 0.4;
                        }
                    }
                }
                else if (ud.state === 'seated') {
                    // Idle breathing bob
                    avatar.position.y = ud.baseY +
                        Math.sin(time * 1.5) * SIM_CONFIG.animation.IDLE_BOB_AMPLITUDE;

                    // Typing arms
                    if (ud.limbs) {
                        ud.limbs.leftArm.rotation.x = Math.sin(time * SIM_CONFIG.animation.TYPING_SPEED) * 0.15;
                        ud.limbs.rightArm.rotation.x = -Math.sin(time * SIM_CONFIG.animation.TYPING_SPEED + 0.5) * 0.15;
                        ud.limbs.leftLeg.rotation.x = 0;
                        ud.limbs.rightLeg.rotation.x = 0;
                    }

                    // Head turn
                    if (ud.limbs?.head) {
                        ud.limbs.head.rotation.y = Math.sin(time * 0.3 + ud.poolIndex * 0.7) * 0.3;
                    }
                }
                else if (ud.state === 'exiting') {
                    // Walk back to entrance
                    ud.walkProgress += delta * SIM_CONFIG.animation.WALK_SPEED * 0.4;

                    if (ud.walkProgress >= 1.0) {
                        // Reached door — release avatar
                        AvatarPool.release(ud.poolIndex);
                    } else {
                        const t = this._easeInOutQuad(ud.walkProgress);
                        avatar.position.x = ud.walkStart.x + (ud.walkTarget.x - ud.walkStart.x) * t;
                        avatar.position.z = ud.walkStart.z + (ud.walkTarget.z - ud.walkStart.z) * t;

                        // Face exit direction
                        const dx = ud.walkTarget.x - ud.walkStart.x;
                        const dz = ud.walkTarget.z - ud.walkStart.z;
                        avatar.rotation.y = Math.atan2(dx, dz);

                        // Walking animation
                        if (ud.limbs) {
                            const walkCycle = ud.walkProgress * 20;
                            ud.limbs.leftLeg.rotation.x = Math.sin(walkCycle) * 0.6;
                            ud.limbs.rightLeg.rotation.x = -Math.sin(walkCycle) * 0.6;
                            ud.limbs.leftArm.rotation.x = -Math.sin(walkCycle) * 0.4;
                            ud.limbs.rightArm.rotation.x = Math.sin(walkCycle) * 0.4;
                        }
                    }
                }
            });

            // --- Legacy occupant mesh visibility (backward compat) ---
            const indicators = this._app.occupantMeshes?.get(roomId);
            if (indicators) {
                const poolCount = AvatarPool.countInRoom(roomId);
                // Hide legacy indicators if pool avatars are active
                indicators.forEach(person => {
                    person.visible = false;
                });
            }

            // --- Window glow based on occupancy ---
            const isOccupied = AvatarPool.countInRoom(roomId) > 0 || rs.currentCount > 0;
            const floorIndex = parseInt(roomId.split('_')[0], 10);
            if (!isNaN(floorIndex)) {
                this._app.windowGlows?.forEach(glow => {
                    if (glow.userData.floorIndex === floorIndex) {
                        const brightness = isOccupied ? 0.4 : 0.05;
                        glow.material.opacity = dampedLerp(glow.material.opacity, brightness, 0.1, delta);
                    }
                });
            }
        });
    }

    /**
     * Apply a target avatar count change — acquire or release avatars.
     */
    _applyTargetChange(rs, newTarget) {
        const currentPoolCount = AvatarPool.countInRoom(rs.roomId);
        const diff = newTarget - currentPoolCount;
        const floorIndex = parseInt(rs.roomId.split('_')[0], 10);
        const floorGroup = this._app.floorGroups[floorIndex];

        if (diff > 0 && rs.roomDef) {
            // Need more avatars — acquire from pool
            const entrance = DoorManager.getEntrancePosition(rs.roomId) || {
                x: rs.roomDef.x + 1.5,
                z: rs.roomDef.z - 1.0,
            };

            for (let i = 0; i < diff; i++) {
                const deskIdx = (currentPoolCount + i) % rs.deskPositions.length;
                const desk = rs.deskPositions[deskIdx];
                if (desk && floorGroup) {
                    AvatarPool.acquire(
                        rs.roomId,
                        floorGroup,
                        entrance,
                        desk
                    );
                }
            }
        }
        else if (diff < 0) {
            // Need fewer avatars — release excess (walking them to exit first)
            const avatars = AvatarPool.getActiveInRoom(rs.roomId);
            const toRemove = Math.abs(diff);
            let removed = 0;

            for (const avatar of avatars) {
                if (removed >= toRemove) break;
                if (avatar.userData.state !== 'exiting') {
                    // Set to exiting state (walk back to door)
                    const entrance = DoorManager.getEntrancePosition(rs.roomId) || {
                        x: rs.roomDef.x + 1.5,
                        z: rs.roomDef.z - 1.0,
                    };

                    avatar.userData.state = 'exiting';
                    avatar.userData.walkStart = {
                        x: avatar.position.x,
                        z: avatar.position.z,
                    };
                    avatar.userData.walkTarget = entrance;
                    avatar.userData.walkProgress = 0;
                    removed++;
                }
            }
        }

        rs.currentCount = newTarget;
    }

    /**
     * Ease-in-out quad for smooth walking.
     */
    _easeInOutQuad(t) {
        return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
    }

    dispose() {
        AvatarPool.dispose();
        DoorManager.dispose();
        this._roomStates.clear();
        this._app = null;
    }
}

export const OccupancyEngine = new OccupancyEngineImpl();
