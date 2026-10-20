// ═══════════════════════════════════════════════════════════════
// furniture.js — furnished layouts for every room type
// ═══════════════════════════════════════════════════════════════
// Each layout draws into a Batch in the room's local frame (origin at the room
// centre on the floor, x = east, z = south) and returns "spots": places where a
// person can be, with the activity they would be doing there (working at a desk,
// running on a treadmill, cooking, sleeping...). The people system fills these
// spots with as many people as the simulation says are in the room.

import * as THREE from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
import { M, T, rand } from '../lib/materials.js';

// ---------------------------------------------------------------- palette
const P = {
    laminate: () => M.std(0xf3f2ef, 0.45),
    oak: () => M.oak(),
    walnut: () => M.walnut(),
    blackMetal: () => M.std(0x222428, 0.4, 0.6),
    chrome: () => M.chrome(),
    greyFab: () => M.fabric('#6b7078'),
    darkFab: () => M.fabric('#3a414b'),
    blueFab: () => M.fabric('#36506b'),
    mustard: () => M.fabric('#c99a3b'),
    teal: () => M.fabric('#2f6f73'),
    terra: () => M.fabric('#b5643c'),
    sage: () => M.fabric('#8a9a7b'),
    linen: () => M.fabric('#e8e2d6'),
    cream: () => M.fabric('#d9d1c2'),
    cognac: () => M.leather(0x8b5a2b),
    marble: () => M.marble(),
    whiteGloss: () => M.std(0xf7f7f5, 0.2),
    ceramic: () => M.std(0xfbfbfa, 0.15),
    screen: () => M.screenOff(),
    rubberBlack: () => M.std(0x1b1c1e, 0.85),
    mirror: () => M.std(0xdfe7ea, 0.03, 1.0),
    glass: () => M.glass(),
    plantPot: () => M.std(0x3b3d40, 0.6),
    potWhite: () => M.std(0xe9e6df, 0.55),
};

function rot(x, z, a, lx, lz) {
    return [x + lx * Math.cos(a) + lz * Math.sin(a), z - lx * Math.sin(a) + lz * Math.cos(a)];
}

/** person spot; facing direction = (sin ry, cos ry) */
function spot(spots, x, z, ry, pose, extra = {}) { spots.push({ x, z, ry, pose, ...extra }); }

const rb = (w, h, d, r = 0.04, s = 2) => new RoundedBoxGeometry(w, h, d, Math.max(1, s - 1), Math.min(r, w / 2 - 1e-3, h / 2 - 1e-3, d / 2 - 1e-3));

// ---------------------------------------------------------------- pieces
export function taskChair(b, x, z, ry, fab = P.darkFab()) {
    b.push(x, 0, z, ry);
    b.add(rb(0.5, 0.08, 0.48, 0.03), fab, 0, 0.48, 0);
    b.add(rb(0.46, 0.55, 0.06, 0.03), fab, 0, 0.82, 0.24, 0, -0.12);
    b.cyl(0.025, 0.025, 0.36, P.chrome(), 0, 0.28, 0, 8);
    for (let i = 0; i < 5; i++) {
        const a = (i / 5) * Math.PI * 2;
        b.add(new THREE.BoxGeometry(0.3, 0.03, 0.04), P.blackMetal(), Math.cos(a) * 0.15, 0.08, Math.sin(a) * 0.15, -a);
        b.sphere(0.03, P.rubberBlack(), Math.cos(a) * 0.3, 0.03, Math.sin(a) * 0.3, 1, 1, 1, 6);
    }
    b.pop();
}

function diningChair(b, x, z, ry, seat = P.oak(), fab = null) {
    b.push(x, 0, z, ry);
    b.add(rb(0.44, 0.05, 0.44, 0.02), fab || seat, 0, 0.45, 0);
    b.add(rb(0.42, 0.4, 0.04, 0.02), seat, 0, 0.7, 0.2, 0, -0.08);
    for (const [lx, lz] of [[-0.19, -0.19], [0.19, -0.19], [-0.19, 0.19], [0.19, 0.19]]) b.block(0.035, 0.44, 0.035, seat, lx, 0, lz);
    b.pop();
}

function stool(b, x, z, h = 0.75, mat = P.cognac()) {
    b.add(new THREE.CylinderGeometry(0.19, 0.19, 0.06, 16), mat, x, h, z);
    b.cyl(0.025, 0.025, h, P.blackMetal(), x, h / 2, z, 8);
    b.add(new THREE.TorusGeometry(0.16, 0.012, 6, 16), P.blackMetal(), x, 0.3, z, 0, Math.PI / 2);
    b.cyl(0.2, 0.22, 0.03, P.blackMetal(), x, 0.015, z, 16);
}

function desk(b, x, z, ry, spots, { w = 1.5, d = 0.75, monitors = 1, mat = P.laminate(), screenMat } = {}) {
    b.push(x, 0, z, ry);
    b.block(w, 0.03, d, mat, 0, 0.72, 0);
    for (const sx of [-1, 1]) {
        b.block(0.05, 0.72, 0.05, P.blackMetal(), sx * (w / 2 - 0.06), 0, -d / 2 + 0.06);
        b.block(0.05, 0.72, 0.05, P.blackMetal(), sx * (w / 2 - 0.06), 0, d / 2 - 0.06);
        b.block(0.05, 0.04, d - 0.1, P.blackMetal(), sx * (w / 2 - 0.06), 0.02, 0);
    }
    b.block(w - 0.1, 0.3, 0.02, P.greyFab(), 0, 0.42, -d / 2 + 0.05);
    for (let i = 0; i < monitors; i++) {
        const mx = monitors === 1 ? 0 : (i - 0.5) * 0.6;
        b.block(0.58, 0.36, 0.03, P.screen(), mx, 0.92, -d / 2 + 0.16);
        if (screenMat) b.add(new THREE.PlaneGeometry(0.54, 0.31), screenMat, mx, 1.1, -d / 2 + 0.176);
        b.block(0.04, 0.18, 0.04, P.blackMetal(), mx, 0.75, -d / 2 + 0.12);
        b.block(0.22, 0.015, 0.16, P.blackMetal(), mx, 0.75, -d / 2 + 0.12);
    }
    b.block(0.44, 0.015, 0.14, P.whiteGloss(), 0, 0.75, -0.02);
    b.block(0.07, 0.02, 0.1, P.whiteGloss(), 0.32, 0.75, 0.0);
    if (rand() < 0.5) b.cyl(0.04, 0.035, 0.1, P.ceramic(), -w / 2 + 0.2, 0.8, 0.05, 10);
    b.pop();
    const [cx, cz] = rot(x, z, ry, 0, d / 2 + 0.25);
    taskChair(b, cx, cz, ry);
    spot(spots, cx, cz, ry + Math.PI, 'sit_desk');
}

function sofa(b, x, z, ry, len = 2.2, fab = P.greyFab(), spots = null, pose = 'sit_relax') {
    b.push(x, 0, z, ry);
    b.add(rb(len, 0.22, 0.92, 0.04), fab, 0, 0.21, 0);
    const n = Math.max(1, Math.round(len / 0.75));
    const cw = (len - 0.36) / n;
    for (let i = 0; i < n; i++) {
        b.add(rb(cw - 0.02, 0.16, 0.66, 0.06, 3), fab, -len / 2 + 0.18 + cw * (i + 0.5), 0.4, 0.08);
        b.add(rb(cw - 0.03, 0.42, 0.2, 0.08, 3), fab, -len / 2 + 0.18 + cw * (i + 0.5), 0.62, -0.32, 0, 0.12);
    }
    for (const sx of [-1, 1]) b.add(rb(0.18, 0.58, 0.92, 0.06), fab, sx * (len / 2 - 0.09), 0.37, 0);
    for (const sx of [-1, 1]) for (const sz of [-1, 1]) b.block(0.04, 0.1, 0.04, P.walnut(), sx * (len / 2 - 0.1), 0, sz * 0.38);
    b.pop();
    if (spots) {
        for (let i = 0; i < n; i++) {
            const [px, pz] = rot(x, z, ry, -len / 2 + 0.18 + cw * (i + 0.5), 0.12);
            spot(spots, px, pz, ry, pose);
        }
    }
}

function armchair(b, x, z, ry, fab = P.mustard(), spots = null) {
    b.push(x, 0, z, ry);
    b.add(rb(0.8, 0.2, 0.8, 0.04), fab, 0, 0.25, 0);
    b.add(rb(0.62, 0.14, 0.6, 0.06, 3), fab, 0, 0.42, 0.06);
    b.add(rb(0.76, 0.5, 0.16, 0.06, 3), fab, 0, 0.62, -0.32, 0, 0.12);
    for (const sx of [-1, 1]) b.add(rb(0.12, 0.42, 0.8, 0.05), fab, sx * 0.34, 0.42, 0);
    for (const sx of [-1, 1]) for (const sz of [-1, 1]) b.block(0.035, 0.15, 0.035, P.walnut(), sx * 0.33, 0, sz * 0.33);
    b.pop();
    if (spots) spot(spots, x, z, ry, 'sit_relax');
}

