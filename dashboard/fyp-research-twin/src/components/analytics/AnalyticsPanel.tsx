'use client';

import React, { useEffect, useState } from 'react';
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, BarChart, Bar } from 'recharts';
import { backendIsCurrent, useBuildingStore } from '../../store/useBuildingStore';
import { api } from '../../lib/api';
import { COLORS, fx, isNum, TYPE_LABEL } from '../../lib/format';
import type { Comparison, Confusion, SeriesPoint } from '../../types/building';

const axis = { fontSize: 10, fill: COLORS.axis };
const tip = {
  contentStyle: { background: '#0f172a', border: '1px solid #334155', fontSize: 11, borderRadius: 6 },
  labelStyle: { color: COLORS.muted }, itemStyle: { padding: 0 }, cursor: { fill: 'rgba(148,163,184,0.08)' },
};
const FLOOR_SHORT: Record<string, string> = { '0': 'Ground', '1': 'Level 1', '2': 'Level 2', '3': 'Level 3', '4': 'Level 4' };

function Card({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
  return (
    <div className="bg-slate-900/60 border border-slate-800 rounded-lg p-2.5 flex flex-col min-h-0">
      <div className="flex items-baseline justify-between gap-2">
        <h4 className="text-[11px] font-semibold text-slate-200">{title}</h4>
        <span className="flex gap-2 shrink-0">
          <span className="flex items-center gap-1 text-[9.5px] text-slate-400"><span className="w-3 h-[3px] rounded" style={{ background: COLORS.ai }} />AI on</span>
          <span className="flex items-center gap-1 text-[9.5px] text-slate-400"><span className="w-3 h-[3px] rounded" style={{ background: COLORS.baseline }} />AI off</span>
        </span>
      </div>
      {note && <div className="text-[9.5px] text-slate-500 mb-1">{note}</div>}
      <div className="flex-1 min-h-[150px]">{children}</div>
    </div>
  );
}

function Matrix({ title, c }: { title: string; c: Confusion | null }) {
  if (!c || !c.n) return <div className="text-[11px] text-slate-500">{title}: no data</div>;
  const cell = (v: number, good: boolean, label: string) => (
    <div className={`rounded px-1.5 py-1 text-center ${good ? 'bg-sky-900/50 text-sky-100' : 'bg-orange-950/50 text-orange-200'}`}>
      <div className="text-[12px] font-bold">{((v / c.n) * 100).toFixed(1)}%</div>
      <div className="text-[9px] opacity-80">{label}</div>
    </div>
  );
  return (
    <div>
      <div className="text-[10.5px] text-slate-300 font-semibold mb-1">{title}</div>
      <div className="grid grid-cols-2 gap-1">
        {cell(c.tp, true, 'occupied, detected')}{cell(c.fn, false, 'missed people')}
        {cell(c.fp, false, 'false alarm')}{cell(c.tn, true, 'empty, detected')}
      </div>
      <div className="text-[10px] text-slate-400 mt-1 font-mono">
        acc {fx((c.accuracy ?? NaN) * 100, 1, '%')} · prec {fx(c.precision, 2)} · rec {fx(c.recall, 2)} · F1 {fx(c.f1, 2)}
      </div>
    </div>
  );
}

export default function AnalyticsPanel() {
  const raw = useBuildingStore((s) => s.raw);
  const link = useBuildingStore((s) => s.link);
  const live = link.connected && backendIsCurrent(raw);
  const [series, setSeries] = useState<SeriesPoint[]>([]);
  const comp: Comparison | null = live ? raw!.comparison : null;
  const seq = raw?.seq ?? 0;
  const bucket = Math.floor(seq / 20);

  useEffect(() => {
    if (!live) return;
    api.analytics().then((a) => setSeries(a.series)).catch(() => {});
  }, [live, bucket]);

  if (!comp) return <div className="p-3 text-[11px] text-slate-500">Waiting for the edge brain…</div>;
  const a = comp.ai, b = comp.conventional;
  const s = series.map((p) => ({ ...p, t: p.t.slice(5, 16).replace('T', ' ') }));
  const endUse = (['hvac', 'lighting', 'plug'] as const).map((k) => ({ k: k === 'hvac' ? 'AC + fans' : k === 'lighting' ? 'Lighting' : 'Plug loads', 'AI on': a.end_use_kwh[k], 'AI off': b.end_use_kwh[k] }));
  const floors = Object.keys(a.floor_kwh).sort().map((f) => ({ k: FLOOR_SHORT[f] ?? f, 'AI on': a.floor_kwh[f], 'AI off': b.floor_kwh[f] ?? 0 }));
  const comfort = Object.keys(a.comfort_by_type).filter((t) => (a.comfort_by_type[t]?.occupied_min ?? 0) > 0).map((t) => ({
    k: `${TYPE_LABEL[t] ?? t}${['corridor', 'lobby', 'bathroom'].includes(t) ? '*' : ''}`,
    'AI on': a.comfort_by_type[t].pmv_over_0_5_pct, 'AI off': b.comfort_by_type[t]?.pmv_over_0_5_pct ?? 0,
  }));
  const kwhFmt = (v: number) => `${v.toFixed(1)} kWh`;

  return (
    <div className="h-full overflow-y-auto p-2 grid grid-cols-3 gap-2 auto-rows-[minmax(200px,1fr)]" data-testid="analytics">
      <Card title="Building power (kW)" note={s.length ? `every 15 simulated minutes, same minutes under each mode, since ${comp.since.slice(5, 16).replace('T', ' ')}` : 'first point after 15 simulated minutes'}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={s} margin={{ top: 6, right: 8, left: -14, bottom: 0 }}>
            <CartesianGrid stroke={COLORS.grid} vertical={false} />
            <XAxis dataKey="t" tick={axis} minTickGap={40} />
            <YAxis tick={axis} />
            <Tooltip {...tip} />
            <Line type="monotone" dataKey="ai_power_kw" name="AI on" stroke={COLORS.ai} strokeWidth={2} dot={false} isAnimationActive={false} />
            <Line type="monotone" dataKey="conv_power_kw" name="AI off" stroke={COLORS.baseline} strokeWidth={2} dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </Card>
      <Card title="Energy used (kWh, cumulative, same minutes)" note={isNum(comp.saving_pct) ? `AI on ${fx(a.total_kwh, 1)} kWh vs AI off ${fx(b.total_kwh, 1)} kWh: ${comp.saving_pct.toFixed(1)}% ${comp.saving_pct >= 0 ? 'less' : 'more'}` : 'measuring…'}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={s} margin={{ top: 6, right: 8, left: -10, bottom: 0 }}>
            <CartesianGrid stroke={COLORS.grid} vertical={false} />
            <XAxis dataKey="t" tick={axis} minTickGap={40} />
            <YAxis tick={axis} />
            <Tooltip {...tip} />
            <Line type="monotone" dataKey="ai_kwh" name="AI on" stroke={COLORS.ai} strokeWidth={2} dot={false} isAnimationActive={false} />
            <Line type="monotone" dataKey="conv_kwh" name="AI off" stroke={COLORS.baseline} strokeWidth={2} dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </Card>
      <div className="bg-slate-900/60 border border-slate-800 rounded-lg p-2.5 space-y-2 overflow-y-auto">
        <h4 className="text-[11px] font-semibold text-slate-200">Occupancy estimation vs simulator truth</h4>
        <div className="grid grid-cols-2 gap-2">
          <Matrix title="PIR + CO₂ fusion (used by the AI)" c={comp.occupancy_fusion} />
          <Matrix title="Random Forest (original model)" c={comp.occupancy_random_forest} />
        </div>
        <div className="text-[9.5px] text-slate-500">Every simulated room, every minute: P ≥ 0.5 counted as occupied. Same sensor readings for both.</div>
      </div>
      <Card title="Energy by end use (kWh)">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={endUse} layout="vertical" margin={{ top: 4, right: 10, left: 10, bottom: 0 }} barGap={2}>
            <CartesianGrid stroke={COLORS.grid} horizontal={false} />
            <XAxis type="number" tick={axis} />
            <YAxis type="category" dataKey="k" tick={axis} width={70} />
            <Tooltip {...tip} formatter={(v) => kwhFmt(Number(v))} />
            <Bar dataKey="AI on" fill={COLORS.ai} radius={[0, 4, 4, 0]} barSize={9} isAnimationActive={false} />
            <Bar dataKey="AI off" fill={COLORS.baseline} radius={[0, 4, 4, 0]} barSize={9} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </Card>
      <Card title="Energy by floor (kWh)">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={floors} margin={{ top: 4, right: 8, left: -10, bottom: 0 }} barGap={2}>
            <CartesianGrid stroke={COLORS.grid} vertical={false} />
            <XAxis dataKey="k" tick={axis} />
            <YAxis tick={axis} />
            <Tooltip {...tip} formatter={(v) => kwhFmt(Number(v))} />
            <Bar dataKey="AI on" fill={COLORS.ai} radius={[4, 4, 0, 0]} barSize={12} isAnimationActive={false} />
            <Bar dataKey="AI off" fill={COLORS.baseline} radius={[4, 4, 0, 0]} barSize={12} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </Card>
      <Card title="Uncomfortable time by room type (% of occupied minutes, |PMV| > 0.5)" note="* transit spaces: shown, but not in the comfort KPI (PMV applies to stays of 15 min or more)">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={comfort} margin={{ top: 4, right: 8, left: -14, bottom: 0 }} barGap={2}>
            <CartesianGrid stroke={COLORS.grid} vertical={false} />
            <XAxis dataKey="k" tick={{ ...axis, fontSize: 9 }} interval={0} />
            <YAxis tick={axis} domain={[0, 100]} />
            <Tooltip {...tip} formatter={(v) => `${Number(v).toFixed(1)}%`} />
            <Bar dataKey="AI on" fill={COLORS.ai} radius={[4, 4, 0, 0]} barSize={8} isAnimationActive={false} />
            <Bar dataKey="AI off" fill={COLORS.baseline} radius={[4, 4, 0, 0]} barSize={8} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </Card>
    </div>
  );
}
