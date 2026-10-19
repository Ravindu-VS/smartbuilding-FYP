// ═══════════════════════════════════════════════════════════════
// VisualStateStore.js — Derived Visual State Per Room
// ═══════════════════════════════════════════════════════════════
// Visual state is DERIVED from backend state. Never flows upward.
// Backend State (read-only) → Visual State (derived) → Renderer

import { SIM_CONFIG } from './SimConfig.js';
import { eventBus, Events } from './EventBus.js';

/**
 * Compute a lightweight hash from selected fields of a room state object.
 * Much faster than JSON.stringify comparison.
 */
export function computeStateHash(roomData) {
    const parts = [];
    for (const fieldPath of SIM_CONFIG.hashFields) {
        const keys = fieldPath.split('.');
        let val = roomData;
        for (const k of keys) {
            val = val?.[k];
            if (val === undefined) break;
        }
        // Round numbers to avoid floating point noise
        if (typeof val === 'number') {
            parts.push(Math.round(val * 100));
        } else if (typeof val === 'boolean') {
            parts.push(val ? 1 : 0);
        } else {
            parts.push(val ?? '');
        }
    }
    return parts.join('|');
}

/**
 * Per-room visual state derived from backend state.
 */
class RoomVisualState {
    constructor(roomId) {
        this.roomId = roomId;

        // Avatar visual state
        this.avatarState = 'none';        // none | approaching | entering | working | leaving
        this.targetAvatarCount = 0;
        this.activeAvatarCount = 0;
        this.previousOccupancy = 0;

        // Door visual state
        this.doorAngle = 0;               // 0 = closed, ~1.2 rad = open
        this.doorTarget = 0;

        // Window visual state
        this.windowAngle = 0;             // 0 = closed, ~0.26 rad (15°) = open
        this.windowTarget = 0;

        // Lighting visual state
        this.lightBrightness = 0;         // 0.0 – 1.0
        this.lightTarget = 0;
        this.lightAction = 'OFF';

        // HVAC visual state
        this.hvacVisualMode = 'off';      // off | cooling | heating | ventilation | eco
        this.fanSpeed = 0;                // 0.0 – 1.0

        // Energy & Thermal
        this.powerWatts = 0;
        this.temperature = 24.0;
        this.pmv = 0; // Predicted Mean Vote (-3 to +3)

        // AI state (from backend, stored for debug/display)
        this.occupancyProbability = 0;
        this.predictedOccupancy = 0;
        this.controlMode = '';

        // Timing
        this.lastUpdateTimestamp = null;
        this.lastBackendHash = '';
        this.isDirty = false;

        // Hero mode
        this.isHeroRoom = false;
        this.heroSyncLatencyMs = 0;
    }