function coffeeTable(b, x, z, w = 1.2, d = 0.6, ry = 0) {
    b.push(x, 0, z, ry);
    b.add(rb(w, 0.04, d, 0.015), P.marble(), 0, 0.4, 0);
    for (const sx of [-1, 1]) b.block(0.04, 0.38, d - 0.1, P.blackMetal(), sx * (w / 2 - 0.08), 0, 0);
    b.block(0.25, 0.04, 0.18, P.terra(), -0.2, 0.42, 0);
    b.cyl(0.06, 0.05, 0.14, P.potWhite(), 0.3, 0.49, 0.05, 12);
    b.pop();
}

function rug(b, x, z, w, d, hex, ry = 0) {
    b.add(new THREE.BoxGeometry(w, 0.012, d), M.fabric(hex), x, 0.006, z, ry);
}

function plant(ctx, x, z, scale = 1, kind = 'shrub', pot = true) {
    if (pot) ctx.b.add(new THREE.CylinderGeometry(0.24 * scale, 0.18 * scale, 0.45 * scale, 16), rand() < 0.5 ? P.plantPot() : P.potWhite(), x, 0.225 * scale, z);
    ctx.plants.push({ kind, x: ctx.ox + x, z: ctx.oz + z, y: ctx.oy + (pot ? 0.42 * scale : 0), s: 0.55 * scale, r: rand() * 6.28 });
}

function tallPlant(ctx, x, z, scale = 1) {
    ctx.b.add(new THREE.CylinderGeometry(0.3, 0.24, 0.55, 16), P.potWhite(), x, 0.275, z);
    ctx.plants.push({ kind: 'flower', x: ctx.ox + x, z: ctx.oz + z, y: ctx.oy + 0.5, s: 0.32 * scale, r: rand() * 6.28 });
}

function bookshelf(b, x, z, ry, w = 1.6, h = 2.0) {
    b.push(x, 0, z, ry);
    b.block(w, h, 0.36, P.oak(), 0, 0, 0);
    const shelves = 5;
    const cols = ['#7a3b2e', '#2f4f6f', '#c9b38a', '#3f5f4a', '#8b8b8b', '#b5643c', '#1f2a36'];
    for (let s = 0; s < shelves; s++) {
        const y = 0.08 + s * (h - 0.1) / shelves;
        b.block(w - 0.06, (h - 0.1) / shelves - 0.04, 0.3, M.std(0x2b2520, 0.9), 0, y, 0.04);
        let bx = -w / 2 + 0.06;
        while (bx < w / 2 - 0.1) {
            const bw = 0.03 + rand() * 0.04, bh = 0.18 + rand() * 0.12;
            if (rand() < 0.85) b.block(bw, bh, 0.22, M.std(new THREE.Color(cols[(rand() * cols.length) | 0]).getHex(), 0.8), bx + bw / 2, y, 0.08);
            bx += bw + 0.005 + (rand() < 0.1 ? 0.15 : 0);
        }
    }
    b.pop();
}

function tvWall(b, x, z, ry, w = 2.4, screenMat = null) {
    b.push(x, 0, z, ry);
    b.block(w, 0.45, 0.42, P.walnut(), 0, 0.1, 0);
    b.block(w, 0.03, 0.42, P.blackMetal(), 0, 0.55, 0);
    b.block(1.45, 0.83, 0.04, P.screen(), 0, 1.0, -0.12);
    if (screenMat) b.add(new THREE.PlaneGeometry(1.4, 0.78), screenMat, 0, 1.415, -0.098);
    b.block(0.6, 0.06, 0.08, P.blackMetal(), 0, 0.58, 0.05);
    b.pop();
}

function bed(b, x, z, ry, width = 1.6, spots = null, duvet = P.linen()) {
    const len = 2.1;
    b.push(x, 0, z, ry);
    b.add(rb(width + 0.1, 0.32, len, 0.04), P.darkFab(), 0, 0.2, 0);
    b.add(rb(width, 0.22, len - 0.08, 0.06, 3), M.std(0xf6f4ef, 0.9), 0, 0.46, 0.02);
    b.add(rb(width + 0.04, 0.08, len * 0.68, 0.04, 3), duvet, 0, 0.6, 0.28);
    b.add(rb(width + 0.2, 1.1, 0.1, 0.04), P.greyFab(), 0, 0.6, -len / 2 - 0.02);
    const np = width > 1.2 ? 2 : 1;
    for (let i = 0; i < np; i++) b.add(rb(0.6, 0.14, 0.38, 0.06, 3), M.std(0xfdfcf9, 0.9), (np === 1 ? 0 : (i - 0.5) * (width * 0.52)), 0.64, -len / 2 + 0.3);
    b.add(rb(width * 0.9, 0.04, 0.5, 0.02), P.mustard(), 0, 0.66, len / 2 - 0.35);
    for (const sx of [-1, 1]) {
        b.block(0.5, 0.48, 0.42, P.walnut(), sx * (width / 2 + 0.38), 0, -len / 2 + 0.25);
        b.cyl(0.07, 0.09, 0.06, P.ceramic(), sx * (width / 2 + 0.38), 0.51, -len / 2 + 0.25, 12);
        b.cyl(0.012, 0.012, 0.3, P.chrome(), sx * (width / 2 + 0.38), 0.69, -len / 2 + 0.25, 6);
        b.cyl(0.11, 0.16, 0.18, P.linen(), sx * (width / 2 + 0.38), 0.9, -len / 2 + 0.25, 16);
    }
    b.pop();
    if (spots) {
        for (let i = 0; i < np; i++) {
            const [px, pz] = rot(x, z, ry, np === 1 ? 0 : (i - 0.5) * width * 0.5, -0.15);
            spot(spots, px, pz, ry, 'lie_bed');
        }
    }
}

function wardrobe(b, x, z, ry, w = 2.0) {
    b.push(x, 0, z, ry);
    b.block(w, 2.3, 0.6, M.std(0xece8e0, 0.5), 0, 0, 0);
    const n = Math.round(w / 0.5);
    for (let i = 1; i < n; i++) b.block(0.008, 2.25, 0.01, M.std(0xbdb8ae, 0.6), -w / 2 + i * (w / n), 0.03, 0.305);
    for (let i = 0; i < n; i++) b.block(0.015, 0.3, 0.02, P.blackMetal(), -w / 2 + (i + 0.5) * (w / n) + (i % 2 ? -0.18 : 0.18), 1.0, 0.31);
    b.pop();
}

function kitchenRun(b, x, z, ry, len, { upper = true, hob = true, sink = true, fridge = true } = {}) {
    // counter along local x, back against local -z
    b.push(x, 0, z, ry);
    const front = M.std(0x2f3a40, 0.45);
    b.block(len, 0.86, 0.6, front, 0, 0.04, 0);
    b.block(len, 0.04, 0.62, P.marble(), 0, 0.9, 0.01);
    b.block(len, 0.08, 0.58, P.rubberBlack(), 0, 0, 0.02);
    for (let i = 0; i < Math.floor(len / 0.6); i++) b.block(0.01, 0.8, 0.01, M.std(0x1d2428, 0.5), -len / 2 + (i + 1) * 0.6, 0.06, 0.3);
    if (upper) {
        b.block(len, 0.7, 0.35, M.std(0xeeeae2, 0.5), 0, 1.5, -0.12);
        b.block(len, 0.02, 0.02, M.std(0xfff4d6, 0.3, 0, { emissive: 0xfff1d0, emissiveIntensity: 0.8 }), 0, 1.49, 0.04);
        b.block(len, 0.6, 0.01, M.std(0xf5f5f3, 0.2), 0, 0.94, -0.3);
    }
    if (sink) {
        b.block(0.6, 0.02, 0.42, P.chrome(), -len / 4, 0.93, 0.02);
        b.cyl(0.015, 0.015, 0.3, P.chrome(), -len / 4, 1.07, -0.18, 8);
        b.add(new THREE.BoxGeometry(0.02, 0.02, 0.18), P.chrome(), -len / 4, 1.22, -0.1);
    }
    if (hob) {
        b.block(0.6, 0.01, 0.5, M.std(0x0c0c0d, 0.1, 0.2), len / 4, 0.93, 0.02);
        for (const [hx, hz] of [[-0.14, -0.1], [0.14, -0.1], [-0.14, 0.12], [0.14, 0.12]]) b.add(new THREE.TorusGeometry(0.08, 0.006, 4, 20), M.std(0x5a5a5a, 0.4), len / 4 + hx, 0.945, 0.02 + hz, 0, Math.PI / 2);
        if (upper) b.block(0.6, 0.3, 0.45, P.chrome(), len / 4, 1.6, -0.1);
    }
    if (fridge) b.block(0.7, 2.0, 0.66, P.chrome(), len / 2 + 0.36, 0, 0.02);
    b.pop();
}

function meetingTable(b, x, z, ry, len, spots, seats) {
    b.push(x, 0, z, ry);
    b.add(rb(len, 0.05, 1.2, 0.02), P.walnut(), 0, 0.74, 0);
    b.block(len * 0.6, 0.7, 0.3, P.blackMetal(), 0, 0.02, 0);
    b.block(0.25, 0.02, 0.15, P.blackMetal(), 0, 0.765, 0);
    b.pop();
    const per = Math.floor(seats / 2);
    for (let i = 0; i < per; i++) {
        const lx = -len / 2 + (i + 0.5) * (len / per);
        for (const sz of [-1, 1]) {
            const [cx, cz] = rot(x, z, ry, lx, sz * 0.85);
            const cry = ry + (sz > 0 ? 0 : Math.PI);
            taskChair(b, cx, cz, cry, P.blueFab());
            spot(spots, cx, cz, cry + Math.PI, 'sit_meeting');
        }
    }
}

