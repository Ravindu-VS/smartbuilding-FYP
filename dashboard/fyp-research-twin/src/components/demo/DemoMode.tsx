'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { X, Play, CheckCircle2, Circle, Loader2, Square, Presentation, MinusCircle } from 'lucide-react';
import { useBuildingStore } from '../../store/useBuildingStore';
import { api } from '../../lib/api';
import { acLabel, fx, isNum } from '../../lib/format';
import type { BuildingStatePayload, ModelsStatus, RoomState } from '../../types/building';

/**
 * Demo: one click runs the whole system for five minutes, hands-free, so it can be explained while it runs.
 * Real Room 101 first (sensors, the board's relay, fan, LEDs and OLED, the AI on real readings), then the
 * digital twin (AI on vs off, people arriving, CO2, a heat load), then the machine-learning models and the
 * energy result. Every tick comes from the live state streamed by the edge brain; nothing is scripted.
 */

const TOTAL_S = 300;
const MEETING = 'f2_meeting_b';
const OFFICE = 'f2_office_b2';

interface Ctx {
  t0: number;                  // real ms when the segment started
  sim0: number;                // simulated minutes when the segment started
  powerBefore: number | null;
  tempBefore: number | null;
  models: ModelsStatus | null;
  demo0: number;               // simulated minutes when the building part (step 4) started
}
type Live = { raw: BuildingStatePayload; rooms: Record<string, RoomState>; hw: string };
interface Check { label: (l: Live, c: Ctx) => string; test: (l: Live, c: Ctx) => boolean; needsBoard?: boolean }
interface Segment {
  id: string; start: number; end: number; title: string; say: string;
  room: (hw: string) => string; tab: 'decisions' | 'meter' | 'models' | 'analytics';
  enter: (hw: string, c: Ctx) => Promise<void>;
  timed?: { at: number; run: (hw: string) => Promise<unknown> }[];
  checks: Check[];
}

const simMin = (iso: string) => new Date(iso + 'Z').getTime() / 60000;
const L = (s: string) => () => s;
const pct = (v: number | null | undefined) => (isNum(v) ? `${(v * 100).toFixed(1)} %` : '–');
const hwRoom = (l: Live) => l.rooms[l.hw];
const board = (l: Live) => !!l.raw.hardware?.connected;
const powerW = (r?: RoomState) => (isNum(r?.power_measurement?.power_mW) ? r!.power_measurement!.power_mW! / 1000 : null);
const offSeg = (l: Live, c: Ctx) => l.raw.meter.segments.find((s) => s.mode === 'conventional' && simMin(s.start + ':00') >= c.sim0 - 1);
const lessMore = (p: number | null | undefined) => (isNum(p) ? `${Math.abs(p).toFixed(0)} % ${p >= 0 ? 'less' : 'more'} energy` : '…');
const ov = (hw: string, fan: number, light: number, reason: string) =>
  api.override({ room_id: hw, fan_speed: fan, light_level: light, minutes: 5, reason });

