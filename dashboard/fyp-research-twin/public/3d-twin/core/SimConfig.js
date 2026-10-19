// ═══════════════════════════════════════════════════════════════
// SimConfig.js — Configurable Simulation Parameters
// ═══════════════════════════════════════════════════════════════
// Single place to tune all thresholds, timing, and behavior.
// No magic numbers anywhere else in the codebase.

export const SIM_CONFIG = {

    // --- Occupancy Probability → Avatar State Thresholds ---
    occupancy: {
        NO_OCCUPANCY_THRESHOLD: 0.10,    // Below → no avatar
        ENTER_THRESHOLD: 0.35,           // Above → avatar near entrance
        WORK_THRESHOLD: 0.70,            // Above → avatar walking to desk
        CONFIRMED_THRESHOLD: 0.90,       // Above → avatar seated/working
    },

    // --- Animation Timing ---
    animation: {
        DECISION_DELAY_MS: 600,          // AI decision → visual action delay
        DOOR_OPEN_DURATION_MS: 800,      // Door swing duration
        DOOR_CLOSE_DELAY_MS: 1200,       // Delay before door auto-closes
        WALK_SPEED: 2.0,                 // Units per second
        IDLE_BOB_AMPLITUDE: 0.05,        // Breathing bob height
        IDLE_HEAD_TURN_INTERVAL: [5, 8], // Seconds between head turns [min, max]
        TYPING_SPEED: 3.0,              // Typing animation frequency
    },

    // --- Room 101 Hero Mode ---
    hero: {
        ROOM_ID: '2_office_a',           // Legacy format room ID
        NEXT_JS_ID: 'f2_office_a',       // Next.js format room ID
        PULSE_COLOR: 0x10b981,           // Green pulse
        PULSE_DURATION_MS: 1500,         // Pulse animation duration
        BORDER_GLOW_INTENSITY: 2.0,      // Emissive intensity during pulse
    },

    // --- Avatar Pool ---
    avatarPool: {
        INITIAL_SIZE: 40,                // Pre-allocated avatars
        MAX_SIZE: 80,                    // Maximum pool size
        SHIRT_COLORS: [0x3366cc, 0xcc3333, 0x33cc66, 0xcccccc, 0xeeaa22, 0x444444, 0x6633cc, 0xcc6633],
        HEIGHT_RANGE: [0.85, 1.05],      // Scale range
        WALK_SPEED_VARIANCE: 0.15,       // ±15% walk speed variance
    },

    // --- Research Visualizations (Phase 6) ---
    research: {
        PMV_COLORS: {
            COLD: 0x3b82f6,    // Blue (-3)
            NEUTRAL: 0x10b981, // Green (0)
            HOT: 0xef4444,     // Red (+3)
        },
        ENERGY_MAX_WATTS: 5000,          // Max expected room power for scaling
        PARTICLE_SPEED: 2.0,             // Energy particle speed
        PARTICLE_COUNT_MAX: 100,         // Max particles per room flow
    },

    // --- State Hash Fields (for dirty checking) ---
    hashFields: [
        'source',
        'hardware.connected',
        'presence.fused_presence',
        'control.control_mode',
        'sensors.Temperature',
        'ai.occupancy_probability',
        'ai.predicted_occupancy',
        'control.light_action',
        'control.hvac_action',
        'device_state.light_on',
        'device_state.hvac_mode',
        'device_state.hvac_speed',
        'ground_truth.true_occupancy',
        'energy.estimated_power_watts',
        'sensors.temperature',
        'temperature'
    ],

    // --- Debug Mode ---
    debug: false,
};
