// ═══════════════════════════════════════════════════════════════
// site.js — streets, junction, parking, plaza, landscape and neighbours
// ═══════════════════════════════════════════════════════════════
// World axes: x = east, y = up, z = south. The building occupies x -15..15,
// z -10..10. A four-lane boulevard runs along the south (entrance) side, a side
// street along the west with a signalised junction, parking and EV charging on the
// east, a garden on the north. Everything here is context: none of it is data.

import * as THREE from 'three';
import { T, M, rep, rand } from '../lib/materials.js';
import { Batch } from '../lib/batch.js';
import { plant, hedge } from './vegetation.js';
import { parkCars, Traffic } from './cars.js';

const ROAD = { z0: 24, z1: 40, median0: 31, median1: 33 };      // main road (east-west)
const SIDE = { x0: -38, x1: -31 };                               // side road (north-south)
const KERB_H = 0.15;

function plane(w, d, mat, x, y, z, ry = 0) {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(w, d), mat);
    m.rotation.x = -Math.PI / 2;
    m.rotation.z = ry;
    m.position.set(x, y, z);
    m.receiveShadow = true;
    return m;
}

function radialTexture(inner = 'rgba(255,226,170,1)') {
    const c = document.createElement('canvas');
    c.width = c.height = 128;
    const ctx = c.getContext('2d');
    const g = ctx.createRadialGradient(64, 64, 2, 64, 64, 64);
    g.addColorStop(0, inner);
    g.addColorStop(0.5, 'rgba(255,220,160,0.35)');
    g.addColorStop(1, 'rgba(255,220,160,0)');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, 128, 128);
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    return t;
}

function textTexture(text, { w = 512, h = 128, color = '#f4f4f0', font = 'bold 84px Arial', bg = null } = {}) {
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    const ctx = c.getContext('2d');
    if (bg) { ctx.fillStyle = bg; ctx.fillRect(0, 0, w, h); }
    ctx.fillStyle = color;
    ctx.font = font;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(text, w / 2, h / 2 + 4);
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    t.anisotropy = 8;
    return t;
}

function facadeTexture(variant) {
    // facade tiles for neighbouring buildings (one tile = 4 bays x 3 floors = 12 m x 10.5 m)
    // map + emissive map (lit windows at night)
    const c = document.createElement('canvas'), e = document.createElement('canvas');
    c.width = e.width = 512; c.height = e.height = 512;
    const ctx = c.getContext('2d'), ex = e.getContext('2d');
    ex.fillStyle = '#000'; ex.fillRect(0, 0, 512, 512);
    const cols = 4, rows = 3, cw = 128, rh = 512 / 3;
    const lit = (x, y, w, h) => {
        if (rand() < 0.4) {
            ex.fillStyle = `rgb(${215 + rand() * 40 | 0},${180 + rand() * 45 | 0},${120 + rand() * 50 | 0})`;
            ex.fillRect(x, y, w, h);
        }
    };
    const glassGrad = (x, y, w, h, top, bottom) => {
        const g = ctx.createLinearGradient(x, y, x + w * 0.4, y + h);
        g.addColorStop(0, top); g.addColorStop(1, bottom);
        ctx.fillStyle = g; ctx.fillRect(x, y, w, h);
    };
    if (variant === 0) {            // white concrete, deep punched windows (residential)
        ctx.fillStyle = '#e9e6df'; ctx.fillRect(0, 0, 512, 512);
        for (let i = 0; i < cols; i++) for (let j = 0; j < rows; j++) {
            const x = i * cw + 18, y = j * rh + 30, w = cw - 36, h = rh - 62;
            ctx.fillStyle = '#b9b4aa'; ctx.fillRect(x - 4, y - 4, w + 8, h + 8);
            glassGrad(x, y, w, h, '#5d7686', '#26333c');
            ctx.fillStyle = '#d9d5cc'; ctx.fillRect(x, y + h - 14, w, 14);     // balcony rail band
            lit(x, y, w, h - 14);
        }
    } else if (variant === 1) {     // reflective blue-green curtain wall, slim vertical mullions
        glassGrad(0, 0, 512, 512, '#6f93a6', '#2e4654');
        for (let x = 0; x <= 512; x += 32) { ctx.fillStyle = 'rgba(210,220,226,0.55)'; ctx.fillRect(x, 0, 3, 512); }
        for (let j = 0; j < rows; j++) { ctx.fillStyle = 'rgba(30,40,48,0.85)'; ctx.fillRect(0, j * rh + rh - 18, 512, 18); }
        for (let i = 0; i < 16; i++) for (let j = 0; j < rows; j++) lit(i * 32 + 3, j * rh, 29, rh - 18);
    } else if (variant === 2) {     // warm stone with tall windows
        ctx.fillStyle = '#d2c3a8'; ctx.fillRect(0, 0, 512, 512);
        for (let i = 0; i < 8; i++) for (let j = 0; j < rows; j++) {
            const x = i * 64 + 14, y = j * rh + 18, w = 36, h = rh - 40;
            glassGrad(x, y, w, h, '#4b5f6b', '#1f2a31');
            lit(x, y, w, h);
        }
        for (let j = 0; j < rows; j++) { ctx.fillStyle = 'rgba(120,100,80,0.25)'; ctx.fillRect(0, j * rh, 512, 4); }
    } else {                        // dark glass with white horizontal spandrels
        ctx.fillStyle = '#f0efea'; ctx.fillRect(0, 0, 512, 512);
        for (let j = 0; j < rows; j++) {
            const y = j * rh + 34, h = rh - 46;
            glassGrad(0, y, 512, h, '#3b4d58', '#161e24');
            for (let x = 0; x <= 512; x += 64) { ctx.fillStyle = 'rgba(200,205,210,0.5)'; ctx.fillRect(x, y, 3, h); }
            for (let i = 0; i < 8; i++) lit(i * 64 + 3, y, 61, h);
        }
    }
    for (let i = 0; i < 2500; i++) { ctx.fillStyle = `rgba(0,0,0,${rand() * 0.04})`; ctx.fillRect(rand() * 512, rand() * 512, 2, 2); }
    const t = new THREE.CanvasTexture(c), te = new THREE.CanvasTexture(e);
    t.colorSpace = te.colorSpace = THREE.SRGBColorSpace;
    t.wrapS = t.wrapT = te.wrapS = te.wrapT = THREE.RepeatWrapping;
    t.anisotropy = 8;
    return { map: t, emissive: te };
}

