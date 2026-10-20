// ═══════════════════════════════════════════════════════════════
// interiors.js — walls, doors, finishes, ceilings, lights and furniture
// ═══════════════════════════════════════════════════════════════
// Built from the room rectangles in the building configuration. Internal walls are
// found where two rooms share an edge; a door is placed where people would walk
// (into corridors and lobbies, within an apartment, between the wellness rooms),
// and every room gets at least one door. Each room has its own lighting material
// (driven by the controller's light level), its own screens (on when occupied),
// its HVAC equipment and its people spots.

import * as THREE from 'three';
import { RectAreaLightUniformsLib } from 'three/addons/lights/RectAreaLightUniformsLib.js';
import { M, T, rep, rand, seedRand } from '../lib/materials.js';
import { Batch } from '../lib/batch.js';
import { GEO, FL, CL, roomBox } from './building.js';
import { furnish } from './furniture.js';
import { plant } from './vegetation.js';
import { RoomHVAC } from './hvac.js';

const WALL_T = 0.12;
const CONNECT = new Set(['corridor', 'lobby']);
const isBed = (r) => /bed|master/i.test(r.room_id + r.name);
const aptKey = (r) => (r.room_id.match(/apt\d/) || [null])[0];

function poolTexture() {
    const c = document.createElement('canvas');
    c.width = c.height = 128;
    const ctx = c.getContext('2d');
    const g = ctx.createRadialGradient(64, 64, 2, 64, 64, 64);
    g.addColorStop(0, 'rgba(255,236,205,1)');
    g.addColorStop(0.55, 'rgba(255,226,185,0.4)');
    g.addColorStop(1, 'rgba(255,220,170,0)');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, 128, 128);
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    return t;
}

function ceilingTexture() {
    const c = document.createElement('canvas');
    c.width = c.height = 256;
    const ctx = c.getContext('2d');
    ctx.fillStyle = '#f3f2ef';
    ctx.fillRect(0, 0, 256, 256);
    ctx.strokeStyle = '#d4d2cc';
    ctx.lineWidth = 3;
    ctx.strokeRect(0, 0, 256, 256);
    for (let i = 0; i < 1500; i++) { ctx.fillStyle = `rgba(0,0,0,${Math.random() * 0.04})`; ctx.fillRect(Math.random() * 256, Math.random() * 256, 2, 2); }
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    return t;
}

