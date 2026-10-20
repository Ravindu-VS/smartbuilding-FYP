// ═══════════════════════════════════════════════════════════════
// AvatarPool.js — Pre-allocated Reusable Avatar Mesh Pool
// ═══════════════════════════════════════════════════════════════
// Object pooling pattern: pre-create N avatar meshes, acquire/release
// as occupancy changes. Avoids runtime mesh creation/disposal.

import * as THREE from 'three';
import { SIM_CONFIG } from '../core/SimConfig.js';
import { SceneRegistry, EntityType } from '../core/SceneRegistry.js';
import { seededRandom, hashString } from '../animation/Tween.js';

class AvatarPoolImpl {
    constructor() {
        this._pool = [];        // All avatars (free + in-use)
        this._free = [];        // Available avatar indices
        this._inUse = new Map(); // roomId → Set<poolIndex>
        this._scene = null;
    }

    /**
     * Initialize the pool by pre-creating avatar meshes.
     */
    init(scene) {
        this._scene = scene;
        const size = SIM_CONFIG.avatarPool.INITIAL_SIZE;

        for (let i = 0; i < size; i++) {
            const avatar = this._createAvatar(i);
            avatar.visible = false;
            scene.add(avatar);
            this._pool.push(avatar);
            this._free.push(i);
        }

        console.log(`[AvatarPool] Pre-allocated ${size} avatars.`);
    }

    /**
     * Create a single avatar mesh group.
     */
    _createAvatar(poolIndex) {
        const group = new THREE.Group();
        group.userData.poolIndex = poolIndex;
        group.userData.state = 'idle';        // idle | walking | seated | exiting
        group.userData.walkTarget = null;      // {x, z} destination
        group.userData.walkProgress = 0;       // 0–1
        group.userData.walkStart = null;       // {x, z} start position
        group.userData.seatPosition = null;    // final desk position
        group.userData.roomId = null;
        group.userData.baseY = 0;
        group.userData.animOffset = Math.random() * 100;

        // Deterministic appearance
        const rng = seededRandom(poolIndex * 7919);
        const shirtIdx = Math.floor(rng() * SIM_CONFIG.avatarPool.SHIRT_COLORS.length);
        const heightScale = SIM_CONFIG.avatarPool.HEIGHT_RANGE[0] +
            rng() * (SIM_CONFIG.avatarPool.HEIGHT_RANGE[1] - SIM_CONFIG.avatarPool.HEIGHT_RANGE[0]);

        const skinMat = new THREE.MeshStandardMaterial({ color: 0xffccaa, roughness: 0.6 });
        const shirtMat = new THREE.MeshStandardMaterial({
            color: SIM_CONFIG.avatarPool.SHIRT_COLORS[shirtIdx], roughness: 0.8
        });
        const pantsMat = new THREE.MeshStandardMaterial({ color: 0x112244, roughness: 0.9 });

        // Torso
        const torso = new THREE.Mesh(new THREE.BoxGeometry(0.4, 0.6, 0.2), shirtMat);
        torso.position.y = 1.0;
        torso.castShadow = true;
        group.add(torso);

        // Head
        const head = new THREE.Mesh(new THREE.BoxGeometry(0.25, 0.3, 0.25), skinMat);
        head.position.y = 1.45;
        head.castShadow = true;
        group.add(head);

        // Arms
        const armGeo = new THREE.BoxGeometry(0.12, 0.5, 0.12);
        const leftArm = new THREE.Mesh(armGeo, skinMat);
        leftArm.position.set(-0.28, 1.0, 0);
        leftArm.castShadow = true;
        const rightArm = new THREE.Mesh(armGeo, skinMat);
        rightArm.position.set(0.28, 1.0, 0);
        rightArm.castShadow = true;
        group.add(leftArm, rightArm);

        // Legs
        const legGeo = new THREE.BoxGeometry(0.16, 0.7, 0.16);
        const leftLeg = new THREE.Mesh(legGeo, pantsMat);
        leftLeg.position.set(-0.1, 0.35, 0);
        leftLeg.castShadow = true;
        const rightLeg = new THREE.Mesh(legGeo, pantsMat);
        rightLeg.position.set(0.1, 0.35, 0);
        rightLeg.castShadow = true;
        group.add(leftLeg, rightLeg);

        // Store limb references for animation
        group.userData.limbs = { leftArm, rightArm, leftLeg, rightLeg, head };

        group.scale.setScalar(heightScale);
        return group;
    }

