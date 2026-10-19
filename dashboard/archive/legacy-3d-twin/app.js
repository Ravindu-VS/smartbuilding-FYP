/**
 * Smart Building Digital Twin — Dashboard Application v3.0
 *
 * Features:
 * - Server-Sent Events (SSE) for real-time streaming (primary)
 * - HTTP polling as fallback
 * - Automatic reconnection with exponential backoff
 * - Chart.js rolling data with 4 room trends
 * - Animated room cards with live sensor data
 * - Energy Savings panel (baseline vs AI comparison)
 * - Live Event Log panel (fetched from /api/events)
 * - Simulation controls (pause/resume, interval, reset)
 * - Connection health monitoring with data freshness
 */

// =============================================================================
// CONFIGURATION
// =============================================================================

const API_BASE = window.location.origin;
const POLL_INTERVAL_MS = 2000;
const EVENT_POLL_INTERVAL_MS = 3000;
const CHART_MAX_POINTS = 80;
const ROOM_ORDER = ['office_1', 'kitchen_1', 'meeting_room_1', 'bathroom_1'];

const ROOM_ICONS = {
    office: '🏢',
    kitchen: '🍳',
    meeting_room: '📋',
    bathroom: '🚿',
};

const ROOM_LABELS = {
    office_1: 'Office A',
    kitchen_1: 'Kitchen',
    meeting_room_1: 'Meeting Room',
    bathroom_1: 'Bathroom',
};

const ROOM_COLORS = {
    office_1:       { border: '#58a6ff', bg: 'rgba(88,166,255,0.1)' },
    kitchen_1:      { border: '#d29922', bg: 'rgba(210,153,34,0.1)' },
    meeting_room_1: { border: '#bc8cff', bg: 'rgba(188,140,255,0.1)' },
    bathroom_1:     { border: '#39d2c0', bg: 'rgba(57,210,192,0.1)' },
};

// =============================================================================
// STATE
// =============================================================================

let pollTimer = null;
let eventPollTimer = null;
let currentInterval = POLL_INTERVAL_MS;
let isPaused = false;
let isConnected = false;
let failCount = 0;
let tickCount = 0;
let useSSE = true;
let eventSource = null;
let reconnectAttempts = 0;
const MAX_RECONNECT_DELAY = 30000;

// Chart instances
let chartOccupancy = null;
let chartCO2 = null;
let chartPower = null;
let chartSavings = null;

// Savings history for the chart
let savingsHistory = [];

// =============================================================================
// INITIALIZATION
// =============================================================================

document.addEventListener('DOMContentLoaded', () => {
    console.log('[Dashboard] Initializing v3.0...');
    initThemeToggle();
    createRoomCards();
    initCharts();
    startEventPolling();

    // Try SSE first, fallback to polling
    if (typeof EventSource !== 'undefined') {
        startSSE();
    } else {
        console.log('[Dashboard] SSE not supported, using polling');
        useSSE = false;
        updateToggleButtons();
        startPolling();
    }
});

// =============================================================================
// THEME TOGGLE
// =============================================================================

function initThemeToggle() {
    const toggleBtn = document.getElementById('theme-toggle');
    if (!toggleBtn) return;

    // Set correct icon visibility on load
    applyThemeIcons();

    toggleBtn.addEventListener('click', () => {
        const html = document.documentElement;
        const current = html.getAttribute('data-theme') || 'dark';
        const next = current === 'dark' ? 'light' : 'dark';

        html.setAttribute('data-theme', next);
        localStorage.setItem('theme', next);

        applyThemeIcons();
        updateChartTheme(next);

        console.log(`[Dashboard] Theme switched to: ${next}`);
    });
}

function applyThemeIcons() {
    const current = document.documentElement.getAttribute('data-theme') || 'dark';
    const darkIcon = document.getElementById('theme-icon-dark');   // moon icon
    const lightIcon = document.getElementById('theme-icon-light'); // sun icon

    if (darkIcon && lightIcon) {
        // Show moon when in light mode (click to go dark), show sun when in dark mode (click to go light)
        darkIcon.style.display  = current === 'light' ? 'block' : 'none';
        lightIcon.style.display = current === 'dark'  ? 'block' : 'none';
    }
}

