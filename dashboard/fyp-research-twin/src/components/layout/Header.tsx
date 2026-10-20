'use client';

import React, { useState } from 'react';
import { Cpu, Server, Play, Pause, FastForward, RotateCcw, Presentation, Sun, Moon, Cloud, Brain, Power } from 'lucide-react';
import { backendIsCurrent, useBuildingStore } from '../../store/useBuildingStore';
import { api } from '../../lib/api';
import { fx } from '../../lib/format';

const SPEEDS = [1, 60, 360, 1800, 3600];

function Pill({ tone, label, value, testId }: { tone: 'ok' | 'warn' | 'bad'; label: React.ReactNode; value: string; testId: string }) {
  const color = tone === 'ok' ? 'text-emerald-300 border-emerald-800 bg-emerald-950/40'
    : tone === 'warn' ? 'text-amber-300 border-amber-800 bg-amber-950/40' : 'text-red-300 border-red-900 bg-red-950/40';
  return (
    <div className={`flex items-center gap-1.5 px-2 py-1 rounded-md border text-[11px] ${color}`}>
      <span className="text-slate-400 flex items-center gap-1">{label}</span>
      <span className="font-semibold" data-testid={testId}>{value}</span>
    </div>
  );
}

/** The master switch: AI decision-making on or off for every room (simulated and real) at once. */
export function AiSwitch({ live, learning, busy, on, onToggle }: { live: boolean; learning: boolean; busy: boolean; on: boolean; onToggle: (v: boolean) => void }) {
  return (
    <button
      onClick={() => onToggle(!on)}
      disabled={!live || learning || busy}
      title={on ? 'AI decides every room. Click to switch to conventional control (schedule) for every room.' : 'Conventional schedule control. Click to let the AI decide every room.'}
      className={`flex items-center gap-2 pl-2 pr-1 py-1 rounded-full border text-[12px] font-bold transition-colors disabled:opacity-40 ${on ? 'border-emerald-500 bg-emerald-950/60 text-emerald-200' : 'border-slate-500 bg-slate-800 text-slate-300'}`}
      data-testid="ai-switch"
    >
      <Power size={14} />
      <span>AI CONTROL</span>
      <span className={`relative w-[52px] h-[22px] rounded-full ${on ? 'bg-emerald-500' : 'bg-slate-600'}`}>
        <span className={`absolute top-[2px] h-[18px] w-[18px] rounded-full bg-white shadow transition-all ${on ? 'left-[32px]' : 'left-[2px]'}`} />
        <span className={`absolute inset-0 flex items-center text-[9px] font-black ${on ? 'justify-start pl-1.5 text-emerald-950' : 'justify-end pr-1.5 text-slate-200'}`}>{on ? 'ON' : 'OFF'}</span>
      </span>
    </button>
  );
}