function treadmill(b, x, z, ry, spots) {
    b.push(x, 0, z, ry);
    b.block(0.8, 0.18, 1.9, P.rubberBlack(), 0, 0, 0);
    b.block(0.56, 0.02, 1.6, M.std(0x2f3135, 0.95), 0, 0.18, 0.05);
    for (const sx of [-1, 1]) b.add(new THREE.BoxGeometry(0.05, 1.2, 0.06), P.blackMetal(), sx * 0.36, 0.75, -0.8, 0, -0.25);
    b.block(0.8, 0.28, 0.22, P.blackMetal(), 0, 1.25, -0.98);
    b.block(0.4, 0.22, 0.02, M.screenOn(0x35d0ff), 0, 1.32, -0.86);
    b.pop();
    spot(spots, x, z, ry + Math.PI, 'run', { y: 0.2 });
}

function bike(b, x, z, ry, spots) {
    b.push(x, 0, z, ry);
    b.block(0.5, 0.06, 1.1, P.blackMetal(), 0, 0, 0);
    b.add(new THREE.BoxGeometry(0.08, 0.8, 0.08), P.blackMetal(), 0, 0.45, 0.15, 0, 0.3);
    b.add(new THREE.BoxGeometry(0.08, 1.0, 0.08), P.blackMetal(), 0, 0.55, -0.32, 0, -0.25);
    b.add(rb(0.22, 0.06, 0.3, 0.02), P.rubberBlack(), 0, 0.88, 0.27);
    b.add(new THREE.BoxGeometry(0.46, 0.04, 0.04), P.chrome(), 0, 1.05, -0.45);
    b.add(new THREE.CylinderGeometry(0.24, 0.24, 0.05, 20), M.std(0xc23b3b, 0.4, 0.5), 0, 0.32, -0.38, 0, 0, Math.PI / 2);
    b.block(0.24, 0.14, 0.02, M.screenOn(0x35d0ff), 0, 1.1, -0.5);
    b.pop();
    const [px, pz] = rot(x, z, ry, 0, 0.25);
    spot(spots, px, pz, ry + Math.PI, 'cycle', { y: 0.38 });
}

function weightBench(b, x, z, ry, spots) {
    b.push(x, 0, z, ry);
    b.add(rb(0.3, 0.08, 1.2, 0.03), P.rubberBlack(), 0, 0.44, 0);
    b.block(0.06, 0.42, 0.06, P.blackMetal(), 0, 0, -0.45);
    b.block(0.06, 0.42, 0.06, P.blackMetal(), 0, 0, 0.45);
    for (const sx of [-1, 1]) b.block(0.06, 1.2, 0.06, P.blackMetal(), sx * 0.55, 0, -0.5);
    b.add(new THREE.CylinderGeometry(0.015, 0.015, 1.7, 8), P.chrome(), 0, 1.05, -0.5, 0, 0, Math.PI / 2);
    for (const sx of [-1, 1]) b.add(new THREE.CylinderGeometry(0.2, 0.2, 0.05, 18), P.rubberBlack(), sx * 0.72, 1.05, -0.5, 0, 0, Math.PI / 2);
    b.pop();
    spot(spots, x, z, ry, 'lie_bench', { y: 0.48 });
}

function dumbbellRack(b, x, z, ry, len = 2.4) {
    b.push(x, 0, z, ry);
    b.block(len, 0.06, 0.5, P.blackMetal(), 0, 0.45, 0);
    b.block(len, 0.06, 0.5, P.blackMetal(), 0, 0.8, 0);
    for (const sx of [-1, 1]) b.block(0.06, 0.85, 0.5, P.blackMetal(), sx * (len / 2 - 0.03), 0, 0);
    for (let i = 0; i < 10; i++) for (const y of [0.55, 0.9]) {
        const dx = -len / 2 + 0.2 + i * (len - 0.4) / 9;
        b.add(new THREE.CylinderGeometry(0.06, 0.06, 0.32, 10), P.rubberBlack(), dx, y, 0, 0, 0, Math.PI / 2);
    }
    b.pop();
}

function yogaMat(b, x, z, ry, hex, spots) {
    b.add(new THREE.BoxGeometry(0.65, 0.008, 1.85), M.std(new THREE.Color(hex).getHex(), 0.9), x, 0.006, z, ry);
    spot(spots, x, z, ry, 'yoga');
}

function locker(b, x, z, ry, len) {
    b.push(x, 0, z, ry);
    const n = Math.round(len / 0.4);
    for (let i = 0; i < n; i++) {
        const lx = -len / 2 + (i + 0.5) * (len / n);
        b.block(len / n - 0.01, 1.9, 0.5, M.std(i % 2 ? 0x45606e : 0x4d6a78, 0.5, 0.3), lx, 0.1, 0);
        b.block(0.02, 0.12, 0.02, P.chrome(), lx + 0.12, 1.1, 0.26);
        for (let k = 0; k < 4; k++) b.block(0.18, 0.01, 0.01, M.std(0x2b3b44, 0.6), lx, 1.65 + k * 0.04, 0.255);
    }
    b.block(len, 0.1, 0.46, M.std(0x2b2d31, 0.7), 0, 0, 0);
    b.pop();
}

function benchSeat(b, x, z, ry, len, spots = null, pose = 'sit_relax') {
    b.push(x, 0, z, ry);
    b.block(len, 0.05, 0.4, P.oak(), 0, 0.44, 0);
    for (const sx of [-1, 1]) b.block(0.05, 0.44, 0.36, P.blackMetal(), sx * (len / 2 - 0.15), 0, 0);
    b.pop();
    if (spots) for (let i = 0; i < Math.floor(len / 0.7); i++) {
        const [px, pz] = rot(x, z, ry, -len / 2 + 0.35 + i * 0.7, 0);
        spot(spots, px, pz, ry, pose);
    }
}

function vanity(b, x, z, ry, len, basins, spots) {
    b.push(x, 0, z, ry);
    b.block(len, 0.12, 0.55, P.marble(), 0, 0.8, 0);
    b.block(len, 0.5, 0.5, P.walnut(), 0, 0.3, -0.02);
    b.block(len, 0.9, 0.02, P.mirror(), 0, 1.15, -0.27);
    b.block(len, 0.03, 0.06, M.std(0xffffff, 0.3, 0, { emissive: 0xfff1d0, emissiveIntensity: 0.9 }), 0, 2.08, -0.24);
    for (let i = 0; i < basins; i++) {
        const lx = -len / 2 + (i + 0.5) * (len / basins);
        b.add(new THREE.CylinderGeometry(0.22, 0.17, 0.12, 20), P.ceramic(), lx, 0.98, 0.02);
        b.cyl(0.012, 0.012, 0.2, P.chrome(), lx, 1.02, -0.2, 8);
        b.block(0.02, 0.02, 0.12, P.chrome(), lx, 1.12, -0.14);
        const [px, pz] = rot(x, z, ry, lx, 0.62);
        spot(spots, px, pz, ry + Math.PI, 'stand_basin');
    }
    b.pop();
}

function wcCubicles(b, x, z, ry, n) {
    b.push(x, 0, z, ry);
    const cw = 1.0, cd = 1.6;
    for (let i = 0; i < n; i++) {
        const lx = -n * cw / 2 + (i + 0.5) * cw;
        b.block(0.035, 2.0, cd, M.std(0x5f6e73, 0.4), lx - cw / 2, 0.15, 0);
        b.block(0.7, 1.85, 0.035, M.std(0x6f7f85, 0.4), lx + 0.05, 0.15, cd / 2);
        b.add(rb(0.38, 0.4, 0.55, 0.12, 3), P.ceramic(), lx, 0.2, -cd / 2 + 0.38);
        b.add(rb(0.36, 0.38, 0.16, 0.05), P.ceramic(), lx, 0.55, -cd / 2 + 0.1);
    }
    b.block(0.035, 2.0, cd, M.std(0x5f6e73, 0.4), n * cw / 2, 0.15, 0);
    b.pop();
}

function bathtub(b, x, z, ry) {
    b.push(x, 0, z, ry);
    b.add(rb(0.8, 0.58, 1.75, 0.25, 4), P.ceramic(), 0, 0.29, 0);
    b.add(rb(0.62, 0.1, 1.55, 0.2, 3), M.std(0x9fc8d8, 0.05, 0.1, { transparent: true, opacity: 0.8 }), 0, 0.5, 0);
    b.cyl(0.015, 0.015, 0.9, P.chrome(), 0, 0.45, -0.95, 8);
    b.pop();
}

function shower(b, x, z, ry, s = 1.0) {
    b.push(x, 0, z, ry);
    b.block(s, 0.04, s, M.std(0x9aa0a2, 0.3), 0, 0, 0);
    b.add(new THREE.BoxGeometry(s, 2.0, 0.01), P.glass(), 0, 1.0, s / 2);
    b.add(new THREE.BoxGeometry(0.01, 2.0, s), P.glass(), s / 2, 1.0, 0);
    b.cyl(0.13, 0.13, 0.02, P.chrome(), 0, 2.15, -s / 2 + 0.25, 16);
    b.cyl(0.012, 0.012, 0.3, P.chrome(), 0, 2.2, -s / 2 + 0.1, 6);
    b.pop();
}

