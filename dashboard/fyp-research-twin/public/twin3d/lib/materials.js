// ═══════════════════════════════════════════════════════════════
// materials.js — procedural PBR textures and the material library
// ═══════════════════════════════════════════════════════════════
// Every texture is drawn on a canvas at start-up (no downloaded assets), so the
// twin runs offline. Textures are made once and cloned with a per-surface repeat,
// so a 15 m floor shows real-size planks or tiles.

import * as THREE from 'three';

const cache = new Map();
let rngState = 12345;
export function rand() {                       // deterministic, so every start looks the same
    rngState = (rngState * 1664525 + 1013904223) >>> 0;
    return rngState / 4294967296;
}
export function seedRand(s) { rngState = (s >>> 0) || 1; }

function canvasTex(key, size, draw, { srgb = true, w = size, h = size } = {}) {
    if (cache.has(key)) return cache.get(key);
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    const ctx = c.getContext('2d');
    draw(ctx, w, h);
    const t = new THREE.CanvasTexture(c);
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.anisotropy = 8;
    if (srgb) t.colorSpace = THREE.SRGBColorSpace;
    cache.set(key, t);
    return t;
}

function noise(ctx, w, h, n, alpha, light = true) {
    for (let i = 0; i < n; i++) {
        const v = light ? 255 : 0;
        ctx.fillStyle = `rgba(${v},${v},${v},${alpha * rand()})`;
        ctx.fillRect(rand() * w, rand() * h, 1 + rand() * 2, 1 + rand() * 2);
    }
}

/** Returns a clone of a cached texture repeated to cover (w x h) metres at `tile` metres per image. */
export function rep(tex, w, h, tile) {
    const t = tex.clone();
    t.needsUpdate = true;
    t.repeat.set(Math.max(0.01, w / tile), Math.max(0.01, h / tile));
    return t;
}

