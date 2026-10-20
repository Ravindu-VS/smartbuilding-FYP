'use client';

import React, { useState } from 'react';
import { ChevronDown, ChevronUp, Users, Thermometer, Lightbulb, Snowflake, Zap, Cpu, Wind, Brain, DoorOpen } from 'lucide-react';
import { backendIsCurrent, useBuildingStore } from '../../store/useBuildingStore';
import { FLOOR_NAMES } from '../../lib/floors';
import { acLabel, fx, isNum, TYPE_LABEL } from '../../lib/format';
import type { RoomState } from '../../types/building';

/**
 * Context panel of the 3D view: what matters at the current level, straight from
 * the edge brain's state. Building: AI on/off and power now vs the same minute in
 * the twin; floor: its rooms; room: occupancy, comfort, devices and the AI's reason.
 */

const glass = 'bg-slate-950/85 backdrop-blur-md border border-slate-700/70 shadow-xl shadow-black/40';

function Stat({ label, value, sub, tone }: { label: string; value: React.ReactNode; sub?: React.ReactNode; tone?: 'ai' | 'off' | 'good' | 'bad' }) {
  const c = tone === 'ai' ? 'text-[#6ea8f0]' : tone === 'off' ? 'text-[#e8865a]' : tone === 'good' ? 'text-emerald-300' : tone === 'bad' ? 'text-red-300' : 'text-white';
  return (
    <div className="bg-slate-900/70 rounded-lg px-2 py-1.5 border border-slate-800 min-w-0">
      <div className="text-[9.5px] uppercase tracking-wider text-slate-500 truncate">{label}</div>
      <div className={`text-[14px] font-bold leading-tight ${c}`}>{value}</div>
      {sub && <div className="text-[9.5px] text-slate-500 leading-tight truncate">{sub}</div>}
    </div>
  );
}

function people(r: RoomState) {
  if (r.source === 'hardware') return !r.hardware?.connected ? '—' : r.presence?.fused_presence ? 'present' : 'none';
  return r.ground_truth ? String(r.ground_truth.true_occupancy) : '—';
}