/** Box with UVs in metres (tile w x h per texture repeat). */
function metricBox(w, h, d, tileU, tileV) {
    const g = new THREE.BoxGeometry(w, h, d);
    const uv = g.attributes.uv;
    const dims = [[d, h], [d, h], [w, d], [w, d], [w, h], [w, h]];
    for (let f = 0; f < 6; f++) for (let k = 0; k < 4; k++) {
        const i = f * 4 + k;
        uv.setXY(i, uv.getX(i) * dims[f][0] / tileU, uv.getY(i) * dims[f][1] / tileV);
    }
    return g;
}

export class Site {
    constructor(app) {
        this.app = app;
        this.group = new THREE.Group();
        this.group.name = 'site';
        app.scene.add(this.group);
        this.signalMats = { main: {}, side: {} };
        this.walkPaths = [];
        this.lightMats = [];
        this._buildGround();
        this._buildRoads();
        this._buildPlaza();
        this._buildParking();
        this._buildLandscape();
        this._buildStreetFurniture();
        this._buildNeighbours();
        this._buildTraffic();
    }

    _buildGround() {
        const g = this.group;
        const grass = new THREE.MeshStandardMaterial({ map: rep(T.grass(), 1400, 1400, 6), roughness: 0.95, color: 0xd8e2c8 });
        const ground = plane(1400, 1400, grass, 0, -0.02, 0);
        g.add(ground);
        // the lot's lawns, slightly raised behind kerbs
        const lawn = new THREE.MeshStandardMaterial({ map: rep(T.grass(), 1, 1, 5), roughness: 0.95 });
        const addLawn = (x0, z0, x1, z1) => {
            const w = x1 - x0, d = z1 - z0;
            const m = new THREE.MeshStandardMaterial({ map: rep(T.grass(), w, d, 5), roughness: 0.95 });
            g.add(plane(w, d, m, (x0 + x1) / 2, 0.1, (z0 + z1) / 2));
        };
        addLawn(-27, -34, 21, -10);     // north garden
        addLawn(-27, -10, -15, 10);     // west garden
        addLawn(21, -34, 60, -25);      // behind parking
        addLawn(56.5, -25, 60, 17);
        void lawn;
    }

