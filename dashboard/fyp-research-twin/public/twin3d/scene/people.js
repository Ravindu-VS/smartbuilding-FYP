// ═══════════════════════════════════════════════════════════════
// people.js — occupants that match the simulation, doing what the room is for
// ═══════════════════════════════════════════════════════════════
// The number of people drawn in a simulated room is the simulator's true
// occupancy (ground_truth.true_occupancy). The live room has no people counter, so
// it shows one person only while its presence sensor reports presence. People walk
// in from the room's door when the count rises and walk out when it falls, then
// take the activity of the spot they go to: typing at a desk, running on a
// treadmill, cooking, sleeping, talking in a group.
//
// All figures are drawn with 11 InstancedMeshes (one per body part), posed on the
// CPU through a small joint hierarchy per person.

import * as THREE from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';

const HIP = 0.93;
const SKIN = [0xf1c9a5, 0xe0ac87, 0xc68e64, 0xa86f48, 0x8d5a3b, 0x6e4430, 0x553324];
const HAIR = [0x16110e, 0x1d1714, 0x2b1d14, 0x3d2a1d, 0x5a4330, 0x8a7a6a, 0xb0a497, 0x1a1a1a];
const SHOES = [0x1b1b1d, 0x2b2420, 0x3b3f45, 0xe9e7e2, 0x6b4a33, 0x1f2a3a];
const PALETTE = {
    work: { shirt: [0xf4f4f2, 0xd9e6f2, 0xa9c4de, 0x2c3e55, 0x6b7280, 0xe8e2d6, 0x8c3b3b, 0x38505f, 0xf0e1d2], pants: [0x22272e, 0x2f3b4c, 0x4a4f57, 0x6b6156, 0x1b1d20, 0x8a7d6b] },
    casual: { shirt: [0xc94f4f, 0x4f7fc9, 0xe0c35a, 0x5aa36b, 0xf2efe8, 0x2f6f73, 0xb5643c, 0x7b6aa8, 0x1f2124, 0xd27aa0], pants: [0x2f3e55, 0x3b4a63, 0x1d1f22, 0x7a6a55, 0xcfc4b0, 0x4a5a3a] },
    sport: { shirt: [0x1f8fd6, 0xe9483b, 0x22c55e, 0x111214, 0xf59e0b, 0x8b5cf6, 0xf4f4f2, 0xec4899], pants: [0x111214, 0x1f2937, 0x374151, 0x111214] },
    staff: { shirt: [0x2b2d31, 0x1f2937, 0x3a2f28], pants: [0x1b1d20, 0x22272e] },
};

function paletteFor(type, pose) {
    if (pose === 'run' || pose === 'cycle' || pose === 'yoga' || pose === 'lift_db' || pose === 'stretch' || pose === 'lie_bench') return 'sport';
    if (type === 'gym') return 'sport';
    if (pose === 'barista') return 'staff';
    if (type === 'office' || type === 'meeting' || type === 'executive' || type === 'server' || type === 'kitchen') return 'work';
    return 'casual';
}

let seed = 4242;
function r() { seed = (seed * 16807) % 2147483647; return seed / 2147483647; }
const pick = (a) => a[(r() * a.length) | 0];
const lerp = (a, b, k) => a + (b - a) * k;

// ---------------------------------------------------------------- poses
const JOINTS = ['y', 'pitch', 'spine', 'side', 'twist', 'head', 'headY', 'shLx', 'shRx', 'shLz', 'shRz', 'elL', 'elR', 'hipLx', 'hipRx', 'hipLz', 'hipRz', 'knL', 'knR', 'dx', 'dz'];

function standBase(t, ph) {
    return {
        y: HIP, pitch: 0, spine: 0.03, side: 0, twist: Math.sin(t * 0.4 + ph) * 0.04, head: 0.05 + Math.sin(t * 0.3 + ph) * 0.04, headY: Math.sin(t * 0.23 + ph * 2) * 0.25,
        shLx: 0.03, shRx: 0.03, shLz: 0.09, shRz: -0.09, elL: -0.12, elR: -0.12,
        hipLx: 0, hipRx: 0, hipLz: 0.03, hipRz: -0.03, knL: 0.03, knR: 0.03, dx: 0, dz: 0,
    };
}