function updateChartTheme(theme) {
    const isDark = theme === 'dark';
    const textColor = isDark ? '#484f58' : '#8c939d';
    const gridColor = isDark ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.04)';
    const legendColor = isDark ? '#8b949e' : '#525a65';
    const tooltipBg = isDark ? 'rgba(13, 17, 23, 0.95)' : 'rgba(255, 255, 255, 0.95)';
    const tooltipBorder = isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)';
    const tooltipTextColor = isDark ? '#e6edf3' : '#1a1d23';

    [chartOccupancy, chartCO2, chartPower, chartSavings].forEach(chart => {
        if (!chart) return;

        // Update scale colors
        ['x', 'y'].forEach(axis => {
            if (chart.options.scales[axis]) {
                chart.options.scales[axis].ticks.color = textColor;
                chart.options.scales[axis].grid.color = gridColor;
            }
        });

        // Update legend
        if (chart.options.plugins.legend) {
            chart.options.plugins.legend.labels.color = legendColor;
        }

        // Update tooltip
        if (chart.options.plugins.tooltip) {
            chart.options.plugins.tooltip.backgroundColor = tooltipBg;
            chart.options.plugins.tooltip.borderColor = tooltipBorder;
            chart.options.plugins.tooltip.titleColor = tooltipTextColor;
            chart.options.plugins.tooltip.bodyColor = tooltipTextColor;
        }

        chart.update('none');
    });
}

// =============================================================================
// ROOM CARDS (Dynamic HTML Generation)
// =============================================================================

function createRoomCards() {
    const grid = document.getElementById('rooms-grid');
    grid.innerHTML = '';

    ROOM_ORDER.forEach(roomId => {
        const card = document.createElement('div');
        card.className = 'room-card mode-EMPTY';
        card.id = `card-${roomId}`;
        card.innerHTML = buildRoomCardHTML(roomId);
        grid.appendChild(card);
    });
}

function buildRoomCardHTML(roomId) {
    const type = roomId.replace(/_\d+$/, '');
    const icon = ROOM_ICONS[type] || '🏠';
    const name = ROOM_LABELS[roomId] || roomId;

    return `
        <div class="room-card-header">
            <span class="room-card-title">${icon} ${name}</span>
            <span class="room-type-tag">${type.replace('_', ' ')}</span>
        </div>

        <div class="prob-gauge">
            <div class="prob-label-row">
                <span class="occ-label">🧠 Confidence / Probability</span>
                <span class="prob-badge" id="prob-badge-${roomId}">--</span>
            </div>
            <div class="prob-bar-bg">
                <div class="prob-bar-fill" id="prob-fill-${roomId}" style="width: 0%"></div>
            </div>
            <span class="prob-value" id="prob-val-${roomId}">0%</span>
        </div>

        <div class="occupancy-row">
            <span class="occ-label">🤖 Predicted</span>
            <span class="occ-value" id="pred-occ-${roomId}">--</span>
        </div>
        <div class="occupancy-row">
            <span class="occ-label">📊 Ground Truth</span>
            <span class="occ-value" id="true-occ-${roomId}">--</span>
        </div>

        <div class="control-status">
            <div class="ctrl-item">
                <span class="ctrl-icon" id="ctrl-mode-icon-${roomId}">⚙️</span>
                <span class="ctrl-value" id="ctrl-mode-${roomId}">--</span>
                <span class="ctrl-label">Mode</span>
            </div>
            <div class="ctrl-item">
                <span class="ctrl-icon">💡</span>
                <span class="ctrl-value" id="ctrl-light-${roomId}">--</span>
                <span class="ctrl-label">Lights</span>
            </div>
            <div class="ctrl-item">
                <span class="ctrl-icon">❄️</span>
                <span class="ctrl-value" id="ctrl-hvac-${roomId}">--</span>
                <span class="ctrl-label">HVAC</span>
            </div>
        </div>

        <div class="sensor-grid">
            <div class="sensor-row">
                <span class="sensor-label">🌡️ Temp</span>
                <span class="sensor-value" id="sensor-temp-${roomId}">--°C</span>
            </div>
            <div class="sensor-row">
                <span class="sensor-label">💧 Humid</span>
                <span class="sensor-value" id="sensor-humid-${roomId}">--%</span>
            </div>
            <div class="sensor-row">
                <span class="sensor-label">🌬️ CO₂</span>
                <span class="sensor-value" id="sensor-co2-${roomId}">-- ppm</span>
            </div>
            <div class="sensor-row">
                <span class="sensor-label">☀️ Light</span>
                <span class="sensor-value" id="sensor-light-${roomId}">-- lux</span>
            </div>
            <div class="sensor-row">
                <span class="sensor-label">💨 H.Ratio</span>
                <span class="sensor-value" id="sensor-hr-${roomId}">--</span>
            </div>
        </div>

        <div class="room-energy-extended">
            <div class="re-col">
                <span class="re-label">⚡ Power Now</span>
                <span class="re-val" id="power-${roomId}">-- W</span>
            </div>
            <div class="re-col">
                <span class="re-label">🔋 Energy Today</span>
                <span class="re-val energy-val" id="energy-${roomId}">-- Wh</span>
            </div>
            <div class="re-col">
                <span class="re-label">🔥 Baseline Today</span>
                <span class="re-val" id="base-energy-${roomId}">-- Wh</span>
            </div>
            <div class="re-col">
                <span class="re-label">💚 Saved</span>
                <span class="re-val savings-green" id="saved-energy-${roomId}">-- Wh (<span id="saved-pct-${roomId}">%</span>)</span>
            </div>
        </div>
    `;
}

