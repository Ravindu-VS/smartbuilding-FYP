// ═══════════════════════════════════════════════════════════════
// environment.js — physical sky, sun, reflections, day/evening/night
// ═══════════════════════════════════════════════════════════════
// "Live" lighting follows the simulation's own clock and weather: the sun is placed
// for Colombo (6.93 N, 79.85 E) at the simulated date and time, and the simulated
// cloud cover greys the sky and softens shadows. The Day / Golden hour / Night
// presets only change the picture (for presenting); they never change the
// simulation, and the toolbar says so.

import * as THREE from 'three';
import { Sky } from 'three/addons/objects/Sky.js';

const LAT = 6.93 * Math.PI / 180;
const LON = 79.85;
const TZ = 5.5;

/** Solar altitude/azimuth (degrees; azimuth 0 = north, 90 = east) for a local date-time. */
export function solarPosition(date) {
    const start = Date.UTC(date.getUTCFullYear(), 0, 0);
    const doy = Math.floor((date.getTime() - start) / 86400000);
    const hour = date.getUTCHours() + date.getUTCMinutes() / 60;       // local clock time stored as UTC fields
    const g = 2 * Math.PI / 365 * (doy - 1 + (hour - 12) / 24);
    const decl = 0.006918 - 0.399912 * Math.cos(g) + 0.070257 * Math.sin(g) - 0.006758 * Math.cos(2 * g)
        + 0.000907 * Math.sin(2 * g) - 0.002697 * Math.cos(3 * g) + 0.00148 * Math.sin(3 * g);
    const eqt = 229.18 * (0.000075 + 0.001868 * Math.cos(g) - 0.032077 * Math.sin(g) - 0.014615 * Math.cos(2 * g)
        - 0.040849 * Math.sin(2 * g));
    const tst = hour * 60 + eqt + 4 * LON - 60 * TZ;
    const ha = (tst / 4 - 180) * Math.PI / 180;
    const cosZ = Math.sin(LAT) * Math.sin(decl) + Math.cos(LAT) * Math.cos(decl) * Math.cos(ha);
    const zen = Math.acos(Math.max(-1, Math.min(1, cosZ)));
    let az = Math.atan2(Math.sin(ha), Math.cos(ha) * Math.sin(LAT) - Math.tan(decl) * Math.cos(LAT));
    az = (az * 180 / Math.PI + 180) % 360;
    return { altitude: 90 - zen * 180 / Math.PI, azimuth: az };
}

export const LIGHTING_PRESETS = {
    live: { label: 'Live (simulation clock)' },
    day: { label: 'Day', iso: '2026-03-16T10:40:00', cloud: 0.15 },
    golden: { label: 'Golden hour', iso: '2026-03-16T17:15:00', cloud: 0.12 },
    night: { label: 'Night', iso: '2026-03-16T20:30:00', cloud: 0.1 },
};