    _buildRoads() {
        const g = this.group;
        const asphalt = (w, d) => new THREE.MeshStandardMaterial({ map: rep(T.asphalt(), w, d, 8), roughness: 0.92, color: 0xb8b8b8 });
        // main road and side road
        g.add(plane(900, ROAD.z1 - ROAD.z0, asphalt(900, 16), 0, 0.005, (ROAD.z0 + ROAD.z1) / 2));
        const sideW = SIDE.x1 - SIDE.x0;
        g.add(plane(sideW, 900, asphalt(sideW, 900), (SIDE.x0 + SIDE.x1) / 2, 0.004, 0));

        const b = new Batch();
        const paving = new THREE.MeshStandardMaterial({ map: rep(T.pavers(), 1, 1, 2.4), roughness: 0.85 });
        const kerb = M.std(0xbdb9b1, 0.8);
        const paint = new THREE.MeshStandardMaterial({ color: 0xf2f1ec, roughness: 0.65, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 });
        const yellow = new THREE.MeshStandardMaterial({ color: 0xe8b923, roughness: 0.65, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 });
        const medianMat = new THREE.MeshStandardMaterial({ map: rep(T.grass(), 1, 1, 3), roughness: 0.95 });

        // sidewalks: a slab with a kerb face (UV in metres so pavers are real size)
        const walk = (x0, z0, x1, z1) => {
            const w = x1 - x0, d = z1 - z0;
            const geo = metricBox(w, KERB_H, d, 2.4, 2.4);
            b.add(geo, paving, (x0 + x1) / 2, KERB_H / 2, (z0 + z1) / 2);
            // kerb stones on the road side are drawn as a thin lighter strip
        };
        const kerbLine = (x0, z0, x1, z1) => {
            const w = Math.max(0.2, Math.abs(x1 - x0)), d = Math.max(0.2, Math.abs(z1 - z0));
            b.box(w, KERB_H + 0.02, d, kerb, (x0 + x1) / 2, (KERB_H + 0.02) / 2, (z0 + z1) / 2);
        };
        // north sidewalk of the main road (gap for the junction, the lay-by and the parking entrance)
        walk(-450, 20, SIDE.x0 - 4, 24); kerbLine(-450, 23.9, SIDE.x0 - 4, 24.1);
        walk(SIDE.x1 + 4, 20, -14, 24); kerbLine(SIDE.x1 + 4, 23.9, -14, 24.1);
        walk(-14, 20, -1, 20.8); kerbLine(-14, 20.7, -1, 20.9);                          // behind the lay-by
        walk(-1, 20, 44, 24); kerbLine(-1, 23.9, 44, 24.1);
        walk(50, 20, 450, 24); kerbLine(50, 23.9, 450, 24.1);
        // south sidewalk
        walk(-450, 40, SIDE.x0 - 4, 44); kerbLine(-450, 39.9, SIDE.x0 - 4, 40.1);
        walk(SIDE.x1 + 4, 40, 450, 44); kerbLine(SIDE.x1 + 4, 39.9, 450, 40.1);
        // side-road sidewalks
        walk(SIDE.x1, -450, SIDE.x1 + 4, 20); kerbLine(SIDE.x1 - 0.1, -450, SIDE.x1 + 0.1, 20);
        walk(SIDE.x0 - 4, -450, SIDE.x0, 20); kerbLine(SIDE.x0 - 0.1, -450, SIDE.x0 + 0.1, 20);
        walk(SIDE.x1, 44, SIDE.x1 + 4, 450); kerbLine(SIDE.x1 - 0.1, 44, SIDE.x1 + 0.1, 450);
        walk(SIDE.x0 - 4, 44, SIDE.x0, 450); kerbLine(SIDE.x0 - 0.1, 44, SIDE.x0 + 0.1, 450);
        // corner blocks at the junction
        walk(SIDE.x1, 20, SIDE.x1 + 4, 24); walk(SIDE.x0 - 4, 20, SIDE.x0, 24);
        walk(SIDE.x1, 40, SIDE.x1 + 4, 44); walk(SIDE.x0 - 4, 40, SIDE.x0, 44);
        // planted median with kerbs (gap at the junction)
        const median = (x0, x1) => {
            const w = x1 - x0;
            b.box(w, 0.2, ROAD.median1 - ROAD.median0, kerb, (x0 + x1) / 2, 0.1, (ROAD.median0 + ROAD.median1) / 2);
            const m = plane(w, ROAD.median1 - ROAD.median0 - 0.3, medianMat, (x0 + x1) / 2, 0.205, (ROAD.median0 + ROAD.median1) / 2);
            g.add(m);
        };
        median(-450, SIDE.x0 - 6);
        median(SIDE.x1 + 6, 40);
        median(54, 450);

        // lane markings
        const y = 0.012;
        const dash = (x0, x1, z, len = 3, gap = 6, w = 0.15) => {
            for (let x = x0; x < x1; x += len + gap) b.add(new THREE.PlaneGeometry(len, w), paint, x + len / 2, y, z, 0, -Math.PI / 2);
        };
        const line = (x0, z0, x1, z1, w = 0.15, mat = paint) => {
            const len = Math.hypot(x1 - x0, z1 - z0);
            b.add(new THREE.PlaneGeometry(len, w), mat, (x0 + x1) / 2, y, (z0 + z1) / 2, -Math.atan2(z1 - z0, x1 - x0), -Math.PI / 2);
        };
        const laneMid1 = (ROAD.z0 + ROAD.median0) / 2, laneMid2 = (ROAD.median1 + ROAD.z1) / 2;
        for (const [a, c] of [[-450, SIDE.x0 - 4], [SIDE.x1 + 4, 450]]) {
            dash(a, c, laneMid1);
            dash(a, c, laneMid2);
            line(a, ROAD.z0 + 0.35, c, ROAD.z0 + 0.35);                    // edge lines
            line(a, ROAD.z1 - 0.35, c, ROAD.z1 - 0.35);
            line(a, ROAD.median0 - 0.3, c, ROAD.median0 - 0.3, 0.12, yellow);
            line(a, ROAD.median1 + 0.3, c, ROAD.median1 + 0.3, 0.12, yellow);
        }
        // side road centre line + edges
        const sx = (SIDE.x0 + SIDE.x1) / 2;
        for (const [a, c] of [[-450, 19.5], [44.5, 450]]) {
            for (let z = a; z < c; z += 9) line(sx, z, sx, Math.min(c, z + 3));
        }
        // zebra crossings on all four arms + stop lines
        const zebraX = (xa, xb, z0, z1) => {           // stripes run along x across a road spanning z
            for (let z = z0 + 0.5; z < z1 - 0.3; z += 1.0) b.add(new THREE.PlaneGeometry(xb - xa, 0.5), paint, (xa + xb) / 2, y, z + 0.25, 0, -Math.PI / 2);
        };
        const zebraZ = (za, zb, x0, x1) => {
            for (let x = x0 + 0.5; x < x1 - 0.3; x += 1.0) b.add(new THREE.PlaneGeometry(0.5, zb - za), paint, x + 0.25, y, (za + zb) / 2, 0, -Math.PI / 2);
        };
        zebraX(SIDE.x1 + 0.8, SIDE.x1 + 3.8, ROAD.z0, ROAD.z1);      // east arm
        zebraX(SIDE.x0 - 3.8, SIDE.x0 - 0.8, ROAD.z0, ROAD.z1);      // west arm
        zebraZ(20.4, 23.6, SIDE.x0, SIDE.x1);                         // north arm
        zebraZ(40.4, 43.6, SIDE.x0, SIDE.x1);                         // south arm
        line(SIDE.x1 + 4.4, ROAD.z1 - 0.2, SIDE.x1 + 4.4, ROAD.median1, 0.4);       // westbound stop line
        line(SIDE.x0 - 4.4, ROAD.z0 + 0.2, SIDE.x0 - 4.4, ROAD.median0, 0.4);       // eastbound stop line
        line(sx, 19.8, SIDE.x1 - 0.2, 19.8, 0.4);                                    // southbound (east lane)
        line(SIDE.x0 + 0.2, 44.2, sx, 44.2, 0.4);                                    // northbound (west lane)
        // arrows before the stop lines
        const arrow = new THREE.Shape([[0, -0.15], [2.2, -0.15], [2.2, -0.45], [3.2, 0], [2.2, 0.45], [2.2, 0.15], [0, 0.15]].map(([a, c]) => new THREE.Vector2(a, c)));
        const arrowGeo = new THREE.ShapeGeometry(arrow);
        const placeArrow = (x, z, ry) => b.add(arrowGeo.clone(), paint, x, y, z, ry, -Math.PI / 2);
        placeArrow(SIDE.x0 - 16, laneMid1 - 1.7, 0);
        placeArrow(SIDE.x0 - 16, laneMid1 + 1.7, 0);
        placeArrow(SIDE.x1 + 16, laneMid2 - 1.7, Math.PI);
        placeArrow(SIDE.x1 + 16, laneMid2 + 1.7, Math.PI);
        // drop-off lay-by and parking entrance
        const layby = plane(13, 3.2, asphalt(13, 3.2), -7.5, 0.008, 22.4);
        g.add(layby);
        kerbLine(-14.1, 20.8, -13.9, 24); kerbLine(-1.1, 20.8, -0.9, 24);
        line(-13.6, 21.2, -1.4, 21.2, 0.12, yellow);
        const drop = new THREE.Mesh(new THREE.PlaneGeometry(6, 1.5), new THREE.MeshStandardMaterial({ map: textTexture('DROP OFF'), transparent: true, roughness: 0.7, polygonOffset: true, polygonOffsetFactor: -3 }));
        drop.rotation.x = -Math.PI / 2;
        drop.position.set(-7.5, 0.014, 22.6);
        g.add(drop);
        b.build(g, { name: 'roads', cast: false });
    }