// =============================================================================
// CHARTS INITIALIZATION
// =============================================================================

function initCharts() {
    const isDark = (document.documentElement.getAttribute('data-theme') || 'dark') === 'dark';
    const tickColor = isDark ? '#484f58' : '#8c939d';
    const gridColor = isDark ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.04)';
    const legendColor = isDark ? '#8b949e' : '#525a65';
    const tooltipBg = isDark ? 'rgba(13, 17, 23, 0.95)' : 'rgba(255, 255, 255, 0.95)';
    const tooltipBorder = isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)';
    const tooltipText = isDark ? '#e6edf3' : '#1a1d23';

    Chart.defaults.color = tickColor;
    Chart.defaults.font.family = "'Inter', sans-serif";

    const commonOptions = {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 200 },
        interaction: { mode: 'index', intersect: false },
        scales: {
            x: {
                display: true,
                ticks: { color: tickColor, maxTicksLimit: 8, font: { size: 9 } },
                grid: { color: gridColor, drawBorder: false },
                border: { display: false },
            },
            y: {
                display: true,
                ticks: { color: tickColor, font: { size: 9 } },
                grid: { color: gridColor, drawBorder: false },
                border: { display: false },
            },
        },
        plugins: {
            legend: {
                display: true,
                position: 'top',
                labels: {
                    color: legendColor,
                    font: { size: 10, weight: 500 },
                    boxWidth: 10,
                    boxHeight: 2,
                    padding: 12,
                    usePointStyle: true,
                    pointStyle: 'line',
                },
            },
            tooltip: {
                backgroundColor: tooltipBg,
                titleFont: { size: 11 },
                bodyFont: { size: 10 },
                titleColor: tooltipText,
                bodyColor: tooltipText,
                borderColor: tooltipBorder,
                borderWidth: 1,
                cornerRadius: 8,
                padding: 10,
            },
        },
    };

    function makeDatasets() {
        return ROOM_ORDER.map(id => ({
            label: ROOM_LABELS[id],
            data: [],
            borderColor: ROOM_COLORS[id].border,
            backgroundColor: ROOM_COLORS[id].bg,
            borderWidth: 1.5,
            pointRadius: 0,
            pointHoverRadius: 3,
            tension: 0.35,
            fill: true,
        }));
    }

    chartOccupancy = new Chart(document.getElementById('chart-occupancy'), {
        type: 'line',
        data: { labels: [], datasets: makeDatasets() },
        options: {
            ...commonOptions,
            scales: {
                ...commonOptions.scales,
                y: {
                    ...commonOptions.scales.y,
                    min: 0,
                    max: 1,
                    ticks: {
                        ...commonOptions.scales.y.ticks,
                        callback: v => (v * 100).toFixed(0) + '%'
                    }
                }
            }
        },
    });

    chartCO2 = new Chart(document.getElementById('chart-co2'), {
        type: 'line',
        data: { labels: [], datasets: makeDatasets() },
        options: commonOptions,
    });

    chartPower = new Chart(document.getElementById('chart-power'), {
        type: 'line',
        data: { labels: [], datasets: makeDatasets() },
        options: commonOptions,
    });

    // Savings chart: 2 datasets (baseline, AI)
    chartSavings = new Chart(document.getElementById('chart-savings'), {
        type: 'line',
        data: {
            labels: [],
            datasets: [
                {
                    label: 'Baseline (No AI)',
                    data: [],
                    borderColor: '#f85149',
                    backgroundColor: 'rgba(248,81,73,0.08)',
                    borderWidth: 2,
                    borderDash: [5, 3],
                    pointRadius: 0,
                    tension: 0.35,
                    fill: true,
                },
                {
                    label: 'AI Optimized',
                    data: [],
                    borderColor: '#3fb950',
                    backgroundColor: 'rgba(63,185,80,0.08)',
                    borderWidth: 2,
                    pointRadius: 0,
                    tension: 0.35,
                    fill: true,
                },
            ],
        },
        options: commonOptions,
    });
}