export class Environment {
    constructor(app) {
        this.app = app;
        this.preset = 'live';
        this.clockIso = null;
        this.cloudLive = 0;
        this._alt = 35;
        this._az = 120;
        this._cloud = 0.1;
        this.day = 1;
        this.sunDir = new THREE.Vector3(0, 1, 0);
        this._envTimer = 0;
        this._envKey = '';
        this.emissives = [];          // { mat, day, night } materials that glow at night
        this.nightObjects = [];       // objects only visible at night (light pools)
        const { scene, renderer } = app;

        this.sky = new Sky();
        this.sky.scale.setScalar(4000);
        this.sky.material.uniforms.mieDirectionalG.value = 0.8;
        scene.add(this.sky);

        this.sun = new THREE.DirectionalLight(0xffffff, 4);
        this.sun.castShadow = true;
        const s = this.sun.shadow;
        s.mapSize.set(4096, 4096);
        s.camera.left = -62; s.camera.right = 62; s.camera.top = 62; s.camera.bottom = -62;
        s.camera.near = 1; s.camera.far = 400;
        s.bias = -0.00025;
        s.normalBias = 0.035;
        s.radius = 2.5;
        scene.add(this.sun);
        scene.add(this.sun.target);

        this.hemi = new THREE.HemisphereLight(0xbfd8ff, 0x4a4338, 0.35);
        scene.add(this.hemi);
        this.moon = new THREE.DirectionalLight(0x9fb4ff, 0);
        this.moon.position.set(-60, 90, 40);
        scene.add(this.moon);

        // stars
        const n = 1800, pos = new Float32Array(n * 3);
        let seed = 7;
        const r = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
        for (let i = 0; i < n; i++) {
            const th = 2 * Math.PI * r(), ph = Math.acos(1 - (r() * 0.5 + 0.03));
            pos[i * 3] = 3000 * Math.sin(ph) * Math.cos(th);
            pos[i * 3 + 1] = 3000 * Math.cos(ph);
            pos[i * 3 + 2] = 3000 * Math.sin(ph) * Math.sin(th);
        }
        const sg = new THREE.BufferGeometry();
        sg.setAttribute('position', new THREE.BufferAttribute(pos, 3));
        this.stars = new THREE.Points(sg, new THREE.PointsMaterial({ color: 0xffffff, size: 1.8, sizeAttenuation: false, transparent: true, opacity: 0, depthWrite: false, fog: false }));
        scene.add(this.stars);

        scene.fog = new THREE.FogExp2(0xc9d6e0, 0.0024);

        this._pmrem = new THREE.PMREMGenerator(renderer);
        this._envScene = new THREE.Scene();
        this._envSky = new Sky();
        this._envSky.scale.setScalar(1000);
        this._envScene.add(this._envSky);
        // a soft ground bounce in the environment so reflections are not black below the horizon
        const ground = new THREE.Mesh(new THREE.CircleGeometry(900, 24), new THREE.MeshBasicMaterial({ color: 0x55524b, side: THREE.DoubleSide }));
        ground.rotation.x = -Math.PI / 2;
        ground.position.y = -5;
        this._envScene.add(ground);
        this._envGround = ground;
        this._envRT = null;
        this.update(0, true);
    }

    setPreset(p) { if (LIGHTING_PRESETS[p]) { this.preset = p; this.update(0, true); } }

    setClock(iso, cloud) {
        this.clockIso = iso || null;
        this.cloudLive = Math.max(0, Math.min(1, Number(cloud) || 0));
    }

    registerEmissive(mat, dayValue, nightValue) { this.emissives.push({ mat, day: dayValue, night: nightValue }); }

    _target() {
        const p = LIGHTING_PRESETS[this.preset];
        let iso = p.iso, cloud = p.cloud;
        if (this.preset === 'live') { iso = this.clockIso; cloud = this.cloudLive; }
        if (iso && iso.includes('T')) {
            const sp = solarPosition(new Date(iso.slice(0, 19) + 'Z'));
            return { alt: sp.altitude, az: sp.azimuth, cloud };
        }
        return { alt: 40, az: 110, cloud: cloud ?? 0.2 };
    }