const SEGMENTS: Segment[] = [
  {
    id: 'system', start: 0, end: 25, tab: 'decisions', room: (hw) => hw,
    title: 'The system', say: 'Room 101 is a real room: an ESP32-S3 with temperature, humidity, light, gas, motion and power sensors. The other 25 rooms are a physics digital twin. A Raspberry Pi runs the AI and this dashboard.',
    enter: async () => {
      useBuildingStore.getState().requestTwinView({ mode: 'building' });
    },
    checks: [
      { label: L('Edge brain on the Raspberry Pi is live'), test: (l) => !!l.raw.clock },
      { label: (l) => `ESP32 board connected (${l.raw.hardware?.real_board ? 'real board' : l.raw.hardware?.sender ?? 'none'})`, test: board, needsBoard: true },
      { label: (l) => `Live readings: ${fx(hwRoom(l)?.sensors.Temperature, 1, ' °C')}, ${fx(hwRoom(l)?.sensors.Light, 0, ' lux')}, eCO₂ ${fx(hwRoom(l)?.sensors.CO2, 0, ' ppm')}`, test: (l) => board(l) && isNum(hwRoom(l)?.sensors.Temperature), needsBoard: true },
      { label: L('25 simulated rooms running on the twin'), test: (l) => l.raw.rooms.filter((r) => r.source === 'simulated').length >= 25 },
    ],
  },
  {
    id: 'actuators', start: 25, end: 85, tab: 'decisions', room: (hw) => hw,
    title: 'Real actuators', say: 'The Pi now drives the real board: light ON, DIM, OFF, then the fan through the relay. Watch the light LED, the yellow status LED (manual), and the OLED energy meter as the fan starts.',
    enter: async (hw) => {
      useBuildingStore.getState().requestTwinView({ mode: 'room', room: hw });
      await ov(hw, 0, 255, 'demo: light ON');
    },
    timed: [
      { at: 10, run: (hw) => ov(hw, 0, 102, 'demo: light DIM') },
      { at: 20, run: (hw) => ov(hw, 0, 0, 'demo: light OFF') },
      { at: 28, run: (hw) => ov(hw, 255, 0, 'demo: fan ON') },
      { at: 48, run: (hw) => ov(hw, 0, 0, 'demo: fan OFF') },
    ],
    checks: [
      { label: L('Board reports light ON (full brightness)'), test: (l) => (hwRoom(l)?.device_state?.light_level ?? 0) >= 250, needsBoard: true },
      { label: L('Board reports light DIM'), test: (l, c) => (Date.now() - c.t0) / 1000 > 10 && Math.abs((hwRoom(l)?.device_state?.light_level ?? 0) - 102) <= 5, needsBoard: true },
      { label: L('Status LED shows MANUAL (yellow)'), test: (l) => hwRoom(l)?.device_state?.status_led === 'MANUAL', needsBoard: true },
      { label: L('Relay closes: fan ON'), test: (l) => !!hwRoom(l)?.device_state?.fan_on, needsBoard: true },
      { label: (l) => `INA219 measures the fan: ${fx(powerW(hwRoom(l)), 2, ' W')}`, test: (l) => !!hwRoom(l)?.device_state?.fan_on && (powerW(hwRoom(l)) ?? 0) > 0.4, needsBoard: true },
      { label: L('Fan OFF again: power back to 0 W'), test: (l, c) => (Date.now() - c.t0) / 1000 > 50 && !hwRoom(l)?.device_state?.fan_on && (powerW(hwRoom(l)) ?? 1) < 0.2, needsBoard: true },
    ],
  },
  {
    id: 'ai_real', start: 85, end: 115, tab: 'decisions', room: (hw) => hw,
    title: 'The AI runs the real room', say: 'Manual control ends and the AI takes over Room 101 from its real sensors. Wave a hand at the PIR sensor: the AI sees the motion and decides the light and the AC. The status LED turns blue.',
    enter: async (hw) => { await api.override({ room_id: hw, clear: true }); },
    checks: [
      { label: L('AI back in control (status LED blue)'), test: (l) => hwRoom(l)?.control?.mode === 'ai' && hwRoom(l)?.device_state?.status_led !== 'MANUAL', needsBoard: true },
      { label: L('PIR motion detected'), test: (l) => !!hwRoom(l)?.presence?.pir_motion, needsBoard: true },
      { label: (l) => `AI estimate P(occupied) ${fx(hwRoom(l)?.ai?.occupancy_probability, 2)} → light ${hwRoom(l)?.control?.light_action ?? '–'}, AC ${hwRoom(l)?.device_state?.ac_led ?? '–'}`, test: (l) => isNum(hwRoom(l)?.ai?.occupancy_probability) && !!hwRoom(l)?.control?.light_action, needsBoard: true },
    ],
  },
  {
    id: 'onoff', start: 115, end: 175, tab: 'meter', room: () => OFFICE,
    title: 'AI ON vs AI OFF', say: 'The whole building from 07:00, 6 simulated minutes per second: three hours with AI control OFF (every room on its time schedule), then three hours ON. The twin runs the other mode over the same minutes, so the energy meter compares like with like.',
    enter: async () => {
      useBuildingStore.getState().requestTwinView({ mode: 'building' });
      await api.setAi(false);
      await api.control('speed', { speed: 360 });
    },
    timed: [{ at: 30, run: () => api.setAi(true) }],
    checks: [
      { label: L('AI OFF: every room follows its schedule'), test: (l) => l.raw.meter.mode === 'conventional' },
      { label: (l, c) => `AI-off period measured: the AI would have used ${lessMore(offSeg(l, c)?.ai_saving_pct)}`, test: (l, c) => (offSeg(l, c)?.minutes ?? 0) >= 120 },
      { label: L('AI back ON'), test: (l, c) => l.raw.meter.mode === 'ai' && (Date.now() - c.t0) / 1000 > 30 },
      { label: (l, c) => `AI-on period: ${l.raw.meter.current && simMin(l.raw.meter.current.start + ':00') >= c.sim0 + 60 ? lessMore(l.raw.meter.current.ai_saving_pct) : '…'} than the schedule over the same minutes`, test: (l, c) => l.raw.meter.current?.mode === 'ai' && simMin(l.raw.meter.current.start + ':00') >= c.sim0 + 60 && (l.raw.meter.current?.minutes ?? 0) >= 120 },
    ],
  },
  {
    id: 'arrive', start: 175, end: 235, tab: 'decisions', room: () => MEETING,
    title: 'People arrive, CO₂ rises', say: 'Six people walk into Meeting Room B with extra CO₂ (a packed room). The PIR and CO₂ readings feed the learned occupancy model; the AI switches on the AC, and above 1000 ppm the safety layer starts the fresh-air fan.',
    enter: async () => {
      useBuildingStore.getState().requestTwinView({ mode: 'room', room: MEETING });
      if (!useBuildingStore.getState().twinLayers.airflow) useBuildingStore.getState().setTwinLayers({ airflow: true });
      await api.control('speed', { speed: 120 });
      await api.scenario('occupancy', MEETING, 6, 90);
      await api.scenario('co2', MEETING, 0.15, 30);
    },
    checks: [
      { label: (l) => `Learned model detects people: P = ${fx(l.rooms[MEETING]?.ai?.occupancy_probability, 2)}`, test: (l) => (l.rooms[MEETING]?.ai?.occupancy_probability ?? 0) >= 0.5 },
      { label: (l) => `AC on: ${acLabel(l.rooms[MEETING]?.control?.hvac_action, l.rooms[MEETING]?.control?.setpoint_c)}`, test: (l) => l.rooms[MEETING]?.control?.hvac_action === 'NORMAL' },
      { label: (l) => `CO₂ above 1000 ppm (${fx(l.rooms[MEETING]?.sensors.CO2, 0, ' ppm')})`, test: (l) => (l.rooms[MEETING]?.sensors.CO2 ?? 0) > 1000 },
      { label: L('Fresh-air fan on (safety rule R4)'), test: (l) => !!l.rooms[MEETING]?.control?.vent_boost },
    ],
  },
  {
    id: 'heat', start: 235, end: 270, tab: 'decisions', room: () => OFFICE,
    title: 'A heat load appears', say: 'Equipment adds 4 kW of heat to occupied Office B2. The AC holds the temperature, and the electricity it costs is measured in the same step.',
    enter: async (_hw, c) => {
      useBuildingStore.getState().requestTwinView({ mode: 'room', room: OFFICE });
      await api.control('speed', { speed: 120 });
      await api.scenario('heat_gain', OFFICE, 4000, 60);
      void c;
    },
    checks: [
      { label: (l, c) => `AC power rises: ${fx(c.powerBefore !== null ? c.powerBefore / 1000 : null, 1)} → ${fx((l.rooms[OFFICE]?.energy?.power_w ?? NaN) / 1000, 1, ' kW')}`, test: (l, c) => c.powerBefore !== null && (l.rooms[OFFICE]?.energy?.power_w ?? 0) - c.powerBefore >= 600 },
      { label: (l, c) => `Temperature held: ${fx(c.tempBefore, 1)} → ${fx(l.rooms[OFFICE]?.sensors.Temperature, 1, ' °C')}`, test: (l, c) => c.tempBefore !== null && isNum(l.rooms[OFFICE]?.sensors.Temperature) && Math.abs(l.rooms[OFFICE]!.sensors.Temperature! - c.tempBefore) <= 0.8 && (Date.now() - c.t0) / 1000 > 8 },
    ],
  },
  {
    id: 'ml', start: 270, end: 290, tab: 'models', room: () => OFFICE,
    title: 'Machine learning', say: 'The occupancy model is scored live against the simulator\'s true head count, next to the hand-built rule it replaced. It keeps learning: every simulated day it retrains and goes live only if it scores better.',
    enter: async () => { useBuildingStore.getState().requestTwinView({ mode: 'building' }); },
    checks: [
      { label: (_l, c) => `Learned model accuracy ${pct(c.models?.live?.shadow.candidate_vs_truth.accuracy)} (rule ${pct(c.models?.live?.shadow.active_vs_truth.accuracy)})`, test: (_l, c) => (c.models?.live?.shadow.candidate_vs_truth.accuracy ?? 0) > (c.models?.live?.shadow.active_vs_truth.accuracy ?? 1) },
      { label: (_l, c) => { const o = c.models?.live?.online_learning; return o ? `Continual learning on: ${o.buffer_rows.toLocaleString()} labelled room-minutes, ${o.rounds.length} retraining round(s)` : 'Continual learning status'; }, test: (_l, c) => !!c.models?.live?.online_learning?.enabled },
      { label: (_l, c) => `30-min temperature forecast error ${fx(c.models?.live?.thermal.live_mae_c, 2, ' K')}`, test: (_l, c) => isNum(c.models?.live?.thermal.live_mae_c) },
    ],
  },
  {
    id: 'result', start: 290, end: 300, tab: 'meter', room: () => OFFICE,
    title: 'Result', say: 'Back to normal: AI on, normal speed, Room 101 under AI control. The energy meter keeps the measured comparison.',
    enter: async (hw) => {
      await api.clearScenarios();
      await api.override({ room_id: hw, clear: true }).catch(() => {});
      await api.setAi(true);
      await api.control('speed', { speed: 360 });
    },
    checks: [
      { label: (l, c) => { const segs = l.raw.meter.segments.filter((g) => simMin(g.start + ':00') >= c.demo0 - 1 && isNum(g.ai_saving_pct) && g.minutes > 0); const m = segs.reduce((t, g) => t + g.minutes, 0); const p = m ? segs.reduce((t, g) => t + g.minutes * (g.ai_saving_pct as number), 0) / m : null; return `Over ${Math.round(m / 60)} simulated hours of this demo the AI used ${lessMore(p)} than the schedule (same minutes, same weather and people)`; }, test: (l, c) => l.raw.meter.segments.some((g) => simMin(g.start + ':00') >= c.demo0 - 1 && g.minutes >= 60) },
      { label: L('AI control on, all rooms back to normal'), test: (l) => l.raw.ai_enabled },
    ],
  },
];