// =============================================================================
// SERVER-SENT EVENTS (SSE)
// =============================================================================

function startSSE() {
    if (eventSource) {
        eventSource.close();
    }

    console.log('[Dashboard] Connecting SSE stream...');
    eventSource = new EventSource(`${API_BASE}/api/stream`);

    eventSource.onopen = () => {
        console.log('[Dashboard] SSE connected');
        reconnectAttempts = 0;
        failCount = 0;
        setConnected(true);
    };

    eventSource.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            failCount = 0;
            setConnected(true);
            updateDashboard(data);
            tickCount++;
            setText('tick-count-display', tickCount);
        } catch (err) {
            console.warn('[Dashboard] SSE parse error:', err);
        }
    };

    eventSource.onerror = (err) => {
        console.warn('[Dashboard] SSE error, reconnecting...');
        failCount++;

        if (failCount >= 3) {
            setConnected(false);
        }

        reconnectAttempts++;
        if (reconnectAttempts > 10) {
            console.log('[Dashboard] Too many SSE failures, switching to polling');
            stopSSE();
            switchToPolling();
        }
    };
}

function stopSSE() {
    if (eventSource) {
        eventSource.close();
        eventSource = null;
    }
}

// =============================================================================
// HTTP POLLING (Fallback)
// =============================================================================

function startPolling() {
    stopPolling();
    poll();
    pollTimer = setInterval(poll, currentInterval);
    console.log(`[Dashboard] Polling started (${currentInterval}ms)`);
}

function stopPolling() {
    if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
    }
}

function restartPolling(intervalMs) {
    stopPolling();
    currentInterval = intervalMs;
    startPolling();
}