export class Interiors {
    constructor(app, building) {
        this.app = app;
        this.building = building;
        this.rooms = new Map();
        this.floors = [];
        this.clip = new THREE.Plane(new THREE.Vector3(0, -1, 0), 1e6);
        RectAreaLightUniformsLib.init();
        const cp = [this.clip];
        this.mat = {
            wall: new THREE.MeshStandardMaterial({ color: 0xf2efe9, map: T.plaster(), roughness: 0.92, clippingPlanes: cp, clipShadows: true }),
            wallTile: new THREE.MeshStandardMaterial({ color: 0xffffff, map: rep(T.tiles('#e9ebea', '#c9cccb', 6), 1, 1, 1.2), roughness: 0.35, clippingPlanes: cp, clipShadows: true }),
            skirt: new THREE.MeshStandardMaterial({ color: 0x3a3c40, roughness: 0.6, clippingPlanes: cp }),
            frame: new THREE.MeshStandardMaterial({ color: 0x2b2e33, roughness: 0.35, metalness: 0.7, clippingPlanes: cp }),
            door: new THREE.MeshStandardMaterial({ color: 0xffffff, map: rep(T.woodFloor('oak'), 1, 1, 1.2), roughness: 0.5, clippingPlanes: cp }),
            glass: new THREE.MeshStandardMaterial({ color: 0xdbe9ee, roughness: 0.05, metalness: 0.1, transparent: true, opacity: 0.2, depthWrite: false, side: THREE.DoubleSide, clippingPlanes: cp }),
            frost: new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.5, transparent: true, opacity: 0.72, side: THREE.DoubleSide, clippingPlanes: cp }),
            ceiling: new THREE.MeshStandardMaterial({ color: 0xffffff, map: rep(ceilingTexture(), 1, 1, 0.6), roughness: 0.9 }),
            ceilingPlain: new THREE.MeshStandardMaterial({ color: 0xf6f4f0, roughness: 0.95 }),
            led: new THREE.MeshStandardMaterial({ color: 0x111111, emissive: 0xff3b3b, emissiveIntensity: 1.2 }),
        };
        this.poolTex = poolTexture();
        this.ledMats = [
            new THREE.MeshStandardMaterial({ color: 0x0a0a0a, emissive: 0x22c55e, emissiveIntensity: 2 }),
            new THREE.MeshStandardMaterial({ color: 0x0a0a0a, emissive: 0x38bdf8, emissiveIntensity: 2 }),
        ];
        this.focus = null;
    }

    /** Build every floor; yields between rooms so the page stays responsive. */
    async buildAll(onProgress) {
        const cfgRooms = this.building.rooms;
        let done = 0;
        for (const fl of this.building.floors) {
            const f = fl.f;
            const rooms = cfgRooms.filter((r) => r.floor_id === f);
            const floor = { f, rooms: [], walls: new THREE.Group(), segs: [] };
            floor.walls.name = `walls_${f}`;
            fl.interior.add(floor.walls);
            this.floors[f] = floor;
            floor.segs = this._segments(rooms);
            this._buildWalls(floor);
            for (const r of rooms) {
                seedRand(1000 + r.room_id.split('').reduce((a, c) => a * 31 + c.charCodeAt(0), 7));
                const rec = this._buildRoom(r, floor, fl.interior);
                floor.rooms.push(rec);
                this.rooms.set(r.room_id, rec);
                done++;
                if (onProgress) onProgress(done / cfgRooms.length);
                await new Promise((res) => setTimeout(res, 0));
            }
        }
    }

    // ------------------------------------------------------------ walls
    _segments(rooms) {
        const segs = [];
        for (let i = 0; i < rooms.length; i++) for (let j = i + 1; j < rooms.length; j++) {
            const A = rooms[i], B = rooms[j];
            const eps = 1e-6;
            // vertical (constant plan x)
            for (const [P, Q] of [[A, B], [B, A]]) {
                if (Math.abs(P.x + P.w - Q.x) < eps) {
                    const a = Math.max(P.z, Q.z), b = Math.min(P.z + P.d, Q.z + Q.d);
                    if (b - a > 0.05) segs.push({ axis: 'z', at: P.x + P.w, a, b, rooms: [P, Q] });
                }
                if (Math.abs(P.z + P.d - Q.z) < eps) {
                    const a = Math.max(P.x, Q.x), b = Math.min(P.x + P.w, Q.x + Q.w);
                    if (b - a > 0.05) segs.push({ axis: 'x', at: P.z + P.d, a, b, rooms: [P, Q] });
                }
            }
        }
        const floorHasConnector = rooms.some((r) => CONNECT.has(r.type));
        const resi = rooms.every((r) => ['residential', 'bathroom', 'corridor', 'lobby'].includes(r.type));
        for (const s of segs) {
            const [A, B] = s.rooms;
            let door = false;
            if (CONNECT.has(A.type) || CONNECT.has(B.type)) {
                const other = CONNECT.has(A.type) ? B : A;
                door = !(CONNECT.has(A.type) && CONNECT.has(B.type)) ? !(isBed(other) || (other.type === 'bathroom' && resi)) : true;
            } else if (aptKey(A) && aptKey(A) === aptKey(B)) door = true;
            else if (!floorHasConnector) door = true;
            else if (resi && !aptKey(A) && !aptKey(B)) door = true;
            s.door = door;
        }
        // every room gets at least one door
        for (const r of rooms) {
            const mine = segs.filter((s) => s.rooms.includes(r));
            if (mine.length && !mine.some((s) => s.door)) mine.sort((p, q) => (q.b - q.a) - (p.b - p.a))[0].door = true;
        }
        for (const s of segs) {
            const len = s.b - s.a;
            const [A, B] = s.rooms;
            const wide = (CONNECT.has(A.type) || CONNECT.has(B.type)) && len > 6;
            s.doorW = wide ? 1.8 : 1.0;
            s.doorAt = len > 5 ? s.a + Math.min(len - 1.4, Math.max(1.4, len * 0.3)) : (s.a + s.b) / 2;
            const glassy = (t) => ['office', 'meeting', 'executive'].includes(t);
            s.kind = (glassy(A.type) && (glassy(B.type) || B.type === 'corridor')) || (glassy(B.type) && A.type === 'corridor') ? 'glass' : 'solid';
            s.tiled = A.type === 'bathroom' || B.type === 'bathroom';
        }
        return segs;
    }

    /** Draw one wall segment into a batch (local y from 0 = floor level). mats override for per-wall clipping. */
    _wallInto(b, s, mats = this.mat) {
        const H = GEO.CEIL;
        // plan -> world: along axis 'x' means the wall runs east-west at plan z = at
        const toWorld = (u) => (s.axis === 'x' ? { x: u - GEO.W / 2, z: GEO.D / 2 - s.at } : { x: s.at - GEO.W / 2, z: GEO.D / 2 - u });
        const ry = s.axis === 'x' ? 0 : Math.PI / 2;
        const piece = (u0, u1, y0, y1, mat, thick = WALL_T) => {
            if (u1 - u0 < 0.01 || y1 - y0 < 0.01) return;
            const c = toWorld((u0 + u1) / 2);
            b.add(new THREE.BoxGeometry(u1 - u0, y1 - y0, thick), mat, c.x, (y0 + y1) / 2, c.z, ry);
        };
        const d0 = s.door ? s.doorAt - s.doorW / 2 : null, d1 = s.door ? s.doorAt + s.doorW / 2 : null;
        const spans = s.door ? [[s.a, d0], [d1, s.b]] : [[s.a, s.b]];
        if (s.kind === 'glass') {
            for (const [u0, u1] of spans) {
                piece(u0, u1, 0, 0.1, mats.skirt, WALL_T);
                piece(u0, u1, 0.1, H - 0.08, mats.glass, 0.02);
                piece(u0, u1, 1.0, 1.35, mats.frost, 0.025);
                piece(u0, u1, H - 0.08, H, mats.frame, 0.1);
                const n = Math.max(1, Math.round((u1 - u0) / 1.2));
                for (let i = 0; i <= n; i++) {
                    const u = u0 + (i * (u1 - u0)) / n;
                    piece(u - 0.025, u + 0.025, 0.1, H - 0.08, mats.frame, 0.08);
                }
            }
        } else {
            const wm = s.tiled ? mats.wallTile : mats.wall;
            for (const [u0, u1] of spans) {
                piece(u0, u1, 0, H, wm);
                piece(u0, u1, 0, 0.09, mats.skirt, WALL_T + 0.02);
            }
        }
        if (s.door) {
            piece(d0, d1, 2.2, H, s.kind === 'glass' ? mats.frame : (s.tiled ? mats.wallTile : mats.wall));
            // frame
            piece(d0 - 0.05, d0, 0, 2.2, mats.frame, WALL_T + 0.03);
            piece(d1, d1 + 0.05, 0, 2.2, mats.frame, WALL_T + 0.03);
            piece(d0, d1, 2.15, 2.2, mats.frame, WALL_T + 0.03);
            // door leaf, open at ~75 degrees into the room on the "first" side
            const leafW = s.doorW > 1.2 ? s.doorW / 2 : s.doorW - 0.05;
            const hinge = toWorld(d0 + 0.03);
            const open = -1.3;
            const leafMat = s.kind === 'glass' ? mats.glass : mats.door;
            const leaf = new THREE.BoxGeometry(leafW, 2.12, 0.045);
            leaf.translate(leafW / 2, 1.06, 0);
            b.add(leaf, leafMat, hinge.x, 0.0, hinge.z, ry + open);
            if (s.doorW > 1.2) {
                const h2 = toWorld(d1 - 0.03);
                const leaf2 = new THREE.BoxGeometry(leafW, 2.12, 0.045);
                leaf2.translate(-leafW / 2, 1.06, 0);
                b.add(leaf2, leafMat, h2.x, 0.0, h2.z, ry - open);
            }
        }
    }

    _buildWalls(floor) {
        const b = new Batch();
        for (const s of floor.segs) this._wallInto(b, s);
        const g = new THREE.Group();
        g.position.y = FL(floor.f);
        b.build(g, { name: `walls_${floor.f}` });
        floor.walls.add(g);
        floor.wallsInner = g;
    }

    // ------------------------------------------------------------ rooms
    _edges(r) {
        // the room's four edges: exterior (on the facade) or internal, with inward normals (world)
        const bx = roomBox(r);
        const W = GEO.W, D = GEO.D;
        return [
            { side: 'S', ext: Math.abs(r.z) < 1e-6, mid: { x: bx.cx, z: bx.z1 }, n: { x: 0, z: -1 }, len: r.w, axis: 'x', at: r.z, a: r.x, b: r.x + r.w },
            { side: 'N', ext: Math.abs(r.z + r.d - D) < 1e-6, mid: { x: bx.cx, z: bx.z0 }, n: { x: 0, z: 1 }, len: r.w, axis: 'x', at: r.z + r.d, a: r.x, b: r.x + r.w },
            { side: 'W', ext: Math.abs(r.x) < 1e-6, mid: { x: bx.x0, z: bx.cz }, n: { x: 1, z: 0 }, len: r.d, axis: 'z', at: r.x, a: r.z, b: r.z + r.d },
            { side: 'E', ext: Math.abs(r.x + r.w - W) < 1e-6, mid: { x: bx.x1, z: bx.cz }, n: { x: -1, z: 0 }, len: r.d, axis: 'z', at: r.x + r.w, a: r.z, b: r.z + r.d },
        ];
    }

    _buildRoom(r, floor, parent) {
        const f = r.floor_id;
        const box = roomBox(r);
        const fl = FL(f), cl = CL(f);
        const group = new THREE.Group();
        group.name = `room_${r.room_id}`;
        parent.add(group);
        const rec = { id: r.room_id, cfg: r, f, box, fl, cl, group, doors: [], spots: [] };

        // floor finish
        const floorMesh = new THREE.Mesh(new THREE.PlaneGeometry(box.w - 0.02, box.d - 0.02), M.floor(r.type, box.w, box.d));
        floorMesh.rotation.x = -Math.PI / 2;
        floorMesh.position.set(box.cx, fl + 0.004, box.cz);
        floorMesh.receiveShadow = true;
        group.add(floorMesh);

        // doors of this room (for people walking in/out), in room-local coordinates
        for (const s of floor.segs) {
            if (!s.door || !s.rooms.includes(r)) continue;
            const u = s.doorAt;
            const inward = 0.7;
            if (s.axis === 'x') {
                const wz = GEO.D / 2 - s.at, wx = u - GEO.W / 2;
                const dir = Math.sign(box.cz - wz);
                rec.doors.push({ x: wx - box.cx, z: wz + dir * inward - box.cz, seg: s });
            } else {
                const wx = s.at - GEO.W / 2, wz = GEO.D / 2 - u;
                const dir = Math.sign(box.cx - wx);
                rec.doors.push({ x: wx + dir * inward - box.cx, z: wz - box.cz, seg: s });
            }
        }
        // street entrances
        if (r.type === 'lobby' && f === 0) rec.doors.push({ x: (7.75 - GEO.W / 2) - box.cx, z: box.d / 2 - 0.8, street: true });
        if (/cafe/.test(r.room_id)) rec.doors.push({ x: 0, z: box.d / 2 - 0.8, street: true });

        // furniture
        const screenMat = new THREE.MeshStandardMaterial({ color: 0x0b1020, emissive: 0x9cc7ff, emissiveIntensity: 0.05, roughness: 0.3 });
        rec.screenMat = screenMat;
        const b = new Batch();
        b.push(box.cx, fl, box.cz);
        const ctx = {
            b, w: box.w, d: box.d, room: r, plants: [], ox: box.cx, oy: fl, oz: box.cz, screenMat,
            ledMat: this.ledMats[(rand() * 2) | 0],
            ext: Object.fromEntries(this._edges(r).map((e) => [e.side, e.ext])),
        };
        rec.spots = furnish(ctx);
        b.pop();
        const furniture = new THREE.Group();
        furniture.name = 'furniture';
        b.build(furniture, { name: `furniture_${r.room_id}` });
        group.add(furniture);
        rec.furniture = furniture;
        const byKind = {};
        for (const p of ctx.plants) (byKind[p.kind] = byKind[p.kind] || []).push(p);
        for (const [kind, list] of Object.entries(byKind)) plant(furniture, kind, list);

        // ceiling + light fixtures (faces down: invisible from above, so cutaways need no extra work)
        const ceiling = new THREE.Group();
        ceiling.name = 'ceiling';
        const commercial = !['residential'].includes(r.type);
        const cm = commercial ? this.mat.ceiling.clone() : this.mat.ceilingPlain;
        if (commercial) { cm.map = rep(this.mat.ceiling.map, box.w, box.d, 0.6); }
        const cp = new THREE.Mesh(new THREE.PlaneGeometry(box.w - 0.02, box.d - 0.02), cm);
        cp.rotation.x = Math.PI / 2;
        cp.position.set(box.cx, cl, box.cz);
        cp.receiveShadow = true;
        ceiling.add(cp);
        const lightMat = new THREE.MeshStandardMaterial({ color: 0xf4f4f2, emissive: 0xfff3df, emissiveIntensity: 0, roughness: 0.4 });
        rec.lightMat = lightMat;
        const lb = new Batch();
        const fixtures = [];
        const residential = r.type === 'residential';
        const spacing = residential ? 1.8 : (r.type === 'corridor' ? 2.4 : 2.4);
        const nx = Math.max(1, Math.round(box.w / spacing)), nz = Math.max(1, Math.round(box.d / spacing));
        for (let i = 0; i < nx; i++) for (let j = 0; j < nz; j++) {
            const x = box.x0 + (i + 0.5) * box.w / nx, z = box.z0 + (j + 0.5) * box.d / nz;
            fixtures.push({ x, z });
            if (residential || r.type === 'bathroom') lb.add(new THREE.CircleGeometry(0.08, 16), lightMat, x, cl - 0.006, z, 0, Math.PI / 2);
            else if (r.type === 'lobby' && f === 0) lb.add(new THREE.RingGeometry(0.45, 0.55, 32), lightMat, x, cl - 0.006, z, 0, Math.PI / 2);
            else lb.add(new THREE.PlaneGeometry(0.6, 1.2), lightMat, x, cl - 0.006, z, 0, Math.PI / 2);
        }
        lb.build(ceiling, { name: 'lights', cast: false, receive: false });
        ceiling.traverse((o) => { if (o.isMesh) o.castShadow = false; });
        group.add(ceiling);
        rec.ceiling = ceiling;
        rec.fixtures = fixtures;

        // light pools on the floor (visible mostly at night and from outside)
        const pb = [];
        const nPool = Math.min(fixtures.length, 9);
        const step = fixtures.length / nPool;
        for (let k = 0; k < nPool; k++) {
            const fx = fixtures[Math.floor(k * step)];
            const g = new THREE.PlaneGeometry(Math.min(5, box.w / Math.max(1, Math.sqrt(nPool)) * 1.5), Math.min(5, box.d / Math.max(1, Math.sqrt(nPool)) * 1.5));
            g.rotateX(-Math.PI / 2);
            g.translate(fx.x, fl + 0.02, fx.z);
            pb.push(g);
        }
        const poolMat = new THREE.MeshBasicMaterial({ map: this.poolTex, color: 0xffe2b0, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false });
        const pools = new THREE.Mesh(mergeAll(pb), poolMat);
        pools.renderOrder = 2;
        pools.visible = false;
        group.add(pools);
        rec.pools = pools;

        // HVAC equipment and airflow
        const edges = this._edges(r);
        const internal = edges.filter((e) => !e.ext);
        const doorSegs = rec.doors.filter((d) => d.seg);
        const wallFor = (thermo) => {
            let e;
            if (thermo && doorSegs.length) {
                const seg = doorSegs[0].seg;
                e = internal.find((ed) => ed.axis === seg.axis && Math.abs(ed.at - seg.at) < 1e-6) || internal[0];
                const u = Math.min(e.b - 0.4, Math.max(e.a + 0.4, seg.doorAt + seg.doorW / 2 + 0.6));
                const pt = e.axis === 'x' ? { x: u - GEO.W / 2, z: GEO.D / 2 - e.at } : { x: e.at - GEO.W / 2, z: GEO.D / 2 - u };
                return { x: pt.x + e.n.x * WALL_T / 2, z: pt.z + e.n.z * WALL_T / 2, ry: Math.atan2(e.n.x, e.n.z) };
            }
            const exterior = edges.filter((ed) => ed.ext).map((ed) => ed.side);
            const opposite = { S: 'N', N: 'S', E: 'W', W: 'E' };
            e = internal.find((ed) => exterior.some((x) => opposite[x] === ed.side)) || internal.sort((p, q) => q.len - p.len)[0] || edges[1];
            let u = (e.a + e.b) / 2;
            // keep clear of a door on this edge
            const sd = doorSegs.find((d) => d.seg.axis === e.axis && Math.abs(d.seg.at - e.at) < 1e-6);
            if (sd && Math.abs(sd.seg.doorAt - u) < 1.4) u = sd.seg.doorAt + (u > sd.seg.doorAt ? 1.5 : -1.5);
            u = Math.min(e.b - 0.6, Math.max(e.a + 0.6, u));
            const pt = e.axis === 'x' ? { x: u - GEO.W / 2, z: GEO.D / 2 - e.at } : { x: e.at - GEO.W / 2, z: GEO.D / 2 - u };
            const off = e.ext ? 0.3 : WALL_T / 2;
            return { x: pt.x + e.n.x * off, z: pt.z + e.n.z * off, ry: Math.atan2(e.n.x, e.n.z) };
        };
        const live = r.data_source === 'hardware';
        rec.live = live;
        rec.hvac = new RoomHVAC(r, { fl, cl, box, wallFor, live });
        group.add(rec.hvac.group, rec.hvac.flowGroup);

        // overlay tints: floor (floor/room views) and volume (building view)
        const tintMat = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.42, depthWrite: false });
        const tintFloor = new THREE.Mesh(new THREE.PlaneGeometry(box.w - 0.1, box.d - 0.1), tintMat);
        tintFloor.rotation.x = -Math.PI / 2;
        tintFloor.position.set(box.cx, fl + 0.03, box.cz);
        tintFloor.renderOrder = 4;
        tintFloor.visible = false;
        const volMat = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.2, depthWrite: false, side: THREE.DoubleSide });
        const tintVol = new THREE.Mesh(new THREE.BoxGeometry(box.w - 0.15, GEO.CEIL - 0.1, box.d - 0.15), volMat);
        tintVol.position.set(box.cx, fl + GEO.CEIL / 2, box.cz);
        tintVol.renderOrder = 4;
        tintVol.visible = false;
        group.add(tintFloor, tintVol);
        rec.tintFloor = tintFloor;
        rec.tintVol = tintVol;
        rec.edges = edges;
        rec.origin = { x: box.cx, y: fl, z: box.cz };
        return rec;
    }

    // ------------------------------------------------------------ views
    /** Floor view cuts every wall at a fixed height; building view shows full walls. */
    setCut(height, f = null) {
        this.clip.constant = height == null ? 1e6 : FL(f) + height;
    }

    /** Room view: walls of the focused room as separate meshes, each cut when it faces the camera. */
    focusRoom(id) {
        this.unfocus();
        const rec = this.rooms.get(id);
        if (!rec) return;
        const floor = this.floors[rec.f];
        const walls = [];
        const group = new THREE.Group();
        group.position.y = rec.fl;
        for (const s of floor.segs) {
            if (!s.rooms.includes(rec.cfg)) continue;
            const plane = new THREE.Plane(new THREE.Vector3(0, -1, 0), 1e6);
            const cp = [plane];
            const mats = {};
            for (const [k, m] of Object.entries(this.mat)) { mats[k] = m.clone(); mats[k].clippingPlanes = cp; }
            const b = new Batch();
            this._wallInto(b, s, mats);
            const g = new THREE.Group();
            b.build(g, { name: 'focus_wall' });
            group.add(g);
            const wx = s.axis === 'x' ? (s.a + s.b) / 2 - GEO.W / 2 : s.at - GEO.W / 2;
            const wz = s.axis === 'x' ? GEO.D / 2 - s.at : GEO.D / 2 - (s.a + s.b) / 2;
            const n = { x: Math.sign(wx - rec.box.cx) * (s.axis === 'z' ? 1 : 0), z: Math.sign(wz - rec.box.cz) * (s.axis === 'x' ? 1 : 0) };
            walls.push({ plane, mats, g, c: { x: wx, z: wz }, n });
        }
        // the room's own windows (the floor's facade is hidden in room view)
        const bm = this.building.m;
        for (const e of rec.edges) {
            if (!e.ext) continue;
            const plane = new THREE.Plane(new THREE.Vector3(0, -1, 0), 1e6);
            const cp = [plane];
            const mats = {
                glass: bm.glass.clone(), frosted: bm.frosted.clone(), frame: bm.frame.clone(), spandrel: bm.spandrel.clone(),
            };
            for (const m of Object.values(mats)) m.clippingPlanes = cp;
            const b = new Batch();
            const H = GEO.CEIL;
            const ry = e.axis === 'x' ? 0 : Math.PI / 2;
            const toW = (u) => (e.axis === 'x' ? { x: u - GEO.W / 2, z: GEO.D / 2 - e.at } : { x: e.at - GEO.W / 2, z: GEO.D / 2 - u });
            const c = toW((e.a + e.b) / 2);
            b.add(new THREE.PlaneGeometry(e.len, H), rec.cfg.type === 'bathroom' ? mats.frosted : mats.glass, c.x, H / 2, c.z, ry);
            const n = Math.max(1, Math.round(e.len / (rec.f === 0 ? 3 : 1.5)));
            for (let i = 0; i <= n; i++) {
                const p = toW(e.a + (i * e.len) / n);
                b.add(new THREE.BoxGeometry(0.06, H, 0.12), mats.frame, p.x, H / 2, p.z, ry);
            }
            b.add(new THREE.BoxGeometry(e.len, 0.08, 0.14), mats.frame, c.x, 0.04, c.z, ry);
            b.add(new THREE.BoxGeometry(e.len, 0.1, 0.14), mats.frame, c.x, H - 0.05, c.z, ry);
            b.add(new THREE.BoxGeometry(e.len, 0.6, 0.08), mats.spandrel, c.x, H + 0.3, c.z, ry);
            const g = new THREE.Group();
            b.build(g, { name: 'focus_window' });
            g.traverse((o) => { if (o.isMesh && o.material.transparent) { o.castShadow = false; o.renderOrder = 5; } });
            group.add(g);
            walls.push({ plane, mats, g, c: { x: c.x, z: c.z }, n: { x: -e.n.x, z: -e.n.z }, ext: true });
        }
        // the floor plate under the room, and a see-through "ghost" ceiling that the AC units hang from
        const slab = new THREE.Mesh(new THREE.BoxGeometry(GEO.W, GEO.SLAB, GEO.D), M.std(0xd8d4cc, 0.85));
        slab.position.y = -GEO.SLAB / 2 - 0.002;
        slab.receiveShadow = true; slab.castShadow = true;
        group.add(slab);
        const edge = new THREE.Mesh(new THREE.BoxGeometry(GEO.W + 0.5, 0.5, GEO.D + 0.5), M.std(0xf3f1ec, 0.6));
        edge.position.y = -GEO.SLAB - 0.12;
        group.add(edge);
        const ghost = new THREE.Group();
        const gm = new THREE.Mesh(new THREE.PlaneGeometry(rec.box.w, rec.box.d), new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.085, depthWrite: false, side: THREE.DoubleSide }));
        gm.rotation.x = -Math.PI / 2;
        ghost.add(gm);
        const pts = [];
        for (let x = -rec.box.w / 2; x <= rec.box.w / 2 + 1e-3; x += 1.2) pts.push(x, 0, -rec.box.d / 2, x, 0, rec.box.d / 2);
        for (let z = -rec.box.d / 2; z <= rec.box.d / 2 + 1e-3; z += 1.2) pts.push(-rec.box.w / 2, 0, z, rec.box.w / 2, 0, z);
        const lg = new THREE.BufferGeometry();
        lg.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3));
        void lg;
        const ol = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints([
            new THREE.Vector3(-rec.box.w / 2, 0, -rec.box.d / 2), new THREE.Vector3(rec.box.w / 2, 0, -rec.box.d / 2),
            new THREE.Vector3(rec.box.w / 2, 0, rec.box.d / 2), new THREE.Vector3(-rec.box.w / 2, 0, rec.box.d / 2)]),
        new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.35, depthWrite: false }));
        ghost.add(ol);
        ghost.position.set(rec.box.cx, GEO.CEIL + 0.005, rec.box.cz);
        ghost.renderOrder = 7;
        group.add(ghost);
        this.app.scene.add(group);
        this.focus = { id, group, walls, rec, ghost };
    }

    unfocus() {
        if (!this.focus) return;
        this.focus.group.traverse((o) => { if (o.isMesh) o.geometry.dispose(); });
        for (const w of this.focus.walls) for (const m of Object.values(w.mats)) m.dispose();
        this.focus.group.removeFromParent();
        this.focus = null;
    }

    /** Per frame in room view: lower the walls between the camera and the room. */
    updateFocusCut(camPos, eyeLevel) {
        if (!this.focus) return;
        const fl = this.focus.rec.fl;
        this.focus.ghost.visible = !eyeLevel;
        for (const w of this.focus.walls) {
            const side = (camPos.x - w.c.x) * w.n.x + (camPos.z - w.c.z) * w.n.z;
            const target = eyeLevel ? GEO.CEIL + 1 : (side > 0.2 ? 0.95 : GEO.CEIL + 1);
            const cur = w.plane.constant - fl;
            const next = cur > 50 ? target : cur + (target - cur) * 0.2;
            w.plane.constant = fl + next;
        }
    }
}

function mergeAll(geos) {
    if (geos.length === 1) return geos[0];
    const pos = [], uv = [], idx = [];
    let off = 0;
    for (const g of geos) {
        const p = g.attributes.position.array, u = g.attributes.uv.array, ix = g.index.array;
        pos.push(...p); uv.push(...u);
        for (const i of ix) idx.push(i + off);
        off += g.attributes.position.count;
    }
    const out = new THREE.BufferGeometry();
    out.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    out.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
    out.setIndex(idx);
    return out;
}
