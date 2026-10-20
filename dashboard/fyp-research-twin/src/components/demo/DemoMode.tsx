'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { X, Play, CheckCircle2, Circle, Loader2, SkipForward, Square, Presentation } from 'lucide-react';
import { useBuildingStore } from '../../store/useBuildingStore';
import { api } from '../../lib/api';
import { acLabel, fx, isNum } from '../../lib/format';
import type { BuildingStatePayload, RoomState } from '../../types/building';

/**
 * Viva demo: guided scenarios. Each step prepares the simulation (time of day, room),
 * applies a real disturbance on the edge brain, and then ticks off what the AI does as
 * it happens - every tick comes from the streamed state, nothing is scripted.
 */

interface Ctx { start: number; powerBefore: number | null; tempBefore: number | null; seq0: number }
interface Check { label: string; test: (r: RoomState, raw: BuildingStatePayload, c: Ctx) => boolean }
interface Step {
  id: string; title: string; room: string; story: string; until: string;
  prepare: { kind: string; value: number; minutes: number; room?: string | null }[];
  main: { kind: string; value: number; minutes: number; room?: string | null }[];
  checks: Check[];
  watchFor: string;
  ai?: { at: number; on: boolean }[];          // switch AI at these simulated minutes after the start
  speed?: number;
}

const offSegment = (raw: BuildingStatePayload, c: Ctx) =>
  raw.meter.segments.find((s) => s.mode === 'conventional' && simMinutes(s.start + ':00') >= c.start - 1);

const simMinutes = (iso: string) => new Date(iso + 'Z').getTime() / 60000;
const lightDecisionsSince = (raw: BuildingStatePayload, seq0: number, to: RegExp) =>
  raw.timeline.filter((e) => e.seq > seq0 && e.kind === 'decision' && to.test(e.summary)).length;