async function poll() {
    try {
        const response = await fetch(`${API_BASE}/api/system/live`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const data = await response.json();
        failCount = 0;
        setConnected(true);
        updateDashboard(data);
        tickCount++;
        setText('tick-count-display', tickCount);

    } catch (err) {
        failCount++;
        console.warn(`[Dashboard] Poll failed (attempt ${failCount}):`, err.message);
        if (failCount >= 3) {
            setConnected(false);
        }
    }
}

// =============================================================================
// EVENT LOG POLLING
// =============================================================================

function startEventPolling() {
    fetchEvents();
    eventPollTimer = setInterval(fetchEvents, EVENT_POLL_INTERVAL_MS);
}

async function fetchEvents() {
    try {
        const response = await fetch(`${API_BASE}/api/events?limit=40`);
        if (!response.ok) return;
        const data = await response.json();
        renderEventLog(data.events || [], data.total_logged || 0);
    } catch (err) {
        // Silent fail — events are non-critical
    }
}

function renderEventLog(events, totalCount) {
    const list = document.getElementById('event-log-list');
    const empty = document.getElementById('event-log-empty');
    const badge = document.getElementById('event-count-badge');

    if (!events || events.length === 0) {
        empty.style.display = 'block';
        list.innerHTML = '';
        badge.textContent = '0 events';
        return;
    }

    empty.style.display = 'none';
    badge.textContent = `${totalCount} events`;

    // Only re-render if new events
    const currentFirstId = list.dataset.firstId;
    if (events.length > 0 && String(events[0].id) === currentFirstId) {
        return; // No change
    }

    list.dataset.firstId = events.length > 0 ? String(events[0].id) : '';

    list.innerHTML = events.map(e => `
        <div class="event-entry">
            <span class="event-time">${e.sim_time && e.sim_time !== 'null' ? e.sim_time : '--:--:--'}</span>
            <span class="event-cat ${e.event_type || ''}">${e.event_type || '??'}</span>
            <span class="event-msg">${e.message || ''}</span>
        </div>
    `).join('');
}

// =============================================================================
// DATA SOURCE SWITCHING
// =============================================================================

function switchToSSE() {
    useSSE = true;
    stopPolling();
    startSSE();
    updateToggleButtons();
    console.log('[Dashboard] Switched to SSE');
}

function switchToPolling() {
    useSSE = false;
    stopSSE();
    startPolling();
    updateToggleButtons();
    console.log('[Dashboard] Switched to polling');
}

function updateToggleButtons() {
    const btnSSE = document.getElementById('btn-sse');
    const btnPoll = document.getElementById('btn-poll');
    if (btnSSE && btnPoll) {
        btnSSE.className = useSSE ? 'toggle-btn active' : 'toggle-btn';
        btnPoll.className = useSSE ? 'toggle-btn' : 'toggle-btn active';
    }
}

// =============================================================================
// DATA UPDATE FUNCTIONS
// =============================================================================

function updateDashboard(data) {
    const rooms = data.rooms || [];
    const system = data.system || {};

    const simConnected = system.simulation_connected || false;
    const hasRooms = rooms && rooms.length > 0;

    if (!simConnected || !hasRooms) {
        updateWaitingState(system);
        updateHeader(system);
        return;
    }

    updateOverview(system);
    updateEnergySavings(system);
    rooms.forEach(room => updateRoomCard(room));
    updateCharts(rooms, system);
    updateSystemStatus(system);
    updateHeader(system);
}

function updateWaitingState(system) {
    const grid = document.getElementById('rooms-grid');
    const cards = grid.querySelectorAll('.room-card');
    cards.forEach(card => {
        card.style.opacity = '0.4';
        card.style.pointerEvents = 'none';
    });

    document.getElementById('total-rooms').textContent = '--';
    document.getElementById('occupied-rooms').textContent = '--';
    document.getElementById('empty-rooms').textContent = '--';
    document.getElementById('total-power').innerHTML = '--<span class="ov-unit">W</span>';
    document.getElementById('total-energy').innerHTML = '--<span class="ov-unit">Wh</span>';

    showOverlay('sim-waiting-overlay', true);
    showOverlay('stale-data-overlay', false);
    showOverlay('api-offline-overlay', false);

    updateHeader(system);
}

function updateOverview(system) {
    animateValue('total-rooms', system.total_rooms || 0);
    animateValue('occupied-rooms', system.occupied_rooms || 0);
    animateValue('empty-rooms', system.empty_rooms || 0);

    const power = system.total_power_watts || 0;
    document.getElementById('total-power').innerHTML =
        `${power.toFixed(0)}<span class="ov-unit">W</span>`;

    const energy = system.total_cumulative_energy_wh || 0;
    const energyDisplay = energy > 1000
        ? `${(energy / 1000).toFixed(2)}<span class="ov-unit">kWh</span>`
        : `${energy.toFixed(1)}<span class="ov-unit">Wh</span>`;
    document.getElementById('total-energy').innerHTML = energyDisplay;

    const modelEl = document.getElementById('model-status');
    if (system.model_loaded) {
        modelEl.className = 'status-badge online';
        modelEl.textContent = 'Online';
    } else {
        modelEl.className = 'status-badge offline';
        modelEl.textContent = 'Offline';
    }
}

function updateEnergySavings(system) {
    const baselinePower = system.baseline_power_watts || 0;
    const aiPower = system.ai_power_watts || 0;
    const baselineEnergy = system.baseline_energy_wh || 0;
    const aiEnergy = system.ai_energy_wh || 0;
    const saved = system.energy_saved_wh || 0;
    const pct = system.percentage_saved || 0;

    // Baseline
    document.getElementById('es-baseline-power').innerHTML =
        `${baselinePower.toFixed(0)} <span class="savings-unit">W</span>`;
    document.getElementById('es-baseline-energy').textContent =
        `${formatEnergy(baselineEnergy)} cumulative`;

    // AI
    document.getElementById('es-ai-power').innerHTML =
        `${aiPower.toFixed(0)} <span class="savings-unit">W</span>`;
    document.getElementById('es-ai-energy').textContent =
        `${formatEnergy(aiEnergy)} cumulative`;

    // Saved
    document.getElementById('es-saved-value').innerHTML =
        `${formatEnergy(saved)} <span class="savings-unit"></span>`;

    // Percentage ring
    const circumference = 2 * Math.PI * 34; // r=34
    const dashArray = (pct / 100) * circumference;
    const circle = document.getElementById('pct-ring-circle');
    const ringText = document.getElementById('pct-ring-text');
    if (circle) {
        circle.setAttribute('stroke-dasharray', `${dashArray} ${circumference}`);
    }
    if (ringText) {
        ringText.textContent = `${pct.toFixed(0)}%`;
    }

    // Badge
    const badge = document.getElementById('savings-pct-badge');
    if (badge) {
        badge.textContent = `${pct.toFixed(1)}% saved`;
    }
}

function updateRoomCard(room) {
    const id = room.room_id;
    const card = document.getElementById(`card-${id}`);
    if (!card) return;

    const ai = room.ai || {};
    const control = room.control || {};
    const sensors = room.sensors || {};
    const energy = room.energy || {};
    const gt = room.ground_truth || {};

    // Control mode class
    const mode = control.control_mode || 'EMPTY';
    card.className = `room-card mode-${mode}`;

    // Re-enable card (in case it was dimmed in waiting state)
    card.style.opacity = '1.0';
    card.style.pointerEvents = '';

    // Probability gauge
    const prob = ai.occupancy_probability || 0;
    const probPct = (prob * 100).toFixed(0);
    const fillEl = document.getElementById(`prob-fill-${id}`);
    const probEl = document.getElementById(`prob-val-${id}`);
    const badgeEl = document.getElementById(`prob-badge-${id}`);

    fillEl.style.width = `${probPct}%`;
    probEl.textContent = `${probPct}%`;

    if (prob >= 0.6) {
        probEl.style.color = '#3fb950';
        fillEl.style.background = 'linear-gradient(90deg, #3fb950, #2dd4bf)';
        badgeEl.textContent = 'HIGH CONFIDENCE';
        badgeEl.style.color = '#3fb950';
    } else if (prob >= 0.2) {
        probEl.style.color = '#d29922';
        fillEl.style.background = 'linear-gradient(90deg, #d29922, #e3b341)';
        badgeEl.textContent = 'MODERATE CONFIDENCE';
        badgeEl.style.color = '#d29922';
    } else {
        probEl.style.color = '#484f58';
        fillEl.style.background = 'linear-gradient(90deg, #484f58, #6e7681)';
        badgeEl.textContent = 'LOW CONFIDENCE';
        badgeEl.style.color = '#8b949e';
    }

    // Predicted occupancy
    const predOccEl = document.getElementById(`pred-occ-${id}`);
    if (ai.predicted_occupancy === 1) {
        predOccEl.textContent = 'Occupied';
        predOccEl.className = 'occ-value occupied';
    } else {
        predOccEl.textContent = 'Empty';
        predOccEl.className = 'occ-value empty';
    }

    // True occupancy
    const trueOccEl = document.getElementById(`true-occ-${id}`);
    if (gt.true_occupancy === 1) {
        trueOccEl.textContent = `Occupied (${gt.occupancy_count || 0})`;
        trueOccEl.className = 'occ-value occupied';
    } else {
        trueOccEl.textContent = 'Empty';
        trueOccEl.className = 'occ-value empty';
    }

    // Control mode badge
    const modeEl = document.getElementById(`ctrl-mode-${id}`);
    modeEl.innerHTML = `<span class="mode-badge ${mode}">${mode}</span>`;

    // Light & HVAC (Actual Applied)
    const actualAction = room.actual_action || control;
    setText(`ctrl-light-${id}`, actualAction.light_action || '--');
    setText(`ctrl-hvac-${id}`, actualAction.hvac_action || '--');

    // Sensors
    setText(`sensor-temp-${id}`, `${(sensors.Temperature || 0).toFixed(1)}°C`);
    setText(`sensor-humid-${id}`, `${(sensors.Humidity || 0).toFixed(1)}%`);
    setText(`sensor-co2-${id}`, `${(sensors.CO2 || 0).toFixed(0)} ppm`);
    setText(`sensor-light-${id}`, `${(sensors.Light || 0).toFixed(0)} lux`);
    setText(`sensor-hr-${id}`, `${(sensors.HumidityRatio || 0).toFixed(5)}`);

    // Power & Energy Extensible Analytics
    const opt = energy.optimization || {};
    setText(`power-${id}`, `${(energy.estimated_power_watts || 0).toFixed(0)} W`);
    
    // Read directly from backend optimiser metrics
    const aiEnergyWh = opt.ai_energy_wh !== undefined ? opt.ai_energy_wh : (energy.cumulative_energy_wh || 0);
    const baselineWh = opt.baseline_energy_wh || 0;
    const savedWh = opt.energy_saved_wh || 0;
    const savedPct = opt.percentage_saved || 0;

    setText(`energy-${id}`, formatEnergy(aiEnergyWh));
    setText(`base-energy-${id}`, formatEnergy(baselineWh));
    setText(`saved-energy-${id}`, `${formatEnergy(savedWh)} (${savedPct.toFixed(1)}%)`);
}

function updateCharts(rooms, system) {
    const now = rooms.length > 0 ? rooms[0].timestamp : '';
    const timeLabel = now ? now.split('T')[1] || '' : '';
    const shortLabel = timeLabel ? timeLabel.substring(0, 5) : '';

    // Room-based charts
    ROOM_ORDER.forEach((roomId, idx) => {
        const room = rooms.find(r => r.room_id === roomId) || {};
        const ai = room.ai || {};
        const sensors = room.sensors || {};
        const energy = room.energy || {};

        pushChartData(chartOccupancy, idx, ai.occupancy_probability || 0);
        pushChartData(chartCO2, idx, sensors.CO2 || 400);
        pushChartData(chartPower, idx, energy.estimated_power_watts || 0);
    });

    // Energy savings chart (building-wide baseline vs AI)
    const baselineE = system.baseline_energy_wh || 0;
    const aiE = system.ai_energy_wh || 0;
    chartSavings.data.datasets[0].data.push(baselineE);
    chartSavings.data.datasets[1].data.push(aiE);
    if (chartSavings.data.datasets[0].data.length > CHART_MAX_POINTS) {
        chartSavings.data.datasets[0].data.shift();
        chartSavings.data.datasets[1].data.shift();
    }
    chartSavings.data.labels.push(shortLabel);
    if (chartSavings.data.labels.length > CHART_MAX_POINTS) {
        chartSavings.data.labels.shift();
    }

    // Update all charts
    [chartOccupancy, chartCO2, chartPower].forEach(chart => {
        chart.data.labels.push(shortLabel);
        if (chart.data.labels.length > CHART_MAX_POINTS) {
            chart.data.labels.shift();
        }
        chart.update('none');
    });
    chartSavings.update('none');
}

function pushChartData(chart, datasetIdx, value) {
    const ds = chart.data.datasets[datasetIdx];
    ds.data.push(value);
    if (ds.data.length > CHART_MAX_POINTS) {
        ds.data.shift();
    }
}

function updateSystemStatus(system) {
    setStatusIndicator('status-model', system.model_loaded);
    setStatusIndicator('status-api', true); // API is online if we got data
    setStatusIndicator('status-sim', system.simulation_running || system.simulation_connected);
    setStatusIndicator('status-connection', isConnected);

    // Data freshness badge
    const freshEl = document.getElementById('status-data-freshness');
    if (freshEl) {
        const simConnected = system.simulation_connected || false;
        const dataStale = system.data_stale || false;

        if (!simConnected) {
            freshEl.textContent = 'WAITING';
            freshEl.className = 'status-text data-status-badge waiting';
        } else if (dataStale) {
            freshEl.textContent = 'STALE';
            freshEl.className = 'status-text data-status-badge stale';
        } else if (!isConnected) {
            freshEl.textContent = 'DISCONNECTED';
            freshEl.className = 'status-text data-status-badge disconnected';
        } else {
            freshEl.textContent = 'LIVE';
            freshEl.className = 'status-text data-status-badge live';
        }
    }

    setText('status-last-update', formatTime(system.last_update));
    setText('status-interval', `${(system.update_interval || 2).toFixed(1)}s`);

    if (system.simulation_paused !== undefined) {
        isPaused = system.simulation_paused;
        updatePauseButton();
    }
}

function updateHeader(system) {
    const simConnected = system.simulation_connected || false;
    const dataStale = system.data_stale || false;
    const simTime = system.simulation_time || '';

    // Display simulation time
    const timeStr = simTime ? simTime.split('T')[1] || '--:--:--' : '--:--:--';
    setText('sim-time-display', timeStr);

    // Update Demo Badge
    const demoBadge = document.getElementById('demo-mode-badge');
    if (demoBadge) {
        demoBadge.style.display = (system.simulation_speed_factor > 100) ? 'flex' : 'none';
    }

    const badge = document.getElementById('connection-badge');
    const dot = document.getElementById('connection-dot');
    const status = document.getElementById('connection-status');

    if (!simConnected) {
        badge.style.opacity = '0.6';
        dot.className = 'status-dot disconnected';
        status.textContent = 'Waiting for Sim';
        showOverlay('sim-waiting-overlay', true);
        showOverlay('stale-data-overlay', false);
    } else if (dataStale) {
        badge.style.opacity = '1.0';
        dot.className = 'status-dot stale';
        status.textContent = 'Stale Data';
        showOverlay('sim-waiting-overlay', false);
        showOverlay('stale-data-overlay', true);
    } else {
        badge.style.opacity = '1.0';
        dot.className = 'status-dot connected';
        status.textContent = 'Live';
        showOverlay('sim-waiting-overlay', false);
        showOverlay('stale-data-overlay', false);
        showOverlay('api-offline-overlay', false);

        const cards = document.querySelectorAll('.room-card');
        cards.forEach(card => {
            card.style.opacity = '1.0';
            card.style.pointerEvents = '';
        });
    }

    setText('rooms-last-update', `Last update: ${formatTime(system.last_update)}`);
}

// =============================================================================
// SIMULATION CONTROLS
// =============================================================================

async function togglePauseResume() {
    const action = isPaused ? 'resume' : 'pause';
    try {
        await fetch(`${API_BASE}/api/simulation/control`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action }),
        });
        isPaused = !isPaused;
        updatePauseButton();
    } catch (err) {
        console.error('Pause/resume failed:', err);
    }
}