function sitBase(t, ph, seat = 0.46) {
    const p = standBase(t, ph);
    return Object.assign(p, { y: seat + 0.09, spine: 0.06, hipLx: -1.52, hipRx: -1.52, knL: 1.5, knR: 1.5, hipLz: 0.06, hipRz: -0.06, shLx: -0.25, shRx: -0.25, elL: -0.9, elR: -0.9 });
}

const POSES = {
    stand: (t, ph) => standBase(t, ph),
    stand_talk: (t, ph) => {
        const p = standBase(t, ph);
        const g = Math.sin(t * 2.1 + ph);
        p.shRx = -0.35 - 0.2 * Math.max(0, g); p.elR = -1.1 + 0.45 * g; p.shRz = -0.15;
        p.shLx = -0.15 + 0.1 * Math.sin(t * 1.3 + ph); p.elL = -0.5;
        p.headY = Math.sin(t * 0.5 + ph) * 0.4; p.head = 0.0;
        return p;
    },
    stand_present: (t, ph) => {
        const p = standBase(t, ph);
        p.shRx = -1.35 + 0.1 * Math.sin(t * 0.9); p.shRz = -0.35; p.elR = -0.15; p.headY = -0.5; p.twist = -0.3;
        return p;
    },
    browse: (t, ph) => {
        const p = standBase(t, ph);
        p.head = 0.38; p.shLx = -0.55; p.elL = -1.0; p.shRx = -0.35 + 0.15 * Math.sin(t * 0.7 + ph); p.elR = -0.9;
        p.twist = Math.sin(t * 0.25 + ph) * 0.35;
        return p;
    },
    stand_basin: (t, ph) => {
        const p = standBase(t, ph);
        p.spine = 0.18; p.head = 0.35; p.shLx = -0.75; p.shRx = -0.75; p.elL = -0.8 + 0.15 * Math.sin(t * 6); p.elR = -0.8 - 0.15 * Math.sin(t * 6);
        return p;
    },
    cook: (t, ph) => {
        const p = standBase(t, ph);
        p.spine = 0.12; p.head = 0.3; p.shLx = -0.7; p.shRx = -0.75 + 0.2 * Math.sin(t * 3 + ph); p.elL = -1.0; p.elR = -1.1 + 0.3 * Math.sin(t * 3.4 + ph);
        p.dx = Math.sin(t * 0.18 + ph) * 0.45;
        return p;
    },
    barista: (t, ph) => POSES.cook(t * 1.3, ph),
    lift_db: (t, ph) => {
        const p = standBase(t, ph);
        const c = Math.sin(t * 2.2 + ph);
        p.elL = -1.2 - 1.0 * Math.max(0, c); p.elR = -1.2 - 1.0 * Math.max(0, -c); p.shLx = -0.05; p.shRx = -0.05;
        p.hipLz = 0.1; p.hipRz = -0.1;
        return p;
    },
    stretch: (t, ph) => {
        const p = standBase(t, ph);
        const c = Math.sin(t * 0.8 + ph);
        p.shLx = -2.9; p.shRx = -2.9; p.elL = -0.2; p.elR = -0.2; p.side = 0.35 * c; p.hipLz = 0.22; p.hipRz = -0.22;
        return p;
    },
    walk: (t, ph) => {
        const p = standBase(t, ph);
        const w = t * 6.8 + ph;
        const s = Math.sin(w);
        p.hipLx = -0.42 * s; p.hipRx = 0.42 * s;
        p.knL = 0.1 + 0.75 * Math.max(0, Math.sin(w + 1.1)); p.knR = 0.1 + 0.75 * Math.max(0, Math.sin(w + 1.1 + Math.PI));
        p.shLx = 0.32 * s; p.shRx = -0.32 * s; p.elL = -0.25; p.elR = -0.25;
        p.y = HIP + 0.025 * Math.abs(Math.cos(w)) - 0.015; p.head = 0.02; p.headY = 0;
        return p;
    },
    run: (t, ph) => {
        const p = standBase(t, ph);
        const w = t * 10.5 + ph;
        const s = Math.sin(w);
        p.spine = 0.15; p.hipLx = -0.75 * s; p.hipRx = 0.75 * s;
        p.knL = 0.3 + 1.3 * Math.max(0, Math.sin(w + 1.2)); p.knR = 0.3 + 1.3 * Math.max(0, Math.sin(w + 1.2 + Math.PI));
        p.shLx = 0.6 * s; p.shRx = -0.6 * s; p.elL = -1.45; p.elR = -1.45;
        p.y = 0.2 + HIP + 0.05 * Math.abs(Math.cos(w)) - 0.04; p.headY = 0; p.head = 0;
        return p;
    },
    cycle: (t, ph) => {
        const p = sitBase(t, ph, 0.88);
        const w = t * 5.5 + ph;
        p.spine = 0.6; p.head = -0.35; p.shLx = -1.15; p.shRx = -1.15; p.elL = -0.25; p.elR = -0.25; p.shLz = 0.12; p.shRz = -0.12;
        p.hipLx = -1.15 + 0.42 * Math.sin(w); p.hipRx = -1.15 + 0.42 * Math.sin(w + Math.PI);
        p.knL = 1.25 + 0.5 * Math.cos(w); p.knR = 1.25 + 0.5 * Math.cos(w + Math.PI);
        p.y = 0.97; p.headY = 0;
        return p;
    },
    sit_desk: (t, ph) => {
        const p = sitBase(t, ph);
        p.spine = 0.14; p.head = 0.18; p.shLx = -0.62; p.shRx = -0.62; p.elL = -1.0 + 0.05 * Math.sin(t * 11 + ph); p.elR = -1.0 + 0.05 * Math.sin(t * 13 + ph);
        p.shLz = 0.18; p.shRz = -0.18; p.headY = Math.sin(t * 0.17 + ph) * 0.15;
        return p;
    },
    sit_meeting: (t, ph) => {
        const p = sitBase(t, ph);
        const g = Math.sin(t * 1.7 + ph);
        p.shLx = -0.6; p.elL = -1.05; p.shRx = -0.6 - 0.25 * Math.max(0, g); p.elR = -1.0 - 0.4 * Math.max(0, g);
        p.headY = Math.sin(t * 0.35 + ph) * 0.55; p.head = 0.02;
        return p;
    },
    sit_cafe: (t, ph) => {
        const p = POSES.sit_meeting(t, ph);
        const sip = Math.max(0, Math.sin(t * 0.45 + ph * 3)) ** 8;
        p.shRx = lerp(p.shRx, -1.0, sip); p.elR = lerp(p.elR, -2.2, sip);
        return p;
    },
    sit_dining: (t, ph) => POSES.sit_cafe(t, ph),
    sit_high: (t, ph) => {
        const p = sitBase(t, ph, 0.76);
        p.hipLx = -1.3; p.hipRx = -1.3; p.knL = 1.85; p.knR = 1.6; p.shLx = -0.6; p.shRx = -0.55; p.elL = -1.1; p.elR = -1.2;
        return p;
    },
    sit_relax: (t, ph) => {
        const p = sitBase(t, ph, 0.43);
        p.spine = -0.28; p.head = 0.1; p.hipLx = -1.35; p.hipRx = -1.35; p.knL = 1.2; p.knR = 1.35; p.shLx = -0.35; p.shRx = -0.3; p.shLz = 0.25; p.shRz = -0.25; p.elL = -0.7; p.elR = -0.75;
        return p;
    },
    sit_bench: (t, ph) => { const p = sitBase(t, ph, 0.46); p.spine = 0.25; p.head = 0.25; p.shLx = -0.5; p.shRx = -0.5; p.elL = -0.6; p.elR = -0.6; return p; },
    lie_bed: (t, ph) => {
        const p = standBase(t, ph);
        return Object.assign(p, { y: 0.72, pitch: -Math.PI / 2, spine: 0, head: -0.25, headY: 0.3 * Math.sin(t * 0.05 + ph), shLx: -0.1, shRx: -0.1, shLz: 0.25, shRz: -0.25, elL: -0.5, elR: -0.4, knL: 0.15, knR: 0.05, hipLz: 0.06, hipRz: -0.05, twist: 0 });
    },
    lie_lounger: (t, ph) => {
        const p = standBase(t, ph);
        return Object.assign(p, { y: 0.5, pitch: -1.15, spine: 0.05, head: 0.3, headY: 0.2 * Math.sin(t * 0.1 + ph), hipLx: -0.4, hipRx: -0.45, knL: 0.25, knR: 0.3, shLx: -0.3, shRx: -0.4, shLz: 0.25, shRz: -0.25, elL: -1.3, elR: -1.4, twist: 0 });
    },
    lie_bench: (t, ph) => {
        const p = standBase(t, ph);
        const c = Math.sin(t * 1.8 + ph);
        return Object.assign(p, { y: 0.6, pitch: -Math.PI / 2, spine: 0, head: -0.2, headY: 0, hipLx: -0.35, hipRx: -0.35, hipLz: 0.35, hipRz: -0.35, knL: 1.3, knR: 1.3, shLx: -1.57 - 0.25 * (1 + c), shRx: -1.57 - 0.25 * (1 + c), shLz: 0.55, shRz: -0.55, elL: -0.7 + 0.6 * c, elR: -0.7 + 0.6 * c, twist: 0 });
    },
    yoga: (t, ph) => {
        const seg = Math.floor((t + ph * 3) / 7) % 3;
        const p = standBase(t, ph);
        if (seg === 0) {           // arms raised (mountain)
            Object.assign(p, { shLx: -3.0, shRx: -3.0, elL: -0.05, elR: -0.05, shLz: 0.1, shRz: -0.1, head: -0.15 });
        } else if (seg === 1) {    // warrior II
            Object.assign(p, { y: HIP - 0.16, hipLx: -0.5, hipRx: 0.15, hipLz: 0.45, hipRz: -0.45, knL: 0.9, knR: 0.05, shLz: 1.55, shRz: -1.55, elL: 0, elR: 0, twist: 0.5, headY: 0.8 });
        } else {                   // tree pose
            Object.assign(p, { hipRz: -0.02, hipLz: 0.9, hipLx: -0.25, knL: 2.3, shLx: -3.05, shRx: -3.05, shLz: -0.08, shRz: 0.08, elL: -0.1, elR: -0.1 });
        }
        return p;
    },
};
POSES.sit_dining = POSES.sit_cafe;