const STEPS: Step[] = [
  {
    id: 'switch', title: '0 · AI ON vs AI OFF (one click)', room: 'f2_office_b2', until: '09:30', speed: 120,
    story: 'A normal weekday morning. AI control is switched OFF for 45 minutes (every room falls back to its time schedule), then back ON for 45 minutes. Watch the energy meter in the top bar.',
    prepare: [], main: [],
    ai: [{ at: 0, on: false }, { at: 45, on: true }],
    watchFor: 'With AI off, lights and AC run by the clock whether rooms are used or not; with AI on they follow the people and the daylight. The digital twin runs the other mode over the same minutes, so each period has an exact comparison.',
    checks: [
      { label: 'AI switched OFF: every room on its schedule', test: (_r, raw) => raw.meter.mode === 'conventional' },
      { label: 'Meter records the AI-off period (45 min)', test: (_r, raw, c) => (offSegment(raw, c)?.minutes ?? 0) >= 44 },
      { label: 'AI switched back ON', test: (_r, raw, c) => raw.meter.mode === 'ai' && simMinutes(raw.clock.iso) - c.start >= 45 },
      { label: 'Same minutes: AI uses less energy than AI off', test: (_r, raw, c) => { const s = offSegment(raw, c); return !!s && (s.ai_saving_pct ?? 0) > 0 && raw.meter.current?.mode === 'ai' && (raw.meter.current?.minutes ?? 0) >= 30 && (raw.meter.current?.ai_saving_pct ?? 0) > 0; } },
    ],
  },
  {
    id: 'arrive', title: '1 · People arrive after hours', room: 'f2_office_b2', until: '19:30',
    story: 'Monday evening, Office B2 is dark and its AC is off. Five people come in to work late. The schedule building does nothing: it is outside its operating hours.',
    prepare: [{ kind: 'occupancy', value: 0, minutes: 3 }],
    main: [{ kind: 'occupancy', value: 5, minutes: 45 }],
    watchFor: 'PIR detects motion → estimate rises → lights within a minute → AC once presence is confirmed → room cools to comfort.',
    checks: [
      { label: 'AI detects people (P ≥ 0.5)', test: (r) => (r.ai?.occupancy_probability ?? 0) >= 0.5 },
      { label: 'Lights switched on (it is dark)', test: (r) => r.control?.light_action === 'ON' || r.control?.light_action === 'DIM' },
      { label: 'AC switched on', test: (r) => r.control?.hvac_action === 'NORMAL' },
      { label: 'Room reaches comfort (|PMV| ≤ 0.5)', test: (r, _raw, c) => isNum(r.comfort?.pmv) && Math.abs(r.comfort!.pmv!) <= 0.5 && c.start > 0 },
    ],
  },
  {
    id: 'empty', title: '2 · A meeting ends early', room: 'f2_meeting_b', until: '17:10',
    story: 'Six people are in Meeting Room B; at 17:25 they all leave. The schedule keeps lights and AC on until 18:30.',
    prepare: [{ kind: 'occupancy', value: 6, minutes: 15 }],
    main: [{ kind: 'occupancy', value: 0, minutes: 60 }],
    watchFor: 'The estimator waits up to 20 min before it is sure (a seated person rarely triggers a PIR), then the AI sets the AC back and switches it off.',
    checks: [
      { label: 'AI concludes the room is empty (P < 0.5)', test: (r) => (r.ai?.occupancy_probability ?? 1) < 0.5 },
      { label: 'AC set back or switched off', test: (r) => r.control?.hvac_action === 'LOW' || r.control?.hvac_action === 'ECO' },
      { label: 'Power well below the schedule (−50 %)', test: (r) => isNum(r.modes?.ai.power_w) && isNum(r.modes?.conventional.power_w) && r.modes!.ai.power_w < 0.5 * r.modes!.conventional.power_w },
    ],
  },
  {
    id: 'overcast', title: '3 · Daylight drops (overcast sky)', room: 'f2_office_b2', until: '11:00',
    story: 'A bright morning turns heavily overcast for 40 minutes (daylight × 0.1). The schedule had its lights on all along.',
    prepare: [{ kind: 'occupancy', value: 6, minutes: 60 }],
    main: [{ kind: 'overcast', value: 0.1, minutes: 40, room: null }],
    watchFor: 'Occupied rooms switch their lights on or dim within a minute or two; when the sun returns they switch off again.',
    checks: [
      { label: 'Office B2 drops below 300 lux of daylight', test: (r) => isNum(r.comfort?.daylight_lux) && r.comfort!.daylight_lux < 300 },
      { label: 'AI turns lights on in Office B2', test: (r) => r.control?.light_action !== 'OFF' },
      { label: 'Lights switched in 5+ rooms across the building', test: (_r, raw, c) => lightDecisionsSince(raw, c.seq0, /lights OFF -> (ON|DIM)/) >= 5 },
      { label: 'Sun returns: lights off again in Office B2', test: (r, raw, c) => r.control?.light_action === 'OFF' && simMinutes(raw.clock.iso) - c.start > 40 },
    ],
  },
  {
    id: 'heat', title: '4 · Thermal disturbance (+4 kW)', room: 'f2_office_b2', until: '14:00',
    story: 'Equipment adds 4 kW of heat to occupied Office B2 for an hour. Watch the physics: the AC holds the room, and pays for it in electricity.',
    prepare: [{ kind: 'occupancy', value: 6, minutes: 90 }],
    main: [{ kind: 'heat_gain', value: 4000, minutes: 60 }],
    watchFor: 'Temperature stays near the set-point; electric power rises by roughly the heat divided by the AC efficiency (COP ≈ 3.5).',
    checks: [
      { label: 'AC power rises (≥ +0.6 kW)', test: (r, _raw, c) => isNum(r.energy?.power_w) && c.powerBefore !== null && r.energy!.power_w! - c.powerBefore >= 600 },
      { label: 'Temperature held within 0.6 °C', test: (r, raw, c) => c.tempBefore !== null && isNum(r.sensors.Temperature) && Math.abs(r.sensors.Temperature - c.tempBefore) <= 0.6 && simMinutes(raw.clock.iso) - c.start >= 10 },
      { label: 'Occupants stay comfortable (|PMV| ≤ 0.5)', test: (r, raw, c) => isNum(r.comfort?.pmv) && Math.abs(r.comfort!.pmv!) <= 0.5 && simMinutes(raw.clock.iso) - c.start >= 15 },
    ],
  },
  {
    id: 'co2', title: '5 · CO₂ builds up', room: 'f2_meeting_b', until: '10:00',
    story: 'A packed meeting (8 people) plus a CO₂ source of 0.15 L/s (the breath of about 30 people) for 25 minutes.',
    prepare: [{ kind: 'occupancy', value: 8, minutes: 60 }],
    main: [{ kind: 'co2', value: 0.15, minutes: 25 }],
    watchFor: 'Above 1000 ppm the safety layer (rule R4) starts the fresh-air fan; below 800 ppm it stops. Ventilation is modelled, so CO₂ really falls — and the fan costs energy.',
    checks: [
      { label: 'CO₂ above 1000 ppm', test: (r) => (r.sensors.CO2 ?? 0) > 1000 },
      { label: 'Fresh-air fan switched on (safety rule R4)', test: (r) => !!r.control?.vent_boost },
      { label: 'CO₂ back below 800 ppm, fan off', test: (r, raw, c) => !r.control?.vent_boost && (r.sensors.CO2 ?? 9999) < 800 && simMinutes(raw.clock.iso) - c.start > 20 },
    ],
  },
];