function updatePauseButton() {
    const icon = document.getElementById('btn-pause-icon');
    const text = document.getElementById('btn-pause-text');
    const btn = document.getElementById('btn-pause-resume');

    if (isPaused) {
        icon.textContent = '▶';
        text.textContent = 'Resume';
        if (btn) btn.style.background = 'linear-gradient(135deg, #3fb950, #2dd4bf)';
    } else {
        icon.textContent = '⏸';
        text.textContent = 'Pause';
        if (btn) btn.style.background = '';
    }
}

async function changeInterval(value) {
    const interval = parseFloat(value);
    document.getElementById('interval-display').textContent = `${interval.toFixed(1)}s`;

    try {
        await fetch(`${API_BASE}/api/simulation/control`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'set_interval', value: interval }),
        });

        if (!useSSE) {
            restartPolling(interval * 1000);
        }
    } catch (err) {
        console.error('Interval change failed:', err);
    }
}

async function resetEnergy() {
    try {
        await fetch(`${API_BASE}/api/simulation/control`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'reset_energy' }),
        });
        console.log('[Dashboard] Energy counters reset');
    } catch (err) {
        console.error('Energy reset failed:', err);
    }
}

// =============================================================================
// UTILITIES
// =============================================================================

function setText(elementId, text) {
    const el = document.getElementById(elementId);
    if (el) el.textContent = text;
}

