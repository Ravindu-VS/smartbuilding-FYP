// ═══════════════════════════════════════════════════════════════
// SimulationClock.js — Pausable, Replayable Simulation Time
// ═══════════════════════════════════════════════════════════════
// ALL animation code reads time from this clock, never Date.now().
// Supports pause, speed control, and future replay/rewind.

import { eventBus, Events } from './EventBus.js';

class SimulationClockImpl {
    constructor() {
        this._simHour = 6.0;           // Current simulation hour (0–24)
        this._speed = 1.0;             // Playback speed multiplier
        this._paused = false;
        this._lastFrameTime = null;    // performance.now() of last tick
        this._totalElapsed = 0;        // Total simulation seconds elapsed
        this._backendTime = null;      // Last backend-provided time string
    }

    /**
     * Called every frame from the animate() loop.
     * @param {number} now — performance.now() value
     * @returns {number} delta in seconds (simulation time, respecting speed)
     */
    tick(now) {
        if (this._lastFrameTime === null) {
            this._lastFrameTime = now;
            return 0;
        }

        const rawDelta = (now - this._lastFrameTime) / 1000; // real seconds
        this._lastFrameTime = now;

        if (this._paused) return 0;

        const simDelta = rawDelta * this._speed;
        this._totalElapsed += simDelta;

        return simDelta;
    }

    /**
     * Set simulation hour from backend (authoritative).
     * @param {number} hour — 0 to 24
     */
    setFromBackend(hour) {
        const previousHour = this._simHour;
        this._simHour = hour;

        if (Math.abs(previousHour - hour) > 0.01) {
            eventBus.emit(Events.TIME_CHANGED, {
                hour: this._simHour,
                previousHour,
                source: 'backend',
            });
        }
    }

    /**
     * Parse a backend time string (e.g., "14:35:00") and set the clock.
     * @param {string} timeStr
     */
    parseBackendTime(timeStr) {
        if (!timeStr || timeStr === 'null' || timeStr === '--:--:--') return;

        this._backendTime = timeStr;
        let str = timeStr;
        if (str.includes('T')) str = str.split('T')[1];
        const parts = str.split(':');
        if (parts.length >= 2) {
            let hour = parseInt(parts[0], 10) + parseInt(parts[1], 10) / 60;
            hour = hour % 24; // Ensure hour wraps around 24 for endless cycles
            this.setFromBackend(hour);
        }
    }

    /** Current simulation hour (0–24). */
    get hour() { return this._simHour; }

    /** Total elapsed simulation seconds. */
    get elapsed() { return this._totalElapsed; }

    /** Current playback speed. */
    get speed() { return this._speed; }
    set speed(val) { this._speed = Math.max(0, val); }

    /** Whether the simulation is paused. */
    get paused() { return this._paused; }

    /** Pause/resume. */
    pause() { this._paused = true; }
    resume() { this._paused = false; }
    togglePause() { this._paused = !this._paused; }

    /** Last raw backend time string. */
    get backendTimeString() { return this._backendTime; }

    /** Get formatted time for display (e.g., "14:35"). */
    get formattedTime() {
        const h = Math.floor(this._simHour);
        const m = Math.floor((this._simHour - h) * 60);
        return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}`;
    }

    /** Is it daytime? */
    get isDaytime() { return this._simHour >= 6 && this._simHour < 18; }

    /** Is it night? */
    get isNight() { return !this.isDaytime; }
}

// Singleton
export const SimulationClock = new SimulationClockImpl();