    update(delta, force = false) {
        const app = this.app;
        const t = this._target();
        const k = force ? 1 : Math.min(1, delta * 2.5);
        this._alt += (t.alt - this._alt) * k;
        let dAz = ((t.az - this._az + 540) % 360) - 180;
        this._az = (this._az + dAz * k + 360) % 360;
        this._cloud += (t.cloud - this._cloud) * (force ? 1 : Math.min(1, delta * 1.5));
        const a = THREE.MathUtils.degToRad(this._alt), z = THREE.MathUtils.degToRad(this._az);
        // scene axes: x = east, y = up, z = south (north is -z)
        this.sunDir.set(Math.cos(a) * Math.sin(z), Math.sin(a), -Math.cos(a) * Math.cos(z)).normalize();

        const day = THREE.MathUtils.smoothstep(this._alt, -7, 7);
        this.day = day;
        const cloud = this._cloud;
        const heavy = THREE.MathUtils.smoothstep(cloud, 0.55, 0.95);
        const u = this.sky.material.uniforms;
        u.sunPosition.value.copy(this.sunDir);
        u.turbidity.value = 2.0 + cloud * 2.5 + heavy * 10;
        u.rayleigh.value = 1.6 - 0.4 * cloud + heavy * 0.8 + (1 - THREE.MathUtils.smoothstep(this._alt, 0, 20)) * 0.8;
        u.mieCoefficient.value = 0.004 + cloud * 0.004 + heavy * 0.025;

        const sunI = Math.max(0, Math.sin(a)) ** 0.45 * 4.6 * (1 - 0.3 * cloud - 0.55 * heavy);
        const sun = this.sun;
        sun.intensity = sunI;
        sun.position.set(this.sunDir.x * 160, Math.max(6, this.sunDir.y * 160), this.sunDir.z * 160);
        sun.target.position.set(0, 0, 0);
        const warm = THREE.MathUtils.smoothstep(this._alt, 1, 28);
        sun.color.setRGB(1, 0.62 + 0.36 * warm, 0.38 + 0.56 * warm);
        sun.castShadow = sunI > 0.05;
        sun.shadow.radius = 2 + cloud * 7;

        this.hemi.intensity = 0.05 + day * (0.32 + 0.4 * heavy);
        this.hemi.color.setHSL(0.58, 0.5 * (1 - heavy), 0.6 + 0.15 * day);
        this.moon.intensity = (1 - day) * 0.4;
        this.stars.material.opacity = (1 - day) * (1 - cloud) * 0.9;
        app.renderer.toneMappingExposure = 0.5 + (1 - day) * 0.55 + heavy * 0.15;

        const dayHaze = new THREE.Color().setHSL(0.58, 0.32 * (1 - heavy), 0.74 - 0.08 * heavy);
        const dusk = new THREE.Color(0xd8a383);
        const horizon = dayHaze.clone().lerp(dusk, (1 - warm) * day * 0.6);
        app.scene.fog.color.copy(new THREE.Color(0x070a12).lerp(horizon, day));
        app.scene.fog.density = 0.0021 + heavy * 0.003 + (1 - day) * 0.0008;

        if (app.bloom) {
            app.bloom.threshold = 0.85 + day * 8.0;
            app.bloom.strength = 0.18 + (1 - day) * 0.5;
            app.bloom.radius = 0.55;
        }
        const night = 1 - day;
        for (const e of this.emissives) e.mat.emissiveIntensity = e.day + (e.night - e.day) * night;
        for (const o of this.nightObjects) o.visible = night > 0.25;
        if (app.onLighting) app.onLighting(day);

        this._envTimer -= delta || 0;
        const key = `${Math.round(this._alt)}_${Math.round(this._az / 6)}_${Math.round(cloud * 10)}`;
        if (force || (this._envTimer <= 0 && key !== this._envKey)) {
            this._envTimer = 2.0;
            this._envKey = key;
            const eu = this._envSky.material.uniforms;
            for (const n of ['sunPosition', 'turbidity', 'rayleigh', 'mieCoefficient', 'mieDirectionalG']) {
                if (eu[n].value && eu[n].value.copy) eu[n].value.copy(u[n].value); else eu[n].value = u[n].value;
            }
            this._envGround.material.color.setRGB(0.6 * (0.08 + 0.92 * day), 0.57 * (0.08 + 0.92 * day), 0.52 * (0.08 + 0.92 * day));
            const rt = this._pmrem.fromScene(this._envScene, 0, 1, 3000);
            if (this._envRT) this._envRT.dispose();
            this._envRT = rt;
            app.scene.environment = rt.texture;
            app.scene.environmentIntensity = 0.1 + 0.32 * day + 0.25 * heavy;
        }
    }
}