function animateValue(elementId, newValue) {
    const el = document.getElementById(elementId);
    if (!el) return;

    const oldValue = parseInt(el.textContent) || 0;
    if (oldValue !== newValue) {
        el.textContent = newValue;
        el.classList.add('value-updated');
        setTimeout(() => el.classList.remove('value-updated'), 600);
    }
}

function setConnected(connected) {
    isConnected = connected;
    const dot = document.getElementById('connection-dot');
    const status = document.getElementById('connection-status');

    if (connected) {
        dot.className = 'status-dot online';
        status.textContent = useSSE ? 'SSE Connected' : 'Connected';
        showOverlay('api-offline-overlay', false);
    } else {
        dot.className = 'status-dot';
        status.textContent = 'Disconnected';
        showOverlay('api-offline-overlay', true);
    }
}

function showOverlay(overlayId, visible) {
    const el = document.getElementById(overlayId);
    if (el) {
        el.style.display = visible ? 'flex' : 'none';
    }
}

function setStatusIndicator(elementId, isOnline) {
    const el = document.getElementById(elementId);
    if (!el) return;
    el.className = `status-indicator ${isOnline ? 'online' : 'offline'}`;
}

function formatTime(isoString) {
    if (!isoString) return '--';
    try {
        const d = new Date(isoString);
        return d.toLocaleTimeString();
    } catch {
        return isoString;
    }
}

function formatEnergy(wh) {
    if (wh > 1000) {
        return `${(wh / 1000).toFixed(2)} kWh`;
    }
    return `${wh.toFixed(1)} Wh`;
}
