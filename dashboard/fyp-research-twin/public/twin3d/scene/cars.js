// ═══════════════════════════════════════════════════════════════
// cars.js — procedural cars, parked cars and street traffic
// ═══════════════════════════════════════════════════════════════
// Street ambience only (no data meaning): cars drive on the left, as in Sri Lanka,
// queue at the junction's traffic lights and light their lamps at night.

import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { rand } from '../lib/materials.js';

function extrudeProfile(points, width, bevel = 0.06) {
    const shape = new THREE.Shape(points.map(([x, y]) => new THREE.Vector2(x, y)));
    const g = new THREE.ExtrudeGeometry(shape, { depth: width - 2 * bevel, bevelEnabled: true, bevelThickness: bevel, bevelSize: bevel, bevelSegments: 3, curveSegments: 6 });
    g.translate(0, 0, -(width - 2 * bevel) / 2);
    return g;
}

function clean(g) {
    for (const k of Object.keys(g.attributes)) if (!['position', 'normal', 'uv'].includes(k)) g.deleteAttribute(k);
    if (!g.index) { const n = g.attributes.position.count; g.setIndex([...Array(n).keys()]); }
    return g;
}

const TYPES = {
    sedan: {
        body: [[-2.3, 0.28], [-2.34, 0.6], [-2.15, 0.78], [-0.95, 0.92], [-0.35, 1.38], [0.8, 1.4], [1.55, 1.0], [2.25, 0.94], [2.33, 0.62], [2.28, 0.28]],
        glass: [[-0.9, 0.95], [-0.36, 1.34], [0.78, 1.36], [1.48, 1.0]],
        width: 1.8, wheelbase: 1.38, track: 0.8, r: 0.33, front: -2.3, rear: 2.3, lightY: 0.72,
    },
    suv: {
        body: [[-2.3, 0.35], [-2.36, 0.75], [-2.2, 0.98], [-1.05, 1.08], [-0.55, 1.72], [1.95, 1.74], [2.32, 1.5], [2.36, 0.8], [2.3, 0.35]],
        glass: [[-1.0, 1.1], [-0.56, 1.66], [1.92, 1.68], [2.22, 1.42], [2.24, 1.1]],
        width: 1.9, wheelbase: 1.42, track: 0.84, r: 0.37, front: -2.3, rear: 2.35, lightY: 0.9,
    },
    hatch: {
        body: [[-1.95, 0.3], [-2.0, 0.62], [-1.85, 0.8], [-0.85, 0.94], [-0.3, 1.45], [1.55, 1.46], [1.92, 1.15], [1.98, 0.62], [1.94, 0.3]],
        glass: [[-0.8, 0.97], [-0.31, 1.4], [1.5, 1.41], [1.84, 1.1]],
        width: 1.75, wheelbase: 1.25, track: 0.78, r: 0.31, front: -1.95, rear: 1.95, lightY: 0.75,
    },
};

const PAINTS = [0xf2f2f0, 0xf2f2f0, 0xe8e8e6, 0xb9bdc2, 0xa7abb0, 0x1b1d20, 0x22262b, 0x3c4148, 0x8c1c1c, 0x1f3f78, 0x6b7b8a, 0x2f4a3a];

const GEOS = {};
function carGeos(type) {
    if (GEOS[type]) return GEOS[type];
    const t = TYPES[type];
    const body = clean(extrudeProfile(t.body, t.width, 0.08));
    const glass = clean(extrudeProfile(t.glass, t.width + 0.04, 0.03));
    const wheels = [];
    const rims = [];
    for (const sx of [-1, 1]) for (const sz of [-1, 1]) {
        const w = new THREE.CylinderGeometry(t.r, t.r, 0.24, 18);
        w.rotateX(Math.PI / 2);
        w.translate(sx * t.wheelbase, t.r, sz * t.track);
        wheels.push(clean(w));
        const rm = new THREE.CylinderGeometry(t.r * 0.62, t.r * 0.62, 0.25, 12);
        rm.rotateX(Math.PI / 2);
        rm.translate(sx * t.wheelbase, t.r, sz * (t.track + 0.005));
        rims.push(clean(rm));
    }
    const head = [], tail = [];
    for (const sz of [-1, 1]) {
        const h = new THREE.BoxGeometry(0.08, 0.12, 0.38);
        h.translate(t.front - 0.02, t.lightY, sz * (t.width / 2 - 0.3));
        head.push(clean(h));
        const tl = new THREE.BoxGeometry(0.08, 0.12, 0.42);
        tl.translate(t.rear + 0.01, t.lightY + 0.05, sz * (t.width / 2 - 0.28));
        tail.push(clean(tl));
    }
    GEOS[type] = {
        body, glass, wheel: mergeGeometries(wheels), rim: mergeGeometries(rims),
        head: mergeGeometries(head), tail: mergeGeometries(tail),
    };
    return GEOS[type];
}

