// ═══════════════════════════════════════════════════════════════
// SceneRegistry.js — O(1) Entity Lookup Registry
// ═══════════════════════════════════════════════════════════════
// Instead of scene.traverse(), maintain indexed maps for every
// visual entity type. Everything becomes O(1) lookup.
//
// Entity ID format: {type}_{floorIndex}_{roomId}_{index}
//   e.g., avatar_2_office_a_1, door_2_office_a, window_2_office_a

class SceneRegistryImpl {
    constructor() {
        // Primary indices: type → Map<entityId, mesh/group>
        this._entities = new Map();    // entityId → { mesh, roomId, floorId, type, metadata }

        // Secondary indices: fast lookup by room and type
        this._byRoom = new Map();      // roomId → Set<entityId>
        this._byType = new Map();      // type → Set<entityId>
        this._byFloor = new Map();     // floorId → Set<entityId>
    }

    /**
     * Register a visual entity.
     * @param {string} entityId — Unique ID (e.g., 'avatar_2_office_a_1')
     * @param {THREE.Object3D} mesh — The Three.js object
     * @param {object} info — { roomId, floorId, type, ...metadata }
     */
    register(entityId, mesh, info) {
        const entry = {
            mesh,
            roomId: info.roomId,
            floorId: info.floorId,
            type: info.type,
            metadata: info,
        };

        this._entities.set(entityId, entry);

        // Index by room
        if (info.roomId) {
            if (!this._byRoom.has(info.roomId)) this._byRoom.set(info.roomId, new Set());
            this._byRoom.get(info.roomId).add(entityId);
        }

        // Index by type
        if (info.type) {
            if (!this._byType.has(info.type)) this._byType.set(info.type, new Set());
            this._byType.get(info.type).add(entityId);
        }

        // Index by floor
        if (info.floorId !== undefined) {
            if (!this._byFloor.has(info.floorId)) this._byFloor.set(info.floorId, new Set());
            this._byFloor.get(info.floorId).add(entityId);
        }
    }

    /**
     * Get entity by exact ID. O(1).
     */
    get(entityId) {
        return this._entities.get(entityId) || null;
    }

    /**
     * Get mesh by exact ID. O(1).
     */
    getMesh(entityId) {
        return this._entities.get(entityId)?.mesh || null;
    }

    /**
     * Get all entities for a room. O(1) lookup, O(n) iteration.
     * @returns {Array<{entityId, mesh, type, metadata}>}
     */
    getByRoom(roomId) {
        const ids = this._byRoom.get(roomId);
        if (!ids) return [];
        return Array.from(ids).map(id => ({ entityId: id, ...this._entities.get(id) }));
    }

    /**
     * Get all entities of a type in a room. O(1) lookup.
     */
    getByRoomAndType(roomId, type) {
        const roomIds = this._byRoom.get(roomId);
        if (!roomIds) return [];
        return Array.from(roomIds)
            .filter(id => this._entities.get(id)?.type === type)
            .map(id => ({ entityId: id, ...this._entities.get(id) }));
    }

    /**
     * Get all entities of a type. O(1) lookup, O(n) iteration.
     */
    getByType(type) {
        const ids = this._byType.get(type);
        if (!ids) return [];
        return Array.from(ids).map(id => ({ entityId: id, ...this._entities.get(id) }));
    }

    /**
     * Get all entities on a floor.
     */
    getByFloor(floorId) {
        const ids = this._byFloor.get(floorId);
        if (!ids) return [];
        return Array.from(ids).map(id => ({ entityId: id, ...this._entities.get(id) }));
    }

    /**
     * Remove an entity from all indices.
     */
    unregister(entityId) {
        const entry = this._entities.get(entityId);
        if (!entry) return;

        if (entry.roomId) this._byRoom.get(entry.roomId)?.delete(entityId);
        if (entry.type) this._byType.get(entry.type)?.delete(entityId);
        if (entry.floorId !== undefined) this._byFloor.get(entry.floorId)?.delete(entityId);
        this._entities.delete(entityId);
    }

    /**
     * Total registered entities (for debug).
     */
    get size() { return this._entities.size; }

    /**
     * Get stats for debug overlay.
     */
    getStats() {
        const stats = {};
        this._byType.forEach((ids, type) => {
            stats[type] = ids.size;
        });
        return stats;
    }

    /**
     * Clear all registrations.
     */
    dispose() {
        this._entities.clear();
        this._byRoom.clear();
        this._byType.clear();
        this._byFloor.clear();
    }
}

// Singleton
export const SceneRegistry = new SceneRegistryImpl();

// Entity type constants
export const EntityType = {
    AVATAR: 'avatar',
    DOOR: 'door',
    WINDOW: 'window',
    FAN: 'fan',
    LIGHT: 'light',
    MONITOR: 'monitor',
    FURNITURE: 'furniture',
    FLOOR_SLAB: 'floor_slab',
    WALL: 'wall',
    BADGE: 'badge',
    PARTICLE: 'particle',
    ENERGY_LINE: 'energy_line',
    HERO_RING: 'hero_ring',
    DEBUG_SPRITE: 'debug_sprite',
};