export default function DemoMode() {
  const open = useBuildingStore((s) => s.demoOpen);
  const setOpen = useBuildingStore((s) => s.setDemoOpen);
  const selectRoom = useBuildingStore((s) => s.selectRoom);
  const rooms = useBuildingStore((s) => s.rooms);
  const [idx, setIdx] = useState(0);
  const [phase, setPhase] = useState<'idle' | 'preparing' | 'running'>('idle');
  const [status, setStatus] = useState<string>('');
  const [ctx, setCtx] = useState<Ctx | null>(null);
  const [done, setDone] = useState<(string | null)[]>([]);
  const cancel = useRef(false);
  const fired = useRef<Set<number>>(new Set());
  const step = STEPS[idx];

  const waitFor = useCallback(async (pred: (raw: BuildingStatePayload) => boolean, timeoutMs = 120000) => {
    const t0 = Date.now();
    while (!cancel.current && Date.now() - t0 < timeoutMs) {
      const r = useBuildingStore.getState().raw;
      if (r && pred(r)) return true;
      await new Promise((res) => setTimeout(res, 250));
    }
    return false;
  }, []);

  const run = async () => {
    cancel.current = false;
    setPhase('preparing'); setDone(step.checks.map(() => null)); setCtx(null);
    try {
      selectRoom(step.room);
      useBuildingStore.getState().requestTwinView({ mode: 'room', room: step.room });
      if (!useBuildingStore.getState().twinLayers.airflow) useBuildingStore.getState().setTwinLayers({ airflow: true });
      setStatus('Clearing earlier scenarios…');
      await api.clearScenarios();
      await api.setAi(true);
      await api.control('speed', { speed: step.speed ?? 60 });
      setStatus(`Fast-forwarding to ${step.until} on a weekday (every minute is simulated)…`);
      await api.control('fast_forward', { until: step.until, weekday: true });
      await waitFor((r) => r.clock.fast_forward_minutes === 0, 180000);
      for (const p of step.prepare) await api.scenario(p.kind, p.room === undefined ? step.room : p.room, p.value, p.minutes);
      const prepMin = step.prepare.length ? Math.max(...step.prepare.map((p) => p.minutes)) : 0;
      if (prepMin === 0) {
        // nothing to set up
      } else if (prepMin < 40) {
        setStatus(`Setting the scene (${prepMin} simulated min)…`);
        await api.control('fast_forward', { minutes: prepMin });
        await waitFor((r) => r.clock.fast_forward_minutes === 0, 60000);
      } else {
        await api.control('fast_forward', { minutes: 10 });
        await waitFor((r) => r.clock.fast_forward_minutes === 0, 60000);
      }
      if (cancel.current) return;
      const r0 = useBuildingStore.getState().raw!;
      const room0 = r0.rooms.find((x) => x.room_id === step.room);
      for (const m of step.main) await api.scenario(m.kind, m.room === undefined ? step.room : m.room, m.value, m.minutes);
      fired.current = new Set();
      setCtx({ start: simMinutes(r0.clock.iso), powerBefore: room0?.energy?.power_w ?? null, tempBefore: room0?.sensors.Temperature ?? null, seq0: r0.timeline.length ? r0.timeline[r0.timeline.length - 1].seq : 0 });
      setStatus('');
      setPhase('running');
    } catch (e) {
      setStatus(`Could not run: ${e instanceof Error ? e.message : String(e)}`);
      setPhase('idle');
    }
  };

  // Tick the checks off from the live state (store subscription: every streamed update)
  useEffect(() => {
    if (phase !== 'running' || !ctx) return;
    return useBuildingStore.subscribe((state) => {
      const r = state.rooms[step.room];
      const live = state.raw;
      if (!r || !live) return;
      const el = simMinutes(live.clock.iso) - ctx.start;
      (step.ai ?? []).forEach((a, i) => {
        if (el >= a.at && !fired.current.has(i)) { fired.current.add(i); api.setAi(a.on).catch(() => {}); }
      });
      setDone((old) => {
        let changed = false;
        const next = step.checks.map((c, i) => {
          if (old[i]) return old[i];
          if (c.test(r, live, ctx)) { changed = true; return live.clock.iso; }
          return null;
        });
        return changed ? next : old;
      });
    });
  }, [phase, ctx, step]);

  const stop = async () => {
    cancel.current = true;
    setPhase('idle'); setStatus(''); setCtx(null);
    try { await api.clearScenarios(); await api.setAi(true); await api.control('speed', { speed: 360 }); } catch { /* shown by the header */ }
  };

  if (!open) return null;
  const r = rooms[step.room];
  const allDone = done.length > 0 && done.every(Boolean);
  const elapsed = (iso: string | null) => (iso && ctx ? `+${Math.max(0, Math.round(simMinutes(iso) - ctx.start))} min` : '');

  return (
    <div className="absolute left-3 bottom-3 z-30 w-[400px] max-h-[calc(100%-24px)] overflow-y-auto rounded-xl border border-sky-700/70 bg-slate-950/95 shadow-2xl shadow-black/60" data-testid="demo-panel">
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-800">
        <div className="flex items-center gap-2 text-[13px] font-bold text-white"><Presentation size={15} className="text-sky-300" />Viva demo</div>
        <button onClick={() => { void stop(); setOpen(false); }} className="p-1 rounded hover:bg-slate-800 text-slate-400"><X size={15} /></button>
      </div>
      <div className="flex gap-1 px-3 pt-2 flex-wrap">
        {STEPS.map((s, i) => (
          <button key={s.id} disabled={phase !== 'idle'} onClick={() => { setIdx(i); setDone([]); setCtx(null); }}
            className={`px-2 py-0.5 rounded text-[10.5px] border ${i === idx ? 'border-sky-500 bg-sky-900/60 text-white' : 'border-slate-700 text-slate-400 hover:text-white'} disabled:opacity-50`}>{i + 1}</button>
        ))}
      </div>
      <div className="px-3 py-2 space-y-2">
        <div className="text-[13px] font-semibold text-white">{step.title}</div>
        <p className="text-[11px] text-slate-300 leading-snug">{step.story}</p>
        <p className="text-[10.5px] text-slate-400 leading-snug"><span className="text-slate-500">Watch for: </span>{step.watchFor}</p>

        <ul className="space-y-1">
          {step.checks.map((c, i) => (
            <li key={c.label} className={`flex items-center gap-2 text-[11.5px] ${done[i] ? 'text-emerald-300' : 'text-slate-400'}`} data-testid={`demo-check-${i}`}>
              {done[i] ? <CheckCircle2 size={15} /> : phase === 'running' ? <Loader2 size={15} className="animate-spin text-slate-600" /> : <Circle size={15} />}
              <span className="flex-1">{c.label}</span>
              <span className="font-mono text-[10px] text-slate-500">{elapsed(done[i])}</span>
            </li>
          ))}
        </ul>

        {phase === 'running' && r && (
          <div className="grid grid-cols-4 gap-1 text-center text-[10px] bg-slate-900 rounded-lg p-1.5 border border-slate-800">
            <div><div className="text-slate-500">P(occ)</div><div className="text-white font-bold">{fx(r.ai?.occupancy_probability, 2)}</div></div>
            <div><div className="text-slate-500">Lights · AC</div><div className="text-white font-bold">{r.control?.light_action} · {acLabel(r.control?.hvac_action, r.control?.setpoint_c).replace('SET-BACK 27°C', '27°C')}</div></div>
            <div><div className="text-slate-500">Temp · CO₂</div><div className="text-white font-bold">{fx(r.sensors.Temperature, 1)}° · {fx(r.sensors.CO2, 0)}</div></div>
            <div><div className="text-slate-500">kW AI on / off</div><div className="text-white font-bold">{fx((r.modes?.ai.power_w ?? NaN) / 1000, 1)} / {fx((r.modes?.conventional.power_w ?? NaN) / 1000, 1)}</div></div>
          </div>
        )}
        {status && <div className="text-[11px] text-sky-200 flex items-center gap-1.5">{phase === 'preparing' && <Loader2 size={13} className="animate-spin" />}{status}</div>}
        {allDone && <div className="text-[11px] text-emerald-300">All observed in the simulation. The decision log below and the room panel show each decision and its reason.</div>}

        <div className="flex gap-2 pt-1">
          {phase === 'idle' && <button onClick={run} className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-sky-600 hover:bg-sky-500 text-white text-[12px] font-semibold" data-testid="demo-run"><Play size={13} />Run this step</button>}
          {phase !== 'idle' && <button onClick={stop} className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-slate-800 hover:bg-slate-700 text-white text-[12px]"><Square size={12} />Stop</button>}
          {idx < STEPS.length - 1 && (
            <button onClick={async () => { await stop(); setIdx(idx + 1); setDone([]); }} className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-slate-800 hover:bg-slate-700 text-white text-[12px]"><SkipForward size={13} />Next step</button>
          )}
        </div>
        <div className="text-[9.5px] text-slate-500">Runs at {step.speed ?? 60}× ({step.speed && step.speed > 60 ? `${step.speed / 60} simulated minutes` : 'one simulated minute'} per second). Each disturbance is applied to the building and its twin alike.</div>
      </div>
    </div>
  );
}
