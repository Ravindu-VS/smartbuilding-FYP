// ═══════════════════════════════════════════════════════════════
// EngineManager.js — Unified Engine Lifecycle Manager
// ═══════════════════════════════════════════════════════════════
// Every engine exposes: init(), onRoomStateChanged(), tick(delta), dispose()
// EngineManager registers them, routes events, and ticks them each frame.
// Adding a new engine NEVER requires touching app.js.

import { eventBus, Events } from './EventBus.js';

class EngineManagerImpl {
    constructor() {
        this._engines = new Map();   // name → engine instance
        this._tickOrder = [];        // ordered list of engine names for tick()
        this._initialized = false;
        this._unsubscribers = [];
    }

    /**
     * Register an engine.
     * @param {string} name — unique engine name
     * @param {object} engine — must expose init(), onRoomStateChanged(), tick(delta), dispose()
     */
    register(name, engine) {
        // Validate engine interface
        const required = ['init', 'onRoomStateChanged', 'tick', 'dispose'];
        for (const method of required) {
            if (typeof engine[method] !== 'function') {
                console.warn(`[EngineManager] Engine "${name}" is missing required method: ${method}. Adding no-op.`);
                engine[method] = () => {};
            }
        }

        this._engines.set(name, engine);
        this._tickOrder.push(name);
        console.log(`[EngineManager] Registered engine: ${name}`);
    }

    /**
     * Initialize all engines and subscribe to the event bus.
     * @param {object} app — SmartBuildingTwin instance (for scene access)
     */
    initAll(app) {
        if (this._initialized) return;

        // Initialize each engine
        this._engines.forEach((engine, name) => {
            try {
                engine.init(app);
                console.log(`[EngineManager] Initialized: ${name}`);
            } catch (err) {
                console.error(`[EngineManager] Failed to init ${name}:`, err);
            }
        });

        // Subscribe to RoomStateChanged and fan out to all engines
        const unsub = eventBus.on(Events.ROOM_STATE_CHANGED, (data) => {
            this._engines.forEach((engine, name) => {
                try {
                    engine.onRoomStateChanged(data);
                } catch (err) {
                    console.error(`[EngineManager] ${name}.onRoomStateChanged error:`, err);
                }
            });
        });
        this._unsubscribers.push(unsub);

        this._initialized = true;
        console.log(`[EngineManager] All ${this._engines.size} engines initialized.`);
    }

    /**
     * Tick all engines (called every frame from animate loop).
     * @param {number} delta — simulation delta in seconds
     */
    tick(delta) {
        for (const name of this._tickOrder) {
            const engine = this._engines.get(name);
            if (engine) {
                try {
                    engine.tick(delta);
                } catch (err) {
                    console.error(`[EngineManager] ${name}.tick error:`, err);
                }
            }
        }
    }

    /**
     * Get a registered engine by name.
     */
    getEngine(name) {
        return this._engines.get(name);
    }

    /**
     * Get all engine names (for debug).
     */
    getEngineNames() {
        return Array.from(this._engines.keys());
    }

    /**
     * Dispose all engines and unsubscribe from events.
     */
    dispose() {
        this._unsubscribers.forEach(unsub => unsub());
        this._unsubscribers = [];

        this._engines.forEach((engine, name) => {
            try {
                engine.dispose();
            } catch (err) {
                console.error(`[EngineManager] ${name}.dispose error:`, err);
            }
        });

        this._engines.clear();
        this._tickOrder = [];
        this._initialized = false;
    }
}

// Singleton
export const EngineManager = new EngineManagerImpl();