function serverRack(b, x, z, ry, ledMat) {
    b.push(x, 0, z, ry);
    b.block(0.6, 2.1, 1.0, M.std(0x16181c, 0.45, 0.5), 0, 0.06, 0);
    b.block(0.56, 1.9, 0.01, M.std(0x0e1013, 0.35, 0.6), 0, 0.15, 0.505);
    for (let u = 0; u < 14; u++) {
        const y = 0.22 + u * 0.13;
        b.block(0.5, 0.02, 0.012, M.std(0x2b2f36, 0.5, 0.5), 0, y, 0.51);
        b.add(new THREE.PlaneGeometry(0.05 + rand() * 0.15, 0.012), ledMat, -0.15 + rand() * 0.3, y + 0.05, 0.517);
    }
    b.pop();
}

function crac(b, x, z, ry) {
    b.push(x, 0, z, ry);
    b.block(1.8, 2.0, 0.85, M.std(0xe9eaec, 0.4, 0.2), 0, 0.06, 0);
    for (let i = 0; i < 12; i++) b.block(1.6, 0.02, 0.01, M.std(0x9aa0a6, 0.4), 0, 1.3 + i * 0.05, 0.43);
    b.block(0.3, 0.16, 0.01, M.screenOn(0x22c55e), 0.55, 1.0, 0.43);
    b.pop();
}

function counter(b, x, z, ry, len, d = 0.7, front = P.walnut(), top = P.marble()) {
    b.push(x, 0, z, ry);
    b.block(len, 1.05, d, front, 0, 0, 0);
    b.block(len + 0.04, 0.04, d + 0.06, top, 0, 1.05, 0);
    b.pop();
}

function displayCase(b, x, z, ry, len) {
    b.push(x, 0, z, ry);
    b.block(len, 0.9, 0.7, M.std(0x2b2d31, 0.5), 0, 0, 0);
    b.add(new THREE.BoxGeometry(len, 0.45, 0.66), P.glass(), 0, 1.13, 0);
    const cakes = ['#c8875a', '#e8d6b9', '#6b3e26', '#e9b6c3', '#f3e2a9'];
    for (let i = 0; i < Math.floor(len / 0.25); i++) b.cyl(0.08, 0.08, 0.07, M.std(new THREE.Color(cakes[i % cakes.length]).getHex(), 0.8), -len / 2 + 0.15 + i * 0.25, 0.95, 0.05, 12);
    b.pop();
}

function shelfUnit(b, x, z, ry, len, h = 1.8, productCols = ['#c94f4f', '#4f7fc9', '#e0c35a', '#5aa36b', '#e8e8e8', '#30343a']) {
    b.push(x, 0, z, ry);
    b.block(len, h, 0.45, M.std(0xf2f0eb, 0.5), 0, 0, -0.02);
    for (let s = 0; s < 4; s++) {
        const y = 0.15 + s * (h - 0.2) / 4;
        b.block(len - 0.04, 0.025, 0.42, M.std(0xdedbd3, 0.4), 0, y, 0.02);
        let px = -len / 2 + 0.06;
        while (px < len / 2 - 0.12) {
            const pw = 0.1 + rand() * 0.16, ph = 0.12 + rand() * 0.22;
            b.block(pw, ph, 0.22 + rand() * 0.1, M.std(new THREE.Color(productCols[(rand() * productCols.length) | 0]).getHex(), 0.6), px + pw / 2, y + 0.025, 0.06);
            px += pw + 0.03;
        }
    }
    b.pop();
}

function clothesRail(b, x, z, ry, len) {
    b.push(x, 0, z, ry);
    for (const sx of [-1, 1]) b.block(0.04, 1.6, 0.04, P.chrome(), sx * len / 2, 0, 0);
    b.add(new THREE.CylinderGeometry(0.015, 0.015, len, 8), P.chrome(), 0, 1.58, 0, 0, 0, Math.PI / 2);
    const cols = ['#2f3e55', '#c9c1b2', '#7a2f2f', '#3f5f4a', '#e8e4dc', '#1f2124', '#b5643c', '#6b7f99'];
    const n = Math.floor(len / 0.09);
    for (let i = 0; i < n; i++) {
        const c = M.fabric(cols[(rand() * cols.length) | 0]);
        b.add(new THREE.BoxGeometry(0.03, 0.75 + rand() * 0.25, 0.48), c, -len / 2 + 0.06 + i * (len - 0.1) / n, 1.12, 0);
    }
    b.pop();
}

function artFrame(b, x, y, z, ry, w, h, seed) {
    const c = document.createElement('canvas');
    c.width = 256; c.height = Math.round(256 * h / w);
    const ctx = c.getContext('2d');
    const pal = [['#e9e3d6', '#c96f4a', '#2f4f5f', '#d9b25a'], ['#f2efe8', '#1f2a36', '#8a9a7b', '#c9a27a'], ['#ece6dc', '#b5643c', '#3a5068', '#e2c79a']][seed % 3];
    ctx.fillStyle = pal[0]; ctx.fillRect(0, 0, c.width, c.height);
    for (let i = 0; i < 5; i++) {
        ctx.fillStyle = pal[1 + (i % 3)];
        ctx.globalAlpha = 0.85;
        if (i % 2) { ctx.beginPath(); ctx.arc(rand() * c.width, rand() * c.height, 20 + rand() * 60, 0, 7); ctx.fill(); }
        else ctx.fillRect(rand() * c.width * 0.6, rand() * c.height * 0.6, 40 + rand() * 120, 20 + rand() * 90);
    }
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    b.push(x, y, z, ry);
    b.block(w + 0.06, h + 0.06, 0.03, P.blackMetal(), 0, -h / 2 - 0.03, 0);
    b.add(new THREE.PlaneGeometry(w, h), new THREE.MeshStandardMaterial({ map: t, roughness: 0.8 }), 0, 0, 0.017);
    b.pop();
}

function textPanel(text, sub, w = 1024, h = 256, bg = '#1c1e22', fg = '#f4f1ea') {
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    const ctx = c.getContext('2d');
    ctx.fillStyle = bg; ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = fg;
    ctx.font = `600 ${Math.round(h * 0.36)}px "Segoe UI", Arial`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(text, w / 2, sub ? h * 0.42 : h / 2);
    if (sub) { ctx.font = `${Math.round(h * 0.14)}px "Segoe UI", Arial`; ctx.fillStyle = '#9aa3ad'; ctx.fillText(sub, w / 2, h * 0.75); }
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    t.anisotropy = 8;
    return t;
}

function whiteboard(b, x, z, ry, w = 1.8) {
    b.push(x, 0, z, ry);
    b.block(w, 1.1, 0.03, M.std(0xfafafa, 0.15), 0, 1.0, 0);
    b.block(w, 0.03, 0.06, P.chrome(), 0, 0.98, 0.03);
    b.pop();
}

function openStand(spots, x0, x1, z0, z1, n, pose = 'stand') {
    // free standing positions on a jittered grid inside a rectangle
    const cols = Math.max(1, Math.ceil(Math.sqrt(n * (x1 - x0) / Math.max(0.1, z1 - z0))));
    const rows = Math.max(1, Math.ceil(n / cols));
    let k = 0;
    for (let j = 0; j < rows; j++) for (let i = 0; i < cols; i++) {
        if (k++ >= n) return;
        const x = x0 + (i + 0.5) * (x1 - x0) / cols + (rand() - 0.5) * 0.4;
        const z = z0 + (j + 0.5) * (z1 - z0) / rows + (rand() - 0.5) * 0.4;
        spot(spots, x, z, rand() * Math.PI * 2, pose);
    }
}

function talkGroups(spots, cx, cz, groups, radius = 0.55) {
    for (const [gx, gz, n] of groups) {
        for (let i = 0; i < n; i++) {
            const a = (i / n) * Math.PI * 2 + rand() * 0.3;
            const x = cx + gx + Math.cos(a) * radius, z = cz + gz + Math.sin(a) * radius;
            spot(spots, x, z, Math.atan2(cx + gx - x, cz + gz - z), 'stand_talk');
        }
    }
}

// ---------------------------------------------------------------- layouts
// ctx: { b, w, d, ext: {N,S,E,W}, room, plants, ox, oy, oz, screenMat, ledMat }
const L = {};

