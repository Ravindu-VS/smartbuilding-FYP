// ═══════════════════════════════════════════════════════════════
// hvac.js — AC equipment, thermostats and the qualitative airflow layer
// ═══════════════════════════════════════════════════════════════
// Large rooms get 4-way ceiling cassettes (one per ~45 m2), small rooms and homes
// a wall-mounted split unit. The airflow layer is QUALITATIVE (not CFD): particle
// jets leave each unit's outlets, run along the ceiling and fall as cool air, and
// room air returns to the unit's grille. How many particles move, and how fast,
// follows the unit's actual state from the simulation (cooling fraction of the AC
// in the simulated rooms, fan PWM on the live room's board); an AC that is OFF or
// in ECO shows no supply jets. Ventilation boost adds a fresh-air (green) stream.

import * as THREE from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
import { M } from '../lib/materials.js';
import { Batch } from '../lib/batch.js';

const VERT = /* glsl */`
uniform float uTime;
uniform float uIntensity;
uniform float uFresh;
uniform float uSize;
uniform float uReach;
uniform float uDrop;
attribute vec3 aOrigin;
attribute vec3 aDir;
attribute vec4 aSeed;
attribute float aKind;
attribute float aLag;
varying float vAlpha;
varying float vKind;
void main() {
    float on = aKind > 2.5 ? uFresh : uIntensity;
    float speed = (0.16 + 0.12 * aSeed.y) * mix(0.55, 1.45, on);
    float t = fract(uTime * speed + aSeed.x - aLag);
    vec3 perp = vec3(-aDir.z, 0.0, aDir.x);
    vec3 p;
    if (aKind < 0.5) {
        float r = 0.42 + uReach * (1.0 - pow(1.0 - t, 2.2)) * mix(0.55, 1.0, on);
        float drop = uDrop * pow(max(0.0, t - 0.22) / 0.78, 1.6) * mix(0.6, 1.0, on);
        float spread = aSeed.w * (0.3 + 0.95 * t);
        p = aOrigin + aDir * r + perp * spread + vec3(0.0, -0.06 - drop, 0.0);
    } else if (aKind < 1.5) {
        float r = 0.12 + uReach * 1.15 * (1.0 - pow(1.0 - t, 2.0)) * mix(0.55, 1.0, on);
        float drop = uDrop * 1.05 * pow(t, 1.4) * mix(0.6, 1.0, on);
        p = aOrigin + aDir * r + perp * aSeed.w * (0.35 + 0.9 * t) + vec3(0.0, -0.14 - drop, 0.0);
    } else if (aKind < 2.5) {
        vec3 start = aOrigin + aDir * (1.1 + 2.2 * abs(aSeed.w)) + vec3(0.0, -1.5 - 0.9 * aSeed.y, 0.0);
        float e = t * t * (3.0 - 2.0 * t);
        p = mix(start, aOrigin + vec3(0.0, -0.04, 0.0), e);
        p.y += sin(t * 3.14159) * 0.25;
    } else {
        float r = 0.1 + uReach * 0.9 * (1.0 - pow(1.0 - t, 2.0));
        float drop = uDrop * 0.8 * pow(t, 1.7);
        p = aOrigin + aDir * r + perp * aSeed.w * (0.6 + 0.6 * t) + vec3(0.0, -0.05 - drop, 0.0);
    }
    float fadeIn = smoothstep(0.0, 0.08, t) * (1.0 - smoothstep(0.82, 1.0, t));
    float visible = step(aSeed.z, on * 1.02) * step(0.01, on);
    vAlpha = fadeIn * visible * (1.0 - aLag * 14.0) * (aKind > 1.5 && aKind < 2.5 ? 0.45 : 1.0);
    vKind = aKind;
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_PointSize = min(12.0, uSize * (1.0 - aLag * 12.0) * (300.0 / max(0.5, -mv.z)));
    gl_Position = projectionMatrix * mv;
}`;

const FRAG = /* glsl */`
uniform vec3 uCool;
uniform vec3 uReturn;
uniform vec3 uFreshCol;
uniform float uOpacity;
varying float vAlpha;
varying float vKind;
void main() {
    vec2 c = gl_PointCoord - 0.5;
    float d = length(c);
    if (d > 0.5 || vAlpha < 0.01) discard;
    float a = smoothstep(0.5, 0.05, d) * vAlpha * uOpacity;
    vec3 col = vKind < 1.5 ? uCool : (vKind < 2.5 ? uReturn : uFreshCol);
    gl_FragColor = vec4(col, a);
}`;

