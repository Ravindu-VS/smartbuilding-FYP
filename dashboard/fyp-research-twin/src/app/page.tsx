'use client';

import React, { useEffect } from 'react';
import { Brain, BarChart3, Gauge, ChevronDown, ChevronUp } from 'lucide-react';
import { EDGE_URL, useNow, useSSE } from '../hooks/useSSE';
import { backendIsCurrent, useBuildingStore } from '../store/useBuildingStore';
import { api } from '../lib/api';
import { fx } from '../lib/format';
import Header from '../components/layout/Header';
import KpiStrip from '../components/building/KpiStrip';
import BuildingNav from '../components/building/BuildingNav';
import VanillaTwinWrapper from '../components/3d/VanillaTwinWrapper';
import RoomPanel from '../components/room/RoomPanel';
import DecisionFeed from '../components/timeline/DecisionFeed';
import AnalyticsPanel from '../components/analytics/AnalyticsPanel';
import EnergyMeterPanel from '../components/analytics/EnergyMeterPanel';
import DemoMode from '../components/demo/DemoMode';

// Every number on this page comes from the edge brain (SSE stream and its API) or is
// measured in the browser (message age). Nothing is hard-coded.

function SyncFooter() {
  const now = useNow(1000);
  const link = useBuildingStore((s) => s.link);
  const raw = useBuildingStore((s) => s.raw);
  const twinSync = useBuildingStore((s) => s.twinSync);
  const age = link.lastMessageAt !== null ? Math.max(0, now - link.lastMessageAt) / 1000 : null;
  const clock = backendIsCurrent(raw) ? raw!.clock : null;
  return (
    <div className="shrink-0 h-6 border-t border-slate-800 bg-slate-950 px-3 flex items-center gap-4 text-[10px] text-slate-500 font-mono">
      <span data-testid="sync-stream">stream: {link.connected ? 'connected' : `not connected${link.error ? ` (${link.error})` : ''}`}</span>
      <span data-testid="sync-age">last update {age !== null ? `${age.toFixed(1)} s ago` : '—'}</span>
      <span>{link.messages.toLocaleString()} updates</span>
      <span data-testid="sync-3d">3D rooms {twinSync ? `${twinSync.matched}/${twinSync.received}` : '—'}</span>
      {clock && <span>control step {clock.control_step_s} s · physics step {clock.physics_step_s} s · {fx(clock.step_ms_median, 1)} ms per step · seed {clock.seed}</span>}
      <span className="ml-auto truncate" title={EDGE_URL}>{EDGE_URL}</span>
    </div>
  );
}

export default function Dashboard() {
  useSSE();
  const link = useBuildingStore((s) => s.link);
  const raw = useBuildingStore((s) => s.raw);
  const config = useBuildingStore((s) => s.config);
  const setConfig = useBuildingStore((s) => s.setConfig);
  const tab = useBuildingStore((s) => s.bottomTab);
  const setTab = useBuildingStore((s) => s.setBottomTab);
  const collapsed = useBuildingStore((s) => s.bottomCollapsed);
  const setCollapsed = useBuildingStore((s) => s.setBottomCollapsed);
  const oldBackend = link.connected && raw !== null && !backendIsCurrent(raw);

  useEffect(() => {
    if (link.connected && !config && !oldBackend) api.config().then(setConfig).catch(() => {});
  }, [link.connected, config, oldBackend, setConfig]);

  return (
    <div className="h-screen bg-slate-950 text-slate-200 flex flex-col font-sans overflow-hidden">
      <Header />
      {oldBackend && (
        <div className="shrink-0 px-6 py-2 bg-red-950/70 border-b border-red-800 text-red-200 text-sm" data-testid="old-backend">
          An older edge brain is answering on port 8001 (different data format, so it is not shown).
          Close every &quot;Edge Brain&quot; window (or run <code className="text-red-100">netstat -ano | findstr :8001</code> and
          <code className="text-red-100"> taskkill /PID &lt;pid&gt; /F</code>), then start <code className="text-red-100">run_local.bat</code> again.
        </div>
      )}
      <KpiStrip />
      <div className="flex-1 flex min-h-0">
        <BuildingNav />
        <main className="flex-1 flex flex-col min-w-0 min-h-0">
          <div className="relative flex-[3] min-h-[300px] bg-slate-950">
            <VanillaTwinWrapper />
            <DemoMode />
          </div>
          <div className={`${collapsed ? 'flex-none' : 'flex-[2] min-h-[200px]'} border-t border-slate-800 flex flex-col bg-slate-950`}>
            <div className="flex items-center gap-1 px-2 pt-1.5 border-b border-slate-800">
              <button onClick={() => setTab('decisions')} className={`px-3 py-1 text-[11.5px] rounded-t-md flex items-center gap-1.5 ${tab === 'decisions' ? 'bg-slate-800 text-white' : 'text-slate-400 hover:text-white'}`} data-testid="tab-decisions"><Brain size={13} />AI decisions</button>
              <button onClick={() => setTab('meter')} className={`px-3 py-1 text-[11.5px] rounded-t-md flex items-center gap-1.5 ${tab === 'meter' ? 'bg-slate-800 text-white' : 'text-slate-400 hover:text-white'}`} data-testid="tab-meter"><Gauge size={13} />Energy meter</button>
              <button onClick={() => setTab('analytics')} className={`px-3 py-1 text-[11.5px] rounded-t-md flex items-center gap-1.5 ${tab === 'analytics' ? 'bg-slate-800 text-white' : 'text-slate-400 hover:text-white'}`} data-testid="tab-analytics"><BarChart3 size={13} />Analytics</button>
              <button onClick={() => setCollapsed(!collapsed)} className="ml-auto mb-1 px-2 py-0.5 text-[11px] rounded-md text-slate-400 hover:text-white hover:bg-slate-800 flex items-center gap-1" title={collapsed ? 'Show the panels' : 'Hide the panels: more room for the 3D view'} data-testid="drawer-toggle">
                {collapsed ? <><ChevronUp size={13} />Show panels</> : <><ChevronDown size={13} />Larger 3D view</>}
              </button>
            </div>
            {!collapsed && <div className="flex-1 min-h-0">{tab === 'decisions' ? <DecisionFeed /> : tab === 'meter' ? <EnergyMeterPanel /> : <AnalyticsPanel />}</div>}
          </div>
        </main>
        <RoomPanel />
      </div>
      <SyncFooter />
    </div>
  );
}