// ---------------------------------------------------------------- rig
class Rig {
    constructor() {
        const o = () => new THREE.Object3D();
        this.root = o();
        this.hips = o(); this.root.add(this.hips);
        this.spine = o(); this.spine.position.y = 0.06; this.hips.add(this.spine);
        this.neck = o(); this.neck.position.y = 0.52; this.spine.add(this.neck);
        this.head = o(); this.head.position.y = 0.07; this.neck.add(this.head);
        this.shL = o(); this.shL.position.set(0.2, 0.45, 0); this.spine.add(this.shL);
        this.shR = o(); this.shR.position.set(-0.2, 0.45, 0); this.spine.add(this.shR);
        this.elL = o(); this.elL.position.y = -0.28; this.shL.add(this.elL);
        this.elR = o(); this.elR.position.y = -0.28; this.shR.add(this.elR);
        this.hdL = o(); this.hdL.position.y = -0.25; this.elL.add(this.hdL);
        this.hdR = o(); this.hdR.position.y = -0.25; this.elR.add(this.hdR);
        this.hipL = o(); this.hipL.position.set(0.095, -0.03, 0); this.hips.add(this.hipL);
        this.hipR = o(); this.hipR.position.set(-0.095, -0.03, 0); this.hips.add(this.hipR);
        this.knL = o(); this.knL.position.y = -0.43; this.hipL.add(this.knL);
        this.knR = o(); this.knR.position.y = -0.43; this.hipR.add(this.knR);
        this.anL = o(); this.anL.position.y = -0.42; this.knL.add(this.anL);
        this.anR = o(); this.anR.position.y = -0.42; this.knR.add(this.anR);
    }