L.office = (ctx) => {
    const { b, w, d } = ctx;
    const spots = [];
    // desks in benches of 4 (two facing pairs), rows across the room, facing the long axis
    const benchW = 3.2, benchD = 1.9;
    const nx = Math.max(1, Math.floor((w - 2.0) / (benchW + 1.4)));
    const nz = Math.max(1, Math.floor((d - 2.6) / (benchD + 1.4)));
    const gx = (w - nx * benchW) / (nx + 1), gz = (d - nz * benchD) / (nz + 1);
    for (let i = 0; i < nx; i++) for (let j = 0; j < nz; j++) {
        const cx = -w / 2 + gx + benchW / 2 + i * (benchW + gx);
        const cz = -d / 2 + gz + benchD / 2 + j * (benchD + gz) + 0.2;
        for (const side of [-1, 1]) for (const k of [-0.8, 0.8]) {
            desk(b, cx + k, cz + side * 0.39, side > 0 ? 0 : Math.PI, spots, { w: 1.55, d: 0.78, monitors: 1 + (rand() < 0.4 ? 1 : 0), screenMat: ctx.screenMat });
        }
        b.block(0.04, 0.38, benchD * 0.4, P.greyFab(), cx, 0.74, cz);       // desk screen divider
        b.block(benchW, 0.36, 0.03, P.sage(), cx, 0.75, cz);
    }
    // break-out corner with soft seating, storage and plants
    const sx = w / 2 - 1.6, sz = -d / 2 + 1.3;
    sofa(b, sx - 0.4, sz, 0, 2.0, P.teal(), spots);
    coffeeTable(b, sx - 0.4, sz + 1.0, 0.9, 0.5);
    for (let i = 0; i < Math.floor((w - 4) / 1.0); i++) b.block(0.9, 1.1, 0.45, M.std(0xeeeae2, 0.5), -w / 2 + 0.6 + i * 1.0, 0, -d / 2 + 0.3);
    plant(ctx, -w / 2 + 0.5, d / 2 - 0.5, 1.4);
    plant(ctx, w / 2 - 0.5, d / 2 - 0.5, 1.4);
    tallPlant(ctx, -w / 2 + 0.6, -d / 2 + 1.2);
    b.block(0.6, 1.0, 0.5, M.std(0xd9dadb, 0.4), w / 2 - 0.4, 0, 0.5);       // printer
    openStand(spots, -w / 2 + 1, w / 2 - 1, d / 2 - 1.1, d / 2 - 0.6, 4, 'stand_talk');
    return spots;
};

L.executive = L.office;

L.meeting = (ctx) => {
    const { b, w, d } = ctx;
    const spots = [];
    const len = Math.min(w - 3.2, 4.4);
    meetingTable(b, 0, 0.2, 0, len, spots, 8);
    // presentation wall
    tvWall(b, 0, -d / 2 + 0.25, 0, 2.2, ctx.screenMat);
    b.block(2.0, 1.15, 0.05, P.screen(), 0, 1.0, -d / 2 + 0.12);
    if (ctx.screenMat) b.add(new THREE.PlaneGeometry(1.92, 1.08), ctx.screenMat, 0, 1.575, -d / 2 + 0.146);
    whiteboard(b, w / 2 - 0.05, 0.2, -Math.PI / 2, 2.2);
    spot(spots, 1.4, -d / 2 + 1.1, Math.PI, 'stand_present');
    spot(spots, -1.5, -d / 2 + 1.2, Math.PI * 0.9, 'stand');
    plant(ctx, -w / 2 + 0.5, -d / 2 + 0.5, 1.3);
    plant(ctx, -w / 2 + 0.5, d / 2 - 0.5, 1.1);
    b.block(1.6, 0.85, 0.45, P.walnut(), -w / 2 + 0.3, 0, 0.3, Math.PI / 2);
    return spots;
};

L.kitchen = (ctx) => {
    const { b, w, d } = ctx;
    const spots = [];
    kitchenRun(b, -0.3, -d / 2 + 0.32, 0, Math.min(3.6, w - 1.6));
    spot(spots, -0.9, -d / 2 + 1.0, Math.PI, 'cook');
    spot(spots, 0.6, -d / 2 + 1.0, Math.PI, 'stand');
    // small dining table with stools
    b.add(rb(1.6, 0.04, 0.8, 0.02), P.oak(), 0, 1.02, 0.6);
    b.block(1.4, 1.0, 0.6, M.std(0xeeeae2, 0.5), 0, 0.02, 0.6);
    for (const [x, z, ry] of [[-0.5, 1.35, Math.PI], [0.5, 1.35, Math.PI], [-0.5, -0.15, 0], [0.5, -0.15, 0]]) {
        stool(b, x, z, 0.75);
        spot(spots, x, z, ry, 'sit_high');
    }
    plant(ctx, w / 2 - 0.4, d / 2 - 0.4, 1.0);
    b.block(0.5, 1.2, 0.5, P.chrome(), -w / 2 + 0.35, 0, d / 2 - 0.4);           // water dispenser
    return spots;
};

L.corridor = (ctx) => {
    const { b, w, d, room } = ctx;
    const spots = [];
    const longX = w >= d;
    const L_ = longX ? w : d;
    for (let i = 0; i < Math.floor(L_ / 4); i++) {
        const t = -L_ / 2 + 2 + i * 4;
        if (longX) { artFrame(b, t, 1.65, -d / 2 + 0.07, 0, 1.0, 0.7, i + room.room_id.length); plant(ctx, t + 1.5, -d / 2 + 0.4, 1.0); }
        else { artFrame(b, -w / 2 + 0.07, 1.65, t, Math.PI / 2, 1.0, 0.7, i); plant(ctx, -w / 2 + 0.4, t + 1.5, 1.0); }
    }
    if (longX) benchSeat(b, 0, d / 2 - 0.45, Math.PI, Math.min(3.2, w * 0.25), spots);
    // walking people along the corridor (the walk pose moves them along a short path)
    for (let i = 0; i < 6; i++) {
        const t = -L_ / 2 + 1.2 + (i + 0.5) * (L_ - 2.4) / 6;
        const off = (i % 2 ? 0.45 : -0.45) * (longX ? d : w) / 4;
        if (longX) spot(spots, t, off, i % 2 ? Math.PI / 2 : -Math.PI / 2, 'walk', { path: [[-L_ / 2 + 1, off], [L_ / 2 - 1, off]] });
        else spot(spots, off, t, i % 2 ? 0 : Math.PI, 'walk', { path: [[off, -L_ / 2 + 1], [off, L_ / 2 - 1]] });
    }
    return spots;
};

L.lobby = (ctx) => {
    const { b, w, d, room } = ctx;
    if (/terrace/i.test(room.name)) return L.terrace(ctx);
    const spots = [];
    // reception desk (curved front) facing the entrance (south, +z)
    const rx = -w / 2 + 4.5, rz = -d / 2 + 3.2;
    const arc = new THREE.CylinderGeometry(2.2, 2.2, 1.1, 32, 1, true, -Math.PI * 0.32, Math.PI * 0.64);
    b.add(arc, M.std(0xf2efe8, 0.35), rx, 0.55, rz - 1.4);
    b.add(new THREE.CylinderGeometry(2.25, 2.25, 0.05, 32, 1, false, -Math.PI * 0.33, Math.PI * 0.66), P.marble(), rx, 1.12, rz - 1.4);
    b.block(2.4, 0.75, 0.6, P.walnut(), rx, 0, rz - 0.4);
    b.block(0.5, 0.32, 0.03, P.screen(), rx - 0.4, 1.0, rz - 0.55);
    taskChair(b, rx, rz - 0.95, Math.PI);
    spot(spots, rx, rz - 0.95, 0, 'sit_desk');
    // feature wall with the building name behind reception
    const logo = new THREE.MeshStandardMaterial({ map: textPanel('SMART HUB', 'digital twin · AI-controlled building', 1024, 300, '#2b2520', '#f2e6d0'), roughness: 0.6 });
    b.add(new THREE.PlaneGeometry(4.2, 1.25), logo, rx, 1.85, -d / 2 + 0.08);
    b.add(new THREE.BoxGeometry(6.2, 2.85, 0.12), M.timberClad(), rx, 1.425, -d / 2 + 0.0);
    // lounge seating
    const lx = w / 2 - 4.2, lz = 0.6;
    rug(b, lx, lz, 4.2, 3.2, '#8c8273');
    sofa(b, lx, lz - 1.1, 0, 2.6, P.cognac(), spots);
    armchair(b, lx - 1.7, lz + 0.5, Math.PI / 2, P.cream(), spots);
    armchair(b, lx + 1.7, lz + 0.5, -Math.PI / 2, P.cream(), spots);
    coffeeTable(b, lx, lz + 0.2, 1.3, 0.7);
    tallPlant(ctx, w / 2 - 0.8, -d / 2 + 0.8, 1.2);
    tallPlant(ctx, -w / 2 + 0.8, d / 2 - 1.2, 1.2);
    plant(ctx, rx + 2.6, rz - 1.8, 1.4);
    // security gates towards the lift core (east)
    for (let i = 0; i < 3; i++) {
        b.block(0.15, 1.0, 1.2, M.std(0xdadcde, 0.3, 0.6), w / 2 - 3.5 + i * 0.9, 0, -d / 2 + 2.2);
        b.add(new THREE.BoxGeometry(0.6, 0.6, 0.015), P.glass(), w / 2 - 3.05 + i * 0.9, 0.85, -d / 2 + 2.2);
    }
    // visitors: standing, waiting, walking in
    talkGroups(spots, 0, 0, [[-2.8, 1.6, 3], [0.2, 3.0, 2]]);
    for (let i = 0; i < 3; i++) spot(spots, -w / 2 + 6.5 + i * 1.2, d / 2 - 1.3, Math.PI, 'walk', { path: [[-w / 2 + 6.5 + i * 1.2, d / 2 - 1], [w / 2 - 3.2 + i * 0.9, -d / 2 + 3.2]] });
    openStand(spots, -w / 2 + 1, -1, 0.5, d / 2 - 1, 4, 'stand');
    return spots;
};