// ---------------------------------------------------------------- textures
export const T = {
    woodFloor(tone = 'oak') {
        const base = { oak: [196, 158, 112], walnut: [124, 86, 58], ash: [214, 196, 166], teak: [165, 112, 66] }[tone];
        return canvasTex(`wood_${tone}`, 512, (ctx, w, h) => {
            const rows = 8, rh = h / rows;
            for (let r = 0; r < rows; r++) {
                let x = -rand() * 300;
                while (x < w) {
                    const len = 220 + rand() * 260;
                    const k = 0.86 + rand() * 0.24;
                    ctx.fillStyle = `rgb(${base[0] * k | 0},${base[1] * k | 0},${base[2] * k | 0})`;
                    ctx.fillRect(x, r * rh, len, rh);
                    // grain
                    for (let g = 0; g < 14; g++) {
                        const gy = r * rh + rand() * rh;
                        ctx.strokeStyle = `rgba(60,35,15,${0.05 + rand() * 0.08})`;
                        ctx.lineWidth = 0.6 + rand() * 1.2;
                        ctx.beginPath();
                        ctx.moveTo(x, gy);
                        ctx.bezierCurveTo(x + len * 0.3, gy + (rand() - 0.5) * 6, x + len * 0.6, gy + (rand() - 0.5) * 6, x + len, gy + (rand() - 0.5) * 4);
                        ctx.stroke();
                    }
                    ctx.fillStyle = 'rgba(40,25,10,0.45)';
                    ctx.fillRect(x, r * rh, 1.5, rh);
                    x += len;
                }
                ctx.fillStyle = 'rgba(40,25,10,0.35)';
                ctx.fillRect(0, r * rh, w, 1.5);
            }
        });
    },
    carpet(hex = '#5e6670') {
        return canvasTex(`carpet_${hex}`, 256, (ctx, w, h) => {
            ctx.fillStyle = hex; ctx.fillRect(0, 0, w, h);
            noise(ctx, w, h, 9000, 0.10); noise(ctx, w, h, 9000, 0.12, false);
            ctx.strokeStyle = 'rgba(0,0,0,0.12)'; ctx.lineWidth = 1;
            ctx.strokeRect(0.5, 0.5, w - 1, h - 1);            // carpet tile seams
        });
    },
    terrazzo() {
        return canvasTex('terrazzo', 512, (ctx, w, h) => {
            ctx.fillStyle = '#d9d5cc'; ctx.fillRect(0, 0, w, h);
            const cols = ['#9a958c', '#b9b2a6', '#7e7a74', '#efece6', '#c2b39b'];
            for (let i = 0; i < 2600; i++) {
                ctx.fillStyle = cols[i % cols.length];
                const r = 1 + rand() * 3.2;
                ctx.beginPath(); ctx.ellipse(rand() * w, rand() * h, r, r * (0.6 + rand() * 0.5), rand() * 3, 0, 7); ctx.fill();
            }
            ctx.strokeStyle = 'rgba(80,80,80,0.18)'; ctx.lineWidth = 2;
            ctx.strokeRect(1, 1, w - 2, h - 2);
        });
    },
    tiles(hex = '#e8e6e1', grout = '#bdb8ae', n = 4) {
        return canvasTex(`tiles_${hex}_${n}`, 512, (ctx, w, h) => {
            ctx.fillStyle = grout; ctx.fillRect(0, 0, w, h);
            const s = w / n;
            for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) {
                const k = 0.95 + rand() * 0.08;
                const c = new THREE.Color(hex).multiplyScalar(k);
                ctx.fillStyle = `#${c.getHexString()}`;
                ctx.fillRect(i * s + 2, j * s + 2, s - 4, s - 4);
            }
            noise(ctx, w, h, 2500, 0.06);
        });
    },
    rubber() {
        return canvasTex('rubber', 256, (ctx, w, h) => {
            ctx.fillStyle = '#3b3e43'; ctx.fillRect(0, 0, w, h);
            const cols = ['#565b62', '#4a5868', '#64676b'];
            for (let i = 0; i < 2200; i++) { ctx.fillStyle = cols[i % 3]; ctx.fillRect(rand() * w, rand() * h, 2, 2); }
            ctx.strokeStyle = 'rgba(0,0,0,0.5)'; ctx.strokeRect(0.5, 0.5, w - 1, h - 1);
        });
    },
    deck() {
        return canvasTex('deck', 512, (ctx, w, h) => {
            const n = 10, bw = w / n;
            for (let i = 0; i < n; i++) {
                const k = 0.85 + rand() * 0.25;
                ctx.fillStyle = `rgb(${150 * k | 0},${105 * k | 0},${70 * k | 0})`;
                ctx.fillRect(i * bw, 0, bw - 4, h);
                for (let g = 0; g < 10; g++) {
                    ctx.fillStyle = `rgba(60,35,20,${0.08 + rand() * 0.08})`;
                    ctx.fillRect(i * bw + rand() * (bw - 6), 0, 1, h);
                }
            }
        });
    },
    plaster() {
        return canvasTex('plaster', 256, (ctx, w, h) => {
            ctx.fillStyle = '#f1eee8'; ctx.fillRect(0, 0, w, h);
            noise(ctx, w, h, 3000, 0.035, false); noise(ctx, w, h, 3000, 0.04);
        });
    },
    fabric(hex) {
        return canvasTex(`fabric_${hex}`, 128, (ctx, w, h) => {
            ctx.fillStyle = hex; ctx.fillRect(0, 0, w, h);
            for (let y = 0; y < h; y += 2) { ctx.fillStyle = `rgba(0,0,0,${0.04 + rand() * 0.04})`; ctx.fillRect(0, y, w, 1); }
            for (let x = 0; x < w; x += 2) { ctx.fillStyle = `rgba(255,255,255,${0.02 + rand() * 0.03})`; ctx.fillRect(x, 0, 1, h); }
        });
    },
    marble() {
        return canvasTex('marble', 512, (ctx, w, h) => {
            ctx.fillStyle = '#f2f0ec'; ctx.fillRect(0, 0, w, h);
            for (let v = 0; v < 14; v++) {
                ctx.strokeStyle = `rgba(120,120,125,${0.08 + rand() * 0.18})`;
                ctx.lineWidth = 0.5 + rand() * 2;
                ctx.beginPath();
                let x = rand() * w, y = 0;
                ctx.moveTo(x, y);
                while (y < h) { x += (rand() - 0.5) * 40; y += 20 + rand() * 30; ctx.lineTo(x, y); }
                ctx.stroke();
            }
        });
    },
    asphalt() {
        return canvasTex('asphalt', 512, (ctx, w, h) => {
            ctx.fillStyle = '#3a3c3f'; ctx.fillRect(0, 0, w, h);
            noise(ctx, w, h, 26000, 0.10); noise(ctx, w, h, 20000, 0.18, false);
            for (let i = 0; i < 18; i++) {             // patches and tyre wear
                ctx.fillStyle = `rgba(${rand() < 0.5 ? '0,0,0' : '90,90,90'},${0.04 + rand() * 0.05})`;
                ctx.beginPath(); ctx.ellipse(rand() * w, rand() * h, 20 + rand() * 60, 8 + rand() * 30, rand() * 3, 0, 7); ctx.fill();
            }
        });
    },
    pavers() {
        return canvasTex('pavers', 512, (ctx, w, h) => {
            ctx.fillStyle = '#8f8a82'; ctx.fillRect(0, 0, w, h);
            const rows = 8, rh = h / rows;
            for (let r = 0; r < rows; r++) {
                const off = (r % 2) * (w / 8);
                for (let x = -off; x < w; x += w / 4) {
                    const k = 0.88 + rand() * 0.18;
                    ctx.fillStyle = `rgb(${196 * k | 0},${189 * k | 0},${178 * k | 0})`;
                    ctx.fillRect(x + 2, r * rh + 2, w / 4 - 4, rh - 4);
                }
            }
            noise(ctx, w, h, 5000, 0.07, false);
        });
    },
    grass() {
        return canvasTex('grass', 512, (ctx, w, h) => {
            ctx.fillStyle = '#4f6b35'; ctx.fillRect(0, 0, w, h);
            for (let i = 0; i < 9; i++) {           // soft patches (mowing, shade, dry spots)
                const g2 = ctx.createRadialGradient(rand() * w, rand() * h, 4, rand() * w, rand() * h, 120 + rand() * 120);
                g2.addColorStop(0, rand() < 0.5 ? 'rgba(120,130,60,0.25)' : 'rgba(40,70,30,0.25)');
                g2.addColorStop(1, 'rgba(0,0,0,0)');
                ctx.fillStyle = g2; ctx.fillRect(0, 0, w, h);
            }
            for (let i = 0; i < 16000; i++) {
                const g = 80 + rand() * 55 | 0, r = 50 + rand() * 45 | 0;
                ctx.fillStyle = `rgba(${r},${g},${32 + rand() * 25 | 0},0.55)`;
                ctx.fillRect(rand() * w, rand() * h, 1 + rand() * 2, 1 + rand() * 4);
            }
        });
    },
    soil() {
        return canvasTex('soil', 256, (ctx, w, h) => {
            ctx.fillStyle = '#4b3a2c'; ctx.fillRect(0, 0, w, h);
            noise(ctx, w, h, 6000, 0.15); noise(ctx, w, h, 6000, 0.2, false);
        });
    },
    stone() {
        return canvasTex('stone', 512, (ctx, w, h) => {
            ctx.fillStyle = '#3a3a3c'; ctx.fillRect(0, 0, w, h);
            let y = 0;
            while (y < h) {
                const rh = 30 + rand() * 40; let x = -rand() * 80;
                while (x < w) {
                    const len = 90 + rand() * 140, k = 0.75 + rand() * 0.5;
                    ctx.fillStyle = `rgb(${70 * k | 0},${68 * k | 0},${66 * k | 0})`;
                    ctx.fillRect(x + 2, y + 2, len - 4, rh - 4);
                    x += len;
                }
                y += rh;
            }
            noise(ctx, w, h, 9000, 0.08);
        });
    },
    timber() {
        return canvasTex('timber', 512, (ctx, w, h) => {
            const n = 16, s = w / n;
            ctx.fillStyle = '#2a1d14'; ctx.fillRect(0, 0, w, h);
            for (let i = 0; i < n; i++) {
                const k = 0.85 + rand() * 0.3;
                ctx.fillStyle = `rgb(${168 * k | 0},${116 * k | 0},${72 * k | 0})`;
                ctx.fillRect(i * s + 3, 0, s - 6, h);
                for (let g = 0; g < 6; g++) { ctx.fillStyle = `rgba(80,50,25,${0.1 + rand() * 0.1})`; ctx.fillRect(i * s + 3 + rand() * (s - 8), 0, 1, h); }
            }
        });
    },
    panel() {                                     // exterior fibre-cement / aluminium panels
        return canvasTex('panel', 512, (ctx, w, h) => {
            ctx.fillStyle = '#eceae5'; ctx.fillRect(0, 0, w, h);
            ctx.strokeStyle = 'rgba(0,0,0,0.12)'; ctx.lineWidth = 3;
            for (let i = 0; i <= 2; i++) { ctx.beginPath(); ctx.moveTo(i * w / 2, 0); ctx.lineTo(i * w / 2, h); ctx.stroke(); }
            ctx.beginPath(); ctx.moveTo(0, h / 2); ctx.lineTo(w, h / 2); ctx.stroke();
            noise(ctx, w, h, 2000, 0.03, false);
        });
    },
    screen(lines, accent = '#22c55e') {           // small device / thermostat display (not cached)
        const c = document.createElement('canvas');
        c.width = 256; c.height = 128;
        const ctx = c.getContext('2d');
        ctx.fillStyle = '#0b1220'; ctx.fillRect(0, 0, 256, 128);
        ctx.fillStyle = accent; ctx.fillRect(0, 0, 256, 6);
        ctx.fillStyle = '#e2e8f0';
        ctx.font = 'bold 44px Segoe UI, Arial'; ctx.fillText(lines[0] || '', 16, 62);
        ctx.font = '24px Segoe UI, Arial'; ctx.fillStyle = '#94a3b8'; ctx.fillText(lines[1] || '', 16, 104);
        const t = new THREE.CanvasTexture(c);
        t.colorSpace = THREE.SRGBColorSpace;
        return { texture: t, canvas: c, ctx };
    },
};