    apply(p) {
        this.hips.position.set(p.dx, p.y, p.dz);
        this.hips.rotation.set(p.pitch, 0, 0);
        this.spine.rotation.set(p.spine, p.twist, p.side);
        this.neck.rotation.set(p.head, p.headY, 0);
        this.shL.rotation.set(p.shLx, 0, p.shLz);
        this.shR.rotation.set(p.shRx, 0, p.shRz);
        this.elL.rotation.set(p.elL, 0, 0);
        this.elR.rotation.set(p.elR, 0, 0);
        this.hipL.rotation.set(p.hipLx, 0, p.hipLz);
        this.hipR.rotation.set(p.hipRx, 0, p.hipRz);
        this.knL.rotation.set(p.knL, 0, 0);
        this.knR.rotation.set(p.knR, 0, 0);
        this.anL.rotation.set(-p.knL * 0.25 - p.hipLx * 0.1, 0, 0);
        this.anR.rotation.set(-p.knR * 0.25 - p.hipRx * 0.1, 0, 0);
    }
}

// ---------------------------------------------------------------- part catalogue
function partDefs() {
    const cap = (rad, len) => new THREE.CapsuleGeometry(rad, len, 3, 8);
    const torso = cap(0.155, 0.27); torso.scale(1.18, 1, 0.74);
    const head = new THREE.SphereGeometry(0.104, 12, 10); head.scale(0.9, 1.12, 1.0);
    const hair = new THREE.SphereGeometry(0.112, 12, 7, 0, Math.PI * 2, 0, Math.PI * 0.62); hair.scale(0.93, 1.0, 1.05);
    const hand = new THREE.SphereGeometry(0.046, 6, 5); hand.scale(0.75, 1.2, 0.5);
    const shoe = new RoundedBoxGeometry(0.1, 0.075, 0.25, 2, 0.03);
    const pelvis = new RoundedBoxGeometry(0.33, 0.2, 0.21, 2, 0.07);
    const neck = new THREE.CylinderGeometry(0.048, 0.052, 0.12, 10);
    // name, geometry, joint key(s), local offset, colour key
    return [
        ['torso', torso, ['spine'], [0, 0.26, 0], 'shirt'],
        ['pelvis', pelvis, ['hips'], [0, 0.0, 0], 'pants'],
        ['neck', neck, ['neck'], [0, 0.02, 0], 'skin'],
        ['head', head, ['head'], [0, 0.11, 0.012], 'skin'],
        ['hair', hair, ['head'], [0, 0.13, -0.012], 'hair'],
        ['uarm', cap(0.05, 0.19), ['shL', 'shR'], [0, -0.13, 0], 'shirt'],
        ['farm', cap(0.041, 0.17), ['elL', 'elR'], [0, -0.12, 0], 'sleeve'],
        ['hand', hand, ['hdL', 'hdR'], [0, -0.035, 0], 'skin'],
        ['thigh', cap(0.078, 0.29), ['hipL', 'hipR'], [0, -0.21, 0], 'pants'],
        ['shin', cap(0.059, 0.3), ['knL', 'knR'], [0, -0.2, 0], 'pants'],
        ['shoe', shoe, ['anL', 'anR'], [0, -0.035, 0.055], 'shoe'],
    ];
}