let MAT = null;
function mats() {
    if (MAT) return MAT;
    MAT = {
        body: new THREE.MeshPhysicalMaterial({ color: 0xffffff, roughness: 0.28, metalness: 0.55, clearcoat: 1.0, clearcoatRoughness: 0.08 }),
        glass: new THREE.MeshStandardMaterial({ color: 0x0e151c, roughness: 0.05, metalness: 0.6, envMapIntensity: 1.5 }),
        tyre: new THREE.MeshStandardMaterial({ color: 0x141414, roughness: 0.9 }),
        rim: new THREE.MeshStandardMaterial({ color: 0xc4c7cb, roughness: 0.3, metalness: 0.9 }),
        head: new THREE.MeshStandardMaterial({ color: 0xf6f3e8, emissive: 0xfff4d6, emissiveIntensity: 0.1, roughness: 0.2 }),
        tail: new THREE.MeshStandardMaterial({ color: 0x5a0d0d, emissive: 0xff2a1a, emissiveIntensity: 0.15, roughness: 0.3 }),
    };
    MAT.headLit = MAT.head.clone();
    MAT.tailLit = MAT.tail.clone();
    return MAT;
}

/** Instanced fleet of one car type. update(i, x, z, heading) sets a car's pose. */
class Fleet {
    constructor(parent, type, count, lit = false) {
        const g = carGeos(type), m = mats();
        this.parts = [
            new THREE.InstancedMesh(g.body, m.body, count),
            new THREE.InstancedMesh(g.glass, m.glass, count),
            new THREE.InstancedMesh(g.wheel, m.tyre, count),
            new THREE.InstancedMesh(g.rim, m.rim, count),
            new THREE.InstancedMesh(g.head, lit ? m.headLit : m.head, count),
            new THREE.InstancedMesh(g.tail, lit ? m.tailLit : m.tail, count),
        ];
        const c = new THREE.Color();
        for (let i = 0; i < count; i++) this.parts[0].setColorAt(i, c.setHex(PAINTS[(rand() * PAINTS.length) | 0]));
        this.parts.forEach((p, i) => {
            p.castShadow = i < 3;
            p.receiveShadow = true;
            p.frustumCulled = false;
            parent.add(p);
        });
        this.m4 = new THREE.Matrix4();
        this.q = new THREE.Quaternion();
        this.up = new THREE.Vector3(0, 1, 0);
        this.one = new THREE.Vector3(1, 1, 1);
        this.p = new THREE.Vector3();
    }

    set(i, x, z, heading) {
        // car model's front is -x; heading = direction of travel (radians, 0 = +x)
        this.q.setFromAxisAngle(this.up, -heading + Math.PI);
        this.m4.compose(this.p.set(x, 0, z), this.q, this.one);
        for (const p of this.parts) p.setMatrixAt(i, this.m4);
    }

    commit() { for (const p of this.parts) p.instanceMatrix.needsUpdate = true; }
}

export function carMaterials() { return mats(); }

/** Parked cars at [{x, z, heading}] (mixed types). */
export function parkCars(parent, spots) {
    const byType = { sedan: [], suv: [], hatch: [] };
    spots.forEach((s) => { const r = rand(); byType[r < 0.45 ? 'sedan' : r < 0.75 ? 'suv' : 'hatch'].push(s); });
    for (const [type, list] of Object.entries(byType)) {
        if (!list.length) continue;
        const f = new Fleet(parent, type, list.length);
        list.forEach((s, i) => f.set(i, s.x, s.z, s.heading));
        f.commit();
        f.parts.forEach((p) => { p.frustumCulled = true; p.computeBoundingSphere(); });
    }
}

