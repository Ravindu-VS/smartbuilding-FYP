// ═══════════════════════════════════════════════════════════════
// RealismEngine.js — physical sky, sun, reflections, night lighting
// ═══════════════════════════════════════════════════════════════
// Drives the look of the scene from the simulation's own clock and weather:
//   * sun position for Colombo (6.93 N, 79.85 E) at the simulated date and time
//     (same solar geometry the physics uses), so shadows fall the right way;
//   * cloud cover from the simulated weather (the overcast scenario greys the sky,
//     softens the sun and dims the light);
//   * a physical sky (Rayleigh/Mie scattering) that is also used as the
//     environment map, so the glass facade reflects the actual sky;
//   * night: stars, a faint moon light, and every room's own lights spilling onto
//     its floor in proportion to the lighting level the controller chose.
// Nothing here invents building data; it only renders what the state says.

import * as THREE from 'three';
import { Sky } from 'three/addons/objects/Sky.js';
import { SimulationClock } from '../core/SimulationClock.js';
import { VisualStateStore } from '../core/VisualStateStore.js';

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
    const tst = hour * 60 + eqt + 4 * LON - 60 * TZ;                  // true solar time, minutes
    const ha = (tst / 4 - 180) * Math.PI / 180;
    const cosZ = Math.sin(LAT) * Math.sin(decl) + Math.cos(LAT) * Math.cos(decl) * Math.cos(ha);
    const zen = Math.acos(Math.max(-1, Math.min(1, cosZ)));
    let az = Math.atan2(Math.sin(ha), Math.cos(ha) * Math.sin(LAT) - Math.tan(decl) * Math.cos(LAT));
    az = (az * 180 / Math.PI + 180) % 360;                             // 0 = north
    return { altitude: 90 - zen * 180 / Math.PI, azimuth: az };
}

function radialTexture() {
    const c = document.createElement('canvas');
    c.width = c.height = 128;
    const ctx = c.getContext('2d');
    const g = ctx.createRadialGradient(64, 64, 4, 64, 64, 64);
    g.addColorStop(0, 'rgba(255,236,200,1)');
    g.addColorStop(0.45, 'rgba(255,226,180,0.55)');
    g.addColorStop(1, 'rgba(255,220,170,0)');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, 128, 128);
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    return t;
}

class RealismEngineImpl {
    constructor() {
        this._app = null;
        this._sun = new THREE.Vector3(0, 1, 0);
        this._alt = 30;
        this._cloud = 0;
        this._envTimer = 0;
        this._envKey = '';
        this._pools = new Map();
        this.quality = 'high';
    }

    init(app) {
        this._app = app;
        app.realism = this;
        const scene = app.scene;

        // Physical sky
        this.sky = new Sky();
        this.sky.scale.setScalar(1800);
        this.sky.material.uniforms.mieDirectionalG.value = 0.8;
        scene.add(this.sky);
        app.camera.far = 4000;
        app.camera.updateProjectionMatrix();
        scene.background = null;

        // Environment (reflections) from the sky only
        this._pmrem = new THREE.PMREMGenerator(app.renderer);
        this._envScene = new THREE.Scene();
        this._envSky = new Sky();
        this._envSky.scale.setScalar(1000);
        this._envScene.add(this._envSky);
        this._envRT = null;

        // Stars (visible at night)
        const starGeo = new THREE.BufferGeometry();
        const pos = new Float32Array(1500 * 3);
        for (let i = 0; i < 1500; i++) {
            const u = Math.random(), v = Math.random() * 0.48 + 0.02;
            const th = 2 * Math.PI * u, ph = Math.acos(1 - v);
            pos[i * 3] = 1500 * Math.sin(ph) * Math.cos(th);
            pos[i * 3 + 1] = 1500 * Math.cos(ph);
            pos[i * 3 + 2] = 1500 * Math.sin(ph) * Math.sin(th);
        }
        starGeo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
        this.stars = new THREE.Points(starGeo, new THREE.PointsMaterial({ color: 0xffffff, size: 2.2, sizeAttenuation: false, transparent: true, opacity: 0, depthWrite: false, fog: false }));
        scene.add(this.stars);

        // Moonlight
        this.moon = new THREE.DirectionalLight(0x9fb4ff, 0);
        this.moon.position.set(-40, 60, -20);
        scene.add(this.moon);

        // Room light pools: each room's own lighting on its floor (from the controller's decision)
        const poolTex = radialTexture();
        app.roomData.forEach((d, key) => {
            const r = d.def;
            const geo = new THREE.PlaneGeometry(Math.max(1, r.w - 0.6), Math.max(1, r.d - 0.6));
            const mat = new THREE.MeshBasicMaterial({ map: poolTex, color: 0xffe2b0, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false });
            const m = new THREE.Mesh(geo, mat);
            m.rotation.x = -Math.PI / 2;
            m.position.set(r.x + r.w / 2, CONFIG_SLAB + 0.05, r.z + r.d / 2);
            m.renderOrder = 2;
            d.group.add(m);
            this._pools.set(key, { mesh: m, level: 0 });
        });

        // The facade glow planes were per floor, not per room: lights are shown per room instead
        (app.windowGlows || []).forEach((g) => { g.visible = false; });
        this._upgradeMaterials();
        this.update(0, true);
    }

