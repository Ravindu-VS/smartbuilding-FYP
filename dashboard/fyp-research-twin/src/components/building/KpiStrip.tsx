'use client';

import React from 'react';
import { TrendingDown, TrendingUp, Gauge } from 'lucide-react';
import { backendIsCurrent, useBuildingStore } from '../../store/useBuildingStore';
import { fx, isNum } from '../../lib/format';

/**
 * Top strip: the building's energy meter (follows the AI switch) and the measured
 * comparison of AI ON against AI OFF over the same simulated minutes (the twin copy
 * always runs the other mode, with identical weather, people and sensor noise).
 */

function Delta({ better, text }: { better: boolean | null; text: string }) {
  if (better === null) return <span className="text-slate-500 text-[10px]">{text}</span>;
  const Icon = better ? TrendingDown : TrendingUp;
  return (
    <span className={`inline-flex items-center gap-0.5 text-[10px] font-semibold ${better ? 'text-emerald-400' : 'text-orange-300'}`}>
      <Icon size={11} />{text}
    </span>
  );
}

function Tile({ label, ai, off, delta, title, testId }: {
  label: string; ai: string; off: string; delta?: React.ReactNode; title: string; testId?: string;
}) {
  return (
    <div className="px-3 py-1.5 min-w-0 border-r border-slate-800 last:border-r-0" title={title}>
      <div className="text-[9.5px] uppercase tracking-wider text-slate-500 truncate">{label}</div>
      <div className="flex items-baseline gap-1.5">
        <span className="text-[15px] font-bold text-white" data-testid={testId}>{ai}</span>
        {delta}
      </div>
      <div className="text-[10px] text-slate-500 truncate">AI off: {off}</div>
    </div>
  );
}

export function span(minutes: number) {
  if (minutes < 60) return `${minutes} min`;
  const h = Math.floor(minutes / 60), m = minutes % 60;
  return h >= 48 ? `${(minutes / 1440).toFixed(1)} days` : `${h} h ${m} min`;
}