function thermostatCanvas() {
    const c = document.createElement('canvas');
    c.width = 160; c.height = 160;
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    return { c, ctx: c.getContext('2d'), t };
}

function drawThermostat(th, s) {
    const { ctx, c } = th;
    ctx.clearRect(0, 0, c.width, c.height);
    ctx.fillStyle = '#0b1220';
    ctx.beginPath(); ctx.roundRect(4, 4, 152, 152, 22); ctx.fill();
    const accent = s.mode === 'cool' ? '#38bdf8' : s.mode === 'setback' ? '#f59e0b' : s.mode === 'fan' ? '#a5f3fc' : '#64748b';
    ctx.strokeStyle = accent; ctx.lineWidth = 6;
    ctx.beginPath(); ctx.arc(80, 74, 56, Math.PI * 0.8, Math.PI * (0.8 + 1.4 * Math.max(0.03, s.intensity)), false); ctx.stroke();
    ctx.fillStyle = '#e2e8f0';
    ctx.font = 'bold 38px Segoe UI, Arial';
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(s.temp == null ? '--' : `${s.temp.toFixed(1)}°`, 80, 70);
    ctx.font = '15px Segoe UI, Arial';
    ctx.fillStyle = '#94a3b8';
    ctx.fillText(s.setpoint == null ? 'SET --' : `SET ${Math.round(s.setpoint)}°`, 80, 104);
    ctx.font = 'bold 15px Segoe UI, Arial';
    ctx.fillStyle = accent;
    ctx.fillText(s.label, 80, 132);
    th.t.needsUpdate = true;
}

