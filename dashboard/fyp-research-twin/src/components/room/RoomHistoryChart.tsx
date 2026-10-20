'use client';

import React from 'react';
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, ComposedChart, Area } from 'recharts';
import type { HistoryPoint } from '../../types/building';
import { COLORS } from '../../lib/format';

const axis = { fontSize: 9, fill: COLORS.axis };
const tip = {
  contentStyle: { background: '#0f172a', border: '1px solid #334155', fontSize: 11, borderRadius: 6 },
  labelStyle: { color: COLORS.muted },
  itemStyle: { padding: 0 },
};

function Mini({ title, children, legend }: { title: string; children: React.ReactElement; legend?: React.ReactNode }) {
  return (
    <div>
      <div className="flex items-center justify-between">
        <span className="text-[9.5px] uppercase tracking-wide text-slate-500">{title}</span>
        {legend}
      </div>
      <div className="h-[86px]">
        <ResponsiveContainer width="100%" height="100%">{children}</ResponsiveContainer>
      </div>
    </div>
  );
}

const Key = ({ items }: { items: { color: string; label: string }[] }) => (
  <span className="flex gap-2">
    {items.map((i) => (
      <span key={i.label} className="flex items-center gap-1 text-[9.5px] text-slate-400">
        <span className="inline-block w-3 h-[2px]" style={{ background: i.color }} />{i.label}
      </span>
    ))}
  </span>
);

const hhmm = (t: string) => (t && t.length >= 16 ? t.slice(11, 16) : t);
const AI_VS_SCHEDULE = [{ color: COLORS.ai, label: 'AI on' }, { color: COLORS.baseline, label: 'AI off' }];

export default function RoomHistoryChart({ data, hardware }: { data: HistoryPoint[]; hardware?: boolean }) {
  if (!data.length) {
    return <div className="text-[11px] text-slate-500">No history yet ({hardware ? 'one point per board reading' : 'sampled every 5 simulated minutes'}).</div>;
  }
  const d = data.map((p) => ({
    ...p,
    t: hhmm(p.t),
    power_kw: p.power_w != null ? p.power_w / 1000 : null,
    ai_kw: p.ai_power_w != null ? p.ai_power_w / 1000 : null,
    conv_kw: p.conv_power_w != null ? p.conv_power_w / 1000 : null,
    occupied: (p.occupants ?? (p.presence ? 1 : 0)) > 0 ? 1 : 0,
  }));
  const margin = { top: 4, right: 4, left: -22, bottom: 0 };
  return (
    <div className="space-y-1.5">
      <Mini title="Air temperature (°C)" legend={!hardware ? <Key items={AI_VS_SCHEDULE} /> : undefined}>
        <LineChart data={d} margin={margin}>
          <CartesianGrid stroke={COLORS.grid} vertical={false} />
          <XAxis dataKey="t" tick={axis} interval="preserveStartEnd" minTickGap={30} />
          <YAxis tick={axis} domain={['auto', 'auto']} width={44} />
          <Tooltip {...tip} />
          {hardware && <Line type="monotone" dataKey="temperature" name="temperature" stroke={COLORS.ai} strokeWidth={2} dot={false} isAnimationActive={false} />}
          {!hardware && <Line type="monotone" dataKey="ai_temperature" name="AI on" stroke={COLORS.ai} strokeWidth={2} dot={false} isAnimationActive={false} />}
          {!hardware && <Line type="monotone" dataKey="conv_temperature" name="AI off" stroke={COLORS.baseline} strokeWidth={2} dot={false} isAnimationActive={false} />}
        </LineChart>
      </Mini>
      {!hardware ? (
        <Mini title="Electric power (kW)" legend={<Key items={AI_VS_SCHEDULE} />}>
          <LineChart data={d} margin={margin}>
            <CartesianGrid stroke={COLORS.grid} vertical={false} />
            <XAxis dataKey="t" tick={axis} interval="preserveStartEnd" minTickGap={30} />
            <YAxis tick={axis} width={44} />
            <Tooltip {...tip} />
            <Line type="stepAfter" dataKey="ai_kw" name="AI on" stroke={COLORS.ai} strokeWidth={2} dot={false} isAnimationActive={false} />
            <Line type="stepAfter" dataKey="conv_kw" name="AI off" stroke={COLORS.baseline} strokeWidth={2} dot={false} isAnimationActive={false} />
          </LineChart>
        </Mini>
      ) : (
        <Mini title="Light at the sensor (lux)">
          <LineChart data={d} margin={margin}>
            <CartesianGrid stroke={COLORS.grid} vertical={false} />
            <XAxis dataKey="t" tick={axis} interval="preserveStartEnd" minTickGap={30} />
            <YAxis tick={axis} width={44} />
            <Tooltip {...tip} />
            <Line type="monotone" dataKey="lux" name="lux" stroke={COLORS.ai} strokeWidth={2} dot={false} isAnimationActive={false} />
          </LineChart>
        </Mini>
      )}
      <Mini title={hardware ? 'Presence sensor vs AI estimate' : 'Occupied (simulator truth) vs AI estimate'}
        legend={<Key items={[{ color: '#64748b', label: hardware ? 'presence' : 'occupied' }, { color: COLORS.ai, label: 'P(occupied)' }]} />}>
        <ComposedChart data={d} margin={margin}>
          <CartesianGrid stroke={COLORS.grid} vertical={false} />
          <XAxis dataKey="t" tick={axis} interval="preserveStartEnd" minTickGap={30} />
          <YAxis tick={axis} domain={[0, 1]} ticks={[0, 0.5, 1]} width={44} />
          <Tooltip {...tip} />
          <Area type="stepAfter" dataKey="occupied" name={hardware ? 'presence' : 'occupied'} stroke="#64748b" fill="#334155" isAnimationActive={false} />
          <Line type="stepAfter" dataKey="p_occ" name="P(occupied)" stroke={COLORS.ai} strokeWidth={2} dot={false} isAnimationActive={false} />
        </ComposedChart>
      </Mini>
    </div>
  );
}