const ZERO = new THREE.Matrix4().makeScale(0, 0, 0);

export class People {
    constructor(app, capacity) {
        this.app = app;
        this.capacity = capacity;
        this.group = new THREE.Group();
        this.group.name = 'people';
        app.scene.add(this.group);
        this.parts = [];
        const mat = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.75 });
        const skinMat = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.55 });
        for (const [name, geo, joints, off, colorKey] of partDefs()) {
            const count = capacity * joints.length;
            const m = new THREE.InstancedMesh(geo, colorKey === 'skin' ? skinMat : mat, count);
            m.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
            m.castShadow = true;
            m.receiveShadow = true;
            m.frustumCulled = false;
            for (let i = 0; i < count; i++) { m.setMatrixAt(i, ZERO); m.setColorAt(i, new THREE.Color(0xffffff)); }
            this.group.add(m);
            this.parts.push({ name, mesh: m, joints, local: new THREE.Matrix4().makeTranslation(...off), colorKey });
        }
        this.slots = new Array(capacity).fill(null);
        this.persons = new Set();
        this.time = 0;
        this._m = new THREE.Matrix4();
        this.visible = true;
        this.visibleTest = () => true;
    }

    _alloc() {
        const i = this.slots.indexOf(null);
        return i;
    }

    /** Create a person (returns null when full). */
    spawn({ x, y = 0, z, ry = 0, pose = 'stand', type = 'office', key = null, from = null, path = null, scope = null }) {
        const slot = this._alloc();
        if (slot < 0) return null;
        const pal = PALETTE[paletteFor(type, pose)];
        const skin = pick(SKIN);
        const shirt = pick(pal.shirt);
        const longSleeve = r() < 0.5 && pal !== PALETTE.sport;
        const colors = {
            skin, shirt, sleeve: longSleeve ? shirt : skin, pants: pick(pal.pants), shoe: pick(SHOES), hair: pick(HAIR),
        };
        const p = {
            slot, key, scope, rig: new Rig(), pose, ry, home: { x, y, z }, pos: new THREE.Vector3(x, y, z), heading: ry,
            cur: null, ph: r() * 10, scale: 0.92 + r() * 0.13, width: 0.94 + r() * 0.14, longHair: r() < 0.35,
            state: from ? 'enter' : 'idle', from, path, pathT: r(), pathDir: 1, fade: from ? 0 : 1, speed: 1.15 + r() * 0.35,
        };
        if (from) { p.pos.set(from.x, from.y ?? y, from.z); }
        p.cur = POSES.stand(0, p.ph);
        this.slots[slot] = p;
        this.persons.add(p);
        // write colours for this slot
        const c = new THREE.Color();
        for (const part of this.parts) {
            const hex = colors[part.colorKey];
            for (let j = 0; j < part.joints.length; j++) part.mesh.setColorAt(slot * part.joints.length + j, c.setHex(hex));
            part.mesh.instanceColor.needsUpdate = true;
        }
        return p;
    }

    /** Ask a person to walk to a point and disappear there. */
    dismiss(p, door, route = null) {
        if (!p || p.state === 'leave') return;
        p.state = 'leave';
        p.to = door;
        p.route = route;
    }

    _free(p) {
        this.slots[p.slot] = null;
        this.persons.delete(p);
        for (const part of this.parts) for (let j = 0; j < part.joints.length; j++) part.mesh.setMatrixAt(p.slot * part.joints.length + j, ZERO);
    }

    update(dt) {
        this.time += dt;
        const t = this.time;
        const k = Math.min(1, dt * 5);
        for (const p of this.persons) {
            let pose = p.pose;
            // movement states
            if (p.state === 'enter' || p.state === 'leave') {
                const target = p.route && p.route.length ? p.route[0] : (p.state === 'enter' ? p.home : p.to);
                const dx = target.x - p.pos.x, dz = target.z - p.pos.z;
                const dist = Math.hypot(dx, dz);
                if (dist > 0.08) {
                    pose = 'walk';
                    p.heading = Math.atan2(dx, dz);
                    const step = Math.min(dist, p.speed * dt);
                    p.pos.x += dx / dist * step; p.pos.z += dz / dist * step;
                    p.pos.y = lerp(p.pos.y, target.y ?? p.pos.y, k);
                    p.fade = Math.min(1, p.fade + dt * 2.5);
                    if (p.state === 'leave' && dist < 0.6) p.fade = Math.max(0, dist / 0.6);
                } else if (p.route && p.route.length) {
                    p.route.shift();                       // reached a waypoint: walk on to the next
                } else if (p.state === 'enter') {
                    p.state = 'idle';
                    p.pos.set(p.home.x, p.home.y, p.home.z);
                } else {
                    this._free(p);
                    continue;
                }
            } else if (p.path) {
                // walk back and forth along a short path (corridors, sidewalks)
                pose = 'walk';
                const pts = p.path;
                let total = 0;
                const segs = [];
                for (let i = 0; i < pts.length - 1; i++) { const l = Math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]); segs.push(l); total += l; }
                p.pathT += (p.pathDir * p.speed * dt) / Math.max(0.1, total);
                if (p.pathT > 1) { p.pathT = 1; p.pathDir = -1; }
                if (p.pathT < 0) { p.pathT = 0; p.pathDir = 1; }
                let d = p.pathT * total, i = 0;
                while (i < segs.length - 1 && d > segs[i]) { d -= segs[i]; i++; }
                const a = pts[i], b = pts[i + 1];
                const f = segs[i] > 0 ? d / segs[i] : 0;
                const ox = p.pathOrigin ? p.pathOrigin.x : 0, oz = p.pathOrigin ? p.pathOrigin.z : 0;
                p.pos.x = ox + a[0] + (b[0] - a[0]) * f;
                p.pos.z = oz + a[1] + (b[1] - a[1]) * f;
                const h = Math.atan2((b[0] - a[0]) * p.pathDir, (b[1] - a[1]) * p.pathDir);
                let dh = ((h - p.heading + Math.PI * 3) % (Math.PI * 2)) - Math.PI;
                p.heading += dh * Math.min(1, dt * 6);
            } else {
                let dh = ((p.ry - p.heading + Math.PI * 3) % (Math.PI * 2)) - Math.PI;
                p.heading += dh * Math.min(1, dt * 4);
            }
            const target = (POSES[pose] || POSES.stand)(t, p.ph);
            const cur = p.cur;
            const kk = pose === 'walk' || pose === 'run' || pose === 'cycle' || pose === 'sit_desk' || pose === 'lift_db' ? Math.min(1, dt * 14) : k;
            for (const j of JOINTS) cur[j] = lerp(cur[j], target[j], kk);
            if (p.state === 'idle' && p.fade < 1) p.fade = Math.min(1, p.fade + dt * 2);
        }
    }

    /** Write instance matrices (call once per frame after update). */
    render() {
        const m = this._m;
        for (const p of this.persons) {
            const vis = this.visible && this.visibleTest(p) && p.fade > 0.01;
            if (!vis) {
                if (p._hidden) continue;
                p._hidden = true;
                for (const part of this.parts) for (let j = 0; j < part.joints.length; j++) part.mesh.setMatrixAt(p.slot * part.joints.length + j, ZERO);
                continue;
            }
            p._hidden = false;
            const rig = p.rig;
            rig.root.position.copy(p.pos);
            rig.root.rotation.set(0, p.heading, 0);
            const s = p.scale * (0.6 + 0.4 * p.fade);
            rig.root.scale.set(s * p.width, s, s * p.width);
            rig.apply(p.cur);
            rig.root.updateMatrixWorld(true);
            for (const part of this.parts) {
                for (let j = 0; j < part.joints.length; j++) {
                    const joint = rig[part.joints[j]];
                    m.multiplyMatrices(joint.matrixWorld, part.local);
                    if (part.name === 'hair' && p.longHair) m.multiply(LONG_HAIR);
                    part.mesh.setMatrixAt(p.slot * part.joints.length + j, m);
                }
            }
        }
        // draw only up to the highest slot in use (unused slots would still cost vertices)
        let top = -1;
        for (const p of this.persons) if (p.slot > top) top = p.slot;
        for (const part of this.parts) {
            part.mesh.count = (top + 1) * part.joints.length;
            part.mesh.instanceMatrix.needsUpdate = true;
        }
    }

    setVisible(v) { this.visible = v; }
}