export default function Header() {
  const raw = useBuildingStore((s) => s.raw);
  const link = useBuildingStore((s) => s.link);
  const hw = useBuildingStore((s) => s.hardware);
  const config = useBuildingStore((s) => s.config);
  const setDemoOpen = useBuildingStore((s) => s.setDemoOpen);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const current = backendIsCurrent(raw);
  const oldBackend = link.connected && raw !== null && !current;
  const live = link.connected && current;
  const clock = live ? raw!.clock : null;
  const learning = clock?.phase === 'learning';
  const ff = clock && clock.fast_forward_minutes > 0;
  const boardValue = !live ? 'unknown' : !hw || !hw.connected ? 'NOT CONNECTED' : hw.real_board ? 'CONNECTED' : 'TEST SENDER';

  const run = async (name: string, fn: () => Promise<unknown>) => {
    setBusy(name); setErr(null);
    try { await fn(); } catch (e) { setErr(e instanceof Error ? e.message : String(e)); } finally { setBusy(null); }
  };

  const daylight = clock ? clock.sun_altitude > 0 : false;
  const SkyIcon = !clock ? Sun : clock.cloud_cover > 0.6 ? Cloud : daylight ? Sun : Moon;

  return (
    <header className="shrink-0 border-b border-slate-800 bg-slate-900/70 px-4 h-14 flex items-center gap-4 z-20 relative">
      <div className="flex items-center gap-2.5 min-w-0">
        <div className={`w-2.5 h-2.5 rounded-full shrink-0 ${live ? 'bg-emerald-400 animate-pulse' : 'bg-red-500'}`} />
        <div className="min-w-0">
          <h1 className="font-bold text-[15px] tracking-tight text-white leading-tight truncate">Smart Building Digital Twin</h1>
          <div className="text-[10px] text-slate-500 leading-tight truncate">Edge AI · 5 floors · 26 rooms · Office A on a real ESP32</div>
        </div>
      </div>

      {/* Simulated clock and its controls */}
      <div className="flex items-center gap-2 mx-auto">
        <div className="flex items-center gap-2 px-3 py-1 rounded-lg bg-slate-950/70 border border-slate-800">
          <SkyIcon size={15} className="text-amber-300" />
          <div className="leading-tight">
            <div className="text-white font-mono text-[15px] font-semibold" data-testid="sim-time">
              {clock ? `${clock.weekday.slice(0, 3)} ${clock.time.slice(0, 5)}` : '--:--'}
            </div>
            <div className="text-[9px] text-slate-500 font-mono">
              {clock ? `${clock.date} · outdoor ${fx(clock.outdoor_c, 1, '°C')} ${fx(clock.outdoor_rh, 0, '%')}` : 'simulated time'}
            </div>
          </div>
          {learning && <span className="ml-1 text-[10px] px-1.5 py-0.5 rounded bg-violet-900/60 border border-violet-700 text-violet-200" data-testid="phase">learning {fx((clock!.learning_progress) * 100, 0, '%')}</span>}
        </div>

        <button
          className="p-1.5 rounded-md border border-slate-700 bg-slate-800 hover:bg-slate-700 disabled:opacity-40"
          title={clock?.running ? 'Pause the simulation' : 'Resume the simulation'}
          disabled={!live || learning || !!busy}
          onClick={() => run('pause', () => api.control(clock?.running ? 'pause' : 'resume'))}
          data-testid="btn-pause"
        >
          {clock?.running ? <Pause size={15} /> : <Play size={15} />}
        </button>
        <select
          className="bg-slate-800 border border-slate-700 rounded-md text-[12px] px-1.5 py-1 font-mono disabled:opacity-40"
          title="Simulated seconds per real second (physics step stays 15 s)"
          value={clock ? String(clock.speed) : '360'}
          disabled={!live || !!busy}
          onChange={(e) => run('speed', () => api.control('speed', { speed: Number(e.target.value) }))}
          data-testid="speed"
        >
          {SPEEDS.map((s) => <option key={s} value={s}>{s === 1 ? '1× real time' : `${s}×`}</option>)}
          {clock && !SPEEDS.includes(clock.speed) && <option value={clock.speed}>{clock.speed}×</option>}
        </select>
        <button
          className="flex items-center gap-1 px-2 py-1 rounded-md border border-slate-700 bg-slate-800 hover:bg-slate-700 text-[12px] disabled:opacity-40"
          title="Simulate the next hour as fast as possible (every minute is still simulated and controlled)"
          disabled={!live || learning || !!busy || !!ff}
          onClick={() => run('ff', () => api.control('fast_forward', { minutes: 60 }))}
        >
          <FastForward size={14} /> 1 h
        </button>
        <button
          className="p-1.5 rounded-md border border-slate-700 bg-slate-800 hover:bg-slate-700 disabled:opacity-40"
          title="Restart the same scenario (same seed: same weather and people)"
          disabled={!live || !!busy}
          onClick={() => { if (window.confirm('Restart the simulation from the start of the scenario (same weather and people)?')) run('reset', () => api.control('reset')); }}
        >
          <RotateCcw size={15} />
        </button>
      </div>

      <div className="flex items-center gap-2">
        <AiSwitch live={live} learning={learning} busy={!!busy} on={raw?.ai_enabled ?? true}
          onToggle={(v) => run('ai', () => api.setAi(v))} />
        <div className="flex items-center gap-1" title="Which AI runs while AI control is ON (the comparison restarts)">
          <Brain size={13} className="text-sky-300" />
          <select
            className="bg-slate-800 border border-slate-700 rounded-md text-[11px] px-1 py-1 max-w-[150px] disabled:opacity-40"
            value={raw?.system?.ai_controller ?? 'mo'}
            disabled={!live || !!busy}
            onChange={(e) => run('ctrl', () => api.setController(e.target.value))}
            data-testid="controller"
          >
            {(config?.controllers ?? [{ id: 'mo', label: 'AI optimizer' }]).map((c) => (
              <option key={c.id} value={c.id}>{c.id === 'mo' ? 'Thesis AI optimizer' : 'Rule on Random Forest'}</option>
            ))}
          </select>
        </div>
        <Pill tone={live ? 'ok' : 'bad'} label={<><Server size={12} />Edge</>} value={oldBackend ? 'OLD VERSION' : live ? 'LIVE' : 'OFFLINE'} testId="link-status" />
        <Pill tone={live && hw?.connected ? (hw.real_board ? 'ok' : 'warn') : 'bad'} label={<><Cpu size={12} />ESP32</>} value={boardValue} testId="header-board-status" />
        <button
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-sky-600 hover:bg-sky-500 text-white text-[12px] font-semibold disabled:opacity-40"
          disabled={!live || learning}
          onClick={() => setDemoOpen(true)}
          data-testid="btn-demo"
        >
          <Presentation size={14} /> Viva demo
        </button>
      </div>
      {err && <div className="absolute right-4 top-14 mt-1 text-[11px] bg-red-950 border border-red-800 text-red-200 px-2 py-1 rounded">{err}</div>}
    </header>
  );
}
