// ═══════════════════════════════════════════════════════════════
// DebugOverlay.js — Research-Grade Debug Information Overlay
// ═══════════════════════════════════════════════════════════════
// Uniform API: init(), onRoomStateChanged(), tick(delta), dispose()
//
// Press D to toggle. Displays floating debug sprites above each room:
//   Room ID | Temp | Humidity | Occupancy | Probability | AI Decision
//   Latency | Dirty | Animation Queue | Door | Window | Fan | Power | FPS
//
// During viva: press D → everything appears → examiners see internal state.

import * as THREE from 'three';
import { SIM_CONFIG } from '../core/SimConfig.js';
import { VisualStateStore } from '../core/VisualStateStore.js';
import { SimulationClock } from '../core/SimulationClock.js';
import { SceneRegistry, EntityType } from '../core/SceneRegistry.js';
import { eventBus } from '../core/EventBus.js';
import { RoomController } from '../controllers/RoomController.js';
import { HeroEngine } from '../engines/heroEngine.js';

class DebugOverlayImpl {
    constructor() {
        this._app = null;
        this._sprites = new Map();    // roomId → THREE.Sprite
        this._canvases = new Map();   // roomId → canvas element
        this._visible = false;
        this._fpsFrames = 0;
        this._fpsTime = 0;
        this._fps = 60;
        this._globalSprite = null;    // Global performance overlay
        this._globalCanvas = null;
    }

    init(app) {
        this._app = app;
        this._createGlobalOverlay();
    }

    /**
     * Create a global FPS / system status overlay in screen space.
     */
    _createGlobalOverlay() {
        // We'll use a DOM-based overlay for the global stats
        // since it's easier to read and doesn't require camera projection
        let overlay = document.getElementById('debug-overlay-global');
        if (!overlay) {
            overlay = document.createElement('div');
            overlay.id = 'debug-overlay-global';
            overlay.style.cssText = `
                position: fixed; top: 8px; left: 8px; z-index: 9999;
                background: rgba(0,0,0,0.85); color: #10b981;
                font-family: 'Courier New', monospace; font-size: 11px;
                padding: 8px 12px; border-radius: 6px;
                border: 1px solid rgba(16,185,129,0.3);
                pointer-events: none; display: none;
                line-height: 1.5; white-space: pre;
            `;
            document.body.appendChild(overlay);
        }
        this._globalOverlay = overlay;
    }

    /**
     * Get or create a debug sprite for a room.
     */
    _getOrCreateSprite(roomId) {
        if (this._sprites.has(roomId)) {
            return { sprite: this._sprites.get(roomId), canvas: this._canvases.get(roomId) };
        }

        const canvas = document.createElement('canvas');
        canvas.width = 512;
        canvas.height = 256;

        const texture = new THREE.CanvasTexture(canvas);
        texture.needsUpdate = true;

        const material = new THREE.SpriteMaterial({
            map: texture,
            transparent: true,
            depthTest: false,
            depthWrite: false,
        });

        const sprite = new THREE.Sprite(material);
        sprite.scale.set(8, 4, 1);
        sprite.visible = false;

        // Position above the room
        const roomData = this._app?.roomData?.get(roomId);
        if (roomData?.def) {
            const def = roomData.def;
            const floorIndex = roomData.floorIndex ?? parseInt(roomId.split('_')[0], 10);
            const y = floorIndex * 3.8 + 5.5;
            sprite.position.set(
                def.x + def.w / 2,
                y,
                def.z + def.d / 2
            );
        }

        // Add to the appropriate floor group
        const floorIndex = parseInt(roomId.split('_')[0], 10);
        const floorGroup = this._app?.floorGroups?.[floorIndex];
        if (floorGroup) {
            floorGroup.add(sprite);
        } else {
            this._app?.scene?.add(sprite);
        }

        this._sprites.set(roomId, sprite);
        this._canvases.set(roomId, canvas);

        SceneRegistry.register(
            `${EntityType.DEBUG_SPRITE}_${roomId}`,
            sprite,
            { roomId, floorId: floorIndex, type: EntityType.DEBUG_SPRITE }
        );

        return { sprite, canvas };
    }

    /**
     * Render debug text onto a room's canvas sprite.
     */
    _renderRoomDebug(roomId, canvas, sprite) {
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, 512, 256);

        const vs = VisualStateStore.get(roomId);
        const rv = RoomController.getRoomVisuals(roomId);

        // Background
        ctx.fillStyle = 'rgba(0, 0, 0, 0.82)';
        ctx.beginPath();
        if (ctx.roundRect) ctx.roundRect(4, 4, 504, 248, 12);
        else ctx.fillRect(4, 4, 504, 248);
        ctx.fill();

        // Border
        const isHero = vs?.isHeroRoom;
        ctx.strokeStyle = isHero ? '#10b981' : 'rgba(100,160,255,0.5)';
        ctx.lineWidth = 2;
        ctx.stroke();

        // Title
        ctx.fillStyle = isHero ? '#10b981' : '#60a5fa';
        ctx.font = 'bold 16px Courier New';
        ctx.fillText(isHero ? `🔴 ${roomId} [LIVE]` : roomId, 16, 28);

