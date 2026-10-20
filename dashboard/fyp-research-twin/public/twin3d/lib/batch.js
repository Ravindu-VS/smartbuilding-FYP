// ═══════════════════════════════════════════════════════════════
// batch.js — merge many small static meshes into one mesh per material
// ═══════════════════════════════════════════════════════════════
// Furniture, facades and site details are made of thousands of boxes and
// cylinders. Drawing each one separately would cost thousands of draw calls, so
// static parts are collected here and merged per material (a room's furniture
// ends up as ~10 meshes). Dynamic parts (lights, people, units) stay separate.

import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';

// Plain-coloured materials are folded into a few shared vertex-colour materials (by
// roughness/metalness), so a room full of differently coloured furniture costs only a
// handful of draw calls. Textured fabrics share one neutral weave texture.
const VC = new Map();
let weave = null;
function weaveTexture() {
    if (weave) return weave;
    const c = document.createElement('canvas');
    c.width = c.height = 128;
    const ctx = c.getContext('2d');
    ctx.fillStyle = '#f2f2f2'; ctx.fillRect(0, 0, 128, 128);
    for (let y = 0; y < 128; y += 2) { ctx.fillStyle = `rgba(0,0,0,${0.05 + Math.random() * 0.05})`; ctx.fillRect(0, y, 128, 1); }
    for (let x = 0; x < 128; x += 2) { ctx.fillStyle = `rgba(255,255,255,${0.03 + Math.random() * 0.04})`; ctx.fillRect(x, 0, 1, 128); }
    weave = new THREE.CanvasTexture(c);
    weave.colorSpace = THREE.SRGBColorSpace;
    weave.wrapS = weave.wrapT = THREE.RepeatWrapping;
    return weave;
}
function vcFor(mat) {
    if (!mat || !mat.isMeshStandardMaterial || mat.isMeshPhysicalMaterial || mat.transparent || mat.userData.noVC) return null;
    if (mat.clippingPlanes || mat.side !== THREE.FrontSide || mat.alphaTest > 0) return null;
    if (mat.emissive && mat.emissive.getHex() !== 0) return null;
    const fabric = mat.userData.vc === 'fabric';
    if (mat.map && !fabric) return null;
    const r = Math.round(mat.roughness * 4) / 4, m = Math.round(mat.metalness * 2) / 2;
    const key = `${fabric ? 'f' : 's'}_${r}_${m}`;
    if (!VC.has(key)) VC.set(key, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: r, metalness: m, map: fabric ? weaveTexture() : null }));
    return { mat: VC.get(key), color: fabric ? mat.userData.vcColor : mat.color };
}

const _m = new THREE.Matrix4();
const _q = new THREE.Quaternion();
const _e = new THREE.Euler();
const _s = new THREE.Vector3();
const _p = new THREE.Vector3();

function normalise(g) {
    // every merged geometry needs the same attributes: position, normal, uv; indexed
    let geo = g;
    if (!geo.index) {
        const n = geo.attributes.position.count;
        const idx = new Array(n);
        for (let i = 0; i < n; i++) idx[i] = i;
        geo.setIndex(idx);
    }
    if (!geo.attributes.normal) geo.computeVertexNormals();
    if (!geo.attributes.uv) {
        geo.setAttribute('uv', new THREE.BufferAttribute(new Float32Array(geo.attributes.position.count * 2), 2));
    }
    for (const k of Object.keys(geo.attributes)) {
        if (k !== 'position' && k !== 'normal' && k !== 'uv' && k !== 'color') geo.deleteAttribute(k);
    }
    geo.morphAttributes = {};
    return geo;
}

export class Batch {
    constructor() {
        this.groups = new Map();   // material -> geometries[]
        this.stack = [new THREE.Matrix4()];
    }

    /** Push a local transform (position, rotation y, scale) for nested furniture. */
    push(x = 0, y = 0, z = 0, ry = 0, rx = 0, rz = 0) {
        _e.set(rx, ry, rz);
        _q.setFromEuler(_e);
        _m.compose(_p.set(x, y, z), _q, _s.set(1, 1, 1));
        const top = this.stack[this.stack.length - 1].clone().multiply(_m);
        this.stack.push(top);
        return this;
    }

    pop() { if (this.stack.length > 1) this.stack.pop(); return this; }

    /** Add a geometry (owned by the batch) with material and a local transform. */
    add(geo, mat, x = 0, y = 0, z = 0, ry = 0, rx = 0, rz = 0, sx = 1, sy = 1, sz = 1) {
        _e.set(rx, ry, rz);
        _q.setFromEuler(_e);
        _m.compose(_p.set(x, y, z), _q, _s.set(sx, sy, sz));
        const world = this.stack[this.stack.length - 1].clone().multiply(_m);
        const g = normalise(geo).clone();
        g.applyMatrix4(world);
        const vc = vcFor(mat);
        let target = mat;
        if (vc) {
            target = vc.mat;
            const n = g.attributes.position.count, arr = new Float32Array(n * 3);
            for (let i = 0; i < n; i++) { arr[i * 3] = vc.color.r; arr[i * 3 + 1] = vc.color.g; arr[i * 3 + 2] = vc.color.b; }
            g.setAttribute('color', new THREE.BufferAttribute(arr, 3));
        } else if (g.attributes.color) g.deleteAttribute('color');
        if (!this.groups.has(target)) this.groups.set(target, []);
        this.groups.get(target).push(g);
        return this;
    }

    box(w, h, d, mat, x, y, z, ry = 0) {
        return this.add(new THREE.BoxGeometry(w, h, d), mat, x, y, z, ry);
    }

    /** Box whose base sits at y (convenient for furniture). */
    block(w, h, d, mat, x, y, z, ry = 0) {
        return this.add(new THREE.BoxGeometry(w, h, d), mat, x, y + h / 2, z, ry);
    }

    cyl(rt, rb, h, mat, x, y, z, seg = 14, rx = 0, rz = 0) {
        return this.add(new THREE.CylinderGeometry(rt, rb, h, seg), mat, x, y, z, 0, rx, rz);
    }

    sphere(r, mat, x, y, z, sx = 1, sy = 1, sz = 1, seg = 12) {
        return this.add(new THREE.SphereGeometry(r, seg, Math.max(6, seg * 0.6 | 0)), mat, x, y, z, 0, 0, 0, sx, sy, sz);
    }

    /** Merge into meshes and add them to `parent`. Returns the created meshes. */
    build(parent, { cast = true, receive = true, name = 'batch' } = {}) {
        const out = [];
        for (const [mat, list] of this.groups) {
            if (!list.length) continue;
            const merged = mergeGeometries(list, false);
            list.forEach((g) => g.dispose());
            if (!merged) continue;
            merged.computeBoundingSphere();
            const mesh = new THREE.Mesh(merged, mat);
            mesh.name = name;
            const transparent = mat.transparent;
            mesh.castShadow = cast && !transparent;
            mesh.receiveShadow = receive;
            mesh.matrixAutoUpdate = false;
            mesh.updateMatrix();
            parent.add(mesh);
            out.push(mesh);
        }
        this.groups.clear();
        return out;
    }
}