    _buildPlaza() {
        const g = this.group;
        const b = new Batch();
        const paving = new THREE.MeshStandardMaterial({ map: rep(T.pavers(), 48, 10, 2.0), roughness: 0.8, color: 0xf2efe8 });
        // forecourt between the building and the sidewalk
        const fore = new THREE.Mesh(metricBox(48, KERB_H, 10, 48, 10), paving);
        fore.position.set(-3, KERB_H / 2, 15);
        fore.receiveShadow = true;
        g.add(fore);
        const stone = M.std(0xcfc9be, 0.7);
        const darkStone = M.std(0x3d3f42, 0.6);
        // building plinth / entrance step band
        b.box(31.2, 0.3, 0.6, stone, 0, 0.15, 10.3);
        // reflecting pool west of the entrance
        b.box(10, 0.45, 5.4, darkStone, -21, 0.22, 15);
        const water = new THREE.Mesh(new THREE.PlaneGeometry(9.4, 4.8), new THREE.MeshPhysicalMaterial({ color: 0x1d3c4a, roughness: 0.04, metalness: 0.2, transmission: 0, envMapIntensity: 2.2, clearcoat: 1 }));
        water.rotation.x = -Math.PI / 2;
        water.position.set(-21, 0.42, 15);
        g.add(water);
        this.water = water;
        // planters with seating edges along the sidewalk
        const planter = M.std(0xd6d1c7, 0.75);
        const soil = new THREE.MeshStandardMaterial({ map: T.soil(), roughness: 1 });
        const planterSpots = [];
        for (const [x, w] of [[-24, 5], [-17.5, 5], [3, 4], [9, 4], [15, 4]]) {
            b.box(w, 0.55, 1.6, planter, x, KERB_H + 0.275, 18.9);
            b.box(w - 0.3, 0.05, 1.3, soil, x, KERB_H + 0.56, 18.9);
            planterSpots.push({ x: x - w / 4, z: 18.9, y: KERB_H + 0.55 }, { x: x + w / 4, z: 18.9, y: KERB_H + 0.55 });
        }
        plant(g, 'shrubFlower', planterSpots.filter((_, i) => i % 2 === 0).map((s) => ({ ...s, s: 0.9 })));
        plant(g, 'shrub', planterSpots.filter((_, i) => i % 2 === 1).map((s) => ({ ...s, s: 0.85 })));
        // café terrace (tables, chairs, umbrellas) in front of the café
        const tableTop = M.std(0xe8e4dc, 0.4);
        const metal = M.std(0x2a2c30, 0.4, 0.7);
        const fabric = new THREE.MeshStandardMaterial({ color: 0xf1ece0, roughness: 0.9, side: THREE.DoubleSide });
        const chairMat = M.std(0x6b4a33, 0.6);
        this.cafeSeats = [];
        for (let i = 0; i < 6; i++) {
            const x = 3.5 + (i % 3) * 4.2, z = 12.6 + Math.floor(i / 3) * 3.6;
            b.cyl(0.42, 0.42, 0.04, tableTop, x, KERB_H + 0.74, z, 20);
            b.cyl(0.03, 0.03, 0.72, metal, x, KERB_H + 0.37, z, 8);
            b.cyl(0.25, 0.25, 0.03, metal, x, KERB_H + 0.02, z, 12);
            for (let k = 0; k < 4; k++) {
                const a = k * Math.PI / 2 + 0.4;
                const cx = x + Math.cos(a) * 0.75, cz = z + Math.sin(a) * 0.75;
                b.push(cx, KERB_H, cz, -a + Math.PI / 2);
                b.block(0.44, 0.04, 0.44, chairMat, 0, 0.44, 0);
                b.block(0.44, 0.42, 0.04, chairMat, 0, 0.46, 0.2);
                for (const [lx, lz] of [[-0.19, -0.19], [0.19, -0.19], [-0.19, 0.19], [0.19, 0.19]]) b.block(0.03, 0.44, 0.03, metal, lx, 0, lz);
                b.pop();
                this.cafeSeats.push({ x: cx, z: cz, ry: a + Math.PI / 2 });
            }
            // umbrella
            b.cyl(0.025, 0.025, 2.4, metal, x, KERB_H + 1.2, z, 8);
            const cone = new THREE.ConeGeometry(1.5, 0.45, 8, 1, true);
            b.add(cone, fabric, x, KERB_H + 2.35, z);
        }
        // bike racks
        for (let i = 0; i < 5; i++) {
            const x = -25 + i * 1.0;
            const hoop = new THREE.TorusGeometry(0.35, 0.025, 6, 16, Math.PI);
            b.add(hoop, M.steel(), x, KERB_H, 11.6, Math.PI / 2);
        }
        // bollards along the forecourt edge (security line)
        for (let x = -12; x <= 0; x += 1.5) b.cyl(0.11, 0.11, 0.9, M.std(0x2b2d31, 0.4, 0.5), x, KERB_H + 0.45, 20.35, 12);
        b.build(g, { name: 'plaza' });
    }

