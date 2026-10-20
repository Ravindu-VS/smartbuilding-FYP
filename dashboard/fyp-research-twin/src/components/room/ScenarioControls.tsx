'use client';

import React, { useState } from 'react';
import { Users, Flame, Wind, DoorOpen, UserMinus, Loader2 } from 'lucide-react';
import { api } from '../../lib/api';
import type { RoomState } from '../../types/building';

/**
 * Change the selected room's conditions. Each control starts a scenario on the edge
 * brain that changes the simulation's real inputs (people, heat, CO2 source, an open
 * window) in BOTH buildings, so the AI and the schedule face the same disturbance.
 */
const DURATIONS = [15, 30, 60, 120];

export default function ScenarioControls({ room, disabled }: { room: RoomState; disabled: boolean }) {
  const cap = room.ground_truth?.max_occupancy ?? 4;
  const [people, setPeople] = useState(Math.max(1, Math.round(cap * 0.6)));
  const [heat, setHeat] = useState(2000);
  const [co2, setCo2] = useState(0.1);
  const [ach, setAch] = useState(4);
  const [minutes, setMinutes] = useState(30);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const go = async (name: string, kind: string, value: number) => {
    setBusy(name); setMsg(null);
    try {
      await api.scenario(kind, room.room_id, value, minutes);
      setMsg(null);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally { setBusy(null); }
  };

  const btn = 'shrink-0 px-2 py-1 rounded-md text-[11px] font-semibold bg-sky-700 hover:bg-sky-600 text-white disabled:opacity-40 flex items-center gap-1';
  const row = 'flex items-center gap-2';
  const lab = 'w-[92px] shrink-0 text-[10.5px] text-slate-300 flex items-center gap-1';
  const val = 'w-[60px] shrink-0 text-right text-[11px] font-mono text-white';
  const off = disabled || !!busy;

  return (
    <div className="space-y-2" data-testid="scenario-controls">
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-slate-400">For the next</span>
        <div className="flex gap-1">
          {DURATIONS.map((d) => (
            <button key={d} onClick={() => setMinutes(d)} disabled={off}
              className={`px-1.5 py-0.5 rounded text-[10.5px] border ${minutes === d ? 'border-sky-500 bg-sky-900/60 text-white' : 'border-slate-700 text-slate-400 hover:text-white'}`}>
              {d} min
            </button>
          ))}
        </div>
      </div>

      <div className={row}>
        <span className={lab}><Users size={12} />People</span>
        <input type="range" min={0} max={cap * 2} value={people} onChange={(e) => setPeople(Number(e.target.value))} className="flex-1 accent-sky-500" disabled={off} />
        <span className={val}>{people} / {cap}</span>
        <button className={btn} disabled={off} onClick={() => go('people', 'occupancy', people)} data-testid="apply-people">
          {busy === 'people' ? <Loader2 size={12} className="animate-spin" /> : null}Set
        </button>
      </div>
      <div className={row}>
        <span className={lab}><UserMinus size={12} />Empty room</span>
        <span className="flex-1 text-[10px] text-slate-500">everyone leaves (meeting ends early)</span>
        <button className={btn} disabled={off} onClick={() => go('empty', 'occupancy', 0)} data-testid="apply-empty">
          {busy === 'empty' ? <Loader2 size={12} className="animate-spin" /> : null}Empty
        </button>
      </div>
      <div className={row}>
        <span className={lab}><Flame size={12} />Heat gain</span>
        <input type="range" min={500} max={6000} step={250} value={heat} onChange={(e) => setHeat(Number(e.target.value))} className="flex-1 accent-sky-500" disabled={off} />
        <span className={val}>+{(heat / 1000).toFixed(2)} kW</span>
        <button className={btn} disabled={off} onClick={() => go('heat', 'heat_gain', heat)} data-testid="apply-heat">
          {busy === 'heat' ? <Loader2 size={12} className="animate-spin" /> : null}Add
        </button>
      </div>
      <div className={row}>
        <span className={lab}><Wind size={12} />CO₂ source</span>
        <input type="range" min={0.02} max={0.3} step={0.01} value={co2} onChange={(e) => setCo2(Number(e.target.value))} className="flex-1 accent-sky-500" disabled={off} />
        <span className={val} title="One seated adult breathes out about 0.005 L/s of CO2">{co2.toFixed(2)} L/s</span>
        <button className={btn} disabled={off} onClick={() => go('co2', 'co2', co2)} data-testid="apply-co2">
          {busy === 'co2' ? <Loader2 size={12} className="animate-spin" /> : null}Add
        </button>
      </div>
      <div className={row}>
        <span className={lab}><DoorOpen size={12} />Open window</span>
        <input type="range" min={1} max={10} step={0.5} value={ach} onChange={(e) => setAch(Number(e.target.value))} className="flex-1 accent-sky-500" disabled={off} />
        <span className={val} title="Extra outdoor air, air changes per hour">+{ach.toFixed(1)} ACH</span>
        <button className={btn} disabled={off} onClick={() => go('window', 'window', ach)} data-testid="apply-window">
          {busy === 'window' ? <Loader2 size={12} className="animate-spin" /> : null}Open
        </button>
      </div>
      <div className="text-[10px] text-slate-500 leading-snug">
        CO₂ {co2.toFixed(2)} L/s ≈ the breath of {Math.round(co2 / 0.005)} seated people. Every change is applied to the
        AI building and the schedule building alike.
      </div>
      {msg && <div className="text-[10.5px] text-red-300">{msg}</div>}
      {room.scenarios && room.scenarios.length > 0 && (
        <div className="space-y-0.5">
          {room.scenarios.map((s, i) => <div key={i} className="text-[10.5px] text-amber-200 bg-amber-950/40 border border-amber-900 rounded px-1.5 py-0.5">Active: {s}</div>)}
        </div>
      )}
    </div>
  );
}
