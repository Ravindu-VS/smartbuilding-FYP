import { create } from 'zustand';
import { BuildingStatePayload, RoomState, SystemState } from '../types/building';

interface BuildingStore {
  rooms: Record<string, RoomState>;
  system: SystemState | null;
  lastUpdate: number;
  isConnected: boolean;
  demoMode: boolean;
  
  // Actions
  updateFromSSE: (payload: BuildingStatePayload) => void;
  setConnectionStatus: (status: boolean) => void;
  toggleDemoMode: (status: boolean) => void;
  
  // Selectors
  getRoom: (id: string) => RoomState | undefined;
}

export const useBuildingStore = create<BuildingStore>((set, get) => ({
  rooms: {},
  system: null,
  lastUpdate: Date.now(),
  isConnected: false,
  demoMode: false,

  updateFromSSE: (payload) => {
    if (get().demoMode) return; // Ignore real SSE if demo mode is active
    
    set((state) => {
      const newRooms = { ...state.rooms };
      
      // The python backend may send data as hierarchical 'floors' array or flat 'rooms' array
      let allRooms: any[] = [];
      if (payload.rooms && Array.isArray(payload.rooms)) {
        allRooms = payload.rooms;
      } else if (payload.floors && Array.isArray(payload.floors)) {
        payload.floors.forEach((floor: any) => {
          if (floor.rooms && Array.isArray(floor.rooms)) {
            allRooms = allRooms.concat(floor.rooms);
          }
        });
      }

      allRooms.forEach((room) => {
        if (!room.room_id) return;
        
        // Ensure Room 101 (f2_office_a) is marked as LIVE hardware
        if (room.room_id === 'f2_office_a') {
          room.isLive = true;
          room.source = 'hardware';
        } else {
          room.isLive = false;
          room.source = 'simulation';
        }

        // Normalize uppercase sensor keys from python backend
        if (room.sensors) {
          const s = room.sensors;
          room.sensors = {
            temperature: s.Temperature ?? s.temperature,
            humidity: s.Humidity ?? s.humidity,
            light: s.Light ?? s.light,
            co2: s.CO2 ?? s.co2,
            occupancy: s.occupancy ?? s.Occupancy ?? 0
          };
        }
        
        newRooms[room.room_id] = room;
      });

      return {
        rooms: newRooms,
        system: payload.system,
        lastUpdate: Date.now(),
        isConnected: payload.system?.api_online ?? true
      };
    });
  },

  setConnectionStatus: (status) => set({ isConnected: status }),
  toggleDemoMode: (status) => set({ demoMode: status }),

  getRoom: (id) => get().rooms[id],
}));