    _buildParking() {
        const g = this.group;
        const w = 34.5, d = 41;
        const lot = plane(w, d, new THREE.MeshStandardMaterial({ map: rep(T.asphalt(), w, d, 8), roughness: 0.9, color: 0xa9a9a9 }), 21.5 + w / 2, 0.006, -24 + d / 2);
        g.add(lot);
        // driveway from the main road
        g.add(plane(6, 7.2, new THREE.MeshStandardMaterial({ map: rep(T.asphalt(), 6, 7.2, 8), roughness: 0.9, color: 0xa9a9a9 }), 47, 0.007, 20.4));
        const b = new Batch();
        const paint = new THREE.MeshStandardMaterial({ color: 0xf2f1ec, roughness: 0.65, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 });
        const evPaint = new THREE.MeshStandardMaterial({ color: 0x2e8b57, roughness: 0.7, polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1 });
        const stopper = M.std(0x9b978f, 0.85);
        const kerb = M.std(0xbdb9b1, 0.8);
        const y = 0.012;
        const bays = [];
        const row = (x0, x1, zFrom, n, facing, ev = 0) => {
            // bay lines along x, bays 2.6 m wide (in z), 5 m deep
            for (let i = 0; i <= n; i++) b.add(new THREE.PlaneGeometry(x1 - x0, 0.12), paint, (x0 + x1) / 2, y, zFrom + i * 2.6, 0, -Math.PI / 2);
            for (let i = 0; i < n; i++) {
                const z = zFrom + i * 2.6 + 1.3;
                const xi = facing < 0 ? x0 + 0.5 : x1 - 0.5;
                b.box(0.25, 0.12, 1.6, stopper, xi, 0.06, z);
                if (i < ev) b.add(new THREE.PlaneGeometry(x1 - x0 - 0.2, 2.45), evPaint, (x0 + x1) / 2, y - 0.001, z, 0, -Math.PI / 2);
                bays.push({ x: (x0 + x1) / 2 + (facing < 0 ? 0.2 : -0.2), z, heading: facing < 0 ? Math.PI : 0, ev: i < ev });
            }
        };
        row(22, 27, -22, 14, -1, 4);         // west row (EV chargers nearest the building)
        row(33.5, 38.5, -22, 13, 1);
        row(38.5, 43.5, -22, 13, -1);
        row(50, 55, -22, 13, 1);
        // islands with trees at the end of the middle rows
        b.box(10, 0.15, 2.2, kerb, 38.5, 0.075, 13.0);
        b.box(10, 0.15, 2.2, kerb, 38.5, 0.075, -23.4);
        // EV chargers
        const charger = M.std(0xf3f3f1, 0.4);
        const screen = M.screenOn(0x22c55e);
        for (let i = 0; i < 4; i++) {
            const z = -22 + i * 2.6 + 1.3;
            b.block(0.32, 1.5, 0.22, charger, 21.75, 0, z);
            b.box(0.02, 0.22, 0.14, screen, 21.92, 1.2, z);
        }
        b.build(g, { name: 'parking', cast: true });
        plant(g, 'flower', [{ x: 36, z: 13 }, { x: 41, z: 13 }, { x: 36, z: -23.4 }, { x: 41, z: -23.4 }].map((p) => ({ ...p, y: 0.15, s: 0.9 })));
        // park cars in ~65% of the bays (fixed seed, decoration only)
        const spots = bays.filter((bay, i) => !bay.ev || i % 2 === 0).filter(() => rand() < 0.65);
        parkCars(g, spots);
        // hedge around the lot
        const hb = new Batch();
        hedge(hb, 21.6, -25, 56.5, -25, 1.1, 0.9);
        hedge(hb, 56.5, -25, 56.5, 17, 1.1, 0.9);
        hedge(hb, 21.5, 16.8, 43.5, 16.8, 0.8, 0.7);
        hedge(hb, 50.5, 16.8, 56.5, 16.8, 0.8, 0.7);
        hb.build(g, { name: 'hedges' });
    }