L.terrace = (ctx) => {
    const { b, w, d } = ctx;
    const spots = [];
    // winter garden: timber battens on the ceiling, planters with trees, loungers, dining
    for (let x = -w / 2 + 0.3; x < w / 2; x += 0.45) b.block(0.08, 0.12, d - 0.2, M.timberClad(), x, 2.7, 0);
    for (const [x, z] of [[-w / 2 + 1.2, -d / 2 + 1.2], [w / 2 - 1.2, -d / 2 + 1.2], [-w / 2 + 1.2, d / 2 - 1.2], [0, -d / 2 + 1.0]]) {
        b.block(1.6, 0.6, 1.6, M.std(0xe2ddd3, 0.7), x, 0, z);
        b.block(1.5, 0.04, 1.5, new THREE.MeshStandardMaterial({ map: T.soil() }), x, 0.58, z);
        ctx.plants.push({ kind: 'flower', x: ctx.ox + x, z: ctx.oz + z, y: ctx.oy + 0.6, s: 0.5, r: rand() * 6 });
    }
    for (let i = 0; i < 4; i++) {
        const x = -w / 2 + 3.2 + i * 1.3;
        b.block(0.7, 0.3, 1.9, M.std(0xe9e6df, 0.6), x, 0, d / 2 - 1.5);
        b.add(rb(0.66, 0.1, 1.3, 0.04, 2), P.linen(), x, 0.34, d / 2 - 1.3);
        b.add(new THREE.BoxGeometry(0.66, 0.08, 0.6), P.linen(), x, 0.5, d / 2 - 2.2, 0, -0.6);
        spot(spots, x, d / 2 - 1.5, 0, 'lie_lounger', { y: 0.38 });
    }
    // dining
    b.add(rb(2.4, 0.05, 1.0, 0.02), P.oak(), w / 2 - 4, 0.74, 0.3);
    for (const sx of [-1, 1]) b.block(0.08, 0.72, 0.8, P.blackMetal(), w / 2 - 4 + sx * 1.0, 0, 0.3);
    for (let i = 0; i < 3; i++) for (const sz of [-1, 1]) {
        const x = w / 2 - 4.8 + i * 0.8, z = 0.3 + sz * 0.75;
        diningChair(b, x, z, sz > 0 ? 0 : Math.PI, P.oak());
        spot(spots, x, z, sz > 0 ? Math.PI : 0, 'sit_dining');
    }
    talkGroups(spots, 0, 0, [[2.5, -1.8, 3], [-3.5, 0.6, 2]]);
    openStand(spots, -2, 2, -1, 1.5, 3, 'stand');
    return spots;
};

L.shop = (ctx) => {
    const { room } = ctx;
    if (/cafe|coffee/i.test(room.name) || /cafe/.test(room.room_id)) return L.cafe(ctx);
    if (/b$/i.test(room.room_id) || /B$/.test(room.name)) return L.retailTech(ctx);
    return L.retailFashion(ctx);
};

L.cafe = (ctx) => {
    const { b, w, d } = ctx;
    const spots = [];
    // service counter along the back (north, -z) with espresso machine and display case
    const cz = -d / 2 + 2.0;
    counter(b, -1.5, cz, 0, 5.2, 0.75, P.walnut(), P.marble());
    displayCase(b, 2.1, cz, 0, 2.0);
    b.block(0.7, 0.42, 0.45, P.chrome(), -2.4, 1.09, cz);                     // espresso machine
    b.block(0.2, 0.5, 0.2, P.blackMetal(), -1.8, 1.09, cz);                    // grinder
    b.block(0.35, 0.25, 0.3, P.screen(), 0.2, 1.09, cz);                       // till
    // back bar shelves and menu boards
    b.block(6.4, 0.9, 0.5, M.std(0x2b2d31, 0.5), -0.6, 0, -d / 2 + 0.3);
    shelfUnit(b, -0.6, -d / 2 + 0.3, 0, 6.2, 2.2, ['#6b3e26', '#c8875a', '#e8d6b9', '#2f4f5f', '#f2efe8']);
    const menu = new THREE.MeshStandardMaterial({ map: textPanel('COFFEE · TEA · BAKERY', 'espresso 450  ·  latte 650  ·  croissant 500', 1024, 256, '#20231f', '#f1ead8'), emissive: 0xffffff, emissiveIntensity: 0.15, roughness: 0.6 });
    menu.emissiveMap = menu.map;
    b.add(new THREE.PlaneGeometry(4.2, 1.05), menu, -0.6, 2.4, -d / 2 + 0.56);
    spot(spots, -2.0, cz - 0.75, 0, 'barista');
    spot(spots, 0.2, cz - 0.75, 0, 'stand');
    // queue
    for (let i = 0; i < 3; i++) spot(spots, 0.6 + i * 0.05, cz + 1.0 + i * 0.75, Math.PI, 'stand');
    // tables: 2-seat and 4-seat, timber tops, chairs
    const tables = [[-w / 2 + 1.6, 1.2, 4], [-w / 2 + 1.6, 3.8, 2], [-w / 2 + 4.4, 2.4, 4], [1.2, 3.6, 2], [3.6, 1.6, 4], [w / 2 - 1.6, 3.8, 2], [w / 2 - 1.6, 1.0, 2]];
    for (const [tx, tz, n] of tables) {
        if (n === 4) b.add(rb(1.2, 0.04, 0.8, 0.015), P.oak(), tx, 0.74, tz);
        else b.cyl(0.38, 0.38, 0.04, P.oak(), tx, 0.74, tz, 20);
        b.cyl(0.03, 0.03, 0.72, P.blackMetal(), tx, 0.36, tz, 8);
        b.cyl(0.24, 0.24, 0.02, P.blackMetal(), tx, 0.01, tz, 12);
        const pos = n === 4 ? [[-0.35, -0.65, 0], [0.35, -0.65, 0], [-0.35, 0.65, Math.PI], [0.35, 0.65, Math.PI]] : [[0, -0.6, 0], [0, 0.6, Math.PI]];
        for (const [px, pz, ry] of pos) {
            diningChair(b, tx + px, tz + pz, ry + Math.PI, P.oak(), P.terra());
            spot(spots, tx + px, tz + pz, ry, 'sit_cafe');
            b.cyl(0.04, 0.035, 0.09, P.ceramic(), tx + px * 0.6, 0.8, tz + pz * 0.45, 10);
        }
    }
    // window bar with stools (south glazing)
    b.block(w - 3, 0.04, 0.45, P.oak(), 0, 1.05, d / 2 - 0.35);
    for (let i = 0; i < 6; i++) {
        const x = -w / 2 + 2.5 + i * (w - 5) / 5;
        stool(b, x, d / 2 - 0.85, 0.75);
        spot(spots, x, d / 2 - 0.85, 0, 'sit_high');
    }
    tallPlant(ctx, w / 2 - 0.7, -d / 2 + 2.6, 1.1);
    plant(ctx, -w / 2 + 0.5, -d / 2 + 2.4, 1.2);
    return spots;
};

L.retailFashion = (ctx) => {
    const { b, w, d } = ctx;
    const spots = [];
    for (let i = 0; i < 3; i++) clothesRail(b, -w / 2 + 2.0 + i * 2.6, -0.4, Math.PI / 2, 2.2);
    shelfUnit(b, 0, -d / 2 + 0.3, 0, w - 2.5, 2.1, ['#2f3e55', '#c9c1b2', '#7a2f2f', '#e8e4dc', '#1f2124']);
    // display table and mirror
    b.add(rb(1.6, 0.06, 0.9, 0.02), P.oak(), w / 2 - 2.0, 0.8, 1.2);
    b.block(1.4, 0.78, 0.7, M.std(0x2b2d31, 0.5), w / 2 - 2.0, 0, 1.2);
    for (let k = 0; k < 6; k++) b.block(0.3, 0.06, 0.25, M.fabric(['#2f3e55', '#c9c1b2', '#7a2f2f'][k % 3]), w / 2 - 2.5 + (k % 3) * 0.45, 0.83 + Math.floor(k / 3) * 0.06, 1.1);
    b.block(0.9, 2.0, 0.04, P.mirror(), w / 2 - 0.1, 0.1, -1.4, Math.PI / 2);
    // checkout
    counter(b, w / 2 - 1.2, d / 2 - 1.4, Math.PI / 2, 1.6, 0.6, M.std(0xf2efe8, 0.4));
    b.block(0.35, 0.25, 0.3, P.screen(), w / 2 - 1.2, 1.09, d / 2 - 1.4);
    spot(spots, w / 2 - 0.55, d / 2 - 1.4, -Math.PI / 2, 'stand');
    for (let i = 0; i < 3; i++) spot(spots, -w / 2 + 2.0 + i * 2.6 + 0.9, -0.4 + (i - 1) * 0.6, -Math.PI / 2, 'browse');
    openStand(spots, -w / 2 + 1, w / 2 - 3, 1.5, d / 2 - 0.8, 6, 'browse');
    plant(ctx, -w / 2 + 0.5, d / 2 - 0.5, 1.2);
    return spots;
};

