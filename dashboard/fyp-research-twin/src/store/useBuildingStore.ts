import { create } from 'zustand';
import {
  BuildingStatePayload, HardwareStatus, RoomState, SystemState, TwinSyncReport,
} from '../types/building';

// The last state received from the edge brain, kept exactly as sent.
// Which room is the hardware room and whether its board is connected come from the
// backend payload, never from the room id.

export interface LinkState {
  connected: boolean;              // SSE open AND a message arrived within STALE_AFTER_MS
  lastMessageAt: number | null;    // client clock (ms)
  messages: number;
  error: string | null;
}

export const STALE_AFTER_MS = 3000;

interface BuildingStore {
  rooms: Record<string, RoomState>;
  system: SystemState | null;
  hardware: HardwareStatus | null;
  raw: BuildingStatePayload | null;
  link: LinkState;
  twinSync: TwinSyncReport | null;

  updateFromSSE: (payload: BuildingStatePayload) => void;
  setLink: (patch: Partial<LinkState>) => void;
  setTwinSync: (report: TwinSyncReport) => void;
}

export const useBuildingStore = create<BuildingStore>((set) => ({
  rooms: {},
  system: null,
  hardware: null,
  raw: null,
  link: { connected: false, lastMessageAt: null, messages: 0, error: null },
  twinSync: null,

  updateFromSSE: (payload) => {
    const rooms: Record<string, RoomState> = {};
    for (const room of payload.rooms ?? []) {
      if (room && room.room_id) rooms[room.room_id] = room;
    }
    set((state) => ({
      rooms,
      system: payload.system ?? null,
      hardware: payload.hardware ?? null,
      raw: payload,
      link: {
        connected: true,
        lastMessageAt: Date.now(),
        messages: state.link.messages + 1,
        error: null,
      },
    }));
  },

  setLink: (patch) => set((state) => ({ link: { ...state.link, ...patch } })),
  setTwinSync: (report) => set({ twinSync: report }),
}));

/**
 * True when the payload comes from the current edge brain (raspberry_pi/edge_brain.py of
 * 19 Oct 2026 or later). An older edge brain still running on port 8001 sends a different
 * format without board status; the dashboard must not show that as live data.
 */
export function backendIsCurrent(system: SystemState | null | undefined): boolean {
  return !!system && typeof system.hardware_room_id === 'string'
    && typeof system.sim_estimated_power_watts === 'number' && !!system.hardware;
}

export function hardwareRoom(state: { rooms: Record<string, RoomState>; system: SystemState | null }) {
  const id = state.system?.hardware_room_id;
  return id ? state.rooms[id] : undefined;
}