export default function KpiStrip() {
  const raw = useBuildingStore((s) => s.raw);
  const link = useBuildingStore((s) => s.link);
  const setTab = useBuildingStore((s) => s.setBottomTab);
  if (!link.connected || !backendIsCurrent(raw)) return null;
  const c = raw!.comparison;
  const m = raw!.meter;
  const learning = raw!.clock.phase === 'learning';
  const a = c.ai, b = c.conventional;
  const enough = a.minutes >= 30;
  const save = enough ? c.saving_pct : null;
  const better = (x: number, y: number) => (Math.abs(x - y) < 1e-9 ? null : x < y);
  const fu = c.occupancy_fusion, rf = c.occupancy_random_forest;
  const cur = m.current;

  if (learning) {
    return (
      <div className="shrink-0 border-b border-slate-800 bg-violet-950/30 px-4 py-1.5 text-[11px] text-violet-200" data-testid="kpi-learning">
        The AI is in its learning week ({raw!.clock.learning_days} simulated days, as in the thesis experiments): it learns each
        room&apos;s routine from its own PIR/CO₂ estimates. Measured results start when it ends.
      </div>
    );
  }

  const aiOn = m.ai_enabled;
  const curAi = cur ? (cur.mode === 'ai' ? cur.kwh : cur.other_kwh) : null;
  const curOff = cur ? (cur.mode === 'ai' ? cur.other_kwh : cur.kwh) : null;

  return (
    <div className="shrink-0 border-b border-slate-800 bg-slate-900/40 flex items-stretch" data-testid="kpi-strip">
      {/* The building's energy meter */}
      <button onClick={() => setTab('meter')} title="Open the energy meter"
        className={`px-3 py-1.5 border-r border-slate-800 flex items-center gap-3 min-w-[330px] text-left hover:bg-slate-800/40 ${aiOn ? 'bg-emerald-950/20' : 'bg-orange-950/20'}`} data-testid="meter-tile">
        <Gauge size={26} className={aiOn ? 'text-emerald-400' : 'text-orange-300'} />
        <div className="min-w-0">
          <div className="text-[9.5px] uppercase tracking-wider text-slate-500">Building energy meter · AI {aiOn ? 'ON' : 'OFF'}</div>
          <div className="flex items-baseline gap-2">
            <span className="text-[19px] font-bold text-white leading-tight" data-testid="meter-power">{fx(m.power_kw, 1, ' kW')}</span>
            <span className="text-[10.5px] text-slate-400">{aiOn ? 'with AI off it would be' : 'with AI on it would be'} {fx(m.other_power_kw, 1, ' kW')}</span>
          </div>
          {cur && (
            <div className="text-[10px] text-slate-400 truncate">
              AI {aiOn ? 'on' : 'off'} for {span(cur.minutes)}: {fx(cur.kwh, 1, ' kWh')} used
              {isNum(curAi) && isNum(curOff) && cur.minutes >= 5 && curOff > 0.01
                ? <span className={curAi <= curOff ? 'text-emerald-400' : 'text-orange-300'}> · AI {curAi <= curOff ? 'saves' : 'uses'} {Math.abs(100 * (1 - curAi / curOff)).toFixed(1)}% {curAi <= curOff ? '' : 'more '}over these minutes</span> : null}
            </div>
          )}
        </div>
      </button>
      <div className="grid grid-cols-6 flex-1 min-w-0">
        <Tile label="Energy, AI on" ai={fx(a.total_kwh, a.total_kwh < 100 ? 1 : 0, ' kWh')} off={fx(b.total_kwh, b.total_kwh < 100 ? 1 : 0, ' kWh')}
          delta={isNum(save) ? <Delta better={save > 0} text={`${Math.abs(save).toFixed(1)}% ${save >= 0 ? 'less' : 'more'}`} /> : <Delta better={null} text="measuring…" />}
          title={`Electricity of the 25 simulated rooms over the same ${span(a.minutes)} under each mode (${c.basis}).`}
          testId="kpi-energy" />
        <Tile label="Cost" ai={`LKR ${fx(a.cost_lkr, 0)}`} off={`LKR ${fx(b.cost_lkr, 0)}`}
          delta={enough ? <Delta better={better(a.cost_lkr, b.cost_lkr)} text={`LKR ${fx(Math.abs(b.cost_lkr - a.cost_lkr), 0)}`} /> : undefined}
          title={`Energy × ${c.tariff_lkr_per_kwh} LKR/kWh (${c.tariff_note}).`} />
        <Tile label="Uncomfortable time" ai={fx(a.thermal_discomfort_pct, 1, '%')} off={fx(b.thermal_discomfort_pct, 1, '%')}
          delta={enough ? <Delta better={better(a.thermal_discomfort_pct, b.thermal_discomfort_pct)} text={`${fx(Math.abs(a.thermal_discomfort_pct - b.thermal_discomfort_pct), 1)} pts`} /> : undefined}
          title={`Share of occupied minutes with |PMV| > 0.5 (ISO 7730), ${a.thermal_discomfort_basis}.`} testId="kpi-comfort" />
        <Tile label="Peak demand (15 min)" ai={fx(a.peak_15min_kw, 1, ' kW')} off={fx(b.peak_15min_kw, 1, ' kW')}
          delta={a.minutes >= 15 ? <Delta better={better(a.peak_15min_kw, b.peak_15min_kw)} text={`${fx(Math.abs(b.peak_15min_kw - a.peak_15min_kw), 1)} kW`} /> : undefined}
          title="Highest 15-minute average power under each mode." />
        <Tile label="Lights on, empty rooms" ai={fx(a.lights_on_empty_pct, 1, '%')} off={fx(b.lights_on_empty_pct, 1, '%')}
          delta={enough ? <Delta better={better(a.lights_on_empty_pct, b.lights_on_empty_pct)} text={`${fx(Math.abs(a.lights_on_empty_pct - b.lights_on_empty_pct), 1)} pts`} /> : undefined}
          title="Share of empty-room minutes (simulator truth) with the lights on." />
        <div className="px-3 py-1.5 min-w-0" title="Occupancy estimate (P ≥ 0.5) of the learned PIR+CO₂ fusion that drives the AI, against the simulator's head count, every room every minute. It keeps retraining on new data while the system runs. The Random Forest is the project's original model (trained on the real UCI office), on the same readings.">
          <div className="text-[9.5px] uppercase tracking-wider text-slate-500 truncate">Occupancy accuracy</div>
          <div className="flex items-baseline gap-1.5">
            <span className="text-[15px] font-bold text-white" data-testid="kpi-accuracy">{isNum(fu.accuracy) ? `${(fu.accuracy * 100).toFixed(1)}%` : '—'}</span>
            <span className="text-[10px] text-slate-400">learned PIR+CO₂</span>
          </div>
          <div className="text-[10px] text-slate-500 truncate">Random Forest: {rf && isNum(rf.accuracy) ? `${(rf.accuracy * 100).toFixed(1)}%` : '—'}</div>
        </div>
      </div>
    </div>
  );
}