L.retailTech = (ctx) => {
    const { b, w, d } = ctx;
    const spots = [];
    // light-timber demo tables with devices, wall displays
    for (let i = 0; i < 2; i++) for (let j = 0; j < 2; j++) {
        const tx = -w / 2 + 2.6 + i * 3.6, tz = -1.2 + j * 2.6;
        b.add(rb(2.6, 0.05, 1.0, 0.02), M.std(0xe6d2b5, 0.5), tx, 0.86, tz);
        b.block(2.2, 0.84, 0.6, M.std(0xf2f0eb, 0.4), tx, 0, tz);
        for (let k = 0; k < 4; k++) {
            b.add(new THREE.BoxGeometry(0.32, 0.01, 0.22), P.screen(), tx - 0.9 + k * 0.6, 0.895, tz);
            if (ctx.screenMat) b.add(new THREE.PlaneGeometry(0.3, 0.2), ctx.screenMat, tx - 0.9 + k * 0.6, 0.902, tz, 0, -Math.PI / 2);
        }
        spot(spots, tx - 0.6, tz + 0.75, Math.PI, 'browse');
        spot(spots, tx + 0.6, tz - 0.75, 0, 'browse');
    }
    shelfUnit(b, 0, -d / 2 + 0.3, 0, w - 1.5, 2.0, ['#1f2124', '#e8e8e8', '#4f7fc9', '#30343a']);
    b.block(2.4, 1.4, 0.05, P.screen(), w / 2 - 0.1, 1.0, 0.5, Math.PI / 2);
    if (ctx.screenMat) b.add(new THREE.PlaneGeometry(2.3, 1.3), ctx.screenMat, w / 2 - 0.13, 1.7, 0.5, -Math.PI / 2);
    counter(b, w / 2 - 1.3, d / 2 - 1.1, 0, 1.8, 0.6, M.std(0xf2efe8, 0.4));
    spot(spots, w / 2 - 1.3, d / 2 - 1.75, 0, 'stand');
    openStand(spots, -w / 2 + 1, w / 2 - 2, 1.6, d / 2 - 0.6, 4, 'browse');
    tallPlant(ctx, -w / 2 + 0.6, d / 2 - 0.6, 1);
    return spots;
};

L.bathroom = (ctx) => {
    const { b, w, d, room } = ctx;
    const spots = [];
    const name = room.name.toLowerCase();
    if (/locker/.test(name)) {
        locker(b, 0, -d / 2 + 0.3, 0, Math.min(w - 2, 8));
        locker(b, -w / 2 + 0.3, 0.6, Math.PI / 2, Math.min(d - 3, 4));
        benchSeat(b, 0, -0.6, 0, 4, spots, 'sit_bench');
        benchSeat(b, 0, 1.2, Math.PI, 4, spots, 'sit_bench');
        for (let i = 0; i < 4; i++) shower(b, w / 2 - 0.6, -d / 2 + 0.7 + i * 1.15, -Math.PI / 2, 1.0);
        vanity(b, -w / 2 + 3.8, d / 2 - 0.3, Math.PI, 3.0, 3, spots);
        openStand(spots, -3, 2, 2.3, d / 2 - 1.2, 3, 'stand');
        return spots;
    }
    if (/public|restroom/.test(name)) {
        wcCubicles(b, -w / 2 + 2.6, -d / 2 + 0.9, 0, 4);
        wcCubicles(b, w / 2 - 2.1, -d / 2 + 0.9, 0, 3);
        vanity(b, -1.0, d / 2 - 0.35, Math.PI, 3.6, 4, spots);
        b.block(0.3, 0.5, 0.2, P.chrome(), w / 2 - 0.5, 1.0, d / 2 - 0.15);       // hand dryer
        openStand(spots, -w / 2 + 1, w / 2 - 1, 0.6, 1.6, 3, 'stand');
        return spots;
    }
    // residential / luxury bath: tub, shower, vanity, WC
    const luxe = /luxury/.test(name);
    bathtub(b, w / 2 - 0.55, luxe ? 0 : -d / 2 + 1.2, 0);
    shower(b, -w / 2 + 0.65, -d / 2 + 0.65, 0, 1.2);
    vanity(b, luxe ? -0.5 : 0.0, d / 2 - 0.32, Math.PI, luxe ? 2.4 : 1.4, luxe ? 2 : 1, spots);
    b.add(rb(0.38, 0.4, 0.55, 0.12, 3), P.ceramic(), -w / 2 + 0.4, 0.2, 0.4);
    b.add(rb(0.36, 0.38, 0.16, 0.05), P.ceramic(), -w / 2 + 0.18, 0.55, 0.4);
    b.block(0.5, 0.012, 0.8, M.fabric('#d9d1c2'), 0.3, 0, 0.6);
    plant(ctx, w / 2 - 0.4, d / 2 - 0.4, 0.9);
    openStand(spots, -0.8, 0.8, -0.6, 0.6, 1, 'stand');
    return spots;
};

L.gym = (ctx) => {
    const { b, w, d, room } = ctx;
    const spots = [];
    if (/yoga|studio/i.test(room.name)) {
        b.block(w - 0.4, 2.2, 0.03, P.mirror(), 0, 0.2, -d / 2 + 0.06);
        b.block(w - 0.4, 0.04, 0.06, P.oak(), 0, 1.0, -d / 2 + 0.12);     // barre
        const cols = ['#7b6aa8', '#5aa38f', '#c9785a', '#4f7fc9', '#d6a33e'];
        const nx = Math.max(2, Math.floor((w - 2) / 1.3)), nz = Math.max(1, Math.floor((d - 3) / 2.3));
        let k = 0;
        for (let j = 0; j < nz; j++) for (let i = 0; i < nx; i++) {
            yogaMat(b, -w / 2 + 1.2 + i * (w - 2.4) / Math.max(1, nx - 1), -d / 2 + 2.6 + j * 2.3, Math.PI, cols[k++ % cols.length], spots);
        }
        spot(spots, 0, -d / 2 + 1.1, 0, 'yoga');
        plant(ctx, w / 2 - 0.5, d / 2 - 0.5, 1.3);
        plant(ctx, -w / 2 + 0.5, d / 2 - 0.5, 1.3);
        return spots;
    }
    // fitness centre: treadmills facing the south glazing, bikes, free weights, mirror wall
    b.block(0.03, 2.2, d - 1.0, P.mirror(), -w / 2 + 0.06, 0.2, 0, 0);
    const nT = Math.max(3, Math.floor((w - 6) / 1.25));
    for (let i = 0; i < nT; i++) treadmill(b, -w / 2 + 2.0 + i * 1.25, d / 2 - 1.6, 0, spots);
    const nB = Math.max(3, Math.floor((w - 8) / 1.1));
    for (let i = 0; i < nB; i++) bike(b, -w / 2 + 2.2 + i * 1.1, d / 2 - 4.4, 0, spots);
    weightBench(b, w / 2 - 3.2, -d / 2 + 3.0, 0, spots);
    weightBench(b, w / 2 - 1.6, -d / 2 + 3.0, 0, spots);
    dumbbellRack(b, w / 2 - 2.4, -d / 2 + 0.5, 0, 3.0);
    for (let i = 0; i < 3; i++) spot(spots, w / 2 - 3.4 + i * 1.0, -d / 2 + 1.4, Math.PI, 'lift_db');
    // functional area with mats
    b.block(4.5, 0.02, 3.2, M.std(0x3a4c5c, 0.9), -w / 2 + 3.5, 0, -d / 2 + 2.2);
    for (let i = 0; i < 3; i++) spot(spots, -w / 2 + 2.2 + i * 1.3, -d / 2 + 2.2, Math.PI, 'stretch');
    b.block(1.2, 1.0, 0.45, M.std(0xeeeae2, 0.5), 2.0, 0, -d / 2 + 0.3);
    plant(ctx, -w / 2 + 0.6, d / 2 - 0.6, 1.3);
    tallPlant(ctx, w / 2 - 0.6, d / 2 - 0.6, 1.0);
    openStand(spots, -1, 3, -d / 2 + 1.2, -d / 2 + 4, 3, 'stand_talk');
    return spots;
};

L.lounge = (ctx) => {
    // spa & wellness: treatment beds, relaxation loungers, reception
    const { b, w, d } = ctx;
    const spots = [];
    for (let i = 0; i < 3; i++) {
        const x = -w / 2 + 1.6 + i * 2.2, z = -d / 2 + 2.0;
        b.add(rb(0.75, 0.12, 1.95, 0.05, 2), P.linen(), x, 0.72, z);
        b.block(0.6, 0.66, 1.7, P.oak(), x, 0, z);
        b.add(rb(0.5, 0.06, 0.4, 0.03, 2), M.std(0xffffff, 0.9), x, 0.82, z - 0.75);
        spot(spots, x, z, 0, 'lie_bed', { lift: 0.14 });
        // privacy curtain
        b.add(new THREE.BoxGeometry(0.02, 2.2, 2.2), M.fabric('#e9e2d4'), x + 1.1, 1.3, z);
    }
    for (let i = 0; i < 3; i++) {
        const x = -w / 2 + 1.6 + i * 2.6, z = d / 2 - 1.5;
        b.block(0.7, 0.32, 1.8, P.oak(), x, 0, z);
        b.add(rb(0.66, 0.1, 1.3, 0.04, 2), P.sage(), x, 0.36, z + 0.2);
        b.add(new THREE.BoxGeometry(0.66, 0.08, 0.6), P.sage(), x, 0.55, z - 0.65, 0, 0.6);
        spot(spots, x, z, 0, 'lie_lounger', { y: 0.38 });
    }
    counter(b, w / 2 - 1.2, 0.2, Math.PI / 2, 1.8, 0.6, P.oak(), P.marble());
    spot(spots, w / 2 - 0.5, 0.2, -Math.PI / 2, 'stand');
    for (let i = 0; i < 5; i++) b.cyl(0.03, 0.03, 0.06, M.std(0xfff1d0, 0.4, 0, { emissive: 0xffc070, emissiveIntensity: 1.5 }), -w / 2 + 1 + i * 0.4, 0.02, d / 2 - 0.3, 8);
    tallPlant(ctx, w / 2 - 0.6, d / 2 - 0.6, 1.1);
    plant(ctx, -w / 2 + 0.5, 0.2, 1.2);
    openStand(spots, -2, 2, 0, 1.2, 2, 'stand_talk');
    return spots;
};