        // Debug lines
        ctx.fillStyle = '#e2e8f0';
        ctx.font = '12px Courier New';
        const lines = [];

        // Row 1: Sensors
        const temp = vs?.lastUpdateTimestamp ? 'FRESH' : 'STALE';
        lines.push(`Prob: ${(vs?.occupancyProbability * 100 || 0).toFixed(1)}%  Occ: ${vs?.targetAvatarCount || 0}  State: ${vs?.avatarState || 'none'}`);

        // Row 2: AI Decision
        lines.push(`AI: ${vs?.controlMode || '—'}  Light: ${vs?.lightAction || '—'}  HVAC: ${vs?.hvacVisualMode || '—'}`);

        // Row 3: Visual state
        const doorDeg = rv ? (rv.doorAngle * 57.3).toFixed(0) : '0';
        const winDeg = rv ? (rv.windowAngle * 57.3).toFixed(0) : '0';
        lines.push(`Door: ${doorDeg}°  Win: ${winDeg}°  Fan: ${(vs?.fanSpeed * 100 || 0).toFixed(0)}%  Glow: ${rv?.monitorGlow?.toFixed(2) || '0'}`);

        // Row 4: Energy
        lines.push(`Power: ${(vs?.powerWatts || 0).toFixed(0)}W  Brightness: ${(vs?.lightTarget * 100 || 0).toFixed(0)}%`);

        // Row 5: Timing
        if (isHero) {
            const heroMetrics = HeroEngine.getMetrics();
            lines.push(`Board data age: ${heroMetrics.latencyMs ?? "—"} ms  Syncs: ${heroMetrics.syncCount}  ${heroMetrics.pulseActive ? '● PULSE' : '○ idle'}`);
        } else {
            lines.push(`Dirty: ${vs?.isDirty ? 'YES' : 'no'}  Updated: ${vs?.lastUpdateTimestamp?.split('T')[1]?.slice(0,8) || '—'}`);
        }

        lines.forEach((line, i) => {
            ctx.fillText(line, 16, 52 + i * 18);
        });

        // Mark texture as needing update
        sprite.material.map.needsUpdate = true;
    }

    /**
     * Render the global performance overlay.
     */
    _renderGlobalOverlay() {
        if (!this._globalOverlay) return;

        const registryStats = SceneRegistry.getStats();
        const heroMetrics = HeroEngine.getMetrics();
        const dirtyCount = VisualStateStore.dirtyCount();
        const recentEvents = eventBus.getRecentEvents(5);

        let text = '';
        text += `┌─── SIMULATION DEBUG ───────────────────┐\n`;
        text += `│ FPS: ${this._fps.toFixed(0).padStart(4)}  Time: ${SimulationClock.formattedTime}  Speed: ${SimulationClock.speed}x${SimulationClock.paused ? ' ⏸' : ''}\n`;
        text += `│ Dirty Rooms: ${dirtyCount}  Entities: ${SceneRegistry.size}\n`;
        text += `│ Registry: ${Object.entries(registryStats).map(([k,v]) => `${k}:${v}`).join(' ')}\n`;
        text += `│ Hero: data age=${heroMetrics.latencyMs ?? "—"} ms  Syncs=${heroMetrics.syncCount}\n`;
        text += `├─── Recent Events ─────────────────────┤\n`;
        recentEvents.forEach(e => {
            text += `│ ${e.event}${e.roomId ? ` [${e.roomId}]` : ''}\n`;
        });
        text += `└───────────────────────────────────────┘`;

        this._globalOverlay.textContent = text;
    }

    onRoomStateChanged({ roomId }) {
        // Rooms auto-tracked when debug is visible
    }

    tick(delta) {
        // FPS counter
        this._fpsFrames++;
        this._fpsTime += delta;
        if (this._fpsTime >= 1.0) {
            this._fps = this._fpsFrames / this._fpsTime;
            this._fpsFrames = 0;
            this._fpsTime = 0;
        }

        // Check if debug mode changed
        const shouldBeVisible = SIM_CONFIG.debug;

        if (shouldBeVisible !== this._visible) {
            this._visible = shouldBeVisible;
            this._sprites.forEach(sprite => { sprite.visible = shouldBeVisible; });
            if (this._globalOverlay) {
                this._globalOverlay.style.display = shouldBeVisible ? 'block' : 'none';
            }
        }

        if (!this._visible) return;

        // Update room debug sprites (throttled to ~4 Hz to save performance)
        if (this._fpsFrames % 15 === 0) {
            // Update existing tracked rooms
            VisualStateStore.getAll().forEach((vs, roomId) => {
                const { sprite, canvas } = this._getOrCreateSprite(roomId);
                sprite.visible = true;
                this._renderRoomDebug(roomId, canvas, sprite);
            });

            this._renderGlobalOverlay();
        }
    }

    dispose() {
        this._sprites.forEach((sprite, roomId) => {
            sprite.parent?.remove(sprite);
            sprite.material.map.dispose();
            sprite.material.dispose();
        });
        this._sprites.clear();
        this._canvases.clear();

        if (this._globalOverlay) {
            this._globalOverlay.remove();
            this._globalOverlay = null;
        }
        this._app = null;
    }
}

export const DebugOverlay = new DebugOverlayImpl();