type Mark = string | 'skip' | null;
const EMPTY_CTX: Ctx = { t0: 0, sim0: 0, powerBefore: null, tempBefore: null, models: null, demo0: 0 };

export default function DemoMode() {
  const open = useBuildingStore((s) => s.demoOpen);
  const setOpen = useBuildingStore((s) => s.setDemoOpen);
  const raw = useBuildingStore((s) => s.raw);
  const rooms = useBuildingStore((s) => s.rooms);
  const [phase, setPhase] = useState<'idle' | 'running' | 'done'>('idle');
  const [seg, setSeg] = useState(0);
  const [now, setNow] = useState(0);
  const [marks, setMarks] = useState<Mark[][]>(SEGMENTS.map((s) => s.checks.map(() => null)));
  const [note, setNote] = useState('');
  const ctx = useRef<Ctx>({ ...EMPTY_CTX });
  const [view, setView] = useState<Ctx>(EMPTY_CTX);   // the same context, for rendering
  const t0 = useRef(0);
  const entered = useRef(-1);
  const fired = useRef<Set<string>>(new Set());
  const stopped = useRef(false);
  const lastTick = useRef(0);
  const modelsRef = useRef<ModelsStatus | null>(null);
  const [ready, setReady] = useState<'no' | 'preparing' | 'yes'>('no');
  const hw = raw?.hardware?.room_id ?? 'f2_office_a';

  const enterSegment = useCallback(async (i: number) => {
    const s = SEGMENTS[i];
    const st = useBuildingStore.getState();
    const r = st.raw;
    const target = s.room(hw);
    st.selectRoom(target);
    st.setBottomTab(s.tab);
    ctx.current = {
      t0: Date.now(), sim0: r ? simMin(r.clock.iso) : 0,
      powerBefore: st.rooms[target]?.energy?.power_w ?? null, tempBefore: st.rooms[target]?.sensors.Temperature ?? null,
      models: modelsRef.current, demo0: i === 3 && r ? simMin(r.clock.iso) : ctx.current.demo0,
    };
    setView(ctx.current);
    try {
      await s.enter(hw, ctx.current);
      if (s.id === 'heat') api.models().then((m) => { modelsRef.current = m; }).catch(() => {});      // ready for step 7
      if (s.id === 'ml') { const m = await api.models(); modelsRef.current = m; ctx.current = { ...ctx.current, models: m }; setView(ctx.current); }
    } catch (e) { setNote(`${s.title}: ${e instanceof Error ? e.message : String(e)}`); }
    if (!r?.hardware?.connected) {
      setMarks((m) => m.map((row, k) => (k === i ? row.map((v, j) => (v ?? (s.checks[j].needsBoard ? 'skip' : null))) : row)));
    }
  }, [hw]);

  // Opening the panel prepares the twin: a weekday at 07:00, held there (real time) until the demo starts
  const prepare = useCallback(async () => {
    setReady('preparing'); setNote('');
    try {
      await api.clearScenarios();
      await api.setAi(true);
      const c = useBuildingStore.getState().raw?.clock;
      const h = c ? Number(c.time.slice(0, 2)) : 0;
      const weekend = c ? /sat|sun/i.test(c.weekday) : false;
      const m = c ? Number(c.time.slice(3, 5)) : 0;
      if (!c || weekend || h !== 6 || m < 45) await api.control('fast_forward', { until: '07:00', weekday: true });
      await api.control('speed', { speed: 1 });
      api.models().then((m) => { modelsRef.current = m; }).catch(() => {});
    } catch (e) { setNote(e instanceof Error ? e.message : String(e)); }
  }, []);

  useEffect(() => {
    if (!open || phase !== 'idle' || ready !== 'no') return;
    const id = setTimeout(() => { void prepare(); }, 0);
    return () => clearTimeout(id);
  }, [open, phase, ready, prepare]);

  // ready once the fast-forward has finished
  useEffect(() => {
    if (ready !== 'preparing') return;
    return useBuildingStore.subscribe((st) => {
      if (st.raw && st.raw.clock.fast_forward_minutes === 0 && st.raw.clock.speed === 1) setReady('yes');
    });
  }, [ready]);

  const start = async () => {
    stopped.current = false; setNote('');
    setMarks(SEGMENTS.map((s) => s.checks.map(() => null)));
    fired.current = new Set(); entered.current = -1;
    ctx.current = { ...EMPTY_CTX, demo0: useBuildingStore.getState().raw ? simMin(useBuildingStore.getState().raw!.clock.iso) : 0 };
    t0.current = Date.now(); lastTick.current = Date.now(); setNow(0); setSeg(0); setPhase('running');
  };

  const stop = useCallback(async (finished = false) => {
    stopped.current = true;
    setPhase(finished ? 'done' : 'idle');
    setReady('no');
    // back to normal in parallel, so closing the panel or the tab right away still restores everything
    await Promise.allSettled([
      api.control('speed', { speed: 360 }), api.setAi(true), api.clearScenarios(),
      api.override({ room_id: hw, clear: true }),
    ]);
  }, [hw]);

  // the clock of the demo: segment changes and timed actions
  useEffect(() => {
    if (phase !== 'running') return;
    const id = setInterval(() => {
      const tick = Date.now();
      const dt = tick - lastTick.current;
      lastTick.current = tick;
      const ffNow = (useBuildingStore.getState().raw?.clock.fast_forward_minutes ?? 0) > 0;
      const tPrev = (tick - dt - t0.current) / 1000;
      // the building part needs the twin at its weekday morning: hold the demo clock until it is there
      if (ffNow && tPrev >= SEGMENTS[3].start - 0.5 && entered.current < 3) {
        t0.current += dt;
        setNote(`The twin is still fast-forwarding to a weekday morning (${Math.round(useBuildingStore.getState().raw?.clock.fast_forward_minutes ?? 0)} simulated min left)…`);
        return;
      }
      const t = (Date.now() - t0.current) / 1000;
      setNow(t);
      if (t >= TOTAL_S) { clearInterval(id); void stop(true); return; }
      const i = SEGMENTS.findIndex((s) => t >= s.start && t < s.end);
      if (i < 0) return;
      if (i !== entered.current) {
        setNote('');
        entered.current = i; setSeg(i);
        void enterSegment(i);
      }
      const s = SEGMENTS[i];
      const local = (Date.now() - ctx.current.t0) / 1000;
      (s.timed ?? []).forEach((a, k) => {
        const key = `${i}:${k}`;
        if (local >= a.at && !fired.current.has(key)) { fired.current.add(key); a.run(hw).catch(() => {}); }
      });
    }, 250);
    return () => clearInterval(id);
  }, [phase, enterSegment, stop, hw]);

  // tick the checks of the current segment from every streamed state
  useEffect(() => {
    if (phase !== 'running') return;
    return useBuildingStore.subscribe((st) => {
      if (!st.raw || entered.current < 0) return;
      const i = entered.current;
      const live: Live = { raw: st.raw, rooms: st.rooms, hw };
      setMarks((old) => {
        let changed = false;
        const row = old[i].map((v, j) => {
          if (v) return v;
          let ok = false;
          try { ok = SEGMENTS[i].checks[j].test(live, ctx.current); } catch { ok = false; }
          if (ok) {
            changed = true;
            let text = '';
            try { text = SEGMENTS[i].checks[j].label(live, ctx.current); } catch { text = ''; }
            return `${st.raw!.clock.time.slice(0, 5)}|${text}`;
          }
          return v;
        });
        if (!changed) return old;
        const next = old.slice(); next[i] = row; return next;
      });
    });
  }, [phase, hw]);

  if (!open) return null;
  const s = SEGMENTS[seg];
  const live: Live | null = raw ? { raw, rooms, hw } : null;
  const remaining = Math.max(0, TOTAL_S - now);
  const passed = marks.flat().filter((m) => m && m !== 'skip').length;
  const total = marks.flat().filter((m) => m !== 'skip').length;
  const r = rooms[s.room(hw)];

  return (
    <div className="absolute left-3 bottom-3 z-30 w-[460px] max-h-[calc(100%-24px)] overflow-y-auto rounded-xl border border-sky-700/70 bg-slate-950/95 shadow-2xl shadow-black/60" data-testid="demo-panel">
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-800">
        <div className="flex items-center gap-2 text-[13px] font-bold text-white"><Presentation size={15} className="text-sky-300" />Demo</div>
        <div className="flex items-center gap-3">
          {phase === 'running' && <span className="font-mono text-[12px] text-sky-200" data-testid="demo-remaining">{Math.floor(remaining / 60)}:{String(Math.floor(remaining % 60)).padStart(2, '0')} left</span>}
          <button onClick={() => { void stop(); setOpen(false); }} className="p-1 rounded hover:bg-slate-800 text-slate-400" title="Close"><X size={15} /></button>
        </div>
      </div>

      <div className="px-3 pt-2">
        <div className="h-1.5 rounded-full bg-slate-800 overflow-hidden"><div className="h-full bg-sky-500 transition-[width] duration-300" style={{ width: `${Math.min(100, (now / TOTAL_S) * 100)}%` }} /></div>
        <div className="flex gap-1 mt-2 flex-wrap">
          {SEGMENTS.map((x, i) => (
            <span key={x.id} className={`px-1.5 py-0.5 rounded text-[10px] border ${phase !== 'idle' && i === seg ? 'border-sky-500 bg-sky-900/60 text-white' : phase !== 'idle' && i < seg ? 'border-emerald-800 text-emerald-300' : 'border-slate-700 text-slate-500'}`}>{i + 1} {x.title}</span>
          ))}
        </div>
      </div>

      <div className="px-3 py-2 space-y-2">
        {phase === 'idle' && (
          <>
            <p className="text-[12px] text-slate-300 leading-snug">Runs the whole system for five minutes without any clicks: the real Room 101 board (sensors, relay and fan, LEDs, OLED energy meter), the AI deciding from real readings, the 25-room digital twin (AI on vs off, people arriving, CO₂, a heat load), the machine-learning models and the energy result.</p>
            <p className="text-[11px] text-slate-400 leading-snug">Have the board powered and the 12 V fan supply on. During step 3, wave a hand at the PIR sensor.</p>
            <div className={`text-[11px] flex items-center gap-1.5 ${ready === 'yes' ? 'text-emerald-300' : 'text-sky-200'}`} data-testid="demo-ready">
              {ready === 'yes' ? <CheckCircle2 size={13} /> : <Loader2 size={13} className="animate-spin" />}
              {ready === 'yes' ? `Twin ready: ${raw?.clock.weekday ?? ''} ${raw?.clock.time.slice(0, 5) ?? ''}, held until you start` : `Preparing the twin: moving to 07:00 on a weekday${raw && raw.clock.fast_forward_minutes > 0 ? ` (${Math.round(raw.clock.fast_forward_minutes)} simulated min left)` : ''}…`}
            </div>
          </>
        )}
        {phase !== 'idle' && (
          <>
            <div className="text-[15px] font-semibold text-white">{seg + 1} · {s.title}</div>
            <p className="text-[12px] text-slate-300 leading-snug">{s.say}</p>
            <ul className="space-y-1">
              {s.checks.map((c, j) => {
                const m = marks[seg][j];
                let label = '';
                if (m && m !== 'skip' && m.includes('|') && m.split('|')[1]) label = m.split('|')[1];   // the reading when it was observed
                else { try { label = live ? c.label(live, view) : ''; } catch { label = ''; } }
                return (
                  <li key={j} className={`flex items-center gap-2 text-[11.5px] ${m === 'skip' ? 'text-slate-500' : m ? 'text-emerald-300' : 'text-slate-400'}`} data-testid={`demo-check-${j}`}>
                    {m === 'skip' ? <MinusCircle size={15} /> : m ? <CheckCircle2 size={15} /> : phase === 'running' ? <Loader2 size={15} className="animate-spin text-slate-600" /> : <Circle size={15} />}
                    <span className="flex-1">{label}{m === 'skip' ? ' (board not connected)' : ''}</span>
                    <span className="font-mono text-[10px] text-slate-500">{m && m !== 'skip' ? m.split('|')[0] : ''}</span>
                  </li>
                );
              })}
            </ul>
            {r && phase === 'running' && (
              <div className="grid grid-cols-4 gap-1 text-center text-[10px] bg-slate-900 rounded-lg p-1.5 border border-slate-800">
                <div><div className="text-slate-500">{r.room_number ? `Room ${r.room_number}` : 'Room'}</div><div className="text-white font-bold truncate">{r.display_name}</div></div>
                <div><div className="text-slate-500">P(occ)</div><div className="text-white font-bold">{fx(r.ai?.occupancy_probability, 2)}</div></div>
                <div><div className="text-slate-500">Light · AC</div><div className="text-white font-bold">{r.control?.light_action ?? '–'} · {r.control?.hvac_action ?? '–'}</div></div>
                <div><div className="text-slate-500">Temp · CO₂</div><div className="text-white font-bold">{fx(r.sensors.Temperature, 1)}° · {fx(r.sensors.CO2, 0)}</div></div>
              </div>
            )}
          </>
        )}
        {note && <div className="text-[11px] text-amber-200">{note}</div>}
        {phase === 'done' && <div className="text-[12px] text-emerald-300" data-testid="demo-summary">Demo finished: {passed} of {total} checks observed live. The AI decisions tab and the energy meter keep the full record.</div>}
        <div className="flex gap-2 pt-1">
          {phase !== 'running' && <button onClick={phase === 'done' ? () => { setPhase('idle'); } : start} disabled={!raw || (phase === 'idle' && ready !== 'yes')} className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-sky-600 hover:bg-sky-500 text-white text-[12px] font-semibold disabled:opacity-40" data-testid="demo-run"><Play size={13} />{phase === 'done' ? 'Prepare another run' : 'Start the 5-minute demo'}</button>}
          {phase === 'running' && <button onClick={() => void stop()} className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-slate-800 hover:bg-slate-700 text-white text-[12px]" data-testid="demo-stop"><Square size={12} />Stop</button>}
        </div>
      </div>
    </div>
  );
}