const LONG_HAIR = new THREE.Matrix4().compose(new THREE.Vector3(0, -0.035, -0.01), new THREE.Quaternion(), new THREE.Vector3(1.04, 1.45, 1.08));

/**
 * Keeps each room's people in step with the simulation: spawns people at the door
 * when the count rises, sends the most recent arrivals out when it falls.
 */
export class RoomOccupants {
    constructor(people, room) {
        this.people = people;
        this.room = room;           // { id, type, spots: [{x,z,ry,pose,y,path}], doors: [{x,z}], origin: {x,y,z} }
        this.persons = [];
        // fixed order in which spots are filled (shuffled once, but deterministic)
        const n = room.spots.length;
        const order = [...Array(n).keys()];
        let s = 0;
        for (const ch of room.id) s = (s * 31 + ch.charCodeAt(0)) >>> 0;
        for (let i = n - 1; i > 0; i--) { s = (s * 1103515245 + 12345) >>> 0; const j = s % (i + 1); [order[i], order[j]] = [order[j], order[i]]; }
        // activity spots first (desks, machines), free standing spots last
        order.sort((a, b) => (room.spots[a].pose === 'stand' ? 1 : 0) - (room.spots[b].pose === 'stand' ? 1 : 0));
        this.order = order;
        this.target = 0;
    }

