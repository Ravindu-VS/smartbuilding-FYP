// ═══════════════════════════════════════════════════════════════
// vegetation.js — trees, coconut palms, shrubs and hedges
// ═══════════════════════════════════════════════════════════════
// Crowns are built from alpha-tested leaf cards (not solid blobs), so trees read as
// real foliage and cast dappled shadows. Each species is one geometry, drawn with
// an InstancedMesh, so a hundred trees cost a handful of draw calls.

import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { rand } from '../lib/materials.js';

function leafTexture(key, palette, kind = 'broad') {
    const c = document.createElement('canvas');
    c.width = c.height = 256;
    const ctx = c.getContext('2d');
    ctx.clearRect(0, 0, 256, 256);
    const n = kind === 'broad' ? 70 : 120;
    for (let i = 0; i < n; i++) {
        const x = 30 + rand() * 196, y = 30 + rand() * 196;
        const r = kind === 'broad' ? 9 + rand() * 12 : 5 + rand() * 6;
        const col = palette[(rand() * palette.length) | 0];
        ctx.save();
        ctx.translate(x, y);
        ctx.rotate(rand() * Math.PI * 2);
        ctx.fillStyle = col;
        ctx.beginPath();
        ctx.ellipse(0, 0, r, r * (kind === 'broad' ? 0.55 : 0.35), 0, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = 'rgba(20,40,10,0.35)';
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(-r, 0); ctx.lineTo(r, 0); ctx.stroke();
        ctx.restore();
    }
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    t.anisotropy = 4;
    return t;
}

function frondTexture() {
    const c = document.createElement('canvas');
    c.width = 512; c.height = 128;
    const ctx = c.getContext('2d');
    ctx.clearRect(0, 0, 512, 128);
    // midrib along x, leaflets angled forward on both sides, shrinking to the tip
    ctx.strokeStyle = '#6b5b2e'; ctx.lineWidth = 4;
    ctx.beginPath(); ctx.moveTo(0, 64); ctx.lineTo(512, 64); ctx.stroke();
    for (let x = 18; x < 500; x += 7) {
        const len = 58 * Math.sin(Math.PI * Math.min(1, x / 520 + 0.08)) * (0.85 + rand() * 0.25);
        for (const s of [-1, 1]) {
            const g = 90 + rand() * 50 | 0;
            ctx.strokeStyle = `rgb(${40 + rand() * 30 | 0},${g},${30 + rand() * 20 | 0})`;
            ctx.lineWidth = 3.2;
            ctx.beginPath();
            ctx.moveTo(x, 64);
            ctx.quadraticCurveTo(x + len * 0.35, 64 + s * len * 0.5, x + len * 0.55, 64 + s * len * 0.95);
            ctx.stroke();
        }
    }
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    t.anisotropy = 4;
    return t;
}

function barkTexture(ring = false) {
    const c = document.createElement('canvas');
    c.width = 64; c.height = 256;
    const ctx = c.getContext('2d');
    ctx.fillStyle = ring ? '#8a7b66' : '#5a4a3a';
    ctx.fillRect(0, 0, 64, 256);
    for (let y = 0; y < 256; y += ring ? 9 : 3) {
        ctx.fillStyle = `rgba(30,22,15,${ring ? 0.45 : 0.12 + rand() * 0.15})`;
        ctx.fillRect(0, y, 64, ring ? 2 : 1);
    }
    for (let i = 0; i < 300; i++) {
        ctx.fillStyle = `rgba(${rand() < 0.5 ? '255,255,255' : '0,0,0'},${0.05 + rand() * 0.07})`;
        ctx.fillRect(rand() * 64, rand() * 256, 2, 6);
    }
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    return t;
}

const MATS = {};
function mats() {
    if (MATS.leafA) return MATS;
    MATS.leafA = new THREE.MeshStandardMaterial({ map: leafTexture('a', ['#3f6b2a', '#4f7d32', '#365e24', '#5d8b3a', '#2f5220']), alphaTest: 0.45, side: THREE.DoubleSide, roughness: 0.85 });
    MATS.leafB = new THREE.MeshStandardMaterial({ map: leafTexture('b', ['#4c7a3c', '#6a9446', '#3a6830', '#7ea457'], 'fine'), alphaTest: 0.45, side: THREE.DoubleSide, roughness: 0.85 });
    MATS.leafFlower = new THREE.MeshStandardMaterial({ map: leafTexture('f', ['#3d6b2c', '#4f7f34', '#c2417a', '#d75a8d', '#3a6328']), alphaTest: 0.45, side: THREE.DoubleSide, roughness: 0.8 });
    MATS.frond = new THREE.MeshStandardMaterial({ map: frondTexture(), alphaTest: 0.4, side: THREE.DoubleSide, roughness: 0.8 });
    MATS.bark = new THREE.MeshStandardMaterial({ map: barkTexture(false), roughness: 0.95 });
    MATS.palmBark = new THREE.MeshStandardMaterial({ map: barkTexture(true), roughness: 0.9 });
    MATS.hedge = new THREE.MeshStandardMaterial({ map: leafTexture('h', ['#355f27', '#447230', '#2c5020', '#52823a'], 'fine'), roughness: 0.95 });
    MATS.hedge.map.wrapS = MATS.hedge.map.wrapT = THREE.RepeatWrapping;
    MATS.coconut = new THREE.MeshStandardMaterial({ color: 0x6d5a2a, roughness: 0.7 });
    return MATS;
}

/** Leaf-card crown inside an ellipsoid. Returns a merged geometry. */
function crown(cx, cy, cz, rx, ry, rz, cards, size) {
    const geos = [];
    for (let i = 0; i < cards; i++) {
        let x, y, z;
        do { x = rand() * 2 - 1; y = rand() * 2 - 1; z = rand() * 2 - 1; } while (x * x + y * y + z * z > 1);
        const s = size * (0.7 + rand() * 0.6);
        const g = new THREE.PlaneGeometry(s, s);
        g.rotateX(rand() * Math.PI);
        g.rotateY(rand() * Math.PI * 2);
        g.rotateZ((rand() - 0.5) * 1.2);
        g.translate(cx + x * rx, cy + y * ry, cz + z * rz);
        geos.push(g);
    }
    return mergeGeometries(geos);
}

function trunk(h, r0, r1, bend = 0.25, seg = 7) {
    const pts = [];
    const ox = (rand() - 0.5) * bend, oz = (rand() - 0.5) * bend;
    for (let i = 0; i <= 6; i++) {
        const t = i / 6;
        pts.push(new THREE.Vector3(ox * t * t, t * h, oz * t * t));
    }
    const curve = new THREE.CatmullRomCurve3(pts);
    const g = new THREE.TubeGeometry(curve, 10, 1, seg, false);
    // taper radius along the length
    const pos = g.attributes.position;
    const v = new THREE.Vector3();
    for (let i = 0; i < pos.count; i++) {
        v.fromBufferAttribute(pos, i);
        const t = Math.min(1, Math.max(0, v.y / h));
        const p = curve.getPoint(t);
        const r = r0 + (r1 - r0) * t;
        v.sub(p).multiplyScalar(r).add(p);
        pos.setXYZ(i, v.x, v.y, v.z);
    }
    g.computeVertexNormals();
    return { geo: g, top: curve.getPoint(1) };
}

/** Species definitions: broadleaf shade tree, flowering tree, small ornamental, coconut palm. */
function buildSpecies(kind) {
    const m = mats();
    if (kind === 'palm') {
        const h = 9;
        const pts = [];
        const lean = 0.9;
        for (let i = 0; i <= 8; i++) {
            const t = i / 8;
            pts.push(new THREE.Vector3(lean * Math.sin(t * 1.4), t * h, 0));
        }
        const curve = new THREE.CatmullRomCurve3(pts);
        const tg = new THREE.TubeGeometry(curve, 16, 0.17, 8, false);
        const pos = tg.attributes.position, v = new THREE.Vector3();
        for (let i = 0; i < pos.count; i++) {      // slight swelling at the base
            v.fromBufferAttribute(pos, i);
            const t = v.y / h;
            const p = curve.getPoint(Math.min(1, Math.max(0, t)));
            v.sub(p).multiplyScalar(1 + 0.6 * Math.max(0, 0.15 - t) / 0.15).add(p);
            pos.setXYZ(i, v.x, v.y, v.z);
        }
        tg.computeVertexNormals();
        const top = curve.getPoint(1);
        const fronds = [];
        const nf = 16;
        for (let i = 0; i < nf; i++) {
            const len = 3.6 + rand() * 0.8;
            const g = new THREE.PlaneGeometry(len, 1.15, 10, 1);
            g.translate(len / 2, 0, 0);
            const droop = 0.12 + rand() * 0.06;
            // lay flat (width along z), fold the leaflets into a V, droop along the length
            g.rotateX(Math.PI / 2);
            const p = g.attributes.position;
            for (let j = 0; j < p.count; j++) {
                const x = p.getX(j);
                const zz = p.getZ(j);
                p.setY(j, -Math.abs(zz) * 0.35 - droop * x * x + 0.35 * x * (i % 3 === 0 ? 0.9 : 0.4));
            }
            g.computeVertexNormals();
            const elev = (i % 3 === 0 ? 0.15 : -0.05) + (rand() - 0.5) * 0.15;
            g.rotateZ(elev);
            g.rotateY((i / nf) * Math.PI * 2 + rand() * 0.3);
            g.translate(top.x, top.y, top.z);
            fronds.push(g);
        }
        const nuts = [];
        for (let i = 0; i < 6; i++) {
            const s = new THREE.SphereGeometry(0.13, 8, 6);
            const a = (i / 6) * Math.PI * 2;
            s.translate(top.x + Math.cos(a) * 0.22, top.y - 0.25, top.z + Math.sin(a) * 0.22);
            nuts.push(s);
        }
        return [
            { geo: tg, mat: m.palmBark },
            { geo: mergeGeometries(fronds), mat: m.frond },
            { geo: mergeGeometries(nuts), mat: m.coconut },
        ];
    }
    if (kind === 'shrub' || kind === 'shrubFlower') {
        const g = crown(0, 0.55, 0, 0.75, 0.55, 0.75, 34, 0.75);
        return [{ geo: g, mat: kind === 'shrub' ? m.leafB : m.leafFlower }];
    }
    const big = kind === 'shade';
    const h = big ? 4.2 : 2.6;
    const t = trunk(h, big ? 0.2 : 0.11, big ? 0.1 : 0.06, 0.5);
    const parts = [t.geo];
    // a few branches into the crown
    for (let i = 0; i < (big ? 4 : 3); i++) {
        const a = rand() * Math.PI * 2;
        const b = new THREE.CylinderGeometry(0.035, 0.07, big ? 2.2 : 1.4, 5);
        b.translate(0, (big ? 1.1 : 0.7), 0);
        b.rotateZ(0.7);
        b.rotateY(a);
        b.translate(t.top.x, t.top.y - 0.6, t.top.z);
        parts.push(b);
    }
    const trunkGeo = mergeGeometries(parts.map((g) => { const x = g.index ? g : g; for (const k of Object.keys(x.attributes)) if (!['position', 'normal', 'uv'].includes(k)) x.deleteAttribute(k); return x; }));
    const cy = t.top.y + (big ? 1.6 : 1.0);
    const leaves = big
        ? mergeGeometries([
            crown(t.top.x, cy, t.top.z, 3.2, 1.7, 3.2, 150, 1.25),
            crown(t.top.x + 1.2, cy + 0.6, t.top.z - 0.6, 1.8, 1.2, 1.8, 50, 1.1),
            crown(t.top.x - 1.0, cy + 0.3, t.top.z + 1.1, 1.8, 1.2, 1.8, 50, 1.1),
        ])
        : crown(t.top.x, cy, t.top.z, 1.6, 1.3, 1.6, 80, 0.95);
    return [
        { geo: trunkGeo, mat: m.bark },
        { geo: leaves, mat: kind === 'flower' ? m.leafFlower : (big ? m.leafA : m.leafB) },
    ];
}

const SPECIES = {};

/**
 * Plant a set of trees of one species: positions [{x, z, y?, s?, r?}].
 * Returns the InstancedMeshes (added to parent).
 */
export function plant(parent, kind, spots, { cast = true } = {}) {
    if (!spots.length) return [];
    if (!SPECIES[kind]) SPECIES[kind] = buildSpecies(kind);
    const out = [];
    const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3(), p = new THREE.Vector3();
    for (const part of SPECIES[kind]) {
        const im = new THREE.InstancedMesh(part.geo, part.mat, spots.length);
        spots.forEach((sp, i) => {
            const sc = sp.s ?? (0.8 + rand() * 0.45);
            q.setFromAxisAngle(new THREE.Vector3(0, 1, 0), sp.r ?? rand() * Math.PI * 2);
            m4.compose(p.set(sp.x, sp.y ?? 0, sp.z), q, s.set(sc, sc * (sp.sy ?? 1), sc));
            im.setMatrixAt(i, m4);
        });
        im.castShadow = cast;
        im.receiveShadow = true;
        im.computeBoundingSphere();
        parent.add(im);
        out.push(im);
    }
    return out;
}

/** Clipped hedge along a straight line. */
export function hedge(batch, x0, z0, x1, z1, h = 1.0, w = 0.8) {
    const m = mats();
    const len = Math.hypot(x1 - x0, z1 - z0);
    const g = new THREE.BoxGeometry(len, h, w);
    const uv = g.attributes.uv;
    for (let i = 0; i < uv.count; i++) uv.setXY(i, uv.getX(i) * len / 1.5, uv.getY(i) * h / 1.5);
    const ry = -Math.atan2(z1 - z0, x1 - x0);
    batch.add(g, m.hedge, (x0 + x1) / 2, h / 2, (z0 + z1) / 2, ry);
}

export function hedgeMaterial() { return mats().hedge; }
