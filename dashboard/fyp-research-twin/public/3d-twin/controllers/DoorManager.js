// ═══════════════════════════════════════════════════════════════
// DoorManager.js — Physical Door Mesh Creation & Registration
// ═══════════════════════════════════════════════════════════════
// Creates a hinged door mesh for each room and registers it in
// SceneRegistry. RoomController handles the rotation animation.

import * as THREE from 'three';
import { SceneRegistry, EntityType } from '../core/SceneRegistry.js';

class DoorManagerImpl {
    constructor() {
        this._doors = new Map(); // roomId → { pivot, panel }
    }

    /**
     * Create doors for all rooms in a floor.
     * @param {THREE.Group} floorGroup — The floor's scene group
     * @param {number} floorIndex — Floor index (0-based)
     * @param {Array} rooms — Room definitions from FLOOR_LAYOUTS
     * @param {number} y0 — Floor base Y position
     */
    createDoorsForFloor(floorGroup, floorIndex, rooms, y0) {
        rooms.forEach(roomDef => {
            if (roomDef.type === 'corridor') return; // Corridors don't have doors

            const roomId = `${floorIndex}_${roomDef.id}`;
            const door = this._createDoor(roomDef, y0);

            floorGroup.add(door.pivot);
            this._doors.set(roomId, door);

            // Register in SceneRegistry for O(1) lookup
            SceneRegistry.register(
                `${EntityType.DOOR}_${roomId}`,
                door.pivot,
                {
                    roomId,
                    floorId: floorIndex,
                    type: EntityType.DOOR,
                    doorPosition: door.position,
                    entrancePosition: door.entrancePosition,
                }
            );
        });
    }

    /**
     * Create a single hinged door.
     * Door is positioned at the room's front-left corner (near x, center z).
     */
    _createDoor(roomDef, y0) {
        // Door position: front wall, offset from left corner
        const doorX = roomDef.x + 1.5;     // 1.5 units from left wall
        const doorZ = roomDef.z;            // On the front wall (z = room.z)
        const doorW = 1.0;                  // Door width
        const doorH = 2.4;                  // Door height

        // Pivot point (hinge) at the left edge of the door
        const pivot = new THREE.Group();
        pivot.position.set(doorX, 0, doorZ); // Fix: Use 0 since it is added to the floorGroup which is already at y0
        pivot.userData.isDoor = true;
        pivot.userData.roomId = `${roomDef.id}`;

        // Door panel (offset from pivot so it swings on the hinge)
        const doorGeo = new THREE.BoxGeometry(doorW, doorH, 0.08);
        const doorMat = new THREE.MeshStandardMaterial({
            color: 0x8B6914,
            roughness: 0.7,
            metalness: 0.1,
        });

        const panel = new THREE.Mesh(doorGeo, doorMat);
        // Offset panel so hinge is at the left edge
        panel.position.set(doorW / 2, doorH / 2, 0);
        panel.castShadow = true;
        panel.receiveShadow = true;
        pivot.add(panel);

        // Door handle (small cylinder)
        const handleGeo = new THREE.CylinderGeometry(0.03, 0.03, 0.15, 8);
        const handleMat = new THREE.MeshStandardMaterial({
            color: 0xcccccc,
            metalness: 0.8,
            roughness: 0.2,
        });
        const handle = new THREE.Mesh(handleGeo, handleMat);
        handle.rotation.z = Math.PI / 2;
        handle.position.set(doorW - 0.15, doorH / 2, 0.06);
        pivot.add(handle);

        // Door frame (thin border)
        const frameMat = new THREE.MeshStandardMaterial({
            color: 0x555555,
            roughness: 0.5,
        });

        // Left frame
        const frameV = new THREE.Mesh(
            new THREE.BoxGeometry(0.08, doorH + 0.1, 0.12),
            frameMat
        );
        frameV.position.set(-0.04, doorH / 2, 0);
        pivot.add(frameV);

        // Right frame
        const frameV2 = frameV.clone();
        frameV2.position.set(doorW + 0.04, doorH / 2, 0);
        pivot.add(frameV2);

        // Top frame
        const frameH = new THREE.Mesh(
            new THREE.BoxGeometry(doorW + 0.16, 0.08, 0.12),
            frameMat
        );
        frameH.position.set(doorW / 2, doorH + 0.04, 0);
        pivot.add(frameH);

        // Entrance position (just outside the door, for avatar spawn point)
        const entrancePosition = {
            x: doorX + doorW / 2,
            z: doorZ - 1.0, // 1 unit outside the room
        };

        return {
            pivot,
            panel,
            position: { x: doorX, z: doorZ },
            entrancePosition,
        };
    }

    /**
     * Get door data for a room.
     */
    getDoor(roomId) {
        return this._doors.get(roomId) || null;
    }

    /**
     * Get the entrance position for a room (where avatars spawn).
     */
    getEntrancePosition(roomId) {
        const door = this._doors.get(roomId);
        return door?.entrancePosition || null;
    }

    /**
     * Get all door room IDs.
     */
    getRoomIds() {
        return [...this._doors.keys()];
    }

    dispose() {
        this._doors.forEach(door => {
            door.pivot.parent?.remove(door.pivot);
            door.pivot.traverse(child => {
                if (child.isMesh) {
                    child.geometry.dispose();
                    child.material.dispose();
                }
            });
        });
        this._doors.clear();
    }
}

export const DoorManager = new DoorManagerImpl();