    _door() {
        const o = this.room.origin;
        const d = this.room.doors.length ? this.room.doors[(Math.random() * this.room.doors.length) | 0] : { x: 0, z: 0 };
        return { x: o.x + d.x, y: o.y, z: o.z + d.z, local: d };
    }

    /** Waypoints so people walk along open floor instead of cutting through furniture. */
    _route(door, sp) {
        const o = this.room.origin;
        const hw = this.room.box.w / 2, hd = this.room.box.d / 2;
        const d = door.local;
        // a point 1 m further into the room from the door
        const inX = Math.abs(Math.abs(d.x) - hw) < Math.abs(Math.abs(d.z) - hd) ? d.x - Math.sign(d.x) * 1.0 : d.x;
        const inZ = Math.abs(Math.abs(d.x) - hw) < Math.abs(Math.abs(d.z) - hd) ? d.z : d.z - Math.sign(d.z) * 1.0;
        // the approach point: just behind where the person will sit or stand (open side)
        const back = /walk/.test(sp.pose) ? 0 : 0.85;
        const ax = sp.x - Math.sin(sp.ry) * back, az = sp.z - Math.cos(sp.ry) * back;
        const clampX = (x) => Math.max(-hw + 0.5, Math.min(hw - 0.5, x));
        const clampZ = (z) => Math.max(-hd + 0.5, Math.min(hd - 0.5, z));
        return [
            { x: o.x + clampX(inX), y: o.y, z: o.z + clampZ(inZ) },
            { x: o.x + clampX(ax), y: o.y, z: o.z + clampZ(az) },
        ];
    }