    _upgradeMaterials() {
        const app = this._app;
        app.scene.traverse((o) => {
            if (!o.isMesh || !o.material) return;
            if (o.userData.isExteriorGlass) {
                // reflective, slightly tinted curtain-wall glass (reflects the simulated sky)
                o.material.transmission = 0;
                o.material.thickness = 0;
                o.material.roughness = 0.03;
                o.material.metalness = 0.35;
                o.material.color.setHex(0x6f9bb3);
                o.material.opacity = 0.42;
                o.userData.originalOpacity = 0.42;
                o.material.envMapIntensity = 3.0;
                o.material.needsUpdate = true;
            }
        });
    }

    setQuality(q) {
        this.quality = q === 'balanced' ? 'balanced' : 'high';
        const app = this._app;
        if (!app) return;
        const size = this.quality === 'high' ? 4096 : 2048;
        if (app.sunLight.shadow.mapSize.width !== size) {
            app.sunLight.shadow.mapSize.set(size, size);
            if (app.sunLight.shadow.map) { app.sunLight.shadow.map.dispose(); app.sunLight.shadow.map = null; }
        }
        if (app.gtaoPass) app.gtaoPass.enabled = this.quality === 'high';
        app.renderer.setPixelRatio(Math.min(window.devicePixelRatio, this.quality === 'high' ? 2 : 1));
    }

    onRoomStateChanged() { /* driven per frame from VisualStateStore */ }

    tick(delta) {
        this.update(delta, false);
    }

