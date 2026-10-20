// ═══════════════════════════════════════════════════════════════
// building.js — the "Smart Hub": a modern five-storey mixed-use building
// ═══════════════════════════════════════════════════════════════
// The envelope is generated from the edge brain's building configuration: the
// 30 m x 20 m plate, 3.5 m floor-to-floor and each room's rectangle. Each room edge
// on the perimeter becomes a facade segment whose glazing suits the room behind it
// (frosted for restrooms, louvred metal for the server room, clear elsewhere).
//
// Architectural concept
//   * podium (ground): full-height shopfront glazing, stone plinth, cantilevered
//     entrance canopy with timber soffit over the lobby doors;
//   * work and wellness floors (L1-L2): curtain wall with angled bronze fins
//     (south/west sun control), horizontal blades on the north;
//   * residential floors (L3-L4): deep south balconies with glass balustrades and
//     planters, alternating glass and white panels to the west and north;
//   * east elevation: timber louvre screen and a stone-clad stair/lift core;
//   * roof: solar canopy (PV) over the west half and screened HVAC condensers whose
//     fans turn with the building's actual cooling load.

import * as THREE from 'three';
import { M, T, rep, rand } from '../lib/materials.js';
import { Batch } from '../lib/batch.js';
import { plant } from './vegetation.js';

export const GEO = {
    H: 3.5, SLAB: 0.3, CEIL: 2.85, W: 30, D: 20,
};

export const FL = (f) => f * GEO.H + GEO.SLAB;           // finished floor level
export const CL = (f) => FL(f) + GEO.CEIL;               // ceiling level
export const wx = (px) => px - GEO.W / 2;                // plan x (east) -> world x
export const wz = (pz) => GEO.D / 2 - pz;                // plan z (north) -> world z (south +)

export function roomBox(r) {
    // world rectangle of a room: x0..x1, z0..z1 (z0 < z1)
    return { x0: wx(r.x), x1: wx(r.x + r.w), z0: wz(r.z + r.d), z1: wz(r.z), cx: wx(r.x + r.w / 2), cz: wz(r.z + r.d / 2), w: r.w, d: r.d };
}

function signTexture(text) {
    const c = document.createElement('canvas');
    c.width = 1024; c.height = 160;
    const ctx = c.getContext('2d');
    ctx.fillStyle = '#1a1c1f';
    ctx.fillRect(0, 0, 1024, 160);
    ctx.fillStyle = '#f5f2ea';
    ctx.font = '600 92px "Segoe UI", Arial';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.letterSpacing = '18px';
    ctx.fillText(text, 512, 84);
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    t.anisotropy = 8;
    return t;
}

function pvTexture() {
    const c = document.createElement('canvas');
    c.width = 256; c.height = 384;
    const ctx = c.getContext('2d');
    ctx.fillStyle = '#c9ccd0';
    ctx.fillRect(0, 0, 256, 384);
    ctx.fillStyle = '#16233a';
    ctx.fillRect(6, 6, 244, 372);
    ctx.strokeStyle = 'rgba(160,180,210,0.35)';
    ctx.lineWidth = 1.5;
    for (let x = 6; x <= 250; x += 244 / 6) { ctx.beginPath(); ctx.moveTo(x, 6); ctx.lineTo(x, 378); ctx.stroke(); }
    for (let y = 6; y <= 378; y += 372 / 10) { ctx.beginPath(); ctx.moveTo(6, y); ctx.lineTo(250, y); ctx.stroke(); }
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    t.anisotropy = 8;
    return t;
}

function greenWallTexture() {
    const c = document.createElement('canvas');
    c.width = c.height = 512;
    const ctx = c.getContext('2d');
    ctx.fillStyle = '#2d4a22';
    ctx.fillRect(0, 0, 512, 512);
    const cols = ['#3f6b2a', '#4f7d32', '#5d8b3a', '#2f5220', '#6b9a44', '#8bb05a', '#a3c46a', '#c2417a'];
    for (let i = 0; i < 2600; i++) {
        ctx.fillStyle = cols[(rand() * (i % 40 === 0 ? 8 : 7)) | 0];
        const x = rand() * 512, y = rand() * 512, r = 3 + rand() * 7;
        ctx.beginPath(); ctx.ellipse(x, y, r, r * 0.6, rand() * 3, 0, 7); ctx.fill();
    }
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    return t;
}

