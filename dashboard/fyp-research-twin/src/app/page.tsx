'use client';

import React from 'react';
import { EDGE_URL, useNow, useSSE } from '../hooks/useSSE';
import { backendIsCurrent, useBuildingStore } from '../store/useBuildingStore';
import { fx, isNum } from '../lib/format';
import VanillaTwinWrapper from '../components/3d/VanillaTwinWrapper';
import HardwareLivePanel from '../components/hardware/HardwareLivePanel';
import { Cpu, Server, Clock } from 'lucide-react';

// Every number on this page comes from the edge brain's SSE payload or is measured
// in the browser (message age). Nothing is hard-coded.

function Pill({ ok, warn, label, value, testId }: { ok: boolean; warn?: boolean; label: React.ReactNode; value: string; testId: string }) {
  const color = ok ? 'text-emerald-400 border-emerald-800 bg-emerald-950/30'
    : warn ? 'text-amber-300 border-amber-800 bg-amber-950/30'
    : 'text-red-400 border-red-900 bg-red-950/30';
  return (
    <div className={`flex items-center gap-2 px-2 py-1 rounded border ${color}`}>
      <span className="text-slate-400">{label}</span>
      <span className="font-bold" data-testid={testId}>{value}</span>
    </div>
  );
}

function Row({ k, v, testId }: { k: string; v: React.ReactNode; testId?: string }) {
  return (
    <div className="flex justify-between gap-2 text-xs py-0.5">
      <span className="text-slate-400">{k}</span>
      <span className="text-slate-100 font-mono text-right" data-testid={testId}>{v}</span>
    </div>
  );
}

