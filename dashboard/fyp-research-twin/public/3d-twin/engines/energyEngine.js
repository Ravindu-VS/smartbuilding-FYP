// ═══════════════════════════════════════════════════════════════
// EnergyEngine.js — Energy Flow Visualization (Placeholder)
// ═══════════════════════════════════════════════════════════════
// Uniform API: init(), onRoomStateChanged(), tick(delta), dispose()
// Will be expanded in Phase 4 with Bezier energy flow curves.

import { VisualStateStore } from '../core/VisualStateStore.js';
import { eventBus, Events } from '../core/EventBus.js';

class EnergyEngineImpl {
    constructor() {
        this._app = null;
        this._roomPower = new Map(); // roomId → power watts
    }

    init(app) {
        this._app = app;
    }

    onRoomStateChanged({ roomId, backendState, visualState }) {
        const prevPower = this._roomPower.get(roomId) || 0;
        const newPower = visualState.powerWatts;

        if (Math.abs(prevPower - newPower) > 5) {
            this._roomPower.set(roomId, newPower);
            eventBus.emit(Events.ENERGY_CHANGED, {
                roomId,
                powerWatts: newPower,
                previousPowerWatts: prevPower,
            });
        }
    }

    tick(delta) {
        // Phase 4: Animate energy flow bezier curves here
    }

    dispose() {
        this._roomPower.clear();
        this._app = null;
    }
}

export const EnergyEngine = new EnergyEngineImpl();