    set(count, { instant = false } = {}) {
        count = Math.max(0, Math.min(count | 0, this.order.length));
        this.target = count;
        const active = this.persons.filter((p) => p.state !== 'leave');
        if (active.length < count) {
            const used = new Set(active.map((p) => p.spotIndex));
            for (const idx of this.order) {
                if (active.length >= count) break;
                if (used.has(idx)) continue;
                const sp = this.room.spots[idx];
                const o = this.room.origin;
                const home = { x: o.x + sp.x, y: o.y + (sp.lift || 0), z: o.z + sp.z };
                const door = instant ? null : this._door();
                const p = this.people.spawn({
                    x: home.x, y: home.y, z: home.z, ry: sp.ry, pose: sp.pose, type: this.room.type, key: this.room.id, scope: this.room.id,
                    from: door, path: sp.path || null,
                });
                if (!p) break;
                if (!instant && door) p.route = this._route(door, sp);
                if (sp.path) p.pathOrigin = { x: o.x, z: o.z };
                if (sp.path && !instant) { p.path = null; p._pendingPath = sp.path; }
                p.spotIndex = idx;
                this.persons.push(p);
                active.push(p);
            }
        } else if (active.length > count) {
            const leaving = active.slice(count);
            for (const p of leaving) {
                if (instant) { this.people._free(p); continue; }
                p.path = null;
                const door = this._door();
                const sp = this.room.spots[p.spotIndex];
                const r = sp ? this._route(door, sp).reverse() : null;
                this.people.dismiss(p, door, r);
            }
        }
        this.persons = this.persons.filter((p) => this.people.persons.has(p));
        // walkers start walking their path once they have entered
        for (const p of this.persons) if (p._pendingPath && p.state === 'idle') { p.path = p._pendingPath; p._pendingPath = null; }
    }

    tick() {
        for (const p of this.persons) if (p._pendingPath && p.state === 'idle') { p.path = p._pendingPath; p._pendingPath = null; }
        this.persons = this.persons.filter((p) => this.people.persons.has(p));
    }
}