export default function Dashboard() {
  useSSE();
  const now = useNow(500);
  const system = useBuildingStore((s) => s.system);
  const hw = useBuildingStore((s) => s.hardware);
  const link = useBuildingStore((s) => s.link);
  const twinSync = useBuildingStore((s) => s.twinSync);

  const oldBackend = link.connected && system !== null && !backendIsCurrent(system);
  const live = link.connected && !oldBackend;
  const msgAgeMs = link.lastMessageAt !== null ? Math.max(0, now - link.lastMessageAt) : null;
  const boardValue = oldBackend ? 'unknown' : !live ? 'unknown' : !hw || !hw.connected ? 'NOT CONNECTED' : hw.real_board ? 'CONNECTED' : 'TEST SENDER';
  const acc = system?.ai_accuracy_simulated;
  const sys = live ? system : null;

  return (
    <div className="h-screen bg-slate-950 text-slate-200 flex flex-col font-sans overflow-hidden">

      <header className="h-14 shrink-0 border-b border-slate-800 bg-slate-900/50 flex items-center justify-between px-6 z-10 relative">
        <div className="flex items-center gap-3">
          <div className={`w-3 h-3 rounded-full ${live ? 'bg-emerald-500 animate-pulse' : 'bg-red-500'}`} />
          <h1 className="font-bold text-lg tracking-tight text-white">Smart Building Digital Twin</h1>
          <span className="text-slate-500 text-xs hidden xl:inline">Office A: real ESP32 sensors · 25 rooms simulated</span>
        </div>
        <div className="flex items-center gap-3 text-xs font-mono">
          <Pill ok={live} label={<><Server size={12} className="inline mr-1" />Edge brain</>} value={oldBackend ? 'OLD VERSION' : live ? 'LIVE' : 'NOT CONNECTED'} testId="link-status" />
          <Pill ok={live && !!hw?.connected && !!hw?.real_board} warn={live && !!hw?.connected && !hw?.real_board}
            label={<><Cpu size={12} className="inline mr-1" />ESP32</>} value={boardValue} testId="header-board-status" />
          <div className="px-2 py-1 bg-slate-800 rounded border border-slate-700 flex gap-2 items-center">
            <Clock size={12} className="text-slate-400" />
            <span className="text-slate-400">Sim clock</span>
            <span className="text-white" data-testid="sim-time">{sys?.simulation_time ? sys.simulation_time.slice(0, 5) : '--:--'}</span>
            {sys && <span className="text-slate-500">{sys.simulation_speed_factor}× · day {sys.day_count + 1}</span>}
          </div>
        </div>
      </header>

      {oldBackend && (
        <div className="shrink-0 px-6 py-2 bg-red-950/70 border-b border-red-800 text-red-200 text-sm" data-testid="old-backend">
          An older edge brain is answering on port 8001 (its data has no board status, so it is not shown).
          Close every &quot;Edge Brain&quot; window (or run <code className="text-red-100">netstat -ano | findstr :8001</code> and
          <code className="text-red-100"> taskkill /PID &lt;pid&gt; /F</code>), then start <code className="text-red-100">run_local.bat</code> again.
        </div>
      )}

      <div className="flex-1 flex overflow-hidden min-h-0">

        <aside className="w-64 shrink-0 border-r border-slate-800 bg-slate-900/30 p-4 flex flex-col gap-4 overflow-y-auto z-10 relative">
          <div className="bg-slate-800/40 border border-slate-700/50 rounded-lg p-3">
            <h2 className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-2">What is real</h2>
            <ul className="space-y-1.5 text-xs text-slate-300">
              <li><span className="text-cyan-300">Office A</span>: real sensors on an ESP32-S3 — {boardValue.toLowerCase()}</li>
              <li><span className="text-slate-100">25 other rooms</span>: simulated by the edge brain{sys ? ` (${sys.simulation_speed_factor}× real time)` : ''}</li>
              <li>Occupancy AI: Random Forest{sys ? (sys.model_loaded ? ' (model loaded)' : ' — model NOT loaded, heuristic used') : ''}</li>
              <li>Control: rule thresholds on the AI probability</li>
              {sys && !sys.gpio_driving && <li className="text-slate-500">Edge-device GPIO outputs: not wired yet</li>}
            </ul>
          </div>

          <div className="bg-slate-800/40 border border-slate-700/50 rounded-lg p-3">
            <h2 className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-2">Data path</h2>
            <div className="text-[11px] font-mono text-center space-y-1">
              <div className="bg-cyan-950/50 border border-cyan-800 text-cyan-300 py-1 rounded">ESP32-S3 (Office A)</div>
              <div className="text-slate-500">↓ HTTP POST every ~3 s</div>
              <div className="bg-slate-800 border border-slate-700 text-slate-200 py-1 rounded">Edge brain (Python, Flask)<br /><span className="text-slate-500">simulator · RF model · rules</span></div>
              <div className="text-slate-500">↓ SSE (push on change)</div>
              <div className="bg-slate-800 border border-slate-700 text-slate-200 py-1 rounded">This dashboard (Next.js + Three.js)</div>
            </div>
          </div>

          <div className="bg-slate-800/40 border border-slate-700/50 rounded-lg p-3">
            <h2 className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-2">Building now</h2>
            <Row k="Rooms with data" v={sys && isNum(sys.rooms_with_data) ? `${sys.rooms_with_data} / ${sys.total_rooms}` : '—'} testId="rooms-with-data" />
            <Row k="Predicted occupied" v={sys ? fx(sys.occupied_rooms, 0) : '—'} />
            <Row k="Power, 25 sim. rooms" v={sys && isNum(sys.sim_estimated_power_watts) ? fx(sys.sim_estimated_power_watts / 1000, 1, ' kW') : '—'} />
            <Row k="Energy since start" v={sys && isNum(sys.sim_cumulative_energy_wh) ? fx(sys.sim_cumulative_energy_wh / 1000, 1, ' kWh') : '—'} />
            <Row k="Office A power" v={sys ? (isNum(sys.hardware_measured_power_watts) ? fx(sys.hardware_measured_power_watts, 2, ' W') : 'not measured') : '—'} />
            <Row k="AI accuracy (sim. rooms)" v={sys && acc && isNum(acc.accuracy) ? fx(acc.accuracy * 100, 1, '%') : '—'} testId="ai-accuracy" />
            <p className="text-[10px] text-slate-500 mt-2 leading-snug">
              Simulated-room power uses assumed watts per action (estimates, not measurements). AI accuracy compares the
              model&apos;s prediction with the simulator&apos;s true occupancy{acc && isNum(acc.room_ticks) ? ` over ${acc.room_ticks.toLocaleString()} room-ticks` : ''}.
              No energy-saving figure is shown: the live demo has no baseline to compare with.
            </p>
          </div>
        </aside>

        <main className="flex-1 relative bg-slate-950 min-w-0">
          <VanillaTwinWrapper />
        </main>

        <aside className="w-[340px] shrink-0 border-l border-slate-800 bg-slate-900/50 flex flex-col z-10 relative overflow-y-auto">
          <HardwareLivePanel />

          <div className="mt-auto p-3 bg-slate-900 border-t border-slate-800/50">
            <h2 className="text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-2">Sync status</h2>
            <Row k="Edge brain stream" v={oldBackend ? 'old edge brain version' : live ? 'connected' : `not connected${link.error ? ` (${link.error})` : ''}`} testId="sync-stream" />
            <Row k="Last update received" v={msgAgeMs !== null ? fx(msgAgeMs / 1000, 1, ' s ago') : '—'} testId="sync-age" />
            <Row k="Updates received" v={link.messages.toLocaleString()} />
            <Row k="Simulation loop" v={sys ? (sys.data_stale ? 'stalled' : 'running') : '—'} />
            <Row k="Rooms found in 3D model" v={twinSync ? `${twinSync.matched} / ${twinSync.received}` : '—'} testId="sync-3d" />
            {twinSync && twinSync.unmatched.length > 0 && (
              <div className="text-[10px] text-red-400 mt-1">Not in 3D model: {twinSync.unmatched.join(', ')}</div>
            )}
            <div className="text-[10px] text-slate-600 mt-2 font-mono truncate" title={EDGE_URL}>{EDGE_URL}</div>
          </div>
        </aside>

      </div>
    </div>
  );
}
