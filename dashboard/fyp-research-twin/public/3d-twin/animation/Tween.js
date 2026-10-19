// ═══════════════════════════════════════════════════════════════
// Tween.js — Lightweight Interpolation Utilities
// ═══════════════════════════════════════════════════════════════
// Smooth interpolation for doors, windows, avatar positions, etc.
// No external dependencies.

/**
 * Linear interpolation.
 */
export function lerp(a, b, t) {
    return a + (b - a) * Math.min(Math.max(t, 0), 1);
}

/**
 * Smooth step (ease in-out).
 */
export function smoothstep(t) {
    t = Math.min(Math.max(t, 0), 1);
    return t * t * (3 - 2 * t);
}

/**
 * Ease out cubic.
 */
export function easeOutCubic(t) {
    t = Math.min(Math.max(t, 0), 1);
    return 1 - Math.pow(1 - t, 3);
}

/**
 * Ease in-out quad.
 */
export function easeInOutQuad(t) {
    t = Math.min(Math.max(t, 0), 1);
    return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
}

/**
 * Interpolate towards target by a damping factor (framerate-independent).
 * @param {number} current
 * @param {number} target
 * @param {number} damping — 0.0 (instant) to 1.0 (never reaches)
 * @param {number} delta — frame delta in seconds
 */
export function dampedLerp(current, target, damping, delta) {
    const factor = 1 - Math.pow(damping, delta * 60);
    return lerp(current, target, factor);
}

/**
 * Simple seeded pseudo-random number generator.
 * Deterministic for the same seed.
 */
export function seededRandom(seed) {
    let s = seed;
    return function() {
        s = (s * 16807 + 0) % 2147483647;
        return (s - 1) / 2147483646;
    };
}

/**
 * Generate a deterministic hash from a string.
 * Used for avatar variety seeding.
 */
export function hashString(str) {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
        const char = str.charCodeAt(i);
        hash = ((hash << 5) - hash) + char;
        hash |= 0; // Convert to 32-bit integer
    }
    return Math.abs(hash);
}
