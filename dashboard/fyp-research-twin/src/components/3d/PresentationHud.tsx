'use client';

import React, { useState } from 'react';
import { X, Users, Zap } from 'lucide-react';
import { backendIsCurrent, useBuildingStore } from '../../store/useBuildingStore';
import { api } from '../../lib/api';
import { fx, isNum } from '../../lib/format';
import { AiSwitch } from '../layout/Header';

/**
 * Top bar shown in presentation mode (the 3D view fills the screen): the simulated
 * clock, the AI master switch and the building's power now with AI on vs AI off.
 */
export default function PresentationHud() {
  const raw = useBuildingStore((s) => s.raw);
  const link = useBuildingStore((s) => s.link);
  const setPresentation = useBuildingStore((s) => s.setPresentation);
  const [busy, setBusy] = useState(false);
  const live = link.connected && backendIsCurrent(raw);
  const clock = live ? raw!.clock : null;
  const m = live ? raw!.meter : null;
  const aiKw = m ? (m.mode === 'ai' ? m.power_kw : m.other_power_kw) : null;
  const offKw = m ? (m.mode === 'ai' ? m.other_power_kw : m.power_kw) : null;
  const saving = isNum(aiKw) && isNum(offKw) && offKw > 0 ? (100 * (offKw - aiKw)) / offKw : null;

  return (
    <div className="absolute top-0 inset-x-0 z-30 h-14 px-4 flex items-center gap-4 bg-gradient-to-b from-slate-950/95 to-slate-950/70 border-b border-slate-800/80 backdrop-blur" data-testid="presentation-hud">
      <div className="min-w-0">
        <div className="text-white font-bold text-[16px] tracking-tight leading-tight">Smart Hub — AI-controlled digital twin</div>
        <div className="text-[11px] text-slate-400 leading-tight">25 simulated rooms + 1 live room (ESP32) · decisions every simulated minute</div>
      </div>
      <div className="mx-auto flex items-center gap-3">
        <div className="px-3 py-1 rounded-lg bg-slate-900/80 border border-slate-700 font-mono text-white text-[18px] font-semibold" data-testid="hud-clock">
          {clock ? `${clock.weekday.slice(0, 3)} ${clock.time.slice(0, 5)}` : '--:--'}
        </div>
        <AiSwitch live={live} learning={clock?.phase === 'learning'} busy={busy} on={raw?.ai_enabled ?? true}
          onToggle={async (v) => { setBusy(true); try { await api.setAi(v); } finally { setBusy(false); } }} />
      </div>
      <div className="flex items-center gap-2">
        <div className="px-2.5 py-1 rounded-lg bg-slate-900/80 border border-slate-700 text-center">
          <div className="text-[9.5px] uppercase tracking-wider text-slate-500">with AI</div>
          <div className="text-[15px] font-bold text-[#6ea8f0] flex items-center gap-1"><Zap size={13} />{fx(aiKw, 1, ' kW')}</div>
        </div>
        <div className="px-2.5 py-1 rounded-lg bg-slate-900/80 border border-slate-700 text-center">
          <div className="text-[9.5px] uppercase tracking-wider text-slate-500">AI off</div>
          <div className="text-[15px] font-bold text-[#e8865a]">{fx(offKw, 1, ' kW')}</div>
        </div>
        <div className="px-2.5 py-1 rounded-lg bg-emerald-950/60 border border-emerald-800 text-center">
          <div className="text-[9.5px] uppercase tracking-wider text-emerald-500">saving now</div>
          <div className="text-[15px] font-bold text-emerald-300">{fx(saving, 1, ' %')}</div>
        </div>
        <div className="px-2.5 py-1 rounded-lg bg-slate-900/80 border border-slate-700 text-center">
          <div className="text-[9.5px] uppercase tracking-wider text-slate-500">people</div>
          <div className="text-[15px] font-bold text-white flex items-center gap-1"><Users size={13} />{live ? raw!.system.people_simulated : '—'}</div>
        </div>
        <button onClick={() => setPresentation(false)} title="Leave presentation mode (Esc)" className="ml-1 h-8 w-8 flex items-center justify-center rounded-lg border border-slate-700 text-slate-300 hover:text-white hover:bg-slate-800" data-testid="hud-exit"><X size={16} /></button>
      </div>
    </div>
  );
}