    _buildLandscape() {
        const g = this.group;
        // shade trees along the boulevard (both sides) and the side street
        const street = [];
        for (let x = -200; x <= 200; x += 12.5) {
            if (x > SIDE.x0 - 8 && x < SIDE.x1 + 8) continue;
            if (x > -15 && x < 0) continue;              // keep the entrance view open
            if (x > 42 && x < 52) continue;              // parking entrance
            street.push({ x, z: 21.4, y: KERB_H });
            street.push({ x: x + 6, z: 42.6, y: KERB_H });
        }
        for (let z = -200; z <= 0; z += 14) street.push({ x: SIDE.x1 + 2.4, z, y: KERB_H }, { x: SIDE.x0 - 2.4, z: z + 7, y: KERB_H });
        plant(g, 'shade', street.filter((_, i) => i % 3 !== 2));
        plant(g, 'flower', street.filter((_, i) => i % 3 === 2));
        // coconut palms on the median and in the gardens
        const palms = [];
        for (let x = -190; x <= 190; x += 16) if (!(x > SIDE.x0 - 10 && x < SIDE.x1 + 10) && !(x > 40 && x < 54)) palms.push({ x, z: 32, y: 0.2, s: 0.9 + rand() * 0.25 });
        palms.push({ x: -24, z: -4 }, { x: -20, z: 4, s: 1.1 }, { x: -23, z: 7.5 }, { x: -12, z: -22 }, { x: 4, z: -27, s: 1.15 }, { x: 16, z: -14 }, { x: -24, z: -28 }, { x: 18, z: 13.5 });
        plant(g, 'palm', palms.map((p) => ({ y: 0.1, ...p })));
        // garden trees and shrubs
        plant(g, 'shade', [{ x: -18, z: -18 }, { x: 8, z: -18 }, { x: -2, z: -30 }, { x: 14, z: -30 }, { x: 30, z: -30 }, { x: 46, z: -30 }].map((p) => ({ ...p, y: 0.1 })));
        plant(g, 'flower', [{ x: -8, z: -14 }, { x: 0, z: -22 }, { x: -22, z: -12 }].map((p) => ({ ...p, y: 0.1 })));
        const shrubs = [];
        for (let x = -26; x < 20; x += 2.2) if (Math.abs(x + 3) > 3) shrubs.push({ x, z: -11.6 - rand() * 0.5, y: 0.1, s: 0.7 + rand() * 0.4 });
        for (let z = -9; z < 9; z += 2.0) shrubs.push({ x: -16.4, z, y: 0.1, s: 0.7 + rand() * 0.3 });
        plant(g, 'shrub', shrubs.filter((_, i) => i % 3));
        plant(g, 'shrubFlower', shrubs.filter((_, i) => !(i % 3)));
        // garden paths
        const path = new THREE.MeshStandardMaterial({ map: rep(T.pavers(), 3, 24, 2.0), roughness: 0.85 });
        g.add(plane(3, 24, path, -3, 0.13, -22));
        const path2 = new THREE.MeshStandardMaterial({ map: rep(T.pavers(), 44, 2.4, 2.0), roughness: 0.85 });
        g.add(plane(44, 2.4, path2, -3, 0.12, -32.6));
        // benches in the garden
        const b = new Batch();
        const wood = M.std(0x8a5a36, 0.6);
        const steel = M.std(0x2b2d31, 0.4, 0.6);
        const bench = (x, z, ry) => {
            b.push(x, 0.1, z, ry);
            b.block(1.8, 0.06, 0.45, wood, 0, 0.42, 0);
            b.block(1.8, 0.4, 0.05, wood, 0, 0.5, -0.22);
            for (const lx of [-0.75, 0.75]) b.block(0.06, 0.42, 0.45, steel, lx, 0, 0);
            b.pop();
        };
        bench(-6, -18, Math.PI / 2); bench(-6, -25, Math.PI / 2); bench(0, -18, -Math.PI / 2); bench(0, -25, -Math.PI / 2);
        bench(-21, 11.2, 0); bench(-16, 11.2, 0);
        // service yard (generator + transformer) at the north-east corner, screened
        const metal = M.std(0x8e949a, 0.5, 0.6);
        b.block(4.2, 2.1, 2.2, metal, 17.5, 0.1, -20);
        b.block(2.2, 1.8, 1.8, M.std(0x5f6b52, 0.6, 0.3), 17.5, 0.1, -16.8);
        for (let i = 0; i < 14; i++) b.block(0.06, 2.4, 0.12, M.timberClad(), 14.6 + i * 0.4, 0.1, -14.7);
        b.build(g, { name: 'garden' });
    }