    update(delta, force) {
        const app = this._app;
        if (!app) return;
        // Sun from the simulated date/time; fall back to the hour if no date yet
        let alt, az;
        const iso = SimulationClock.backendTimeString;
        if (iso && iso.includes('T')) {
            const p = solarPosition(new Date(iso.slice(0, 19) + 'Z'));
            alt = p.altitude; az = p.azimuth;
        } else {
            const h = SimulationClock.hour;
            alt = Math.sin(((h - 6) / 12) * Math.PI) * 75; az = h < 12 ? 90 : 270;
        }
        const k = force ? 1 : Math.min(1, delta * 3);
        this._alt += (alt - this._alt) * k;
        const cloudTarget = Math.max(0, Math.min(1, SimulationClock.cloudCover || 0));
        this._cloud += (cloudTarget - this._cloud) * (force ? 1 : Math.min(1, delta * 1.5));
        const a = THREE.MathUtils.degToRad(this._alt), zz = THREE.MathUtils.degToRad(az);
        // scene axes: x = east, y = up, z = north (as in the building model)
        this._sun.set(Math.cos(a) * Math.sin(zz), Math.sin(a), Math.cos(a) * Math.cos(zz)).normalize();

        const day = THREE.MathUtils.smoothstep(this._alt, -8, 6);          // 0 night … 1 day
        const cloud = this._cloud;
        const u = this.sky.material.uniforms;
        u.sunPosition.value.copy(this._sun);
        // Scattered clouds keep a blue sky; heavy overcast (> 0.6) greys it out
        const heavy = THREE.MathUtils.smoothstep(cloud, 0.55, 0.95);
        u.turbidity.value = 1.8 + cloud * 2.5 + heavy * 12;
        u.rayleigh.value = 2.3 - 0.5 * cloud + heavy * 0.8;
        u.mieCoefficient.value = 0.003 + cloud * 0.004 + heavy * 0.03;

        // Sun light
        const cx = 15, cz = 10;
        const sunI = Math.max(0, Math.sin(a)) ** 0.5 * 5.2 * (1 - 0.35 * cloud - 0.55 * heavy);
        app.sunLight.intensity = sunI;
        app.sunLight.position.set(cx + this._sun.x * 90, Math.max(4, this._sun.y * 90), cz + this._sun.z * 90);
        app.sunLight.target.position.set(cx, 0, cz);
        if (!app.sunLight.target.parent) app.scene.add(app.sunLight.target);
        const warm = THREE.MathUtils.smoothstep(this._alt, 2, 25);
        app.sunLight.color.setRGB(1, 0.72 + 0.26 * warm, 0.5 + 0.44 * warm);
        app.sunLight.castShadow = sunI > 0.05;
        app.sunLight.shadow.radius = 2 + cloud * 8;
        if (app.hemiLight) {
            app.hemiLight.intensity = 0.08 + day * (0.35 + 0.45 * heavy);
            app.hemiLight.color.setHSL(0.58, 0.45 * (1 - heavy), 0.55 + 0.2 * day);
            app.hemiLight.groundColor.setHex(0x3d3a33);
        }
        if (app.ambientLight) app.ambientLight.intensity = 0.04 + 0.12 * day;
        if (app.fillLight) app.fillLight.intensity = 0.15 + 0.35 * day * (1 - cloud);
        this.moon.intensity = (1 - day) * 0.35;
        this.stars.material.opacity = (1 - day) * (1 - cloud) * 0.9;
        app.renderer.toneMappingExposure = 0.36 + (1 - day) * 0.6 + heavy * 0.2;

        // Fog/haze colour follows the sky near the horizon
        if (app.scene.fog) {
            const dayHaze = new THREE.Color().setHSL(0.585, 0.38 * (1 - heavy), 0.70 - 0.1 * heavy);
            app.scene.fog.color.copy(new THREE.Color(0x05070d).lerp(dayHaze, day));
            app.scene.fog.density = 0.0016 + heavy * 0.004 + (1 - day) * 0.001;
        }

        // Bloom only for real light sources: the bright daytime sky must not bloom
        if (app.bloomPass) {
            app.bloomPass.threshold = 1.0 + day * 9.0;
            app.bloomPass.strength = 0.25 + (1 - day) * 0.35;
        }

        // City windows light up at night
        if (app.cityWindowMat) app.cityWindowMat.emissiveIntensity = 0.05 + (1 - day) * 1.4;

        // Room light pools (per room, from the light level the controller chose)
        this._pools.forEach((p, key) => {
            const vs = VisualStateStore.get(key);
            const target = vs ? vs.lightTarget : 0;
            p.level += (target - p.level) * Math.min(1, (delta || 0.016) * 4);
            p.mesh.material.opacity = p.level * (0.10 + 0.55 * (1 - day));
            p.mesh.visible = p.level > 0.01;
        });

        // Reflections: re-render the sky into the environment map when it changes
        this._envTimer -= delta || 0;
        const key = `${Math.round(this._alt)}_${Math.round(az / 5)}_${Math.round(cloud * 10)}`;
        if (force || (this._envTimer <= 0 && key !== this._envKey)) {
            this._envTimer = 2.0;
            this._envKey = key;
            const eu = this._envSky.material.uniforms;
            for (const n of ['sunPosition', 'turbidity', 'rayleigh', 'mieCoefficient', 'mieDirectionalG']) {
                if (eu[n].value && eu[n].value.copy) eu[n].value.copy(u[n].value); else eu[n].value = u[n].value;
            }
            const rt = this._pmrem.fromScene(this._envScene, 0, 1, 4000);
            if (this._envRT) this._envRT.dispose();
            this._envRT = rt;
            app.scene.environment = rt.texture;
            app.scene.environmentIntensity = 0.12 + 0.28 * day + 0.25 * heavy;
        }
    }

    dispose() {
        this._pools.clear();
        this._app = null;
    }
}

const CONFIG_SLAB = 0.3;
export const RealismEngine = new RealismEngineImpl();
