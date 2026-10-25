// ═══════════════════════════════════════════════════════════════
// main.js — Smart Hub 3D digital twin (building / floor / room views)
// ═══════════════════════════════════════════════════════════════
// Runs inside the dashboard's iframe. It has no connection of its own: the page
// forwards the edge brain's building configuration (CONFIG) and every state update
// (SYNC_STATE), so the 3D view shows exactly what the panels show.
//
// Page -> twin messages
//   CONFIG {config}                       building geometry and rooms (single source)
//   SYNC_STATE {rooms, clock, system, hardware, ai_enabled, seq}
//   LINK_STATUS {ok, detail}
//   UI_COMMAND {action, payload}          setView, selectRoom, setOverlay, setLayers,
//                                         setLighting, setQuality, cameraPreset,
//                                         resetCamera, setPresentation, tour
// Twin -> page messages
//   TWIN_READY, ROOM_SELECTED {room_id}, VIEW_CHANGED {mode, floor, room},
//   TWIN_SYNC_REPORT {matched, received, modelRooms, unmatched, seq}, TWIN_STATS

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { GTAOPass } from 'three/addons/postprocessing/GTAOPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { CSS2DRenderer, CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { Environment } from './scene/environment.js';
import { Site } from './scene/site.js';
import { Building, FL, CL, GEO, roomBox } from './scene/building.js';
import { Interiors } from './scene/interiors.js';
import { People, RoomOccupants } from './scene/people.js';

const params = new URLSearchParams(location.search);
const EMBEDDED = params.has('embedded');
const STANDALONE = params.has('standalone');
const EDGE = params.get('edge') || 'http://127.0.0.1:8001';
const FLOOR_NAMES = ['Ground · Retail & Lobby', 'Level 1 · Health & Recreation', 'Level 2 · Offices', 'Level 3 · Apartments', 'Level 4 · Penthouse'];
const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

const ICON = {
    people: '<svg class="i" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="9" cy="7" r="4"/><path d="M2 21v-2a4 4 0 0 1 4-4h6a4 4 0 0 1 4 4v2"/><path d="M16 3.1a4 4 0 0 1 0 7.8M22 21v-2a4 4 0 0 0-3-3.9"/></svg>',
    temp: '<svg class="i" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 14.8V4a2 2 0 1 0-4 0v10.8a4 4 0 1 0 4 0z"/></svg>',
    bulb: '<svg class="i" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18h6M10 22h4M12 2a7 7 0 0 0-4 12.7V17h8v-2.3A7 7 0 0 0 12 2z"/></svg>',
    snow: '<svg class="i" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v20M4.9 4.9l14.2 14.2M2 12h20M4.9 19.1 19.1 4.9"/></svg>',
    chip: '<svg class="i" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/></svg>',
};

function post(msg) {
    if (window.parent && window.parent !== window) window.parent.postMessage(msg, location.origin);
}

class App {
    constructor() {
        this.stage = document.getElementById('stage');
        this.view = { mode: 'building', floor: null, room: null, preset: 'hero', eye: false };
        this.layers = { people: true, airflow: false, labels: true };
        this.overlay = { mode: 'none', colors: {} };
        this.selected = null;
        this.hover = null;
        this.state = null;
        this.config = null;
        this.quality = 'high';
        this.presentation = false;
        this.tour = null;
        this.clock = new THREE.Clock();
        this.time = 0;
        this.frames = 0;
        this.fpsT = 0;
        this.fps = 0;
        this._initRenderer();
        this.env = new Environment(this);
        this._setLoading(0.08, 'Building the street and landscape…');
        this.site = new Site(this);
        this._initPicking();
        this._initLabels();
        this.camTween = null;
        this.applyCameraPreset('hero', false);
        window.addEventListener('message', (e) => this._onMessage(e));
        new ResizeObserver(() => this._resize()).observe(this.stage);
        window.addEventListener('resize', () => this._resize());
        this._resize();
        this.renderer.setAnimationLoop(() => this._frame());
        this._setLoading(0.2, EMBEDDED || STANDALONE ? 'Waiting for the building configuration from the edge brain…' : 'Open inside the dashboard (or add ?standalone=1)');
        // handshake: repeat READY until the page has sent the configuration (the page's
        // listener may attach after this document loads), and answer PING at any time
        this._announce();
        this._readyTimer = setInterval(() => { if (this.config) clearInterval(this._readyTimer); else this._announce(); }, 1000);
        if (STANDALONE) this._standalone();
    }

    // ------------------------------------------------------------ setup
    _initRenderer() {
        const r = new THREE.WebGLRenderer({ antialias: false, powerPreference: 'high-performance', stencil: false });
        r.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        r.outputColorSpace = THREE.SRGBColorSpace;
        r.toneMapping = THREE.ACESFilmicToneMapping;
        r.toneMappingExposure = 0.6;
        r.shadowMap.enabled = true;
        r.shadowMap.type = THREE.PCFSoftShadowMap;
        r.shadowMap.autoUpdate = false;          // updated at ~20 Hz in the frame loop (moving people and cars)
        r.localClippingEnabled = true;
        r.info.autoReset = false;
        this.stage.appendChild(r.domElement);
        this.renderer = r;
        this.scene = new THREE.Scene();
        this.camera = new THREE.PerspectiveCamera(40, 1, 0.1, 6000);
        this.controls = new OrbitControls(this.camera, r.domElement);
        this.controls.enableDamping = true;
        this.controls.dampingFactor = 0.08;
        this.controls.screenSpacePanning = false;
        this.controls.zoomToCursor = true;
        this.controls.addEventListener('start', () => { if (this.tour) this.stopTour(); this.camTween = null; this.controls.autoRotate = false; });

        const size = new THREE.Vector2(1, 1);
        const rt = new THREE.WebGLRenderTarget(size.x, size.y, { type: THREE.HalfFloatType, samples: 4 });
        this.composer = new EffectComposer(r, rt);
        this.renderPass = new RenderPass(this.scene, this.camera);
        this.composer.addPass(this.renderPass);
        this.gtao = new GTAOPass(this.scene, this.camera, 1, 1);
        this.gtao.output = GTAOPass.OUTPUT.Default;
        this.gtao.updateGtaoMaterial({ radius: 0.6, distanceExponent: 1.4, thickness: 1.2, scale: 1.0, samples: 12 });
        this.gtao.updatePdMaterial({ lumaPhi: 10, depthPhi: 2, normalPhi: 3, radius: 6, rings: 2, samples: 12 });
        this.gtao.blendIntensity = 0.85;
        this.composer.addPass(this.gtao);
        this.bloom = new UnrealBloomPass(new THREE.Vector2(256, 256), 0.3, 0.55, 2.0);
        this.composer.addPass(this.bloom);
        this.composer.addPass(new OutputPass());
    }