    _buildStreetFurniture() {
        const g = this.group;
        const b = new Batch();
        const pole = M.std(0x3a3d42, 0.45, 0.7);
        const headMat = new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xffe6b8, emissiveIntensity: 0, roughness: 0.3 });
        this.app.env.registerEmissive(headMat, 0.0, 6.0);
        const pools = [];
        const lamp = (x, z, ry, h = 8) => {
            b.push(x, KERB_H, z, ry);
            b.cyl(0.07, 0.11, h, pole, 0, h / 2, 0, 10);
            b.box(1.6, 0.08, 0.1, pole, 0.8, h - 0.1, 0);
            b.box(0.7, 0.1, 0.32, pole, 1.5, h - 0.12, 0);
            b.add(new THREE.PlaneGeometry(0.6, 0.26), headMat, 1.5, h - 0.18, 0, 0, Math.PI / 2);
            b.pop();
            const c = Math.cos(ry), s = Math.sin(ry);
            pools.push({ x: x + 1.5 * c, z: z - 1.5 * s });
        };
        for (let x = -200; x <= 200; x += 25) {
            if (x > SIDE.x0 - 6 && x < SIDE.x1 + 6) continue;
            lamp(x, 23.3, -Math.PI / 2);              // arm reaching over the road (towards +z)
            lamp(x + 12, 40.7, Math.PI / 2);
        }
        for (let z = -200; z < 15; z += 25) lamp(SIDE.x1 + 0.6, z, Math.PI);
        for (let z = -18; z <= 10; z += 14) { lamp(38.5, z, 0, 7); lamp(38.5, z, Math.PI, 7); }
        // light pools on the ground at night
        const poolMat = new THREE.MeshBasicMaterial({ map: radialTexture(), transparent: true, opacity: 0.55, blending: THREE.AdditiveBlending, depthWrite: false });
        const poolGeo = new THREE.PlaneGeometry(14, 14);
        poolGeo.rotateX(-Math.PI / 2);
        const im = new THREE.InstancedMesh(poolGeo, poolMat, pools.length);
        const m4 = new THREE.Matrix4();
        pools.forEach((p, i) => { m4.makeTranslation(p.x, 0.2, p.z); im.setMatrixAt(i, m4); });
        im.renderOrder = 3;
        im.visible = false;
        g.add(im);
        this.app.env.nightObjects.push(im);

        // traffic signals at the junction corners
        const head = M.std(0x1c1e21, 0.5, 0.3);
        const lens = (hex) => new THREE.MeshStandardMaterial({ color: 0x111111, emissive: hex, emissiveIntensity: 0.05, roughness: 0.3 });
        const mk = () => ({ red: lens(0xff2a1a), amber: lens(0xffb21a), green: lens(0x2bff6a) });
        this.signalMats = { main: mk(), side: mk() };
        const signal = (x, z, ry, group) => {
            b.push(x, KERB_H, z, ry);
            b.cyl(0.08, 0.08, 4.2, pole, 0, 2.1, 0, 10);
            b.block(0.34, 1.0, 0.28, head, 0, 3.0, 0);
            const ms = this.signalMats[group];
            [['red', 3.78], ['amber', 3.5], ['green', 3.22]].forEach(([k, yy]) => {
                b.add(new THREE.CircleGeometry(0.1, 16), ms[k], 0, yy, 0.145);
            });
            b.pop();
        };
        signal(SIDE.x1 + 0.6, ROAD.z1 + 0.6, 0, 'main');              // faces westbound traffic? (towards +z side)
        signal(SIDE.x0 - 0.6, ROAD.z0 - 0.6, Math.PI, 'main');
        signal(SIDE.x1 + 0.6, ROAD.z0 - 0.6, Math.PI / 2, 'side');
        signal(SIDE.x0 - 0.6, ROAD.z1 + 0.6, -Math.PI / 2, 'side');

        // bus shelter on the far sidewalk
        const glass = M.glass();
        b.push(12, KERB_H, 43.2, 0);
        b.block(6, 0.12, 1.8, M.std(0xe9e9e6, 0.5), 0, 2.6, 0);
        b.block(6, 2.4, 0.05, glass, 0, 0.2, 0.75);
        for (const x of [-2.9, 2.9]) b.block(0.08, 2.6, 0.08, pole, x, 0, 0.75);
        b.block(3, 0.06, 0.45, M.std(0x8a5a36, 0.6), 0, 0.45, 0.45);
        b.pop();
        const ad = new THREE.Mesh(new THREE.PlaneGeometry(1.4, 2.0), new THREE.MeshStandardMaterial({ map: textTexture('CITY BUS', { w: 256, h: 384, font: 'bold 44px Arial', bg: '#1f4e79' }), emissive: 0xffffff, emissiveIntensity: 0.0, roughness: 0.4 }));
        ad.material.emissiveMap = ad.material.map;
        this.app.env.registerEmissive(ad.material, 0.0, 0.8);
        ad.position.set(14.2, KERB_H + 1.25, 43.92);
        ad.rotation.y = Math.PI;
        g.add(ad);
        b.build(g, { name: 'street' });
    }

    _buildNeighbours() {
        const g = this.group;
        const variants = [0, 1, 2, 3].map(facadeTexture);
        const mats = variants.map((v, i) => {
            const glassy = i === 1 || i === 3;
            const m = new THREE.MeshStandardMaterial({ map: v.map, emissiveMap: v.emissive, emissive: 0xffffff, emissiveIntensity: 0, roughness: glassy ? 0.18 : 0.75, metalness: glassy ? 0.45 : 0, envMapIntensity: glassy ? 1.6 : 1 });
            this.app.env.registerEmissive(m, 0, 1.15);
            return m;
        });
        const roof = M.std(0x9a9c9e, 0.85);
        const parapet = M.std(0xe6e4df, 0.7);
        const shopGlass = new THREE.MeshStandardMaterial({ color: 0x1d2730, roughness: 0.1, metalness: 0.5, emissive: 0xffd9a0, emissiveIntensity: 0 });
        this.app.env.registerEmissive(shopGlass, 0, 0.5);
        const canopy = M.std(0x2b2d31, 0.5, 0.4);
        const unit = M.std(0xcfd2d5, 0.5, 0.3);
        const b = new Batch();
        const block = (x, z, w, d, h, v, { shop = false, crown = true } = {}) => {
            const base = shop ? 4.2 : 0;
            if (shop) {
                b.add(new THREE.BoxGeometry(w - 0.6, base, d - 0.6), shopGlass, x, base / 2, z);
                b.box(w + 0.6, 0.35, d + 0.6, canopy, x, base, z);
            }
            const hh = h - base;
            b.add(metricBox(w, hh, d, 12, 10.5), mats[v], x, base + hh / 2, z);
            b.box(w + 0.25, 0.9, d + 0.25, parapet, x, h + 0.45, z);
            b.box(w - 0.4, 0.2, d - 0.4, roof, x, h + 0.1, z);
            if (crown && w > 14) for (let i = 0; i < 3; i++) b.block(2.2, 1.4, 1.4, unit, x - w / 4 + i * 2.8, h + 0.2, z + d / 5);
        };
        // across the boulevard: a street of low-rise shops/apartments, towers behind
        block(-82, 60, 30, 22, 14.7, 2, { shop: true });
        block(-46, 58, 26, 18, 18.2, 0, { shop: true });
        block(-14, 59, 24, 20, 11.2, 3, { shop: true });
        block(22, 60, 34, 22, 21, 0, { shop: true });
        block(64, 59, 30, 20, 14.7, 2, { shop: true });
        block(102, 61, 30, 24, 17.5, 3, { shop: true });
        block(-30, 104, 30, 30, 52, 1);
        block(40, 112, 34, 30, 66, 3);
        block(110, 118, 30, 30, 44, 1);
        // west of the side street
        block(-64, -4, 26, 30, 17.5, 0, { shop: true });
        block(-66, -48, 30, 34, 24.5, 2);
        block(-110, 20, 30, 30, 38, 1);
        // north, beyond the garden
        block(-16, -66, 36, 22, 21, 0);
        block(32, -70, 30, 26, 28, 3);
        block(-60, -104, 30, 30, 56, 1);
        // east, beyond the parking
        block(84, -6, 26, 36, 17.5, 2);
        block(86, -56, 30, 30, 31.5, 0);
        block(128, 30, 30, 30, 49, 1);
        // distant skyline (fades into the haze)
        for (let i = 0; i < 54; i++) {
            const a = (i / 54) * Math.PI * 2 + rand() * 0.08;
            const r = 240 + rand() * 260;
            const w = 18 + rand() * 24;
            block(Math.cos(a) * r, Math.sin(a) * r, w, w * (0.7 + rand() * 0.6), 24 + rand() * 96, rand() < 0.5 ? 1 : (rand() * 4) | 0, { crown: false });
        }
        b.build(g, { name: 'neighbours' });
    }

    _buildTraffic() {
        const lanes = [
            { axis: 'x', fixed: (ROAD.z0 + ROAD.median0) / 2 - 1.7, dir: 1, from: -260, to: 260, stopAt: SIDE.x0 - 5, group: 'main' },
            { axis: 'x', fixed: (ROAD.z0 + ROAD.median0) / 2 + 1.7, dir: 1, from: -260, to: 260, stopAt: SIDE.x0 - 5, group: 'main' },
            { axis: 'x', fixed: (ROAD.median1 + ROAD.z1) / 2 - 1.7, dir: -1, from: 260, to: -260, stopAt: SIDE.x1 + 5, group: 'main' },
            { axis: 'x', fixed: (ROAD.median1 + ROAD.z1) / 2 + 1.7, dir: -1, from: 260, to: -260, stopAt: SIDE.x1 + 5, group: 'main' },
            { axis: 'z', fixed: (SIDE.x0 + SIDE.x1) / 2 + 1.75, dir: 1, from: -260, to: 260, stopAt: 19.2, group: 'side' },
            { axis: 'z', fixed: (SIDE.x0 + SIDE.x1) / 2 - 1.75, dir: -1, from: 260, to: -260, stopAt: 44.8, group: 'side' },
        ];
        this.traffic = new Traffic(this.group, lanes, 5);
        this.traffic.onSignal = (sig) => this._applySignals(sig);
        this._applySignals(this.traffic.signal);
        // pedestrian routes along the sidewalks (used by the people system)
        this.walkPaths = [
            [[-120, 22.2], [-44, 22.2], [-44, 42.2], [120, 42.2]],
            [[120, 21.9], [-25, 21.9], [-29, 21.9], [-29, 120]],
            [[-29, -120], [-29, 21.5], [60, 21.5]],
            [[-120, 41.8], [80, 41.8]],
            [[-40, -120], [-40, 21.6], [-120, 21.6]],
            [[-9, 11.5], [-9, 19.5], [-30, 21.5], [-30, -60]],
            [[-8, 11.5], [-8, 21.0], [44, 21.0], [47, 16], [47, -10], [52, -10]],
        ];
    }

    _applySignals(sig) {
        for (const grp of ['main', 'side']) {
            const ms = this.signalMats[grp];
            if (!ms.red) continue;
            for (const k of ['red', 'amber', 'green']) ms[k].emissiveIntensity = sig[grp] === k ? 4.0 : 0.04;
        }
    }

    update(dt, day) {
        if (this.traffic) this.traffic.update(dt);
        const cm = this.traffic && this.traffic.fleet ? null : null;
        void cm; void day;
    }

    setCarLights(night) {
        const m = this.traffic && Object.values(this.traffic.fleet)[0];
        if (!m) return;
        const head = m.parts[4].material, tail = m.parts[5].material;
        head.emissiveIntensity = 0.1 + night * 4.0;
        tail.emissiveIntensity = 0.15 + night * 2.5;
    }
}