/** Equipment + airflow for one room. */
export class RoomHVAC {
    constructor(room, { fl, cl, box, wallFor, live }) {
        this.room = room;
        this.group = new THREE.Group();          // equipment (units, thermostat)
        this.group.name = `hvac_${room.room_id}`;
        this.flowGroup = new THREE.Group();
        this.units = [];
        this.state = { intensity: 0, mode: 'off', fresh: 0 };
        this._key = '';
        const area = box.w * box.d;
        // visual only: the simulation models one AC (its capacity) per room; large rooms
        // get ceiling cassettes, small rooms and bathrooms/kitchens a wall split unit
        const useSplit = area < 60 || (['residential', 'bathroom', 'kitchen'].includes(room.type) && area < 100);
        const ledMat = new THREE.MeshStandardMaterial({ color: 0x111111, emissive: 0x22c55e, emissiveIntensity: 0, roughness: 0.4 });
        this.ledMat = ledMat;
        const white = M.std(0xf5f5f3, 0.45);
        const grille = M.std(0xdfe1e3, 0.6);
        const dark = M.std(0x3a3d42, 0.6);
        const origins = [];
        const eb = new Batch();          // static equipment merged per room (few draw calls)
        if (!useSplit) {
            const n = Math.max(1, Math.round(area / 45));
            const cols = Math.max(1, Math.round(Math.sqrt(n * box.w / box.d)));
            const rows = Math.max(1, Math.ceil(n / cols));
            for (let i = 0; i < cols; i++) for (let j = 0; j < rows; j++) {
                const x = box.x0 + (i + 0.5) * box.w / cols, z = box.z0 + (j + 0.5) * box.d / rows;
                eb.push(x, cl, z);
                eb.add(new THREE.BoxGeometry(1.02, 0.05, 1.02), M.std(0xc9cdd1, 0.5), 0, 0.005, 0);   // housing edge (reads as a device)
                eb.add(new RoundedBoxGeometry(0.95, 0.06, 0.95, 1, 0.02), white, 0, -0.03, 0);
                eb.add(new THREE.BoxGeometry(0.5, 0.01, 0.5), grille, 0, -0.065, 0);
                for (let k = 0; k < 4; k++) {
                    const a = (k * Math.PI) / 2;
                    eb.add(new THREE.BoxGeometry(0.62, 0.012, 0.07), dark, Math.sin(a) * 0.37, -0.066, Math.cos(a) * 0.37, a);
                }
                eb.add(new THREE.CircleGeometry(0.015, 8), ledMat, 0.4, -0.067, 0.4, 0, Math.PI / 2);
                eb.pop();
                this.units.push({ kind: 0, pos: new THREE.Vector3(x, cl, z) });
                for (let k = 0; k < 4; k++) {
                    const a = (k * Math.PI) / 2;
                    origins.push({ kind: 0, o: new THREE.Vector3(x, cl, z), dir: new THREE.Vector3(Math.sin(a), 0, Math.cos(a)) });
                }
                origins.push({ kind: 2, o: new THREE.Vector3(x, cl, z) });
            }
        } else {
            // wall split on an internal wall (or the back wall), facing into the room
            const w = wallFor();
            eb.push(w.x, cl - 0.42, w.z, w.ry);
            eb.add(new RoundedBoxGeometry(0.98, 0.3, 0.24, 2, 0.06), white, 0, 0, 0.12);
            eb.add(new THREE.CircleGeometry(0.012, 8), ledMat, 0.36, -0.06, 0.245);
            eb.pop();
            const flap = new THREE.Mesh(new THREE.BoxGeometry(0.82, 0.015, 0.09), grille);
            flap.position.set(w.x + Math.sin(w.ry) * 0.2, cl - 0.42 - 0.14, w.z + Math.cos(w.ry) * 0.2);
            flap.rotation.order = 'YXZ';
            flap.rotation.y = w.ry;
            this.group.add(flap);
            this.units.push({ kind: 1, pos: new THREE.Vector3(w.x, cl - 0.42, w.z), flap });
            const dir = new THREE.Vector3(Math.sin(w.ry), 0, Math.cos(w.ry));
            const o = new THREE.Vector3(w.x, cl - 0.42, w.z).addScaledVector(dir, 0.25);
            origins.push({ kind: 1, o, dir });
            origins.push({ kind: 2, o: new THREE.Vector3(w.x, cl - 0.3, w.z).addScaledVector(dir, 0.2) });
        }
        // thermostat on a wall near the door
        const tw = wallFor(true);
        this.thermo = thermostatCanvas();
        const tm = new THREE.MeshStandardMaterial({ map: this.thermo.t, emissive: 0xffffff, emissiveMap: this.thermo.t, emissiveIntensity: 0.55, roughness: 0.3 });
        const th = new THREE.Mesh(new THREE.PlaneGeometry(0.16, 0.16), tm);
        th.position.set(tw.x, fl + 1.45, tw.z);
        th.rotation.y = tw.ry;
        th.position.x += Math.sin(tw.ry) * 0.075;
        th.position.z += Math.cos(tw.ry) * 0.075;
        const nrm = new THREE.Vector3(Math.sin(tw.ry), 0, Math.cos(tw.ry));
        const bezelPos = th.position.clone().addScaledVector(nrm, -0.012);
        eb.add(new RoundedBoxGeometry(0.19, 0.19, 0.025, 1, 0.02), M.std(0xf0f0ee, 0.4), bezelPos.x, bezelPos.y, bezelPos.z, tw.ry);
        this.group.add(th);
        if (live) {
            // the real board: ESP32 sensor node mounted next to the thermostat
            const nodePos = bezelPos.clone().add(new THREE.Vector3(Math.cos(tw.ry) * 0.3, 0, -Math.sin(tw.ry) * 0.3));
            eb.add(new RoundedBoxGeometry(0.16, 0.1, 0.05, 1, 0.01), M.std(0x1f2937, 0.5), nodePos.x, nodePos.y, nodePos.z, tw.ry);
            this.nodeLed = new THREE.MeshStandardMaterial({ color: 0x111111, emissive: 0x22d3ee, emissiveIntensity: 2 });
            const lp = nodePos.clone().addScaledVector(nrm, 0.027);
            eb.add(new THREE.CircleGeometry(0.008, 8), this.nodeLed, lp.x, lp.y, lp.z, tw.ry);
            this.nodePos = nodePos;
        }
        eb.build(this.group, { name: `hvac_${room.room_id}`, cast: false });
        this.thermoPos = th.position.clone();
        drawThermostat(this.thermo, { temp: null, setpoint: null, mode: 'off', intensity: 0, label: '—' });

        // airflow particles for all units of the room
        const P = [];
        const add = (kind, o, dir, count, lags) => {
            for (let i = 0; i < count; i++) {
                const seed = [Math.random(), Math.random(), Math.random(), (Math.random() * 2 - 1)];
                let d = dir;
                if (kind === 2) { const a = Math.random() * Math.PI * 2; d = new THREE.Vector3(Math.cos(a), 0, Math.sin(a)); }
                for (const lag of lags) P.push({ o, d: d || new THREE.Vector3(1, 0, 0), seed, kind, lag });
            }
        };
        for (const u of origins) {
            if (u.kind === 0) add(0, u.o, u.dir, 46, [0, 0.012, 0.024]);
            else if (u.kind === 1) add(1, u.o, u.dir, 150, [0, 0.012, 0.024]);
            else add(2, u.o, null, 40, [0]);
        }
        // fresh-air diffuser (ventilation boost) near the room centre
        add(3, new THREE.Vector3(box.cx + box.w * 0.18, cl, box.cz - box.d * 0.18), new THREE.Vector3(0, 0, 1), 70, [0, 0.015]);
        const n = P.length;
        const geo = new THREE.BufferGeometry();
        const pos = new Float32Array(n * 3), aO = new Float32Array(n * 3), aD = new Float32Array(n * 3), aS = new Float32Array(n * 4), aK = new Float32Array(n), aL = new Float32Array(n);
        P.forEach((p, i) => {
            pos.set([p.o.x, p.o.y, p.o.z], i * 3);
            aO.set([p.o.x, p.o.y, p.o.z], i * 3);
            aD.set([p.d.x, 0, p.d.z], i * 3);
            aS.set(p.seed, i * 4);
            aK[i] = p.kind; aL[i] = p.lag;
        });
        geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
        geo.setAttribute('aOrigin', new THREE.BufferAttribute(aO, 3));
        geo.setAttribute('aDir', new THREE.BufferAttribute(aD, 3));
        geo.setAttribute('aSeed', new THREE.BufferAttribute(aS, 4));
        geo.setAttribute('aKind', new THREE.BufferAttribute(aK, 1));
        geo.setAttribute('aLag', new THREE.BufferAttribute(aL, 1));
        geo.boundingSphere = new THREE.Sphere(new THREE.Vector3(box.cx, fl + 1.5, box.cz), Math.hypot(box.w, box.d) / 2 + 3);
        this.uniforms = {
            uTime: { value: 0 }, uIntensity: { value: 0 }, uFresh: { value: 0 }, uSize: { value: 0.42 },
            uReach: { value: Math.min(2.6, 0.9 + Math.sqrt(area) * 0.12) }, uDrop: { value: 1.55 },
            uCool: { value: new THREE.Color(0x2fa8ff) }, uReturn: { value: new THREE.Color(0xff9d5c) }, uFreshCol: { value: new THREE.Color(0x22c55e) },
            uOpacity: { value: 0.9 },
        };
        const mat = new THREE.ShaderMaterial({
            vertexShader: VERT, fragmentShader: FRAG, uniforms: this.uniforms,
            transparent: true, depthWrite: false, blending: THREE.NormalBlending,
        });
        this.points = new THREE.Points(geo, mat);
        this.points.renderOrder = 8;
        this.points.frustumCulled = true;
        this.flowGroup.add(this.points);
        this.flowGroup.visible = false;
    }