export class Building {
    constructor(app, config) {
        this.app = app;
        this.config = config;
        this.group = new THREE.Group();
        this.group.name = 'building';
        app.scene.add(this.group);
        const b = config.building || {};
        GEO.W = b.width_m || 30;
        GEO.D = b.depth_m || 20;
        GEO.H = b.floor_height_m || 3.5;
        GEO.SLAB = b.slab_m ?? 0.3;
        this.nFloors = b.floors || (config.floors || []).length || 5;
        this.rooms = config.rooms || [];
        this.floors = [];
        this.hit = new Map();          // room_id -> invisible pick box
        this.roomGlass = new Map();    // room_id -> facade glass material (glows when the room's lights are on at night)
        this.fans = [];
        this._mats();
        for (let f = 0; f < this.nFloors; f++) this._floor(f);
        this._roof();
        this._entrance();
    }

    _mats() {
        const env = this.app.env;
        this.m = {
            glass: M.curtainGlass(),
            frosted: new THREE.MeshStandardMaterial({ color: 0xe9eef0, roughness: 0.55, transparent: true, opacity: 0.86, side: THREE.DoubleSide }),
            spandrel: new THREE.MeshStandardMaterial({ color: 0x2a3036, roughness: 0.18, metalness: 0.5, envMapIntensity: 1.6 }),
            frame: M.std(0x26292e, 0.35, 0.75),
            white: new THREE.MeshStandardMaterial({ color: 0xf4f2ee, roughness: 0.55 }),
            bronze: M.std(0x6e5a44, 0.35, 0.8),
            timber: new THREE.MeshStandardMaterial({ color: 0xffffff, map: T.timber(), roughness: 0.6 }),
            stone: new THREE.MeshStandardMaterial({ color: 0xffffff, map: rep(T.stone(), 1, 1, 3), roughness: 0.85 }),
            plinth: M.std(0x3b3d40, 0.6),
            metalLouvre: M.std(0x9aa0a6, 0.45, 0.7),
            balustrade: new THREE.MeshPhysicalMaterial({ color: 0xcfe3ea, roughness: 0.04, metalness: 0.1, transparent: true, opacity: 0.25, side: THREE.DoubleSide, depthWrite: false }),
            soffit: new THREE.MeshStandardMaterial({ color: 0xffffff, map: rep(T.timber(), 1, 1, 1.6), roughness: 0.6 }),
            led: new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xffd9a0, emissiveIntensity: 0, roughness: 0.4 }),
            down: new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xfff0d0, emissiveIntensity: 0, roughness: 0.3 }),
            green: new THREE.MeshStandardMaterial({ map: greenWallTexture(), roughness: 0.95 }),
            pv: new THREE.MeshStandardMaterial({ map: pvTexture(), roughness: 0.25, metalness: 0.4, envMapIntensity: 1.6 }),
            planter: M.std(0xe2ddd3, 0.7),
            soil: new THREE.MeshStandardMaterial({ map: T.soil(), roughness: 1 }),
            unit: M.std(0xdfe2e5, 0.5, 0.2),
            fan: M.std(0x2b2e33, 0.5, 0.3),
            slab: M.std(0xd8d4cc, 0.85),
        };
        env.registerEmissive(this.m.led, 0.0, 2.2);
        env.registerEmissive(this.m.down, 0.0, 4.0);
    }

    roomAt(f, px, pz) {
        return this.rooms.find((r) => r.floor_id === f && px >= r.x - 1e-6 && px <= r.x + r.w + 1e-6 && pz >= r.z - 1e-6 && pz <= r.z + r.d + 1e-6);
    }

    /** Perimeter segments of a floor: [{side, a, b, room}] with a, b along the side in plan metres. */
    _segments(f) {
        const segs = [];
        const rooms = this.rooms.filter((r) => r.floor_id === f);
        for (const r of rooms) {
            if (Math.abs(r.z) < 1e-6) segs.push({ side: 'S', a: r.x, b: r.x + r.w, room: r });
            if (Math.abs(r.z + r.d - GEO.D) < 1e-6) segs.push({ side: 'N', a: r.x, b: r.x + r.w, room: r });
            if (Math.abs(r.x) < 1e-6) segs.push({ side: 'W', a: r.z, b: r.z + r.d, room: r });
            if (Math.abs(r.x + r.w - GEO.W) < 1e-6) segs.push({ side: 'E', a: r.z, b: r.z + r.d, room: r });
        }
        return segs;
    }

    /** world transform helpers for a side: position along the side t (plan metres) -> (x, z), outward normal */
    _side(side, t, out = 0) {
        switch (side) {
            case 'S': return { x: wx(t), z: wz(0) + out, nx: 0, nz: 1, ry: 0 };
            case 'N': return { x: wx(t), z: wz(GEO.D) - out, nx: 0, nz: -1, ry: Math.PI };
            case 'W': return { x: wx(0) - out, z: wz(t), nx: -1, nz: 0, ry: -Math.PI / 2 };
            default: return { x: wx(GEO.W) + out, z: wz(t), nx: 1, nz: 0, ry: Math.PI / 2 };
        }
    }

    _floor(f) {
        const m = this.m;
        const group = new THREE.Group();
        group.name = `floor_${f}`;
        const shell = new THREE.Group();          // exterior of this floor
        shell.name = `shell_${f}`;
        const interior = new THREE.Group();       // filled by the interiors module
        interior.name = `interior_${f}`;
        group.add(shell, interior);
        this.group.add(group);
        const b = new Batch();
        const W = GEO.W, D = GEO.D, H = GEO.H;
        const y0 = f * H, fl = FL(f), cl = CL(f), yTop = (f + 1) * H;
        const cx = 0, cz = 0;

        // floor slab (structure) + exposed slab edge
        b.box(W, GEO.SLAB, D, m.slab, cx, y0 + GEO.SLAB / 2, cz);
        // slab-edge band: white, projecting more on the sunny south and west
        const proj = { S: f === 0 ? 0.25 : 0.9, W: f === 0 ? 0.25 : 0.7, N: 0.3, E: 0.3 };
        if (f === 0) {
            b.box(W + 0.5, 0.3, D + 0.5, m.plinth, 0, 0.15, 0);
        } else {
            const bandY = y0 + 0.13, bandH = 0.5;
            b.box(W + proj.W + proj.E, bandH, proj.S, m.white, (proj.E - proj.W) / 2, bandY, D / 2 + proj.S / 2);
            b.box(W + proj.W + proj.E, bandH, proj.N, m.white, (proj.E - proj.W) / 2, bandY, -D / 2 - proj.N / 2);
            b.box(proj.W, bandH, D, m.white, -W / 2 - proj.W / 2, bandY, 0);
            b.box(proj.E, bandH, D, m.white, W / 2 + proj.E / 2, bandY, 0);
            // warm LED line under the band edge (lit at night)
            b.box(W + proj.W + proj.E - 0.2, 0.03, 0.05, m.led, (proj.E - proj.W) / 2, bandY - bandH / 2 - 0.01, D / 2 + proj.S - 0.08);
        }

        // facade segments generated from the rooms behind them
        const glassH = cl - fl;
        for (const s of this._segments(f)) {
            const len = s.b - s.a;
            const mid = (s.a + s.b) / 2;
            const p = this._side(s.side, mid);
            const type = s.room.type;
            const isCoreSide = s.side === 'E' && f >= 0 && s.b > 6 && s.a < 14;
            if (!this.roomGlass.has(s.room.room_id)) {
                const gm = (type === 'bathroom' ? m.frosted : m.glass).clone();
                gm.emissive = new THREE.Color(0xffd6a0);
                gm.emissiveIntensity = 0;
                this.roomGlass.set(s.room.room_id, gm);
            }
            const glassMat = this.roomGlass.get(s.room.room_id);
            if (type === 'server' && (s.side === 'N' || s.side === 'E')) {
                // louvred metal screen in front of an insulated wall
                b.add(new THREE.BoxGeometry(len, glassH, 0.2), m.spandrel, p.x - p.nx * 0.1, fl + glassH / 2, p.z - p.nz * 0.1, p.ry);
                for (let yy = fl + 0.15; yy < cl; yy += 0.18) {
                    b.add(new THREE.BoxGeometry(len, 0.04, 0.16), m.metalLouvre, p.x + p.nx * 0.05, yy, p.z + p.nz * 0.05, p.ry, -0.6);
                }
            } else {
                const pane = new THREE.PlaneGeometry(len, glassH);
                const mesh = new THREE.Mesh(pane, glassMat);
                mesh.position.set(p.x, fl + glassH / 2, p.z);
                mesh.rotation.y = p.ry;
                mesh.castShadow = false;
                mesh.receiveShadow = false;
                mesh.renderOrder = 5;
                mesh.userData.facadeGlass = true;
                shell.add(mesh);
                // mullions every 1.5 m (3 m on the ground floor), sill and head frame
                const step = f === 0 ? 3 : 1.5;
                const n = Math.max(1, Math.round(len / step));
                for (let i = 0; i <= n; i++) {
                    const q = this._side(s.side, s.a + (i * len) / n, 0.04);
                    b.add(new THREE.BoxGeometry(0.06, glassH, 0.14), m.frame, q.x, fl + glassH / 2, q.z, p.ry);
                }
                const hp = this._side(s.side, mid, 0.04);
                b.add(new THREE.BoxGeometry(len, 0.08, 0.14), m.frame, hp.x, fl + 0.04, hp.z, p.ry);
                b.add(new THREE.BoxGeometry(len, 0.08, 0.14), m.frame, hp.x, cl - 0.04, hp.z, p.ry);
                if (f === 0) b.add(new THREE.BoxGeometry(len, 0.05, 0.12), m.frame, hp.x, fl + 2.45, hp.z, p.ry);
            }
            // spandrel between ceiling and the next slab band (dark glass)
            const spTop = f === this.nFloors - 1 ? yTop + 0.35 : yTop - 0.12;
            const sp = this._side(s.side, mid, 0.01);
            b.add(new THREE.BoxGeometry(len, spTop - cl, 0.08), m.spandrel, sp.x, (cl + spTop) / 2, sp.z, p.ry);

            // sun shading by floor and orientation
            if (f >= 1 && f <= 2 && (s.side === 'S' || s.side === 'W')) {
                // angled bronze fins
                const n = Math.round(len / 1.5);
                for (let i = 0; i <= n; i++) {
                    const q = this._side(s.side, s.a + (i * len) / n, 0.32);
                    b.add(new THREE.BoxGeometry(0.07, yTop - 0.12 - (y0 + 0.38), 0.5), m.bronze, q.x, (y0 + 0.38 + yTop - 0.12) / 2, q.z, p.ry + 0.35);
                }
            } else if (f >= 1 && s.side === 'N') {
                for (const dy of [0.35, 0.75]) {
                    const q = this._side(s.side, mid, 0.45);
                    b.add(new THREE.BoxGeometry(len, 0.03, 0.6), m.metalLouvre, q.x, cl - dy, q.z, p.ry, 0.15);
                }
            } else if (f >= 1 && s.side === 'E' && !isCoreSide) {
                const n = Math.round(len / 0.32);
                for (let i = 0; i <= n; i++) {
                    const q = this._side(s.side, s.a + (i * len) / n, 0.28);
                    b.add(new THREE.BoxGeometry(0.05, yTop - 0.12 - (y0 + 0.38), 0.16), m.timber, q.x, (y0 + 0.38 + yTop - 0.12) / 2, q.z, p.ry);
                }
            } else if (f >= 3 && s.side === 'W') {
                // residential west: white vertical panels framing the glass (privacy + shade)
                const n = Math.max(1, Math.round(len / 3));
                for (let i = 0; i <= n; i++) {
                    const q = this._side(s.side, s.a + (i * len) / n, 0.25);
                    b.add(new THREE.BoxGeometry(0.6, glassH + 0.3, 0.5), m.white, q.x, fl + glassH / 2, q.z, p.ry);
                }
            }
        }

        // residential balconies on the south (L3, L4): slab, glass balustrade, planters, furniture
        if (f >= 3) {
            const depth = 2.1;
            b.box(W + 0.4, 0.28, depth, m.white, 0, fl - 0.14, D / 2 + depth / 2);
            // timber soffit under the balcony
            b.add(new THREE.PlaneGeometry(W + 0.2, depth - 0.1), m.soffit, 0, fl - 0.285, D / 2 + depth / 2, 0, Math.PI / 2);
            const bal = new THREE.Mesh(new THREE.PlaneGeometry(W + 0.2, 1.05), m.balustrade);
            bal.position.set(0, fl + 0.53, D / 2 + depth - 0.06);
            bal.renderOrder = 6;
            shell.add(bal);
            b.box(W + 0.3, 0.05, 0.08, m.frame, 0, fl + 1.07, D / 2 + depth - 0.06);
            const sideBal = (x) => {
                const g = new THREE.Mesh(new THREE.PlaneGeometry(depth, 1.05), m.balustrade);
                g.position.set(x, fl + 0.53, D / 2 + depth / 2);
                g.rotation.y = Math.PI / 2;
                g.renderOrder = 6;
                shell.add(g);
            };
            sideBal(-W / 2 - 0.15); sideBal(W / 2 + 0.15);
            // planters with greenery at the balcony edge
            const spots = [];
            for (const x of [-13.6, -4.9, 5, 13.6]) {
                b.block(1.6, 0.6, 0.55, m.planter, x, fl, D / 2 + depth - 0.4);
                b.block(1.5, 0.04, 0.45, m.soil, x, fl + 0.58, D / 2 + depth - 0.4);
                spots.push({ x: x - 0.4, z: D / 2 + depth - 0.4, y: fl + 0.6, s: 0.55 }, { x: x + 0.4, z: D / 2 + depth - 0.4, y: fl + 0.6, s: 0.5 });
            }
            plant(shell, 'shrub', spots);
            // balcony furniture
            const wood = M.std(0x7a5236, 0.6), cushion = M.fabric('#d8d2c6');
            for (const x of f === 4 ? [-9, -6.5, 9.5] : [-9, 9]) {
                b.block(0.7, 0.35, 1.8, wood, x, fl, D / 2 + 1.05);
                b.block(0.66, 0.1, 1.2, cushion, x, fl + 0.35, D / 2 + 0.85);
                b.add(new THREE.BoxGeometry(0.66, 0.08, 0.6), cushion, x, fl + 0.55, D / 2 + 1.6, 0, 0.6);
            }
            b.cyl(0.35, 0.35, 0.04, M.std(0xe8e4dc, 0.4), 0, fl + 0.72, D / 2 + 1.1, 18);
            b.cyl(0.03, 0.03, 0.7, m.frame, 0, fl + 0.36, D / 2 + 1.1, 8);
        }

        // green wall on the west elevation (L1-L3), north part
        if (f >= 1 && f <= 3) {
            const gw = new THREE.Mesh(new THREE.BoxGeometry(0.25, H, 6.5), m.green);
            gw.position.set(-W / 2 - 0.45, y0 + H / 2 + 0.15, -6.25);
            gw.castShadow = true; gw.receiveShadow = true;
            shell.add(gw);
        }

        // stair / lift core on the east, one segment per floor (stone, glazed stair slot)
        const coreX = W / 2 + 2, coreW = 4, coreD = 8;
        b.add(new THREE.BoxGeometry(coreW, H, coreD), m.stone, coreX, y0 + H / 2, 0);
        b.add(new THREE.BoxGeometry(0.06, H - 0.6, 1.2), m.frame, coreX + coreW / 2 + 0.01, y0 + H / 2, 2.4);
        const slot = new THREE.Mesh(new THREE.PlaneGeometry(1.1, H - 0.7), m.glass);
        slot.position.set(coreX + coreW / 2 + 0.02, y0 + H / 2, 2.4);
        slot.rotation.y = Math.PI / 2;
        shell.add(slot);
        if (f === 0) {
            // lift lobby door on the core's south face
            b.add(new THREE.BoxGeometry(1.6, 2.4, 0.08), m.frame, coreX, 0.3 + 1.2, coreD / 2 + 0.02);
        }

        b.build(shell, { name: `shell_${f}` });

        // room pick boxes (invisible) for selection
        for (const r of this.rooms.filter((rr) => rr.floor_id === f)) {
            const rb = roomBox(r);
            const hb = new THREE.Mesh(new THREE.BoxGeometry(rb.w - 0.05, glassH - 0.05, rb.d - 0.05), new THREE.MeshBasicMaterial({ visible: false }));
            hb.position.set(rb.cx, fl + glassH / 2, rb.cz);
            hb.userData.roomId = r.room_id;
            hb.userData.floor = f;
            group.add(hb);
            this.hit.set(r.room_id, hb);
        }

        this.floors.push({ group, shell, interior, f });
    }

    _roof() {
        const m = this.m;
        const group = new THREE.Group();
        group.name = 'roof';
        this.group.add(group);
        this.roofGroup = group;
        const b = new Batch();
        const W = GEO.W, D = GEO.D;
        const y = this.nFloors * GEO.H;
        b.box(W, 0.35, D, m.slab, 0, y + 0.175, 0);
        // roof band (crisp white edge) and parapet
        b.box(W + 1.8, 0.7, 1.0, m.white, 0.15, y + 0.35, D / 2 + 0.5);
        b.box(W + 1.8, 0.7, 0.4, m.white, 0.15, y + 0.35, -D / 2 - 0.2);
        b.box(0.8, 0.7, D, m.white, -W / 2 - 0.4, y + 0.35, 0);
        b.box(0.4, 0.7, D, m.white, W / 2 + 0.2, y + 0.35, 0);
        b.box(W + 1.8, 0.03, 0.05, m.led, 0.15, y - 0.01, D / 2 + 0.95);
        // roof deck finish
        b.add(new THREE.PlaneGeometry(W - 0.4, D - 0.4), new THREE.MeshStandardMaterial({ map: rep(T.deck(), W, D, 2.5), roughness: 0.8 }), 0, y + 0.36, 0, 0, -Math.PI / 2);
        // glass balustrade around the roof
        const bal = (len, x, z, ry) => {
            const g = new THREE.Mesh(new THREE.PlaneGeometry(len, 1.1), m.balustrade);
            g.position.set(x, y + 0.7 + 0.55, z);
            g.rotation.y = ry;
            g.renderOrder = 6;
            group.add(g);
        };
        bal(W, 0, D / 2 - 0.1, 0); bal(W, 0, -D / 2 + 0.1, 0); bal(D, -W / 2 + 0.1, 0, Math.PI / 2);

        // solar canopy over the west half: slim columns, steel frame, PV modules tilted to the south
        const cx0 = -14, cx1 = 1, cz0 = -8.5, cz1 = 8.5, hc = y + 3.6;
        for (const x of [cx0 + 0.5, (cx0 + cx1) / 2, cx1 - 0.5]) for (const z of [cz0 + 0.5, cz1 - 0.5]) b.cyl(0.11, 0.11, hc - y, m.frame, x, (y + hc) / 2, z, 12);
        b.box(cx1 - cx0, 0.25, 0.2, m.frame, (cx0 + cx1) / 2, hc, cz0 + 0.5);
        b.box(cx1 - cx0, 0.25, 0.2, m.frame, (cx0 + cx1) / 2, hc, cz1 - 0.5);
        for (let x = cx0 + 0.5; x <= cx1; x += 3.5) b.box(0.15, 0.2, cz1 - cz0, m.frame, x, hc + 0.05, (cz0 + cz1) / 2);
        const pvGeo = new THREE.BoxGeometry(1.0, 0.04, 1.7);
        for (let x = cx0 + 0.6; x < cx1 - 0.4; x += 1.05) {
            for (let z = cz0 + 0.6; z < cz1 - 0.6; z += 1.75) b.add(pvGeo.clone(), m.pv, x + 0.5, hc + 0.22 + (z - cz0) * 0.04, z + 0.85, 0, -0.08);
        }
        // roof garden under the canopy
        const spots = [];
        for (const [x, z] of [[-12, -6], [-12, 6], [-1.5, -6], [-1.5, 6]]) {
            b.block(2.2, 0.55, 2.2, m.planter, x, y + 0.36, z);
            b.block(2.0, 0.04, 2.0, m.soil, x, y + 0.9, z);
            spots.push({ x, z, y: y + 0.94, s: 0.75 });
        }
        plant(group, 'flower', spots.map((s) => ({ ...s, s: 0.45 })));
        const wood = M.std(0x7a5236, 0.6);
        for (const x of [-9, -6.5, -4]) { b.block(1.8, 0.45, 0.45, wood, x, y + 0.36, 0); }

        // screened plant area on the east half: condensers with fans
        const px0 = 4, px1 = 13.5, pz0 = -7, pz1 = 7;
        for (let i = 0; i < 3; i++) for (let j = 0; j < 2; j++) {
            const ux = px0 + 1.6 + i * 3.1, uz = pz0 + 3 + j * 7.5;
            b.block(2.4, 1.3, 1.1, m.unit, ux, y + 0.36, uz);
            // fan guards (rings) on top
            for (const dx of [-0.6, 0.6]) {
                b.add(new THREE.TorusGeometry(0.42, 0.03, 6, 24), m.fan, ux + dx, y + 1.68, uz, 0, Math.PI / 2);
                const fan = new THREE.Mesh(new THREE.BoxGeometry(0.8, 0.02, 0.12), m.fan);
                const fan2 = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.02, 0.8), m.fan);
                const fg = new THREE.Group();
                fg.add(fan, fan2);
                fg.position.set(ux + dx, y + 1.67, uz);
                group.add(fg);
                this.fans.push(fg);
            }
        }
        // louvred screen around the plant
        for (let x = px0; x <= px1; x += 0.25) {
            b.block(0.05, 1.9, 0.14, m.metalLouvre, x, y + 0.36, pz0 - 0.4);
            b.block(0.05, 1.9, 0.14, m.metalLouvre, x, y + 0.36, pz1 + 0.4);
        }
        for (let z = pz0 - 0.4; z <= pz1 + 0.4; z += 0.25) b.block(0.14, 1.9, 0.05, m.metalLouvre, px0 - 0.3, y + 0.36, z);
        // lift overrun on the core
        b.add(new THREE.BoxGeometry(4, 3.2, 8), m.stone, W / 2 + 2, y + 1.6, 0);
        b.box(4.4, 0.25, 8.4, m.white, W / 2 + 2, y + 3.3, 0);
        b.build(group, { name: 'roof' });
    }

    _entrance() {
        const m = this.m;
        const shell = this.floors[0].shell;
        const b = new Batch();
        // lobby entrance: canopy cantilevered 4.5 m over the doors
        const x0 = wx(2), x1 = wx(13);            // lobby is plan x 0..15 on the south side
        const cw = x1 - x0, ccx = (x0 + x1) / 2;
        const zf = GEO.D / 2, depth = 4.6, y = 4.15;
        b.box(cw, 0.32, depth, m.white, ccx, y, zf + depth / 2);
        b.add(new THREE.PlaneGeometry(cw - 0.2, depth - 0.15), m.soffit, ccx, y - 0.165, zf + depth / 2, 0, Math.PI / 2);
        for (let i = 0; i < 5; i++) for (let j = 0; j < 2; j++) {
            b.add(new THREE.CircleGeometry(0.09, 16), m.down, x0 + 1.2 + i * (cw - 2.4) / 4, y - 0.17, zf + 1.3 + j * 2.0, 0, Math.PI / 2);
        }
        // fascia sign
        const sign = new THREE.Mesh(new THREE.PlaneGeometry(cw * 0.55, 0.28), new THREE.MeshStandardMaterial({ map: signTexture('S M A R T   H U B'), emissive: 0xffffff, emissiveIntensity: 0, roughness: 0.5 }));
        sign.material.emissiveMap = sign.material.map;
        this.app.env.registerEmissive(sign.material, 0.05, 1.4);
        sign.position.set(ccx, y, zf + depth + 0.005);
        shell.add(sign);
        // stone portal and automatic sliding doors (closed glass with frames)
        const dx0 = wx(6), dx1 = wx(9.5);
        b.box(0.5, 3.0, 0.5, m.stone, dx0 - 0.25, 0.3 + 1.5, zf + 0.25);
        b.box(0.5, 3.0, 0.5, m.stone, dx1 + 0.25, 0.3 + 1.5, zf + 0.25);
        b.box(dx1 - dx0 + 1.0, 0.4, 0.5, m.stone, (dx0 + dx1) / 2, 0.3 + 3.0, zf + 0.25);
        b.box(0.05, 2.5, 0.08, m.frame, (dx0 + dx1) / 2, 0.3 + 1.25, zf + 0.06);
        // entrance mat
        b.add(new THREE.PlaneGeometry(dx1 - dx0, 2.2), M.std(0x2b2d30, 0.95), (dx0 + dx1) / 2, 0.31, zf + 1.2, 0, -Math.PI / 2);
        b.build(shell, { name: 'entrance' });
    }

    /** Hide floors above f (null = show all). */
    isolate(f) {
        for (const fl of this.floors) fl.group.visible = f == null || fl.f <= f;
        this.roofGroup.visible = f == null;
    }

    /** Show/hide the exterior skin of a floor (floor and room views peel it away). */
    setShellVisible(f, visible) {
        const fl = this.floors[f];
        if (fl) fl.shell.visible = visible;
    }

    update(dt, coolingFraction) {
        const spd = (0.4 + 22 * Math.max(0, Math.min(1, coolingFraction))) * dt;
        for (const fan of this.fans) fan.rotation.y += spd;
    }
}