// ---------------------------------------------------------------- materials
const matCache = new Map();
function cached(key, make) {
    if (!matCache.has(key)) matCache.set(key, make());
    return matCache.get(key);
}

export const M = {
    std(hex, rough = 0.6, metal = 0, extra = {}) {
        return cached(`std_${hex}_${rough}_${metal}_${JSON.stringify(extra)}`, () => new THREE.MeshStandardMaterial({ color: hex, roughness: rough, metalness: metal, ...extra }));
    },
    white: () => M.std(0xf2f0eb, 0.75),
    offwhite: () => M.std(0xe7e3db, 0.8),
    wallPaint: () => cached('wallPaint', () => new THREE.MeshStandardMaterial({ color: 0xf4f1ec, roughness: 0.9, map: T.plaster() })),
    wallTop: () => M.std(0x2b2d31, 0.8),
    concrete: () => M.std(0xd8d4cc, 0.85),
    exteriorWhite: () => cached('extWhite', () => new THREE.MeshStandardMaterial({ color: 0xf3f1ec, roughness: 0.7 })),
    aluminium: () => M.std(0x30353b, 0.38, 0.8),
    brushed: () => M.std(0xb9bcc0, 0.32, 0.9),
    steel: () => M.std(0x8d9196, 0.35, 0.85),
    black: () => M.std(0x16181b, 0.5, 0.2),
    chrome: () => M.std(0xe6e8ea, 0.12, 1.0),
    oak: () => cached('oak', () => new THREE.MeshStandardMaterial({ color: 0xffffff, map: rep(T.woodFloor('ash'), 1, 1, 1.2), roughness: 0.55 })),
    walnut: () => cached('walnut', () => new THREE.MeshStandardMaterial({ color: 0xffffff, map: rep(T.woodFloor('walnut'), 1, 1, 1.2), roughness: 0.5 })),
    timberClad: () => cached('timberClad', () => new THREE.MeshStandardMaterial({ color: 0xffffff, map: T.timber(), roughness: 0.65 })),
    stoneClad: () => cached('stoneClad', () => new THREE.MeshStandardMaterial({ color: 0xffffff, map: T.stone(), roughness: 0.85, bumpMap: T.stone(), bumpScale: 0.6 })),
    marble: () => cached('marble', () => new THREE.MeshStandardMaterial({ color: 0xffffff, map: T.marble(), roughness: 0.18 })),
    fabric: (hex) => cached(`fab_${hex}`, () => {
        const m = new THREE.MeshStandardMaterial({ color: 0xffffff, map: T.fabric(hex), roughness: 0.95 });
        m.userData.vc = 'fabric';
        m.userData.vcColor = new THREE.Color(hex);
        return m;
    }),
    leather: (hex) => M.std(hex, 0.45),
    screenOff: () => M.std(0x0a0c10, 0.25, 0.4),
    screenOn: (hex = 0x4b8bff) => cached(`scr_${hex}`, () => new THREE.MeshStandardMaterial({ color: 0x0b1020, emissive: hex, emissiveIntensity: 0.9, roughness: 0.3 })),
    plantLeaf: (hex = 0x3f7a35) => M.std(hex, 0.8),
    pot: () => M.std(0xd9d4ca, 0.6),
    glass: () => cached('glassInt', () => new THREE.MeshStandardMaterial({ color: 0xdbe9ee, roughness: 0.05, metalness: 0.1, transparent: true, opacity: 0.22, depthWrite: false })),
    curtainGlass: () => cached('glassExt', () => new THREE.MeshPhysicalMaterial({ color: 0x7ea6bb, roughness: 0.04, metalness: 0.25, transparent: true, opacity: 0.38, envMapIntensity: 2.4, side: THREE.DoubleSide, depthWrite: false })),
    lightPanel: () => cached('lightPanel', () => new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xfff3dc, emissiveIntensity: 0, roughness: 0.4 })),
    floor(type, w, d) {
        // floor finish per room type, textures at real size
        const mk = (tex, tile, rough, hex = 0xffffff) => new THREE.MeshStandardMaterial({ color: hex, map: rep(tex, w, d, tile), roughness: rough });
        switch (type) {
            case 'office': case 'executive': return mk(T.carpet('#5d6670'), 0.6, 0.95);
            case 'meeting': return mk(T.carpet('#4f5a68'), 0.6, 0.95);
            case 'lobby': return mk(T.terrazzo(), 2.4, 0.35);
            case 'corridor': return mk(T.terrazzo(), 2.4, 0.4);
            case 'shop': return mk(T.tiles('#e9e5de', '#c9c3b8', 2), 1.2, 0.4);
            case 'kitchen': return mk(T.tiles('#d9d6cf', '#a9a398', 4), 1.2, 0.45);
            case 'bathroom': return mk(T.tiles('#cfd3d4', '#9aa0a2', 4), 1.2, 0.35);
            case 'gym': return mk(T.rubber(), 1.0, 0.95);
            case 'server': return mk(T.tiles('#b8bcc0', '#8a8f94', 2), 1.2, 0.6);
            case 'lounge': return mk(T.woodFloor('teak'), 2.0, 0.55);
            case 'residential': return mk(T.woodFloor('oak'), 2.0, 0.5);
            default: return mk(T.woodFloor('oak'), 2.0, 0.55);
        }
    },
};

export function box(w, h, d, mat, x = 0, y = 0, z = 0, opts = {}) {
    const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat);
    m.position.set(x, y, z);
    m.castShadow = opts.cast !== false;
    m.receiveShadow = opts.receive !== false;
    return m;
}

export function cyl(rt, rb, h, mat, x = 0, y = 0, z = 0, seg = 16, opts = {}) {
    const m = new THREE.Mesh(new THREE.CylinderGeometry(rt, rb, h, seg), mat);
    m.position.set(x, y, z);
    m.castShadow = opts.cast !== false;
    m.receiveShadow = opts.receive !== false;
    return m;
}
