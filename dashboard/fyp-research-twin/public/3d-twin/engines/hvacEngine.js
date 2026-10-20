// ═══════════════════════════════════════════════════════════════
// HVACEngine.js — AI-Driven HVAC & Window Control (WITH AIRFLOW PARTICLES)
// ═══════════════════════════════════════════════════════════════

import * as THREE from 'three';
import { VisualStateStore } from '../core/VisualStateStore.js';
import { eventBus, Events } from '../core/EventBus.js';
import { dampedLerp } from '../animation/Tween.js';

class HVACEngineImpl {
    constructor() {
        this._app = null;
        this._roomWindowAngles = new Map();
        this._roomFanSpeeds = new Map();
        this._particleSystems = new Map(); // roomId -> { points, geometry, velocities, count }
        this._particleTexture = null;
    }

    init(app) {
        this._app = app;
        
        // Create a radial gradient texture for glowing particles
        const canvas = document.createElement('canvas');
        canvas.width = 32; canvas.height = 32;
        const ctx = canvas.getContext('2d');
        const grad = ctx.createRadialGradient(16, 16, 0, 16, 16, 16);
        grad.addColorStop(0, 'rgba(255,255,255,1)');
        grad.addColorStop(0.2, 'rgba(0, 200, 255, 1)');
        grad.addColorStop(0.5, 'rgba(0, 100, 255, 0.5)');
        grad.addColorStop(1, 'rgba(0,0,0,0)');
        ctx.fillStyle = grad;
        ctx.fillRect(0, 0, 32, 32);
        
        this._particleTexture = new THREE.CanvasTexture(canvas);
    }

    _createParticleSystem(roomId) {
        const roomData = this._app.roomData.get(roomId);
        if (!roomData || !roomData.def || !roomData.group) return null;
        
        const rd = roomData.def;
        const count = 400;
        
        const geometry = new THREE.BufferGeometry();
        const positions = new Float32Array(count * 3);
        const velocities = new Float32Array(count * 3);
        const alphas = new Float32Array(count);
        
        for(let i=0; i<count; i++) {
            // Start at ceiling vent (center of room)
            positions[i*3] = rd.x + rd.w/2 + (Math.random()-0.5);
            positions[i*3+1] = 3.2; // near the ceiling (coordinates are local to the floor)
            positions[i*3+2] = rd.z + rd.d/2 + (Math.random()-0.5);
            
            velocities[i*3] = (Math.random() - 0.5) * 2;
            velocities[i*3+1] = -1.0 - Math.random(); // downward
            velocities[i*3+2] = (Math.random() - 0.5) * 2;
            
            alphas[i] = Math.random();
        }
        
        geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
        geometry.setAttribute('alpha', new THREE.BufferAttribute(alphas, 1));
        
        // ShaderMaterial for glowing, fading particles
        const material = new THREE.ShaderMaterial({
            uniforms: {
                pointTexture: { value: this._particleTexture },
                color: { value: new THREE.Color(0x00c8ff) }
            },
            vertexShader: `
                attribute float alpha;
                varying float vAlpha;
                void main() {
                    vAlpha = alpha;
                    vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
                    gl_PointSize = (15.0 / -mvPosition.z);
                    gl_Position = projectionMatrix * mvPosition;
                }
            `,
            fragmentShader: `
                uniform vec3 color;
                uniform sampler2D pointTexture;
                varying float vAlpha;
                void main() {
                    gl_FragColor = vec4(color * 2.5, vAlpha) * texture2D(pointTexture, gl_PointCoord);
                }
            `,
            transparent: true,
            blending: THREE.AdditiveBlending,
            depthWrite: false
        });
        
        const points = new THREE.Points(geometry, material);
        points.visible = false;
        
        // Add to the floor group
        roomData.group.add(points);
        
        return { points, geometry, velocities, count, rd, floorY: 0.3 };
    }

    onRoomStateChanged({ roomId, backendState, visualState }) {
        if (!this._roomWindowAngles.has(roomId)) this._roomWindowAngles.set(roomId, 0);
        if (!this._roomFanSpeeds.has(roomId)) this._roomFanSpeeds.set(roomId, 0);

        if (!this._particleSystems.has(roomId)) {
            const sys = this._createParticleSystem(roomId);
            if (sys) this._particleSystems.set(roomId, sys);
        }

        const vs = visualState;
        
        // Show particles while the AC runs (NORMAL = cooling, LOW = set-back)
        const sys = this._particleSystems.get(roomId);
        if (sys) {
            sys.points.visible = (vs.hvacVisualMode === 'cooling' || vs.hvacVisualMode === 'ventilation');
        }

        const prevAngle = this._roomWindowAngles.get(roomId);
        if (vs.windowTarget > 0.1 && prevAngle < 0.1) eventBus.emit(Events.WINDOW_OPENED, { roomId });
        else if (vs.windowTarget < 0.1 && prevAngle > 0.1) eventBus.emit(Events.WINDOW_CLOSED, { roomId });

        eventBus.emit(Events.HVAC_CHANGED, { roomId, action: vs.hvacVisualMode, speed: vs.fanSpeed });
    }

    tick(delta) {
        if (!this._app) return;

        this._roomFanSpeeds.forEach((currentSpeed, roomId) => {
            const vs = VisualStateStore.get(roomId);
            this._roomFanSpeeds.set(roomId, dampedLerp(currentSpeed, vs.fanSpeed, 0.1, delta));
            
            // Update particles
            const sys = this._particleSystems.get(roomId);
            if (sys && sys.points.visible) {
                const pos = sys.geometry.attributes.position.array;
                const alpha = sys.geometry.attributes.alpha.array;
                const vel = sys.velocities;
                
                // Increase speed based on fan speed
                const speedMult = (vs.hvacVisualMode === 'cooling') ? 2.0 : 1.0;
                
                for(let i=0; i<sys.count; i++) {
                    let i3 = i * 3;
                    pos[i3] += vel[i3] * delta * speedMult;
                    pos[i3+1] += vel[i3+1] * delta * speedMult;
                    pos[i3+2] += vel[i3+2] * delta * speedMult;
                    
                    alpha[i] -= delta * 0.5 * speedMult;
                    
                    // Reset if hits floor or fades out
                    if (pos[i3+1] < sys.floorY + 0.1 || alpha[i] <= 0) {
                        pos[i3] = sys.rd.x + sys.rd.w/2 + (Math.random()-0.5) * 1.5;
                        pos[i3+1] = 3.2; // ceiling
                        pos[i3+2] = sys.rd.z + sys.rd.d/2 + (Math.random()-0.5) * 1.5;
                        
                        vel[i3] = (Math.random() - 0.5) * 2;
                        vel[i3+1] = -1.0 - Math.random() * 2;
                        vel[i3+2] = (Math.random() - 0.5) * 2;
                        
                        alpha[i] = 1.0;
                    }
                }
                sys.geometry.attributes.position.needsUpdate = true;
                sys.geometry.attributes.alpha.needsUpdate = true;
            }
        });
    }

    dispose() {
        this._roomWindowAngles.clear();
        this._roomFanSpeeds.clear();
        this._particleSystems.clear();
        this._app = null;
    }
}

export const HVACEngine = new HVACEngineImpl();