export default function TwinContext() {
  const raw = useBuildingStore((s) => s.raw);
  const rooms = useBuildingStore((s) => s.rooms);
  const view = useBuildingStore((s) => s.twinView);
  const selectRoom = useBuildingStore((s) => s.selectRoom);
  const request = useBuildingStore((s) => s.requestTwinView);
  const presentation = useBuildingStore((s) => s.presentation);
  const demoOpen = useBuildingStore((s) => s.demoOpen);
  const selectedRoom = useBuildingStore((s) => s.selectedRoom);
  const [openState, setOpen] = useState<boolean | null>(null);
  if (!backendIsCurrent(raw) || demoOpen) return null;
  // in the dashboard the panels on the right already show the details: start folded
  const open = openState ?? presentation;
  const m = raw!.meter;
  const aiKw = m.mode === 'ai' ? m.power_kw : m.other_power_kw;
  const offKw = m.mode === 'ai' ? m.other_power_kw : m.power_kw;
  const savingNow = isNum(aiKw) && isNum(offKw) && offKw > 0 ? (100 * (offKw - aiKw)) / offKw : null;
  const width = presentation ? 'w-[380px]' : 'w-[310px]';

  let title = 'Smart Hub · whole building';
  let body: React.ReactNode = null;

  if (view.mode === 'building') {
    const hw = raw!.hardware;
    const seg = m.current;
    body = (
      <>
        <div className="grid grid-cols-2 gap-1.5">
          <Stat label="Control now" value={raw!.ai_enabled ? 'AI ON' : 'AI OFF'} tone={raw!.ai_enabled ? 'good' : 'off'} sub={raw!.ai_enabled ? 'every room decided by the AI' : 'conventional schedule'} />
          <Stat label="People inside" value={raw!.system.people_simulated} sub={`${raw!.system.occupied_rooms} of ${raw!.system.simulated_rooms} simulated rooms occupied`} />
          <Stat label="Power with AI" value={`${fx(aiKw, 1)} kW`} tone="ai" sub={m.mode === 'ai' ? 'the building (switched)' : 'its twin, same minute'} />
          <Stat label="Power AI off" value={`${fx(offKw, 1)} kW`} tone="off" sub={m.mode === 'ai' ? 'its twin, same minute' : 'the building (switched)'} />
        </div>
        <div className="flex items-center justify-between text-[11px] mt-1.5 px-0.5">
          <span className="text-slate-400">Saving right now</span>
          <span className={`font-bold ${isNum(savingNow) && savingNow >= 0 ? 'text-emerald-300' : 'text-orange-300'}`}>{fx(savingNow, 1, ' %')}</span>
        </div>
        {seg && (
          <div className="flex items-center justify-between text-[11px] px-0.5">
            <span className="text-slate-400">Since the last switch ({Math.round(seg.minutes)} min)</span>
            <span className="text-slate-200">{fx(seg.kwh, 1)} vs {fx(seg.other_kwh, 1)} kWh</span>
          </div>
        )}
        <button onClick={() => hw && request({ mode: 'room', room: hw.room_id })} className="mt-1.5 w-full flex items-center gap-2 px-2 py-1.5 rounded-lg border border-cyan-800/70 bg-cyan-950/30 text-left hover:border-cyan-500" data-testid="ctx-live-room">
          <Cpu size={14} className={hw?.connected ? 'text-cyan-300' : 'text-red-400'} />
          <div className="min-w-0 flex-1">
            <div className="text-[11.5px] text-white font-semibold">Live room · {hw?.room_name ?? 'Office A'}</div>
            <div className="text-[10px] text-slate-400 truncate">{hw?.connected ? `ESP32 streaming · ${hw.readings_received} readings` : hw?.state === 'lost' ? 'board lost — values hidden' : 'board not connected — values hidden, never invented'}</div>
          </div>
          <DoorOpen size={13} className="text-slate-500" />
        </button>
      </>
    );
  } else if (view.mode === 'floor' && view.floor !== null) {
    const f = raw!.floors.find((x) => x.floor_id === view.floor);
    const list = Object.values(rooms).filter((r) => r.floor_id === view.floor);
    title = FLOOR_NAMES[view.floor] ?? `Floor ${view.floor}`;
    const diff = f ? (f.ai_power_w - f.conv_power_w) / 1000 : null;
    body = (
      <>
        {f && (
          <div className="grid grid-cols-3 gap-1.5">
            <Stat label="People" value={f.people} />
            <Stat label="Power now" value={`${fx(f.power_w / 1000, 1)} kW`} />
            <Stat label="AI vs off" value={`${isNum(diff) ? (diff <= 0 ? '−' : '+') : ''}${fx(isNum(diff) ? Math.abs(diff) : null, 1)} kW`} tone={isNum(diff) && diff <= 0 ? 'good' : 'off'} sub="same minute" />
          </div>
        )}
        <div className="mt-1.5 space-y-0.5 max-h-[220px] overflow-y-auto pr-0.5">
          {list.map((r) => {
            const hw = r.source === 'hardware';
            return (
              <button key={r.room_id} onClick={() => selectRoom(r.room_id)} onDoubleClick={() => request({ mode: 'room', room: r.room_id })}
                className="w-full grid grid-cols-[1fr_42px_46px_22px_22px] items-center gap-1 px-1.5 py-1 rounded-md hover:bg-slate-800/80 text-[11px] text-left" title="Click: select · double-click: room view">
                <span className="truncate text-slate-200 flex items-center gap-1">{r.display_name}{hw && <Cpu size={10} className={r.hardware?.connected ? 'text-cyan-300' : 'text-red-400'} />}</span>
                <span className="text-slate-400 flex items-center gap-0.5"><Users size={10} />{people(r)}</span>
                <span className="text-slate-400">{fx(r.sensors?.Temperature, 1, '°')}</span>
                <Lightbulb size={12} className={r.control?.light_action === 'ON' ? 'text-yellow-300' : r.control?.light_action === 'DIM' ? 'text-yellow-600' : 'text-slate-700'} />
                <Snowflake size={12} className={r.control?.hvac_action === 'NORMAL' ? 'text-sky-300' : r.control?.hvac_action === 'LOW' ? 'text-sky-700' : 'text-slate-700'} />
              </button>
            );
          })}
        </div>
        <div className="text-[9.5px] text-slate-500 mt-1">Double-click a room (here or in 3D) to go inside.</div>
      </>
    );
  } else if (view.mode === 'room' && view.room && rooms[view.room]) {
    const r = rooms[view.room];
    const hw = r.source === 'hardware';
    const connected = hw ? !!r.hardware?.connected : true;
    title = r.display_name;
    const ai = r.modes?.ai, conv = r.modes?.conventional;
    body = (
      <>
        <div className="flex items-center gap-1.5 mb-1.5">
          <span className={`text-[9.5px] font-bold px-1.5 py-0.5 rounded border ${hw ? 'border-cyan-600 text-cyan-300 bg-cyan-950/40' : 'border-slate-600 text-slate-300 bg-slate-800/60'}`}>{hw ? 'LIVE · ESP32' : 'SIMULATED'}</span>
          <span className="text-[10.5px] text-slate-400">{TYPE_LABEL[r.room_type] ?? r.room_type} · {FLOOR_NAMES[r.floor_id]}</span>
        </div>
        {hw && !connected ? (
          <div className="text-[11px] text-red-200 bg-red-950/40 border border-red-900 rounded-lg px-2 py-1.5">The board is not connected, so this room shows no values. Connect the ESP32 (or run the test sender) to see live data here.</div>
        ) : (
          <div className="grid grid-cols-2 gap-1.5">
            <Stat label={hw ? 'Presence (sensor)' : 'People (sim. truth)'} value={<span className="flex items-center gap-1"><Users size={13} />{people(r)}</span>}
              sub={isNum(r.ai?.occupancy_probability) ? `AI estimate P(occupied) ${r.ai!.occupancy_probability.toFixed(2)}` : undefined} />
            <Stat label="Temperature" value={<span className="flex items-center gap-1"><Thermometer size={13} />{fx(r.sensors?.Temperature, 1, ' °C')}</span>}
              sub={isNum(r.device_state?.setpoint) ? `set-point ${r.device_state!.setpoint!.toFixed(0)} °C` : r.comfort ? `PMV ${fx(r.comfort.pmv, 2)}` : undefined} />
            <Stat label="Lights" value={<span className="flex items-center gap-1"><Lightbulb size={13} />{r.control?.light_action ?? '—'}</span>}
              sub={r.comfort ? `daylight ${fx(r.comfort.daylight_lux, 0)} lx` : isNum(r.sensors?.Light) ? `${r.sensors.Light} lx measured` : undefined} />
            <Stat label="AC" value={<span className="flex items-center gap-1"><Snowflake size={13} />{acLabel(r.control?.hvac_action, r.control?.setpoint_c)}</span>}
              sub={r.control?.vent_boost ? <span className="text-emerald-300 flex items-center gap-0.5"><Wind size={10} />ventilation boost</span> : hw && isNum(r.device_state?.hvac_speed) ? `fan PWM ${r.device_state!.hvac_speed}` : isNum(r.device_state?.hvac_speed) ? `cooling ${r.device_state!.hvac_speed}%` : undefined} />
            {!hw && ai && conv && <>
              <Stat label="Power, AI on" value={<span className="flex items-center gap-1"><Zap size={13} />{fx(ai.power_w / 1000, 2)} kW</span>} tone="ai" />
              <Stat label="Power, AI off" value={`${fx(conv.power_w / 1000, 2)} kW`} tone="off" sub="same room, same minute (twin)" />
            </>}
            {hw && r.energy && <Stat label="Power (measured)" value={`${fx(r.energy.measured_power_watts, 2)} W`} sub="INA226 on the board" />}
          </div>
        )}
        {r.control?.reason && (
          <div className="mt-1.5 text-[10.5px] text-slate-300 bg-slate-900/70 border border-slate-800 rounded-lg px-2 py-1.5 leading-snug">
            <span className="text-sky-300 font-semibold flex items-center gap-1 mb-0.5"><Brain size={11} />{r.control.mode === 'ai' ? 'AI decision' : 'Schedule (AI off)'}</span>{r.control.reason}
          </div>
        )}
      </>
    );
  }

  // building and floor views: the selected room in brief, with a way in
  const sel = selectedRoom ? rooms[selectedRoom] : null;
  const selCard = sel && view.mode !== 'room' && (view.mode === 'building' || sel.floor_id === view.floor) ? (
    <div className="mt-1.5 rounded-lg border border-sky-800/70 bg-sky-950/30 px-2 py-1.5" data-testid="ctx-selected">
      <div className="flex items-center gap-1.5">
        <span className="text-[11.5px] font-semibold text-white truncate">{sel.display_name}</span>
        <span className={`text-[9px] font-bold px-1 rounded border ${sel.source === 'hardware' ? 'border-cyan-600 text-cyan-300' : 'border-slate-600 text-slate-400'}`}>{sel.source === 'hardware' ? 'LIVE' : 'SIM'}</span>
        <span className="ml-auto text-[10px] text-slate-400">{FLOOR_NAMES[sel.floor_id]}</span>
      </div>
      <div className="flex items-center gap-3 text-[10.5px] text-slate-300 mt-0.5">
        <span className="flex items-center gap-0.5"><Users size={11} />{people(sel)}</span>
        <span className="flex items-center gap-0.5"><Thermometer size={11} />{fx(sel.sensors?.Temperature, 1, '°C')}</span>
        <span className="flex items-center gap-0.5"><Lightbulb size={11} />{sel.control?.light_action ?? '—'}</span>
        <span className="flex items-center gap-0.5"><Snowflake size={11} />{acLabel(sel.control?.hvac_action, sel.control?.setpoint_c)}</span>
      </div>
      <button onClick={() => request({ mode: 'room', room: sel.room_id })} className="mt-1 w-full text-[11px] font-semibold text-white bg-sky-700 hover:bg-sky-600 rounded-md py-1 flex items-center justify-center gap-1" data-testid="ctx-enter-room"><DoorOpen size={12} />Enter room</button>
    </div>
  ) : null;

  return (
    <div className={`absolute left-2 bottom-2 z-20 ${width} ${glass} rounded-xl`} data-testid="twin-context">
      <button className="w-full flex items-center justify-between px-3 py-1.5" onClick={() => setOpen(!open)}>
        <span className={`font-semibold text-white truncate ${presentation ? 'text-[14px]' : 'text-[12px]'}`}>{title}</span>
        {open ? <ChevronDown size={14} className="text-slate-400" /> : <ChevronUp size={14} className="text-slate-400" />}
      </button>
      {open && <div className="px-2.5 pb-2.5">{body}{selCard}</div>}
      {!open && selCard && <div className="px-2.5 pb-2.5 -mt-1">{selCard}</div>}
    </div>
  );
}
