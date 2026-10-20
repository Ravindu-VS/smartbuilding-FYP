'use client';

import React, { useEffect, useRef, useState } from 'react';
import { Brain, FlaskConical, Cpu, ShieldAlert, Info, CheckCircle2, Power } from 'lucide-react';
import { backendIsCurrent, useBuildingStore } from '../../store/useBuildingStore';
import { api } from '../../lib/api';
import type { TimelineEvent } from '../../types/building';
import { fx, isNum } from '../../lib/format';

type Filter = 'all' | 'decisions' | 'scenarios' | 'hardware' | 'selected';

/** Every action the AI takes, with its reason, as it happens (from /api/timeline). */
export default function DecisionFeed() {
  const raw = useBuildingStore((s) => s.raw);
  const link = useBuildingStore((s) => s.link);
  const selectRoom = useBuildingStore((s) => s.selectRoom);
  const selected = useBuildingStore((s) => s.selectedRoom);
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [filter, setFilter] = useState<Filter>('all');
  const [open, setOpen] = useState<number | null>(null);
  const lastSeq = useRef(0);
  const lastFetch = useRef(0);
  const inFlight = useRef(false);
  const live = link.connected && backendIsCurrent(raw);
  const head = raw?.timeline?.length ? raw.timeline[raw.timeline.length - 1].seq : 0;

  useEffect(() => {
    if (!live) return;
    if (head < lastSeq.current) {          // the simulation was reset: start again
      lastSeq.current = 0;
      setEvents([]);
    }
    if (head === lastSeq.current || inFlight.current) return;
    const now = Date.now();
    if (now - lastFetch.current < 700) return;
    lastFetch.current = now;
    inFlight.current = true;
    api.timeline({ after: lastSeq.current, limit: 200 }).then((ev) => {
      if (!ev.length) return;
      lastSeq.current = Math.max(lastSeq.current, ev[ev.length - 1].seq);
      setEvents((old) => {
        const seen = new Set(old.map((e) => e.seq));
        return [...old, ...ev.filter((e) => !seen.has(e.seq))].slice(-300);
      });
    }).catch(() => {}).finally(() => { inFlight.current = false; });
  }, [live, head]);

  const shown = [...events].reverse().filter((e) =>
    filter === 'all' ? true
      : filter === 'decisions' ? e.kind === 'decision' || e.kind === 'assessment'
        : filter === 'scenarios' ? e.kind === 'scenario'
          : filter === 'hardware' ? e.source === 'hardware'
            : e.room_id === selected,
  ).slice(0, 120);

  const chip = (f: Filter, label: string) => (
    <button key={f} onClick={() => setFilter(f)} className={`px-2 py-0.5 rounded text-[10.5px] border ${filter === f ? 'border-sky-500 bg-sky-900/50 text-white' : 'border-slate-700 text-slate-400 hover:text-white'}`}>{label}</button>
  );

  return (
    <div className="h-full flex flex-col min-h-0" data-testid="decision-feed">
      <div className="flex items-center gap-1.5 px-3 py-1.5 border-b border-slate-800">
        {chip('all', 'All')}{chip('decisions', 'AI decisions')}{chip('scenarios', 'Scenarios')}{chip('hardware', 'Office A (real)')}
        {selected && chip('selected', 'Selected room')}
        <span className="ml-auto text-[10px] text-slate-500">{events.length} events · newest first</span>
      </div>
      <div className="flex-1 overflow-y-auto min-h-0">
        {shown.length === 0 && <div className="p-3 text-[11px] text-slate-500">{live ? 'No events yet.' : 'Waiting for the edge brain…'}</div>}
        {shown.map((e) => {
          const Icon = e.kind === 'switch' ? Power : e.kind === 'scenario' ? FlaskConical : e.source === 'hardware' ? Cpu : e.kind === 'decision' ? Brain : Info;
          const hasSafety = e.safety && e.safety.notes.length > 0;
          const isOpen = open === e.seq;
          return (
            <div key={e.seq} className={`px-3 py-1.5 border-b border-slate-800/70 text-[11px] ${isOpen ? 'bg-slate-800/40' : 'hover:bg-slate-800/20'}`}>
              <div className="flex items-start gap-2 cursor-pointer" onClick={() => setOpen(isOpen ? null : e.seq)}>
                <span className="font-mono text-slate-500 w-[54px] shrink-0">{e.sim_time ? e.sim_time.slice(11, 16) : e.real_time?.slice(11, 19)}</span>
                <Icon size={13} className={`mt-[1px] shrink-0 ${e.kind === 'scenario' ? 'text-amber-300' : e.source === 'hardware' ? 'text-cyan-300' : e.kind === 'decision' ? 'text-sky-300' : 'text-slate-400'}`} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5 flex-wrap">
                    {e.room_name && (
                      <button className="text-slate-300 hover:text-white underline-offset-2 hover:underline" onClick={(ev) => { ev.stopPropagation(); if (e.room_id) selectRoom(e.room_id); }}>{e.room_name}</button>
                    )}
                    {e.mode === 'conventional' && <span className="text-[9px] px-1 rounded bg-slate-700 text-slate-200">AI OFF</span>}
                    <span className={e.kind === 'decision' ? 'text-white font-semibold' : e.kind === 'switch' ? 'text-emerald-300 font-semibold' : 'text-slate-300'}>{e.summary}</span>
                    {hasSafety && <ShieldAlert size={12} className="text-amber-300" />}
                    {e.outcome && <CheckCircle2 size={12} className="text-emerald-400" />}
                  </div>
                  {!isOpen && e.why && e.why.length > 0 && <div className="text-[10.5px] text-slate-500 truncate">{e.why.slice(0, 3).join(' · ')}</div>}
                </div>
              </div>
              {isOpen && (
                <div className="pl-[70px] pt-1 space-y-1 text-[10.5px]">
                  {e.why && <ul className="list-disc pl-4 text-slate-300 space-y-0.5">{e.why.map((w, i) => <li key={i}>{w}</li>)}</ul>}
                  {e.observed && (
                    <div className="text-slate-400">Observed: {fx(e.observed.temperature as number, 1, ' °C')}, {fx(e.observed.light_lux as number, 0, ' lux')}, CO₂ {fx(e.observed.co2 as number, 0, ' ppm')}, P {fx(e.observed.p_occupancy as number, 2)}
                      {isNum(e.observed.p_random_forest as number) ? ` (Random Forest ${fx(e.observed.p_random_forest as number, 2)})` : ''}
                      {e.simulator_truth ? ` · truth: ${e.simulator_truth.occupants} people` : ''}</div>
                  )}
                  {e.proposed && <div className="text-slate-400">Proposed: lights {e.proposed.light}, AC {e.proposed.hvac}{e.proposed.setpoint ? ` ${e.proposed.setpoint}°C` : ''} → safety: {e.safety?.accepted ? 'accepted' : 'changed'}{hasSafety ? ` (${e.safety!.notes.join('; ')})` : ''}</div>}
                  {e.outcome && <div className="text-emerald-300/90">After 15 min: {fx(e.outcome.temperature as number, 1, ' °C')}{isNum(e.expected?.t_pred as number) ? ` (predicted ${fx(e.expected!.t_pred as number, 1, ' °C')})` : ''}{isNum(e.outcome.power_w as number) ? `, ${fx(e.outcome.power_w as number, 0, ' W')}` : ''}{isNum(e.outcome.pmv as number) ? `, PMV ${fx(e.outcome.pmv as number, 2)}` : ''}{isNum(e.outcome.occupants as number) ? `, ${e.outcome.occupants} people` : ''}</div>}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
