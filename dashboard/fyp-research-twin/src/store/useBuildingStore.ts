import { create } from 'zustand';
import {
  BuildingConfig, BuildingStatePayload, HardwareStatus, RoomState, SystemState, TwinSyncReport,
} from '../types/building';

// The last state received from the edge brain, kept exactly as sent, plus what the
// user is looking at (selected floor/room, overlay). Which room is the hardware room
// and whether its board is connected come from the backend payload.

export const API_VERSION = 3;

export interface LinkState {
  connected: boolean;              // SSE open AND a message arrived within STALE_AFTER_MS
  lastMessageAt: number | null;    // client clock (ms)
  messages: number;
  error: string | null;
}

export type Overlay = 'none' | 'comfort' | 'temperature' | 'power' | 'estimate';

export const STALE_AFTER_MS = 3000;

/** The three levels of the 3D view. */
export type TwinMode = 'building' | 'floor' | 'room';
export interface TwinView { mode: TwinMode; floor: number | null; room: string | null; eye: boolean; preset?: string; isolated?: number | null }
export type TwinLighting = 'live' | 'day' | 'golden' | 'night';
export interface TwinLayers { people: boolean; airflow: boolean; labels: boolean }
export interface TwinStats { fps: number; calls: number; triangles: number; quality: 'high' | 'balanced'; auto: boolean }

interface BuildingStore {
  rooms: Record<string, RoomState>;
  system: SystemState | null;
  hardware: HardwareStatus | null;
  raw: BuildingStatePayload | null;
  link: LinkState;
  twinSync: TwinSyncReport | null;
  config: BuildingConfig | null;

  selectedFloor: number;
  selectedRoom: string | null;
  overlay: Overlay;
  bottomTab: 'decisions' | 'analytics' | 'meter' | 'models';
  demoOpen: boolean;
  bottomCollapsed: boolean;

  // 3D view: what it shows (reported by the twin) and what the user asked for
  twinView: TwinView;
  twinRequest: { seq: number; view: { mode: TwinMode; floor?: number | null; room?: string | null; eye?: boolean }; preset?: string } | null;
  twinLayers: TwinLayers;
  twinLighting: TwinLighting;
  twinQuality: 'high' | 'balanced';
  twinStats: TwinStats | null;
  presentation: boolean;
  tour: boolean;

  updateFromSSE: (payload: BuildingStatePayload) => void;
  setLink: (patch: Partial<LinkState>) => void;
  setTwinSync: (report: TwinSyncReport) => void;
  setConfig: (cfg: BuildingConfig) => void;
  selectFloor: (f: number) => void;
  selectRoom: (id: string | null) => void;
  setOverlay: (o: Overlay) => void;
  setBottomTab: (t: 'decisions' | 'analytics' | 'meter' | 'models') => void;
  setDemoOpen: (v: boolean) => void;
  setBottomCollapsed: (v: boolean) => void;
  setTwinView: (v: TwinView) => void;
  requestTwinView: (view: { mode: TwinMode; floor?: number | null; room?: string | null; eye?: boolean }, preset?: string) => void;
  setTwinLayers: (p: Partial<TwinLayers>) => void;
  setTwinLighting: (l: TwinLighting) => void;
  setTwinQuality: (q: 'high' | 'balanced') => void;
  setTwinStats: (s: TwinStats) => void;
  setPresentation: (v: boolean) => void;
  setTour: (v: boolean) => void;
}

export const useBuildingStore = create<BuildingStore>((set) => ({
  rooms: {},
  system: null,
  hardware: null,
  raw: null,
  link: { connected: false, lastMessageAt: null, messages: 0, error: null },
  twinSync: null,
  config: null,

  selectedFloor: 2,
  selectedRoom: null,
  overlay: 'none',
  bottomTab: 'decisions',
  demoOpen: false,
  bottomCollapsed: false,
  twinView: { mode: 'building', floor: null, room: null, eye: false },
  twinRequest: null,
  twinLayers: { people: true, airflow: false, labels: true },
  twinLighting: 'live',
  twinQuality: 'high',
  twinStats: null,
  presentation: false,
  tour: false,

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
      link: { connected: true, lastMessageAt: Date.now(), messages: state.link.messages + 1, error: null },
    }));
  },

  setLink: (patch) => set((state) => ({ link: { ...state.link, ...patch } })),
  setTwinSync: (report) => set({ twinSync: report }),
  setConfig: (config) => set({ config }),
  selectFloor: (selectedFloor) => set({ selectedFloor }),
  selectRoom: (selectedRoom) => set((s) => ({
    selectedRoom,
    selectedFloor: selectedRoom && s.rooms[selectedRoom] ? s.rooms[selectedRoom].floor_id : s.selectedFloor,
  })),
  setOverlay: (overlay) => set({ overlay }),
  setBottomTab: (bottomTab) => set({ bottomTab, bottomCollapsed: false }),
  setDemoOpen: (demoOpen) => set({ demoOpen }),
  setBottomCollapsed: (bottomCollapsed) => set({ bottomCollapsed }),
  setTwinView: (twinView) => set({ twinView }),
  requestTwinView: (view, preset) => set((s) => ({ twinRequest: { seq: (s.twinRequest?.seq ?? 0) + 1, view, preset } })),
  setTwinLayers: (p) => set((s) => ({ twinLayers: { ...s.twinLayers, ...p } })),
  setTwinLighting: (twinLighting) => set({ twinLighting }),
  setTwinQuality: (twinQuality) => set({ twinQuality }),
  setTwinStats: (twinStats) => set({ twinStats }),
  setPresentation: (presentation) => set({ presentation }),
  setTour: (tour) => set({ tour }),
}));

/** True when the payload comes from the current edge brain (API v3, twin/live.py). */
export function backendIsCurrent(raw: BuildingStatePayload | null | undefined): boolean {
  return !!raw && raw.api_version === API_VERSION && !!raw.clock && !!raw.meter && !!raw.system?.hardware;
}

export function hardwareRoom(state: { rooms: Record<string, RoomState>; system: SystemState | null }) {
  const id = state.system?.hardware_room_id;
  return id ? state.rooms[id] : undefined;
}

// Development only: lets the automated end-to-end tests drive the dashboard like a user would.
if (typeof window !== 'undefined' && process.env.NODE_ENV !== 'production') {
  (window as unknown as Record<string, unknown>).__buildingStore = useBuildingStore;
}