    /**
     * s: { intensity 0..1, mode 'cool'|'setback'|'fan'|'off', fresh 0|1, temp, setpoint, label }
     */
    setState(s) {
        this.state = s;
        this.uniforms.uFresh.value = s.fresh ? 1 : 0;
        const col = s.mode === 'fan' ? 0x5ec8ff : s.mode === 'setback' ? 0x7cc4ef : 0x2fa8ff;
        this.uniforms.uCool.value.setHex(col);
        this.ledMat.emissive.setHex(s.mode === 'cool' ? 0x22c55e : s.mode === 'setback' ? 0xf59e0b : s.mode === 'fan' ? 0x38bdf8 : 0x000000);
        this.ledMat.emissiveIntensity = s.mode === 'off' ? 0 : 2.5;
        const key = `${s.temp == null ? '-' : s.temp.toFixed(1)}|${s.setpoint}|${s.mode}|${Math.round(s.intensity * 20)}|${s.label}`;
        if (key !== this._key) { this._key = key; drawThermostat(this.thermo, s); }
    }

    update(dt, t) {
        // ease the visible intensity towards the state (no popping)
        const u = this.uniforms;
        u.uIntensity.value += ((this.state.intensity || 0) - u.uIntensity.value) * Math.min(1, dt * 1.5);
        u.uTime.value = t;
        for (const unit of this.units) if (unit.flap) unit.flap.rotation.x = 0.15 + 0.9 * u.uIntensity.value;
        if (this.nodeLed) this.nodeLed.emissiveIntensity = this.live ? 1.5 + Math.sin(t * 6) : 0.2;
    }
}