/**
 * Traffic on a set of straight lanes with one signalised stop line per lane.
 * lanes: [{ axis: 'x'|'z', fixed, dir: +1|-1, from, to, stopAt, group: 'main'|'side' }]
 */
export class Traffic {
    constructor(parent, lanes, perLane = 4) {
        this.lanes = lanes;
        this.cars = [];
        const total = lanes.length * perLane;
        this.fleets = { sedan: [], suv: [], hatch: [] };
        const types = [];
        for (let i = 0; i < total; i++) { const r = rand(); types.push(r < 0.45 ? 'sedan' : r < 0.75 ? 'suv' : 'hatch'); }
        const counts = { sedan: 0, suv: 0, hatch: 0 };
        types.forEach((t) => counts[t]++);
        this.fleet = {};
        for (const t of Object.keys(counts)) if (counts[t]) this.fleet[t] = new Fleet(parent, t, counts[t], true);
        const idx = { sedan: 0, suv: 0, hatch: 0 };
        let k = 0;
        lanes.forEach((lane, li) => {
            const len = Math.abs(lane.to - lane.from);
            for (let j = 0; j < perLane; j++) {
                const t = types[k++];
                this.cars.push({ lane: li, s: (j / perLane) * len + rand() * 8, v: 8 + rand() * 4, vmax: 9 + rand() * 4, type: t, i: idx[t]++ });
            }
        });
        this.time = 0;
        this.signal = { main: 'green', side: 'red' };
        this.onSignal = null;
    }

    _phase(t) {
        // 32 s cycle: main green 16, amber 3, all-red 1, side green 9, amber 3
        const c = t % 32;
        if (c < 16) return { main: 'green', side: 'red' };
        if (c < 19) return { main: 'amber', side: 'red' };
        if (c < 20) return { main: 'red', side: 'red' };
        if (c < 29) return { main: 'red', side: 'green' };
        return { main: 'red', side: 'amber' };
    }

    update(dt) {
        dt = Math.min(dt, 0.1);
        this.time += dt;
        const sig = this._phase(this.time);
        if (sig.main !== this.signal.main || sig.side !== this.signal.side) {
            this.signal = sig;
            if (this.onSignal) this.onSignal(sig);
        }
        const byLane = this.lanes.map(() => []);
        this.cars.forEach((c) => byLane[c.lane].push(c));
        byLane.forEach((list, li) => {
            const lane = this.lanes[li];
            const len = Math.abs(lane.to - lane.from);
            const stopS = lane.stopAt != null ? Math.abs(lane.stopAt - lane.from) : null;
            list.sort((a, b) => a.s - b.s);
            for (let j = 0; j < list.length; j++) {
                const c = list[j];
                const ahead = list[(j + 1) % list.length];
                let gap = (ahead.s - c.s + len) % len;
                if (list.length === 1) gap = 1e9;
                let target = c.vmax;
                // keep distance to the car ahead (simple car-following)
                target = Math.min(target, Math.max(0, (gap - 7.5) * 0.9));
                // stop at a red/amber light if the stop line is ahead and reachable
                if (stopS != null && this.signal[lane.group] !== 'green') {
                    const d = stopS - c.s;
                    if (d > 0.5 && d < 45) target = Math.min(target, Math.max(0, (d - 1.5) * 0.55));
                }
                const acc = target > c.v ? 2.2 : 6.0;
                c.v += Math.sign(target - c.v) * Math.min(Math.abs(target - c.v), acc * dt);
                c.s = (c.s + c.v * dt) % len;
                const along = lane.from + lane.dir * c.s;
                const heading = lane.axis === 'x' ? (lane.dir > 0 ? 0 : Math.PI) : (lane.dir > 0 ? Math.PI / 2 : -Math.PI / 2);
                const x = lane.axis === 'x' ? along : lane.fixed;
                const z = lane.axis === 'x' ? lane.fixed : along;
                this.fleet[c.type].set(c.i, x, z, heading);
            }
        });
        for (const f of Object.values(this.fleet)) f.commit();
    }
}
