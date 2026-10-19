// ═══════════════════════════════════════════════════════════════
// AnimationQueue.js — Cancellable Animation Sequences
// ═══════════════════════════════════════════════════════════════
// Manages ordered animation steps per entity (avatar, door, etc).
// Supports cancellation: when backend state changes rapidly,
// queued animations are cleared and the entity transitions
// directly to the latest target state.

import { easeInOutQuad } from './Tween.js';

/**
 * A single animation step.
 */
class AnimStep {
    /**
     * @param {string} type — Step type (e.g., 'walk', 'rotate', 'wait', 'callback')
     * @param {object} params — Type-specific parameters
     * @param {number} duration — Duration in seconds
     */
    constructor(type, params, duration) {
        this.type = type;
        this.params = params;
        this.duration = duration;
        this.elapsed = 0;
        this.completed = false;
    }

    /**
     * Advance the step by delta seconds.
     * @returns {number} progress 0.0 – 1.0
     */
    advance(delta) {
        this.elapsed += delta;
        const progress = Math.min(this.elapsed / this.duration, 1.0);
        if (progress >= 1.0) {
            this.completed = true;
        }
        return easeInOutQuad(progress);
    }
}

/**
 * Animation queue for a single entity (e.g., one avatar, one door).
 */
export class AnimationQueue {
    constructor(entityId) {
        this.entityId = entityId;
        this._steps = [];
        this._currentIndex = 0;
        this._cancelled = false;
        this._onComplete = null;
    }

    /**
     * Add a step to the queue.
     * @param {string} type
     * @param {object} params
     * @param {number} duration — seconds
     */
    enqueue(type, params, duration) {
        this._steps.push(new AnimStep(type, params, duration));
        return this;
    }

    /**
     * Add a wait/delay step.
     * @param {number} seconds
     */
    wait(seconds) {
        return this.enqueue('wait', {}, seconds);
    }

    /**
     * Add a callback step (fires immediately, zero duration).
     * @param {Function} fn
     */
    callback(fn) {
        return this.enqueue('callback', { fn }, 0.001);
    }

    /**
     * Set completion callback.
     */
    onComplete(fn) {
        this._onComplete = fn;
        return this;
    }

    /**
     * Cancel all remaining steps. The entity should transition to its final state.
     */
    cancel() {
        this._cancelled = true;
        this._steps = [];
        this._currentIndex = 0;
    }

    /**
     * Whether the queue is cancelled.
     */
    get isCancelled() { return this._cancelled; }

    /**
     * Whether all steps are complete.
     */
    get isComplete() {
        return this._cancelled || this._currentIndex >= this._steps.length;
    }

    /**
     * Get the current step.
     */
    get currentStep() {
        if (this._currentIndex < this._steps.length) {
            return this._steps[this._currentIndex];
        }
        return null;
    }

    /**
     * Advance the queue by delta seconds.
     * @returns {AnimStep|null} the current step (so the caller can process it)
     */
    tick(delta) {
        if (this.isComplete) {
            if (this._onComplete) {
                this._onComplete();
                this._onComplete = null;
            }
            return null;
        }

        const step = this._steps[this._currentIndex];
        const progress = step.advance(delta);

        // Handle callback steps
        if (step.type === 'callback' && step.params.fn) {
            step.params.fn();
            step.params.fn = null; // Prevent double-fire
        }

        // Move to next step when current completes
        if (step.completed) {
            this._currentIndex++;
        }

        return { step, progress };
    }

    /**
     * Get queue length (for debug).
     */
    get length() { return this._steps.length; }
    get remaining() { return Math.max(0, this._steps.length - this._currentIndex); }
}