L.server = (ctx) => {
    const { b, w, d } = ctx;
    const spots = [];
    // raised floor tiles are the floor finish; two rows of racks with a cold aisle, CRAC units on the end
    const n = Math.max(4, Math.floor((w - 4) / 0.62));
    for (const row of [-1, 1]) {
        for (let i = 0; i < n; i++) serverRack(b, -w / 2 + 1.6 + i * 0.62, row * 1.1, row > 0 ? 0 : Math.PI, ctx.ledMat);
    }
    // cold-aisle containment: glass roof + doors
    b.add(new THREE.BoxGeometry(n * 0.62, 0.02, 1.2), P.glass(), -w / 2 + 1.3 + n * 0.31, 2.2, 0);
    crac(b, w / 2 - 1.2, -d / 2 + 0.55, 0);
    crac(b, w / 2 - 1.2, d / 2 - 0.55, Math.PI);
    b.block(0.6, 1.8, 0.5, M.std(0xb03a2e, 0.5), -w / 2 + 0.4, 0, -d / 2 + 0.4);   // fire suppression
    spot(spots, -w / 2 + 3, 0, Math.PI / 2, 'stand');
    spot(spots, w / 2 - 3, 2.6, -Math.PI / 2, 'stand');
    return spots;
};

L.residential = (ctx) => {
    const { b, w, d, room } = ctx;
    const name = room.name.toLowerCase();
    const spots = [];
    if (/bed/.test(name)) {
        const big = /master/.test(name);
        const along = d >= w;            // bed head against the long wall
        bed(b, 0, along ? -d / 2 + 1.25 : 0, along ? 0 : Math.PI / 2, big ? 1.9 : 1.6, spots, big ? P.cream() : P.linen());
        wardrobe(b, along ? -w / 2 + 0.32 : 0, along ? d / 2 - 1.8 : -d / 2 + 0.32, along ? Math.PI / 2 : 0, big ? 2.6 : 2.0);
        rug(b, 0, along ? -d / 2 + 2.5 : 0.6, 2.2, 1.6, big ? '#8c8273' : '#b9ae9c');
        // desk / dressing table
        const dx = along ? w / 2 - 0.5 : w / 2 - 1.2, dz = along ? d / 2 - 1.6 : d / 2 - 0.45;
        b.block(along ? 0.55 : 1.2, 0.03, along ? 1.2 : 0.55, P.walnut(), dx, 0.74, dz);
        b.block(along ? 0.5 : 1.1, 0.72, 0.04, P.walnut(), dx, 0, dz + (along ? 0 : 0.2));
        const ry = along ? -Math.PI / 2 : 0;
        const [cx, cz] = rot(dx, dz, ry, 0, 0.65);
        diningChair(b, cx, cz, ry, P.walnut(), P.cream());
        spot(spots, cx, cz, ry + Math.PI, 'sit_desk');
        if (big) {
            armchair(b, -w / 2 + 1.2, d / 2 - 1.2, Math.PI * 0.75, P.cream(), spots);
            tallPlant(ctx, w / 2 - 0.6, -d / 2 + 0.6, 1.1);
        } else plant(ctx, w / 2 - 0.45, -d / 2 + 0.45, 1.0);
        return spots;
    }
    // living spaces: sofa facing the TV, dining, open kitchen, reading corner
    const pent = /penthouse|lounge/.test(name);
    const lx = -w / 4 - (pent ? 1.5 : 0), lz = pent ? -1.0 : -0.6;
    rug(b, lx, lz, pent ? 4.6 : 3.4, pent ? 3.6 : 2.8, pent ? '#6f665a' : '#9b8f7d');
    sofa(b, lx, lz + 1.1, Math.PI, pent ? 3.0 : 2.4, pent ? P.cream() : P.greyFab(), spots);
    armchair(b, lx + (pent ? 2.3 : 1.8), lz - 0.2, -Math.PI / 2, pent ? P.cognac() : P.mustard(), spots);
    if (pent) { sofa(b, lx - 2.3, lz - 0.2, Math.PI / 2, 2.2, P.cream(), spots); }
    coffeeTable(b, lx, lz, 1.2, 0.65);
    tvWall(b, lx, -d / 2 + 0.3, 0, pent ? 3.0 : 2.4, ctx.screenMat);
    // dining
    const tx = w / 4 + (pent ? 1.5 : 0.4), tz = pent ? 2.0 : 1.4;
    const seats = pent ? 8 : 4;
    const tl = pent ? 2.6 : 1.6;
    b.add(rb(tl, 0.05, 1.0, 0.02), pent ? P.marble() : P.oak(), tx, 0.74, tz);
    for (const sx of [-1, 1]) b.block(0.06, 0.72, 0.7, P.blackMetal(), tx + sx * (tl / 2 - 0.25), 0, tz);
    const per = seats / 2;
    for (let i = 0; i < per; i++) for (const sz of [-1, 1]) {
        const x = tx - tl / 2 + (i + 0.5) * tl / per, z = tz + sz * 0.72;
        diningChair(b, x, z, sz > 0 ? 0 : Math.PI, P.walnut(), pent ? P.cognac() : P.linen());
        spot(spots, x, z, sz > 0 ? Math.PI : 0, 'sit_dining');
    }
    // pendant lights over the table
    for (let i = 0; i < (pent ? 3 : 2); i++) {
        const px = tx - (pent ? 0.8 : 0.4) + i * 0.8;
        b.cyl(0.004, 0.004, 1.0, P.blackMetal(), px, 2.35, tz, 4);
        b.add(new THREE.SphereGeometry(0.16, 16, 10, 0, Math.PI * 2, 0, Math.PI / 2), M.std(0x2b2d31, 0.5, 0.4, { side: THREE.DoubleSide }), px, 1.75, tz);
    }
    // kitchen along the far wall, island with stools
    kitchenRun(b, w / 4 + 0.4, -d / 2 + 0.32, 0, pent ? 4.2 : 3.0, { fridge: true });
    spot(spots, w / 4 + 0.2, -d / 2 + 1.0, Math.PI, 'cook');
    b.add(rb(pent ? 2.6 : 1.8, 0.05, 0.9, 0.02), P.marble(), w / 4 + 0.4, 0.92, -d / 2 + 2.2);
    b.block(pent ? 2.4 : 1.6, 0.88, 0.7, M.std(0x2f3a40, 0.45), w / 4 + 0.4, 0.02, -d / 2 + 2.2);
    for (let i = 0; i < (pent ? 3 : 2); i++) {
        const x = w / 4 - 0.2 + i * 0.6;
        stool(b, x, -d / 2 + 2.95, 0.72);
        spot(spots, x, -d / 2 + 2.95, Math.PI, 'sit_high');
    }
    bookshelf(b, -w / 2 + 0.22, d / 2 - 1.6, Math.PI / 2, 1.8, 2.1);
    tallPlant(ctx, -w / 2 + 0.6, -d / 2 + 0.6, pent ? 1.3 : 1.0);
    plant(ctx, w / 2 - 0.45, d / 2 - 0.45, 1.2);
    b.cyl(0.015, 0.015, 1.6, P.blackMetal(), -w / 2 + 0.6, 0.8, d / 2 - 0.6, 6);       // floor lamp
    b.cyl(0.2, 0.24, 0.3, P.linen(), -w / 2 + 0.6, 1.65, d / 2 - 0.6, 16);
    if (pent) {
        // grand piano silhouette and art
        b.add(rb(1.5, 0.3, 1.9, 0.2, 3), M.std(0x0d0d0f, 0.15, 0.2), w / 2 - 1.5, 0.75, d / 2 - 1.6);
        for (const [x, z] of [[-0.5, -0.6], [0.5, -0.6], [0, 0.7]]) b.block(0.06, 0.62, 0.06, M.std(0x0d0d0f, 0.2), w / 2 - 1.5 + x, 0, d / 2 - 1.6 + z);
        artFrame(b, lx, 1.8, d / 2 - 0.05, Math.PI, 2.0, 1.2, 1);
        talkGroups(spots, 0, 0, [[1.2, 0.6, 3]]);
    }
    return spots;
};

/** Build the furniture of a room into `b` (already pushed to the room frame). */
export function furnish(ctx) {
    const fn = L[ctx.room.type] || L.office;
    const spots = fn(ctx) || [];
    // make sure there are enough places for the room's maximum occupancy
    const need = (ctx.room.max_occupancy || 4) + 2 - spots.length;
    if (need > 0) openStand(spots, -ctx.w / 2 + 1, ctx.w / 2 - 1, -ctx.d / 2 + 1, ctx.d / 2 - 1, need, 'stand');
    return spots;
}