    /**
     * Derive visual state from backend room data.
     * @param {object} backendState — Raw room state from SSE
     * @returns {boolean} true if state actually changed
     */
    deriveFrom(backendState) {
        const newHash = computeStateHash(backendState);
        if (newHash === this.lastBackendHash) {
            this.isDirty = false;
            return false;
        }

        this.lastBackendHash = newHash;
        this.isDirty = true;
        this.lastUpdateTimestamp = backendState.timestamp || null;

        // --- Occupancy ---
        const prevOcc = this.targetAvatarCount;
        this.occupancyProbability = backendState.ai?.occupancy_probability ?? 0;
        this.predictedOccupancy = backendState.ai?.predicted_occupancy ?? 0;
        this.targetAvatarCount = backendState.ground_truth?.true_occupancy ?? backendState.sensors?.occupancy ?? backendState.ai?.predicted_occupancy ?? 0;

        // Determine avatar state from probability thresholds
        const prob = this.occupancyProbability;
        const thresholds = SIM_CONFIG.occupancy;
        if (prob < thresholds.NO_OCCUPANCY_THRESHOLD) {
            this.avatarState = 'none';
        } else if (prob < thresholds.ENTER_THRESHOLD) {
            this.avatarState = 'approaching';
        } else if (prob < thresholds.WORK_THRESHOLD) {
            this.avatarState = 'entering';
        } else {
            this.avatarState = 'working';
        }

        // Track transitions for door logic
        this.previousOccupancy = prevOcc;

        // --- Lighting ---
        const lightAction = backendState.control?.light_action ||
                            backendState.control?.light ||
                            (backendState.device_state?.light_on ? 'ON' : 'OFF');
        this.lightAction = lightAction;
        if (lightAction === 'ON' || lightAction === 'FULL') {
            this.lightTarget = 1.0;
        } else if (lightAction === 'DIM') {
            this.lightTarget = 0.4;
        } else {
            this.lightTarget = 0.0;
        }

        // --- HVAC ---
        const hvacAction = backendState.control?.hvac_action ||
                           backendState.control?.hvac ||
                           backendState.device_state?.hvac_mode || 'off';
        const normalizedHvac = hvacAction.toUpperCase();
        if (normalizedHvac === 'COOLING' || normalizedHvac === 'NORMAL') {
            this.hvacVisualMode = 'cooling';
            this.windowTarget = 0;
        } else if (normalizedHvac === 'HEATING') {
            this.hvacVisualMode = 'heating';
            this.windowTarget = 0;
        } else if (normalizedHvac === 'LOW') {
            this.hvacVisualMode = 'ventilation';
            this.windowTarget = 0;
        } else if (normalizedHvac === 'VENTILATION' || normalizedHvac === 'ECO') {
            this.hvacVisualMode = normalizedHvac.toLowerCase();
            this.windowTarget = 0.26; // 15 degrees
        } else {
            this.hvacVisualMode = 'off';
            this.windowTarget = 0;
        }

        this.fanSpeed = (backendState.device_state?.hvac_speed ?? 0) / 100;
        this.controlMode = backendState.control?.control_mode || '';

        // --- Energy & Thermal ---
        this.powerWatts = backendState.energy?.estimated_power_watts ?? 0;
        this.temperature = backendState.sensors?.temperature ?? backendState.temperature ?? 24.0;
        
        // Simple PMV approximation based on temperature (assuming 24C is neutral 0)
        // 20C -> -2, 22C -> -1, 24C -> 0, 26C -> +1, 28C -> +2
        this.pmv = (this.temperature - 24.0) * 0.5;
        this.pmv = Math.max(-3, Math.min(3, this.pmv));

        // --- Hero Room ---
        this.isHeroRoom = (backendState.source === 'hardware' || backendState.isLive === true);
        if (this.isHeroRoom && this.lastUpdateTimestamp) {
            try {
                this.heroSyncLatencyMs = Date.now() - new Date(this.lastUpdateTimestamp).getTime();
            } catch { this.heroSyncLatencyMs = 0; }
        }

        return true;
    }
}

/**
 * Store for all room visual states.
 */
class VisualStateStoreImpl {
    constructor() {
        this._rooms = new Map();
    }

    /**
     * Get or create visual state for a room.
     * @param {string} roomId
     * @returns {RoomVisualState}
     */
    get(roomId) {
        if (!this._rooms.has(roomId)) {
            this._rooms.set(roomId, new RoomVisualState(roomId));
        }
        return this._rooms.get(roomId);
    }

    /**
     * Process a backend state update for a room.
     * Returns true if the visual state changed.
     */
    processBackendUpdate(roomId, backendState, previousBackendState) {
        const visual = this.get(roomId);
        return visual.deriveFrom(backendState);
    }

    /**
     * Get all room visual states (for debug).
     */
    getAll() {
        return this._rooms;
    }

    /**
     * Get count of dirty rooms.
     */
    dirtyCount() {
        let count = 0;
        this._rooms.forEach(v => { if (v.isDirty) count++; });
        return count;
    }
}

// Singleton
export const VisualStateStore = new VisualStateStoreImpl();