    /**
     * Acquire an avatar from the pool for a room.
     * @returns {THREE.Group|null} — The avatar mesh, or null if pool exhausted.
     */
    acquire(roomId, floorGroup, startPos, targetPos) {
        if (this._free.length === 0) {
            // Dynamically grow if under max
            if (this._pool.length < SIM_CONFIG.avatarPool.MAX_SIZE) {
                const idx = this._pool.length;
                const avatar = this._createAvatar(idx);
                avatar.visible = false;
                this._scene.add(avatar);
                this._pool.push(avatar);
                this._free.push(idx);
            } else {
                return null;
            }
        }

        const idx = this._free.pop();
        const avatar = this._pool[idx];
        
        // Reparent to floor group so it moves during explode mode
        if (avatar.parent !== floorGroup) {
            floorGroup.add(avatar);
        }

        // Configure for this room
        avatar.userData.roomId = roomId;
        avatar.userData.baseY = 0.32; // local to the floor group: standing on the slab (0.3 m) + floor finish
        avatar.userData.state = 'walking';
        avatar.userData.walkStart = { x: startPos.x, z: startPos.z };
        avatar.userData.walkTarget = { x: targetPos.x, z: targetPos.z };
        avatar.userData.seatPosition = { x: targetPos.x, z: targetPos.z };
        avatar.userData.walkProgress = 0;

        // Position at start (door entrance)
        avatar.position.set(startPos.x, 0.32, startPos.z);
        avatar.visible = true;

        // Track in-use
        if (!this._inUse.has(roomId)) this._inUse.set(roomId, new Set());
        this._inUse.get(roomId).add(idx);

        // Register in SceneRegistry
        SceneRegistry.register(
            `${EntityType.AVATAR}_pool_${idx}`,
            avatar,
            { roomId, floorId: parseInt(String(roomId).split('_')[0], 10), type: EntityType.AVATAR, poolIndex: idx }
        );

        return avatar;
    }

    /**
     * Release an avatar back to the pool.
     */
    release(poolIndex) {
        const avatar = this._pool[poolIndex];
        if (!avatar) return;

        const roomId = avatar.userData.roomId;
        avatar.visible = false;
        avatar.userData.state = 'idle';
        avatar.userData.roomId = null;

        // Remove from in-use tracking
        this._inUse.get(roomId)?.delete(poolIndex);
        this._free.push(poolIndex);

        SceneRegistry.unregister(`${EntityType.AVATAR}_pool_${poolIndex}`);
    }

    /**
     * Release all avatars in a room.
     */
    releaseRoom(roomId) {
        const indices = this._inUse.get(roomId);
        if (!indices) return;

        // Copy to avoid mutation during iteration
        const toRelease = [...indices];
        toRelease.forEach(idx => this.release(idx));
    }

    /**
     * Get all active avatars in a room.
     */
    getActiveInRoom(roomId) {
        const indices = this._inUse.get(roomId);
        if (!indices) return [];
        return [...indices].map(idx => this._pool[idx]);
    }

    /**
     * Count active avatars in a room.
     */
    countInRoom(roomId) {
        return this._inUse.get(roomId)?.size || 0;
    }

    /**
     * Get all pool stats.
     */
    getStats() {
        return {
            total: this._pool.length,
            free: this._free.length,
            inUse: this._pool.length - this._free.length,
        };
    }

    dispose() {
        this._pool.forEach(avatar => {
            avatar.parent?.remove(avatar);
            avatar.traverse(child => {
                if (child.isMesh) {
                    child.geometry.dispose();
                    child.material.dispose();
                }
            });
        });
        this._pool = [];
        this._free = [];
        this._inUse.clear();
    }
}

export const AvatarPool = new AvatarPoolImpl();