    _resize() {
        const w = Math.max(2, this.stage.clientWidth), h = Math.max(2, this.stage.clientHeight);
        this._size = `${w}x${h}`;
        this.renderer.setSize(w, h, false);
        this.renderer.domElement.style.width = `${w}px`;
        this.renderer.domElement.style.height = `${h}px`;
        this.composer.setSize(w, h);
        this.gtao.setSize(w, h);
        this.labelRenderer.setSize(w, h);
        this.camera.aspect = w / h;
        this.camera.updateProjectionMatrix();
    }

    _setLoading(p, msg) {
        const bar = document.getElementById('loadbar'), m = document.getElementById('loadmsg');
        if (bar) bar.style.width = `${Math.round(p * 100)}%`;
        if (m && msg) m.textContent = msg;
        if (p >= 1) {
            const el = document.getElementById('loading');
            el.classList.add('done');
            setTimeout(() => { el.style.display = 'none'; }, 800);
        }
    }

    setQuality(q) {
        this.quality = q === 'balanced' ? 'balanced' : 'high';
        this.gtao.enabled = this.quality === 'high';
        this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, this.quality === 'high' ? 2 : 1));
        const s = this.quality === 'high' ? 4096 : 2048;
        const sh = this.env.sun.shadow;
        if (sh.mapSize.x !== s) { sh.mapSize.set(s, s); if (sh.map) { sh.map.dispose(); sh.map = null; } }
        this._resize();
    }

    // ------------------------------------------------------------ data
    async _standalone() {
        try {
            const cfg = await (await fetch(`${EDGE}/api/building/config`)).json();
            this.onConfig(cfg);
            const poll = async () => {
                try {
                    const s = await (await fetch(`${EDGE}/api/rooms/current-state`)).json();
                    if (!window.__freezeState) this.onState(s);
                    this._link(true, '');
                } catch (e) { this._link(false, 'edge brain not reachable'); }
                setTimeout(poll, 1000);
            };
            poll();
        } catch (e) {
            this._setLoading(0.2, `Edge brain not reachable at ${EDGE}`);
            setTimeout(() => this._standalone(), 3000);
        }
    }

    _announce() { post({ type: 'TWIN_READY', hasConfig: !!this.config }); }

    _onMessage(e) {
        if (e.origin !== location.origin || !e.data || typeof e.data !== 'object') return;
        const m = e.data;
        if (m.type === 'PING') this._announce();
        else if (m.type === 'CONFIG') this.onConfig(m.config);
        else if (m.type === 'SYNC_STATE') {
            // Each message is a full snapshot. On a slow device the page can send faster than this view applies
            // them; processing every one built a backlog (the view fell more than a minute behind in the browser
            // tests). Keep only the newest and apply it once the queued messages have been read.
            const scheduled = this._pendingState != null;
            this._pendingState = m;
            if (!scheduled) setTimeout(() => { const st = this._pendingState; this._pendingState = null; if (st) this.onState(st); }, 0);
        }
        else if (m.type === 'LINK_STATUS') this._link(m.ok, m.detail);
        else if (m.type === 'UI_COMMAND') this.command(m.action, m.payload);
    }

    _link(ok, detail) {
        const el = document.getElementById('link');
        el.style.display = ok ? 'none' : 'block';
        el.textContent = ok ? '' : `Not receiving live data${detail ? ` — ${detail}` : ''}`;
    }

    async onConfig(cfg) {
        if (this.config || !cfg || !cfg.rooms) return;
        this.config = cfg;
        this.roomCfg = new Map(cfg.rooms.map((r) => [r.room_id, r]));
        this._setLoading(0.3, 'Raising the building…');
        await new Promise((r) => setTimeout(r, 0));
        this.building = new Building(this, cfg);
        this.interiors = new Interiors(this, this.building);
        await this.interiors.buildAll((p) => this._setLoading(0.3 + 0.6 * p, 'Furnishing the rooms…'));
        const capacity = cfg.rooms.reduce((a, r) => a + (r.max_occupancy || 4), 0) + 60;
        this.people = new People(this, capacity);
        this.people.visibleTest = (p) => this._personVisible(p);
        this.occupants = new Map();
        for (const rec of this.interiors.rooms.values()) this.occupants.set(rec.id, new RoomOccupants(this.people, rec));
        // pedestrians on the sidewalks (street life only)
        let i = 0;
        for (const path of this.site.walkPaths) {
            for (let k = 0; k < 5; k++) {
                const p = this.people.spawn({ x: path[0][0], z: path[0][1], y: 0.15, ry: 0, pose: 'walk', type: 'casual', scope: 'street', path });
                if (p) { p.pathT = (k + Math.random() * 0.5) / 5; p.pathDir = (i + k) % 2 ? 1 : -1; p.speed = 1.1 + Math.random() * 0.5; p.pos.y = 0.15; }
            }
            i++;
        }
        this._buildRoomLabels();
        this._buildFrames();
        this.ready = true;
        this._applyView(false);
        this._setLoading(1, 'Ready');
        if (this.pendingState) { this.onState(this.pendingState, true); this.pendingState = null; }
        post({ type: 'VIEW_CHANGED', ...this._viewMsg() });
    }

    onState(s, instant = false) {
        if (!this.ready) { this.pendingState = s; return; }
        const firstSync = !this.state;
        this.state = s;
        if (s.clock) this.env.setClock(s.clock.iso, s.clock.cloud_cover);
        const rooms = s.rooms || [];
        let matched = 0;
        const unmatched = [];
        let coolSum = 0, coolN = 0;
        for (const r of rooms) {
            const rec = this.interiors.rooms.get(r.room_id);
            if (!rec) { unmatched.push(r.room_id); continue; }
            matched++;
            rec.data = r;
            const hw = r.source === 'hardware';
            const connected = hw ? !!(r.hardware && r.hardware.connected) : true;
            const ds = r.device_state || {};
            // lights
            let level = 0;
            if (hw) level = connected && ds.light_level != null ? Math.max(0, Math.min(1, ds.light_level / 255)) : 0;
            else level = ds.light_level != null ? ds.light_level : (r.control && r.control.light_action === 'ON' ? 1 : r.control && r.control.light_action === 'DIM' ? 0.4 : 0);
            rec.lightLevel = level;
            // occupancy
            let n = 0;
            if (hw) n = connected && r.presence && r.presence.fused_presence ? 1 : 0;
            else n = r.ground_truth ? r.ground_truth.true_occupancy || 0 : 0;
            rec.people = n;
            rec.screenMat.emissiveIntensity = n > 0 ? 0.9 : 0.03;
            const occ = this.occupants.get(rec.id);
            if (occ) occ.set(n, { instant: instant || firstSync });
            // hvac
            let intensity = 0, mode = 'off', label = 'OFF';
            if (hw) {
                const pwm = connected && ds.hvac_speed != null ? ds.hvac_speed : 0;
                intensity = Math.max(0, Math.min(1, pwm / 255));
                mode = intensity > 0.01 ? 'fan' : 'off';
                label = intensity > 0.01 ? `FAN ${Math.round(intensity * 100)}%` : (connected ? 'FAN OFF' : 'NO BOARD');
            } else {
                const hm = ds.hvac_mode || 'off';
                const cool = (ds.hvac_speed || 0) / 100;
                mode = hm === 'comfort' ? 'cool' : hm === 'setback' ? 'setback' : 'off';
                intensity = mode === 'off' ? 0 : Math.max(0.12, Math.min(1, cool));
                const act = r.control ? r.control.hvac_action : null;
                label = act ? `${act}${mode !== 'off' && ds.setpoint ? ` ${Math.round(ds.setpoint)}°` : ''}` : mode.toUpperCase();
                coolSum += mode === 'off' ? 0 : cool; coolN++;
            }
            rec.hvacState = { intensity, mode, label, fresh: !!(r.control && r.control.vent_boost), temp: r.sensors ? r.sensors.Temperature : null, setpoint: hw ? (r.control && r.control.setpoint_c) : ds.setpoint };
            rec.hvac.live = hw && connected;
            rec.hvac.setState(rec.hvacState);
            rec.connected = connected;
        }
        this.coolingFraction = coolN ? coolSum / coolN : 0;
        this._updateLabels();
        post({ type: 'TWIN_SYNC_REPORT', matched, received: rooms.length, modelRooms: this.interiors.rooms.size, unmatched, seq: s.seq ?? null });
    }

    // ------------------------------------------------------------ commands
    command(action, p) {
        switch (action) {
            case 'setView': this.setView(p.mode, p.floor ?? null, p.room ?? null, { preset: p.preset, eye: p.eye }); break;
            case 'selectRoom': this.select(p, false); break;
            case 'isolateFloor': this.isolateFloor(p); break;
            case 'setOverlay': this.overlay = { mode: p.mode, colors: p.colors || {} }; this._applyOverlay(); break;
            case 'setLayers': Object.assign(this.layers, p); this._applyLayers(); break;
            case 'setLighting': this.env.setPreset(p); break;
            case 'setQuality': this._qualityLocked = true; this.setQuality(p); break;
            case 'cameraPreset': this.applyCameraPreset(p, true); break;
            case 'resetCamera': this.applyCameraPreset(null, true); break;
            case 'setPresentation': this.presentation = !!p; document.body.classList.toggle('present', this.presentation); break;
            case 'tour': if (p) this.startTour(); else this.stopTour(); break;
            default: break;
        }
    }

    select(id, notify = true) {
        this.selected = id && this.interiors && this.interiors.rooms.has(id) ? id : null;
        if (notify) post({ type: 'ROOM_SELECTED', room_id: this.selected });
        this._updateSelection();
        this._updateLabels();
    }

    isolateFloor(f) {
        if (this.view.mode !== 'building') return;
        this.view.isolated = f ?? null;
        if (this.building) this.building.isolate(this.view.isolated);
        this._applyLayers();
        this._updateSelection();
        this._updateLabels();
        post({ type: 'VIEW_CHANGED', ...this._viewMsg() });
    }

    setView(mode, floor = null, room = null, { animate = true, preset = null, eye = false } = {}) {
        if (!this.interiors) { this.view = { mode, floor, room, preset, eye }; return; }
        if (mode === 'room') {
            const rec = this.interiors.rooms.get(room);
            if (!rec) return;
            floor = rec.f;
        }
        if (mode === 'floor' && floor == null) floor = this.selected ? this.interiors.rooms.get(this.selected).f : 2;
        const same = this.view.mode === mode && this.view.floor === floor && this.view.room === room && !!this.view.eye === !!eye;
        this.view = { mode, floor, room, preset: preset || (mode === 'building' ? 'hero' : mode === 'floor' ? 'iso' : eye ? 'eye' : 'overview'), eye: !!eye, isolated: null };
        const newSel = room && room !== this.selected;
        if (newSel) this.selected = room;
        this._applyView(animate && !same);
        // the view first, then the selection: the page then never "corrects" the view
        post({ type: 'VIEW_CHANGED', ...this._viewMsg() });
        if (newSel) post({ type: 'ROOM_SELECTED', room_id: room });
    }

    _viewMsg() { return { mode: this.view.mode, floor: this.view.floor, room: this.view.room, eye: this.view.eye, preset: this.view.preset, isolated: this.view.isolated ?? null }; }

    _applyView(animate = true) {
        const v = this.view;
        const B = this.building, I = this.interiors;
        if (!B || !I) return;
        // envelope (room view replaces the floor's facade with the room's own windows)
        B.isolate(v.mode === 'building' ? (v.isolated ?? null) : v.floor);
        for (const fl of B.floors) B.setShellVisible(fl.f, !(v.mode === 'room' && fl.f === v.floor));
        // walls: building = full, floor = cut, room = only the focused room's walls
        I.setCut(v.mode === 'floor' ? 1.55 : null, v.floor);
        if (v.mode === 'room') I.focusRoom(v.room); else I.unfocus();
        for (const fl of I.floors) fl.walls.visible = v.mode !== 'room';
        for (const rec of I.rooms.values()) {
            const inRoom = v.mode !== 'room' || rec.id === v.room;
            rec.group.visible = inRoom;
            rec.hvac.group.visible = v.mode === 'room' || (v.mode === 'building');
            rec.ceiling.visible = v.mode !== 'floor';
        }
        this._applyLayers();
        this._applyOverlay();
        this._roomLights();
        this.applyCameraPreset(v.preset, animate);
        this._updateSelection();
        this._updateLabels();
    }

    _applyLayers() {
        if (this.people) this.people.setVisible(this.layers.people);
        if (!this.interiors) return;
        for (const rec of this.interiors.rooms.values()) {
            const show = this.layers.airflow && (this.view.mode !== 'building' || this.view.isolated != null) && (this.view.mode !== 'room' || rec.id === this.view.room);
            rec.hvac.flowGroup.visible = show && (this.view.mode === 'room' || rec.f === (this.view.floor ?? this.view.isolated));
        }
        this.labelRenderer.domElement.style.display = this.layers.labels ? '' : 'none';
    }

    _applyOverlay() {
        if (!this.interiors) return;
        const on = this.overlay.mode && this.overlay.mode !== 'none';
        for (const rec of this.interiors.rooms.values()) {
            const c = on ? this.overlay.colors[rec.id] : null;
            const show = !!c;
            if (c) { rec.tintFloor.material.color.set(c); rec.tintVol.material.color.set(c); }
            rec.tintFloor.visible = show && this.view.mode !== 'building';
            rec.tintVol.visible = show && this.view.mode === 'building';
        }
    }

    _personVisible(p) {
        if (p.scope === 'street') return true;
        const rec = this.interiors.rooms.get(p.scope);
        if (!rec) return false;
        const v = this.view;
        if (v.mode === 'room') return rec.id === v.room;
        const top = v.mode === 'floor' ? v.floor : (v.isolated ?? 99);
        return rec.f <= top;
    }

    // ------------------------------------------------------------ camera
    _presetFor(name) {
        const v = this.view;
        if (v.mode === 'building' || !this.interiors) {
            const P = {
                hero: { pos: [-38, 21, 40], target: [1, 7.5, 2] },
                street: { pos: [-14, 1.75, 41.5], target: [-3, 8, 4] },
                aerial: { pos: [46, 96, 78], target: [8, 0, 4] },
                garden: { pos: [38, 20, -58], target: [2, 8, -2] },
                corner: { pos: [42, 10, 36], target: [0, 9, 0] },
            };
            return P[name] || P.hero;
        }
        if (v.mode === 'floor') {
            const y = FL(v.floor);
            const P = {
                iso: { pos: [-24, y + 30, 32], target: [0, y, 0.5] },
                top: { pos: [0, y + 46, 0.01], target: [0, y, 0] },
                low: { pos: [-30, y + 12, 34], target: [0, y + 1, 0] },
                east: { pos: [34, y + 26, 22], target: [0, y, 0] },
            };
            return P[name] || P.iso;
        }
        const rec = this.interiors.rooms.get(v.room);
        const b = rec.box;
        const y = rec.fl;
        if (name === 'eye' || v.eye) {
            // stand at the inner corner, look towards the windows
            const ext = rec.edges.filter((e) => e.ext);
            const look = ext.length ? ext[0] : rec.edges[0];
            const back = { x: -look.n.x, z: -look.n.z };
            void back;
            const ex = b.cx + look.n.x * (b.w / 2 - 0.9) + (look.n.z !== 0 ? -b.w * 0.3 : 0);
            const ez = b.cz + look.n.z * (b.d / 2 - 0.9) + (look.n.x !== 0 ? -b.d * 0.3 : 0);
            return { pos: [ex, y + 1.6, ez], target: [b.cx - look.n.x * 0.5, y + 1.3, b.cz - look.n.z * 0.5], eye: true };
        }
        // overview: from outside the building, looking in and down
        let dx = b.cx, dz = b.cz;
        const len = Math.hypot(dx, dz);
        if (len < 2) { dx = -0.6; dz = 1; } else { dx /= len; dz /= len; }
        if (name === 'top') return { pos: [b.cx, y + Math.max(b.w, b.d) * 1.5 + 6, b.cz + 0.01], target: [b.cx, y, b.cz] };
        const dist = Math.max(b.w, b.d) * 0.78 + 4.5;
        const side = name === 'side' ? 1 : 0;
        const ang = Math.atan2(dx, dz) + (side ? 0.9 : 0.35);
        return { pos: [b.cx + Math.sin(ang) * dist, y + dist * 0.85, b.cz + Math.cos(ang) * dist], target: [b.cx, y + 0.6, b.cz] };
    }

    applyCameraPreset(name, animate = true) {
        const v = this.view;
        if (name) v.preset = name;
        const p = this._presetFor(v.preset);
        const c = this.controls;
        // limits per view
        if (v.mode === 'building' || !this.interiors) {
            c.minDistance = 10; c.maxDistance = 260; c.maxPolarAngle = 1.5; c.minPolarAngle = 0.05;
        } else if (v.mode === 'floor') {
            c.minDistance = 8; c.maxDistance = 90; c.maxPolarAngle = 1.3; c.minPolarAngle = 0.02;
        } else {
            const rec = this.interiors.rooms.get(v.room);
            const m = Math.max(rec.box.w, rec.box.d);
            if (p.eye) { c.minDistance = 0.5; c.maxDistance = m; c.maxPolarAngle = 2.2; c.minPolarAngle = 0.6; }
            else { c.minDistance = 2.5; c.maxDistance = m * 2.5 + 14; c.maxPolarAngle = 1.45; c.minPolarAngle = 0.05; }
        }
        v.eye = !!p.eye;
        const to = { pos: new THREE.Vector3(...p.pos), target: new THREE.Vector3(...p.target) };
        if (!animate) {
            this.camera.position.copy(to.pos);
            c.target.copy(to.target);
            c.update();
            this.camTween = null;
            return;
        }
        // fly via a raised midpoint so the camera never passes through walls or slabs
        const from = { pos: this.camera.position.clone(), target: c.target.clone() };
        const mid = from.pos.clone().lerp(to.pos, 0.5);
        mid.y = Math.max(from.pos.y, to.pos.y) + Math.min(25, from.pos.distanceTo(to.pos) * 0.25);
        this.camTween = { from, to, mid, t: 0, dur: Math.min(2.2, 1.0 + from.pos.distanceTo(to.pos) / 120) };
    }

    _updateCamera(dt) {
        const c = this.controls;
        if (this.camTween) {
            const tw = this.camTween;
            tw.t = Math.min(1, tw.t + dt / tw.dur);
            const k = ease(tw.t);
            // quadratic bezier through the raised midpoint
            const a = tw.from.pos.clone().lerp(tw.mid, k), b = tw.mid.clone().lerp(tw.to.pos, k);
            this.camera.position.copy(a.lerp(b, k));
            c.target.copy(tw.from.target.clone().lerp(tw.to.target, k));
            if (tw.t >= 1) this.camTween = null;
        }
        c.update();
        // keep the target inside the area of the current view (no getting lost)
        const t = c.target;
        const v = this.view;
        if (v.mode === 'building' || !this.interiors) {
            t.x = THREE.MathUtils.clamp(t.x, -90, 90); t.z = THREE.MathUtils.clamp(t.z, -90, 90); t.y = THREE.MathUtils.clamp(t.y, 0, 30);
        } else if (v.mode === 'floor') {
            const y = FL(v.floor);
            t.x = THREE.MathUtils.clamp(t.x, -22, 22); t.z = THREE.MathUtils.clamp(t.z, -16, 16); t.y = THREE.MathUtils.clamp(t.y, y - 1, y + 4);
        } else {
            const rec = this.interiors.rooms.get(v.room);
            const b = rec.box;
            t.x = THREE.MathUtils.clamp(t.x, b.x0 - 1, b.x1 + 1); t.z = THREE.MathUtils.clamp(t.z, b.z0 - 1, b.z1 + 1); t.y = THREE.MathUtils.clamp(t.y, rec.fl, rec.cl);
        }
        if (this.camera.position.y < 0.6) this.camera.position.y = 0.6;
    }

    // ------------------------------------------------------------ picking
    _initPicking() {
        this.ray = new THREE.Raycaster();
        this.mouse = new THREE.Vector2();
        const el = this.renderer.domElement;
        let down = null;
        el.addEventListener('pointerdown', (e) => { down = { x: e.clientX, y: e.clientY, t: performance.now() }; });
        el.addEventListener('pointermove', (e) => { this._pm = e; });
        el.addEventListener('pointerleave', () => { this._pm = null; this._setHover(null); });
        el.addEventListener('pointerup', (e) => {
            if (!down) return;
            const moved = Math.hypot(e.clientX - down.x, e.clientY - down.y) > 5;
            down = null;
            if (moved) return;
            const id = this._pick(e);
            if (id) this.select(id, true);
        });
        el.addEventListener('dblclick', (e) => {
            const id = this._pick(e);
            if (!id) return;
            const rec = this.interiors.rooms.get(id);
            if (this.view.mode === 'building') this.setView('floor', rec.f, null);
            else this.setView('room', rec.f, id);
        });
    }

    _pick(e) {
        if (!this.building) return null;
        const rect = this.renderer.domElement.getBoundingClientRect();
        this.mouse.set(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
        this.ray.setFromCamera(this.mouse, this.camera);
        const v = this.view;
        const top = v.mode === 'building' ? (v.isolated ?? 99) : v.floor;
        const boxes = [];
        for (const [id, hb] of this.building.hit) {
            const f = hb.userData.floor;
            if (f > top) continue;
            if (v.mode !== 'building' && f !== v.floor) continue;
            boxes.push(hb);
        }
        const hits = this.ray.intersectObjects(boxes, false);
        return hits.length ? hits[0].object.userData.roomId : null;
    }

    _setHover(id) {
        if (this.hover === id) return;
        this.hover = id;
        const el = this.renderer.domElement;
        el.style.cursor = id ? 'pointer' : '';
        this._updateSelection();
        if (!this.tip) return;
        if (!id) { this.tip.visible = false; return; }
        const rec = this.interiors.rooms.get(id);
        const d = rec.data || {};
        const hw = rec.live;
        const t = d.sensors && d.sensors.Temperature != null ? `${d.sensors.Temperature.toFixed(1)} °C` : '—';
        const ppl = hw ? (rec.connected ? (rec.people ? 'presence detected' : 'no presence') : 'board not connected') : `${rec.people ?? '—'} people`;
        this.tip.element.innerHTML = `<b>${rec.cfg.name}</b> ${hw ? '<span class="badge">LIVE</span>' : ''}<br><small>${FLOOR_NAMES[rec.f] || ''} · ${ppl} · ${t}</small><br><small>${this.view.mode === 'building' ? 'double-click: floor view' : 'double-click: room view'}</small>`;
        this.tip.position.set(rec.box.cx, CL(rec.f) + 0.3, rec.box.cz);
        this.tip.visible = true;
    }

    // ------------------------------------------------------------ labels and frames
    _initLabels() {
        this.labelRenderer = new CSS2DRenderer({ element: document.getElementById('labels') });
        const tipEl = document.createElement('div');
        tipEl.className = 'tip';
        this.tip = new CSS2DObject(tipEl);
        this.tip.visible = false;
        this.scene.add(this.tip);
    }

    _buildRoomLabels() {
        this.cards = new Map();
        this.hotspots = [];
        for (const rec of this.interiors.rooms.values()) {
            const el = document.createElement('div');
            el.className = `lbl card${rec.live ? ' live' : ''}`;
            el.addEventListener('click', (e) => { e.stopPropagation(); if (this.selected === rec.id) this.setView('room', rec.f, rec.id); else this.select(rec.id, true); });
            el.addEventListener('dblclick', (e) => { e.stopPropagation(); this.setView('room', rec.f, rec.id); });
            const obj = new CSS2DObject(el);
            obj.position.set(rec.box.cx, rec.fl + 1.7, rec.box.cz);
            obj.visible = false;
            this.scene.add(obj);
            this.cards.set(rec.id, { el, obj });
        }
        // floor tags on the west facade (building view)
        this.floorTags = [];
        for (const fl of this.building.floors) {
            const el = document.createElement('div');
            el.className = 'lbl floortag';
            el.textContent = FLOOR_NAMES[fl.f] || `Floor ${fl.f}`;
            el.addEventListener('click', (e) => { e.stopPropagation(); this.setView('floor', fl.f, null); });
            const obj = new CSS2DObject(el);
            obj.position.set(-GEO.W / 2 - 3.2, FL(fl.f) + 1.6, GEO.D / 2 + 1.0);
            obj.center.set(1, 0.5);
            this.scene.add(obj);
            this.floorTags.push({ el, obj, f: fl.f });
        }
        // LIVE beacon for the real room(s)
        this.beacons = [];
        for (const rec of this.interiors.rooms.values()) {
            if (!rec.live) continue;
            const el = document.createElement('div');
            el.className = 'lbl beacon';
            el.addEventListener('click', (e) => { e.stopPropagation(); this.setView('room', rec.f, rec.id); });
            const obj = new CSS2DObject(el);
            obj.position.set(rec.box.x0 - 0.5, CL(rec.f) + 1.0, rec.box.z1 + 1.2);
            this.scene.add(obj);
            this.beacons.push({ el, obj, rec });
        }
        // room view hotspots (filled on demand)
        this.hotGroup = new THREE.Group();
        this.scene.add(this.hotGroup);
    }

    _buildFrames() {
        // selection / hover / live frames: translucent box + edges
        const mk = (color, opacity, edgeOpacity) => {
            const g = new THREE.Group();
            const box = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshBasicMaterial({ color, transparent: true, opacity, depthWrite: false }));
            const edges = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(1, 1, 1)), new THREE.LineBasicMaterial({ color, transparent: true, opacity: edgeOpacity }));
            box.renderOrder = 9; edges.renderOrder = 10;
            g.add(box, edges);
            g.visible = false;
            this.scene.add(g);
            return { g, box, edges };
        };
        this.selFrame = mk(0x38bdf8, 0.1, 0.95);
        this.hovFrame = mk(0xffffff, 0.05, 0.6);
        this.liveFrames = [];
        for (const rec of this.interiors.rooms.values()) {
            if (!rec.live) continue;
            const f = mk(0x22d3ee, 0.06, 0.9);
            this.liveFrames.push({ ...f, rec });
        }
    }

    _placeFrame(fr, rec, flat) {
        const b = rec.box;
        const h = flat ? 0.08 : GEO.CEIL + 0.05;
        fr.g.position.set(b.cx, rec.fl + h / 2 - (flat ? 0 : 0.02), b.cz);
        fr.g.scale.set(b.w + 0.12, h, b.d + 0.12);
        fr.g.visible = true;
    }

    _updateSelection() {
        if (!this.selFrame || !this.interiors) return;
        const v = this.view;
        const sel = this.selected ? this.interiors.rooms.get(this.selected) : null;
        const flat = v.mode !== 'building';
        const visibleRec = (rec) => (v.mode === 'building' ? rec.f <= (v.isolated ?? 99) : v.mode === 'floor' ? rec.f === v.floor : false);
        if (sel && visibleRec(sel)) this._placeFrame(this.selFrame, sel, flat); else this.selFrame.g.visible = false;
        const hov = this.hover && this.hover !== this.selected ? this.interiors.rooms.get(this.hover) : null;
        if (hov && visibleRec(hov)) this._placeFrame(this.hovFrame, hov, flat); else this.hovFrame.g.visible = false;
        for (const lf of this.liveFrames) {
            if (visibleRec(lf.rec) && lf.rec.id !== this.selected) this._placeFrame(lf, lf.rec, flat); else lf.g.visible = false;
        }
    }

    _updateLabels() {
        if (!this.cards) return;
        const v = this.view;
        for (const [id, c] of this.cards) {
            const rec = this.interiors.rooms.get(id);
            const show = v.mode === 'floor' && rec.f === v.floor;
            c.obj.visible = show;
            if (!show) continue;
            c.el.classList.toggle('sel', this.selected === id);
            c.el.innerHTML = this._cardHtml(rec);
        }
        for (const t of this.floorTags) {
            t.obj.visible = v.mode === 'building' && t.f <= (v.isolated ?? 99);
            t.el.classList.toggle('sel', v.isolated === t.f);
        }
        for (const bc of this.beacons) {
            const rec = bc.rec;
            const d = rec.data || {};
            const st = d.hardware ? d.hardware.state : 'never_connected';
            const ok = !!rec.connected;
            bc.el.classList.toggle('bad', !ok);
            bc.el.innerHTML = `<span class="dot ${ok ? 'live' : 'bad'}"></span>LIVE · ${rec.cfg.name} <small>${ok ? 'ESP32 streaming' : st === 'lost' ? 'board lost' : 'board not connected'}</small>`;
            bc.obj.visible = v.mode === 'building' && rec.f <= (v.isolated ?? 99);
        }
        this._updateHotspots();
    }

    _cardHtml(rec) {
        const d = rec.data || {};
        const hw = rec.live;
        const t = d.sensors && d.sensors.Temperature != null ? `${d.sensors.Temperature.toFixed(1)}°C` : '—';
        const ppl = hw ? (rec.connected ? (rec.people ? 'yes' : 'none') : '—') : (rec.people ?? '—');
        const lvl = rec.lightLevel ?? 0;
        const light = lvl > 0.75 ? 'ON' : lvl > 0.05 ? 'DIM' : 'OFF';
        const hs = rec.hvacState || { mode: 'off', label: '—' };
        const badge = hw ? `<span class="badge${rec.connected ? '' : ' bad'}">LIVE</span>` : '';
        return `<h4><span class="dot ${hw ? (rec.connected ? 'live' : 'bad') : ''}"></span>${rec.cfg.name}${badge}</h4>
            <div class="row"><span title="${hw ? 'presence sensor (cannot count people)' : 'people (simulated truth)'}">${ICON.people}${ppl}</span><span>${ICON.temp}${t}</span></div>
            <div class="row"><span class="${light !== 'OFF' ? 'on' : ''}">${ICON.bulb}${light}</span><span class="${hs.mode === 'cool' || hs.mode === 'fan' ? 'cool' : hs.mode === 'setback' ? 'eco' : ''}">${ICON.snow}${hs.label}</span></div>
            <div class="enter">click again to enter the room ›</div>`;
    }

    _updateHotspots() {
        // room view: point at the thermostat, the AC, the people and the live sensor node
        const v = this.view;
        const key = v.mode === 'room' ? v.room : null;
        if (this._hotKey !== key) {
            for (const h of this.hotspots) { h.obj.removeFromParent(); }
            this.hotspots = [];
            this._hotKey = key;
            if (key) {
                const rec = this.interiors.rooms.get(key);
                const add = (kind, pos) => {
                    const el = document.createElement('div');
                    el.className = 'hot';
                    el.innerHTML = `<span class="pin ${kind === 'node' ? 'live' : kind === 'ac' ? '' : 'warm'}"></span><span class="txt"></span>`;
                    const obj = new CSS2DObject(el);
                    obj.position.copy(pos);
                    obj.center.set(0, 0.5);
                    this.hotGroup.add(obj);
                    this.hotspots.push({ kind, el, obj, txt: el.querySelector('.txt') });
                };
                add('thermo', rec.hvac.thermoPos.clone().add(new THREE.Vector3(0, 0.15, 0)));
                const u = rec.hvac.units[0];
                if (u) add('ac', u.pos.clone().add(new THREE.Vector3(0, -0.25, 0)));
                add('people', new THREE.Vector3(rec.box.cx, rec.fl + 2.1, rec.box.cz));
                const lf = rec.fixtures[0];
                if (lf) add('light', new THREE.Vector3(lf.x, rec.cl - 0.1, lf.z));
                if (rec.live && rec.hvac.nodePos) add('node', rec.hvac.nodePos.clone().add(new THREE.Vector3(0, 0.55, 0)));
            }
        }
        if (!key) return;
        const rec = this.interiors.rooms.get(key);
        const d = rec.data || {};
        const hs = rec.hvacState || {};
        const hw = rec.live;
        for (const h of this.hotspots) {
            if (h.kind === 'thermo') {
                const t = d.sensors && d.sensors.Temperature != null ? `${d.sensors.Temperature.toFixed(1)} °C` : '—';
                h.txt.innerHTML = `Thermostat ${t}<small>${hs.setpoint != null ? `set-point ${Math.round(hs.setpoint)} °C · ` : ''}room average from ${hw ? 'the real sensor' : 'the simulation'}</small>`;
            } else if (h.kind === 'ac') {
                h.txt.innerHTML = `AC ${hs.label || '—'}<small>${hw ? 'fan on the model = AC (PWM from the board)' : `cooling ${Math.round((hs.intensity || 0) * 100)} % of capacity${hs.fresh ? ' · ventilation boost' : ''}`}</small>`;
            } else if (h.kind === 'people') {
                h.txt.innerHTML = hw ? `${rec.connected ? (rec.people ? 'Presence detected' : 'No presence') : 'Board not connected'}<small>PIR + mmWave on the board (cannot count people)</small>`
                    : `${rec.people ?? '—'} ${rec.people === 1 ? 'person' : 'people'}<small>simulated truth · AI estimate P(occ) ${d.ai && d.ai.occupancy_probability != null ? d.ai.occupancy_probability.toFixed(2) : '—'}</small>`;
            } else if (h.kind === 'light') {
                const lvl = rec.lightLevel ?? 0;
                h.txt.innerHTML = `Lights ${lvl > 0.75 ? 'ON' : lvl > 0.05 ? 'DIM' : 'OFF'} ${Math.round(lvl * 100)} %<small>${d.control && d.control.light_action ? `controller: ${d.control.light_action}` : ''}${d.comfort && d.comfort.daylight_lux != null ? ` · daylight ${d.comfort.daylight_lux} lx` : ''}</small>`;
            } else if (h.kind === 'node') {
                const s = d.sensors || {};
                h.txt.innerHTML = `ESP32 sensor node<small>${rec.connected ? `CO₂ ${s.CO2 ?? '—'} ppm · ${s.Light ?? '—'} lx · RH ${s.Humidity ?? '—'} %` : 'not connected — values hidden'}</small>`;
            }
        }
    }

    // ------------------------------------------------------------ per-frame room lighting
    _roomLights() {
        // real area lights only for the room being viewed (cheap elsewhere: emissive + light pools)
        if (this.areaLights) { for (const l of this.areaLights) l.removeFromParent(); }
        this.areaLights = [];
        if (this.view.mode !== 'room' || !this.interiors) return;
        const rec = this.interiors.rooms.get(this.view.room);
        const b = rec.box;
        const nx = b.w > 9 ? 2 : 1, nz = b.d > 9 ? 2 : 1;
        for (let i = 0; i < nx; i++) for (let j = 0; j < nz; j++) {
            const l = new THREE.RectAreaLight(0xfff1dc, 0, (b.w / nx) * 0.8, (b.d / nz) * 0.8);
            l.position.set(b.x0 + (i + 0.5) * b.w / nx, rec.cl - 0.02, b.z0 + (j + 0.5) * b.d / nz);
            l.lookAt(l.position.x, rec.fl, l.position.z);
            this.scene.add(l);
            this.areaLights.push(l);
        }
    }

    _updateRoomVisuals(dt) {
        const night = 1 - this.env.day;
        for (const rec of this.interiors.rooms.values()) {
            const target = rec.lightLevel ?? 0;
            rec._lvl = (rec._lvl ?? target) + (target - (rec._lvl ?? target)) * Math.min(1, dt * 3);
            const l = rec._lvl;
            rec.lightMat.emissiveIntensity = l * (1.4 + 2.2 * night);
            const gm = this.building.roomGlass.get(rec.id);
            if (gm) gm.emissiveIntensity = l * night * 0.75;
            const poolOp = l * (0.05 + 0.5 * night) * (this.view.mode === 'room' ? 0.4 : 1);
            rec.pools.material.opacity = poolOp;
            rec.pools.visible = poolOp > 0.01;
            if (rec.group.visible) rec.hvac.update(dt, this.time);
        }
        if (this.areaLights && this.areaLights.length) {
            const rec = this.interiors.rooms.get(this.view.room);
            const l = rec._lvl ?? 0;
            const total = (rec.box.w * rec.box.d);
            for (const a of this.areaLights) a.intensity = l * (2.2 + 1.5 * night) * Math.min(1.4, 60 / total + 0.6);
        }
        for (const lf of this.liveFrames) {
            const pulse = 0.55 + 0.45 * Math.sin(this.time * 3);
            lf.edges.material.opacity = (lf.rec.connected ? 0.95 : 0.55) * pulse;
            lf.edges.material.color.setHex(lf.rec.connected ? 0x22d3ee : 0xf87171);
            lf.box.material.color.setHex(lf.rec.connected ? 0x22d3ee : 0xf87171);
            lf.box.material.opacity = lf.rec.connected ? 0.07 : 0.025;
        }
        // server LED flicker
        const ledI = 1.6 + Math.sin(this.time * 9) * 0.6;
        for (const m of this.interiors.ledMats) m.emissiveIntensity = ledI;
    }

    // ------------------------------------------------------------ tour
    startTour() {
        const steps = [
            { mode: 'building', preset: 'hero', dur: 9, rotate: true },
            { mode: 'building', preset: 'street', dur: 6 },
            { mode: 'floor', floor: 2, preset: 'iso', dur: 8, rotate: true },
            { mode: 'room', room: this._liveRoomId() || 'f2_office_a', dur: 10, rotate: true },
            { mode: 'room', room: 'f1_gym', dur: 10, rotate: true, airflow: true },
            { mode: 'room', room: 'f0_cafe', dur: 8, rotate: true },
            { mode: 'room', room: 'f4_lounge', eye: true, dur: 8 },
            { mode: 'building', preset: 'aerial', dur: 7, rotate: true },
        ].filter((s) => !s.room || this.interiors.rooms.has(s.room));
        this.tour = { steps, i: -1, t: 0, airflowBefore: this.layers.airflow };
        this._nextTourStep();
    }

    _nextTourStep() {
        const tr = this.tour;
        tr.i = (tr.i + 1) % tr.steps.length;
        tr.t = 0;
        const s = tr.steps[tr.i];
        this.layers.airflow = s.airflow ? true : tr.airflowBefore;
        this.setView(s.mode, s.floor ?? null, s.room ?? null, { preset: s.preset, eye: s.eye });
        this.controls.autoRotate = !!s.rotate;
        this.controls.autoRotateSpeed = 0.6;
        post({ type: 'TOUR_STEP', index: tr.i, total: tr.steps.length });
    }

    stopTour() {
        if (!this.tour) return;
        this.layers.airflow = this.tour.airflowBefore;
        this.tour = null;
        this.controls.autoRotate = false;
        this._applyLayers();
        post({ type: 'TOUR_STEP', index: -1, total: 0 });
    }

    _liveRoomId() {
        for (const rec of this.interiors.rooms.values()) if (rec.live) return rec.id;
        return null;
    }

    // ------------------------------------------------------------ frame
    _frame() {
        try { this._frameInner(); } catch (e) {
            if (!this._errLogged) { this._errLogged = true; console.error('twin frame error', e); }
        }
    }

    _frameInner() {
        const dt = Math.min(0.1, this.clock.getDelta());
        // never miss a size change (resize observers can be late when frames are slow)
        if (`${this.stage.clientWidth}x${this.stage.clientHeight}` !== this._size) this._resize();
        this.time += dt;
        this.env.update(dt);
        this.site.update(dt, this.env.day);
        this.site.setCarLights(1 - this.env.day);
        if (this.ready) {
            this._updateRoomVisuals(dt);
            for (const occ of this.occupants.values()) occ.tick();
            this.building.update(dt, this.coolingFraction || 0);
            if (this.view.mode === 'room') this.interiors.updateFocusCut(this.camera.position, this.view.eye);
        }
        if (this.ready) { this.people.update(dt); this.people.render(); }
        if (this.tour) {
            this.tour.t += dt;
            if (this.tour.t > this.tour.steps[this.tour.i].dur && !this.camTween) this._nextTourStep();
        }
        if (this._pm && this.ready && !this.camTween && (this._pmT = (this._pmT || 0) + dt) > 0.06) {
            this._pmT = 0;
            this._setHover(this._pick(this._pm));
        }
        this._updateCamera(dt);
        this._shadowT = (this._shadowT || 0) + dt;
        if (this._shadowT > 0.05) { this._shadowT = 0; this.renderer.shadowMap.needsUpdate = true; }
        this.renderer.info.reset();
        this.composer.render(dt);
        this.labelRenderer.render(this.scene, this.camera);
        this.frames++;
        this.fpsT += dt;
        if (this.fpsT > 2) {
            this.fps = this.frames / this.fpsT;
            this.frames = 0; this.fpsT = 0;
            const info = this.renderer.info.render;
            // automatic quality: drop to "balanced" when the GPU cannot keep up
            if (this.quality === 'high' && this.fps < 26 && !this._qualityLocked) {
                this._slow = (this._slow || 0) + 1;
                if (this._slow >= 2) { this.setQuality('balanced'); this._autoBalanced = true; }
            } else this._slow = 0;
            post({ type: 'TWIN_STATS', fps: Math.round(this.fps), calls: info.calls, triangles: info.triangles, quality: this.quality, auto: !!this._autoBalanced });
            window.__twinStats = { fps: this.fps, calls: info.calls, triangles: info.triangles };
        }
    }
}

window.twin = new App();
