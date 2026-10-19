// ═══════════════════════════════════════════════════════════════
// EventBus.js — Lightweight Pub/Sub Simulation Event Bus
// ═══════════════════════════════════════════════════════════════
// All engines subscribe to events. No engine calls another directly.
// This makes adding Phase 2–13 modules trivial.

class SimEventBus {
    constructor() {
        this._listeners = new Map();
        this._eventLog = [];       // Last N events for debug
        this._maxLogSize = 100;
    }

    /**
     * Subscribe to an event.
     * @param {string} eventName
     * @param {Function} callback
     * @returns {Function} unsubscribe function
     */
    on(eventName, callback) {
        if (!this._listeners.has(eventName)) {
            this._listeners.set(eventName, new Set());
        }
        this._listeners.get(eventName).add(callback);

        // Return unsubscribe function for clean disposal
        return () => this.off(eventName, callback);
    }

    /**
     * Unsubscribe from an event.
     */
    off(eventName, callback) {
        const listeners = this._listeners.get(eventName);
        if (listeners) {
            listeners.delete(callback);
            if (listeners.size === 0) {
                this._listeners.delete(eventName);
            }
        }
    }

    /**
     * Emit an event to all subscribers.
     * @param {string} eventName
     * @param {*} data
     */
    emit(eventName, data) {
        // Log for debug overlay
        this._eventLog.push({
            event: eventName,
            timestamp: performance.now(),
            roomId: data?.roomId || null,
        });
        if (this._eventLog.length > this._maxLogSize) {
            this._eventLog.shift();
        }

        const listeners = this._listeners.get(eventName);
        if (listeners) {
            listeners.forEach(callback => {
                try {
                    callback(data);
                } catch (err) {
                    console.error(`[EventBus] Error in ${eventName} handler:`, err);
                }
            });
        }
    }

    /**
     * Get recent event log (for debug overlay).
     */
    getRecentEvents(count = 10) {
        return this._eventLog.slice(-count);
    }

    /**
     * Get subscriber count for an event (for debug).
     */
    listenerCount(eventName) {
        return this._listeners.has(eventName) ? this._listeners.get(eventName).size : 0;
    }

    /**
     * Remove all listeners (for disposal).
     */
    dispose() {
        this._listeners.clear();
        this._eventLog = [];
    }
}

// Singleton instance
export const eventBus = new SimEventBus();

// Event name constants — prevents typos
export const Events = {
    ROOM_STATE_CHANGED: 'RoomStateChanged',
    AVATAR_ENTERED: 'AvatarEntered',
    AVATAR_EXITED: 'AvatarExited',
    DOOR_OPENED: 'DoorOpened',
    DOOR_CLOSED: 'DoorClosed',
    LIGHTING_CHANGED: 'LightingChanged',
    HVAC_CHANGED: 'HVACChanged',
    WINDOW_OPENED: 'WindowOpened',
    WINDOW_CLOSED: 'WindowClosed',
    HERO_ROOM_SYNC: 'HeroRoomSync',
    AI_DECISION: 'AIDecision',
    ENERGY_CHANGED: 'EnergyChanged',
    TIME_CHANGED: 'TimeChanged',
};
