'use client';

import React from 'react';
import { Lightbulb, Snowflake, Users, Cpu, AlertTriangle, Wind, ChevronRight } from 'lucide-react';
import { backendIsCurrent, useBuildingStore } from '../../store/useBuildingStore';
import { fx, isNum } from '../../lib/format';
import type { RoomState } from '../../types/building';
import { FLOOR_NAMES } from '../../lib/floors';

function RoomRow({ r, selected, onClick, onEnter }: { r: RoomState; selected: boolean; onClick: () => void; onEnter: () => void }) {
  const hw = r.source === 'hardware';
  const connected = hw ? !!r.hardware?.connected : true;
  const people = hw ? (r.presence?.fused_presence == null ? null : r.presence.fused_presence ? 'present' : 'none') : r.ground_truth?.true_occupancy;
  const p = r.ai?.occupancy_probability;
  const light = r.control?.light_action;
  const ac = r.control?.hvac_action;
  const t = r.sensors?.Temperature;
  const busy = r.scenarios && r.scenarios.length > 0;
  return (
    <button
      onClick={onClick}
      onDoubleClick={onEnter}
      title="Click: select · double-click: open the room view in 3D"
      className={`w-full text-left px-2 py-1.5 rounded-md flex items-center gap-2 text-[11.5px] transition-colors ${selected ? 'bg-sky-900/50 ring-1 ring-sky-600' : 'hover:bg-slate-800/70'}`}
      data-testid={`nav-room-${r.room_id}`}
    >
      <span className={`w-1.5 h-6 rounded-full shrink-0 ${hw ? (connected ? 'bg-cyan-400' : 'bg-red-500') : isNum(p) && p >= 0.5 ? 'bg-sky-500' : 'bg-slate-700'}`} title={isNum(p) ? `AI P(occupied) ${p.toFixed(2)}` : 'no estimate'} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1">
          <span className={`truncate ${selected ? 'text-white font-semibold' : 'text-slate-200'}`}>{r.display_name}</span>
          {hw && <Cpu size={11} className={connected ? 'text-cyan-300' : 'text-red-400'} />}
          {busy && <span className="text-[9px] px-1 rounded bg-amber-900/60 text-amber-200 border border-amber-800">scenario</span>}
        </div>
        <div className="flex items-center gap-2 text-[10px] text-slate-500">
          <span className="flex items-center gap-0.5"><Users size={10} />{people ?? '—'}</span>
          <span>{fx(t, 1, '°C')}</span>
          {isNum(p) && <span>P {p.toFixed(2)}</span>}
        </div>
      </div>
      <Lightbulb size={13} className={light === 'ON' ? 'text-yellow-300' : light === 'DIM' ? 'text-yellow-600' : 'text-slate-700'} />
      <Snowflake size={13} className={ac === 'NORMAL' ? 'text-sky-300' : ac === 'LOW' ? 'text-sky-700' : 'text-slate-700'} />
      {r.control?.vent_boost ? <Wind size={13} className="text-emerald-300" /> : null}
    </button>
  );
}

export default function BuildingNav() {
  const raw = useBuildingStore((s) => s.raw);
  const link = useBuildingStore((s) => s.link);
  const rooms = useBuildingStore((s) => s.rooms);
  const selectedFloor = useBuildingStore((s) => s.selectedFloor);
  const selectedRoom = useBuildingStore((s) => s.selectedRoom);
  const selectFloor = useBuildingStore((s) => s.selectFloor);
  const selectRoom = useBuildingStore((s) => s.selectRoom);
  const requestTwinView = useBuildingStore((s) => s.requestTwinView);
  const live = link.connected && backendIsCurrent(raw);
  const floors = live ? [...raw!.floors].sort((a, b) => b.floor_id - a.floor_id) : [];
  const alerts = live ? raw!.alerts : [];

  return (
    <aside className="w-[268px] shrink-0 border-r border-slate-800 bg-slate-900/30 flex flex-col min-h-0">
      <div className="px-3 pt-3 pb-2 flex items-baseline justify-between">
        <h2 className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Building</h2>
        {live && <span className="text-[10px] text-slate-500">{raw!.system.people_simulated} people (simulated)</span>}
      </div>
      <div className="flex-1 overflow-y-auto px-2 pb-2 space-y-1.5">
        {!live && <div className="text-[11px] text-slate-500 px-2">Waiting for the edge brain…</div>}
        {floors.map((f) => {
          const open = f.floor_id === selectedFloor;
          const fr = Object.values(rooms).filter((r) => r.floor_id === f.floor_id);
          const diffKw = (f.ai_power_w - f.conv_power_w) / 1000;
          return (
            <div key={f.floor_id} className={`rounded-lg border ${open ? 'border-slate-600 bg-slate-800/40' : 'border-slate-800 bg-slate-900/40'}`}>
              <button className="w-full px-2.5 py-2 text-left" onClick={() => { selectFloor(f.floor_id); selectRoom(null); requestTwinView({ mode: 'floor', floor: f.floor_id }); }} data-testid={`nav-floor-${f.floor_id}`}>
                <div className="flex items-center gap-1.5">
                  <ChevronRight size={13} className={`text-slate-500 transition-transform ${open ? 'rotate-90' : ''}`} />
                  <span className="text-[12px] font-semibold text-slate-100 truncate">{FLOOR_NAMES[f.floor_id] ?? `Floor ${f.floor_id}`}</span>
                  {(f.hardware_rooms?.length ?? 0) > 0 && <Cpu size={11} className="text-cyan-300" />}
                </div>
                <div className="mt-1 grid grid-cols-3 gap-1 text-[10px] text-slate-400 pl-5">
                  <span title="People in the simulated rooms (simulator truth)"><Users size={10} className="inline mr-0.5" />{f.people}</span>
                  <span title="Electric power of this floor now (the building, as switched)">{fx(f.power_w / 1000, 1, ' kW')}</span>
                  <span title="Power now under AI minus power under AI off (same minute, digital twin)" className={isNum(diffKw) ? (diffKw <= 0 ? 'text-emerald-400' : 'text-orange-300') : ''}>
                    AI {isNum(diffKw) ? `${diffKw <= 0 ? '−' : '+'}${Math.abs(diffKw).toFixed(1)} kW` : '—'}
                  </span>
                </div>
              </button>
              {open && (
                <div className="px-1 pb-1.5 space-y-0.5">
                  {fr.map((r) => (
                    <RoomRow key={r.room_id} r={r} selected={selectedRoom === r.room_id} onClick={() => selectRoom(r.room_id)} onEnter={() => { selectRoom(r.room_id); requestTwinView({ mode: 'room', room: r.room_id }); }} />
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
      {alerts.length > 0 && (
        <div className="border-t border-slate-800 p-2 max-h-28 overflow-y-auto space-y-1" data-testid="alerts">
          {alerts.slice(0, 6).map((a, i) => (
            <button key={i} onClick={() => selectRoom(a.room_id)} className={`w-full text-left text-[10.5px] flex items-start gap-1 px-1.5 py-1 rounded border ${a.level === 'critical' ? 'border-red-800 bg-red-950/50 text-red-200' : 'border-amber-800/70 bg-amber-950/30 text-amber-200'}`}>
              <AlertTriangle size={11} className="mt-0.5 shrink-0" />{a.text}
            </button>
          ))}
        </div>
      )}
    </aside>
  );
}
