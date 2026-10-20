'use client';

import React, { useEffect, useState } from 'react';
import { ResponsiveContainer, ComposedChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, ReferenceArea } from 'recharts';
import { Cpu, Power } from 'lucide-react';
import { backendIsCurrent, useBuildingStore } from '../../store/useBuildingStore';
import { api } from '../../lib/api';
import { COLORS, fx, isNum } from '../../lib/format';
import type { Meter, SeriesPoint } from '../../types/building';
import { span } from '../building/KpiStrip';

/**
 * The energy meter: the building's power over time with the AI switch positions
 * shaded, one row per switch period (what the building used, and what the twin copy
 * used over the same minutes under the other mode), the same hours of the day on
 * different days, and the real room's measured (INA226) meter.
 */
const axis = { fontSize: 10, fill: COLORS.axis };
const tip = {
  contentStyle: { background: '#0f172a', border: '1px solid #334155', fontSize: 11, borderRadius: 6 },
  labelStyle: { color: COLORS.muted }, itemStyle: { padding: 0 },
};
const t5 = (iso: string | null) => (iso ? iso.slice(5, 16).replace('T', ' ') : 'now');

export default function EnergyMeterPanel() {
  const raw = useBuildingStore((s) => s.raw);
  const link = useBuildingStore((s) => s.link);
  const live = link.connected && backendIsCurrent(raw);
  const [series, setSeries] = useState<SeriesPoint[]>([]);
  const [meter, setMeter] = useState<Meter | null>(null);
  const bucket = Math.floor((raw?.seq ?? 0) / 8);
  const switchedAt = raw?.meter?.current?.start;

  useEffect(() => {
    if (!live) return;
    api.analytics().then((a) => { setSeries(a.series); setMeter(a.meter); }).catch(() => {});
  }, [live, bucket, switchedAt]);

  if (!live) return <div className="p-3 text-[11px] text-slate-500">Waiting for the edge brain…</div>;
  const m = meter ?? raw!.meter;
  const real = raw!.meter.real_rooms?.[0];
  const data = series.map((p) => ({ ...p, t: p.t.slice(5, 16).replace('T', ' ') }));
  // shaded bands for the periods with AI off
  const bands: { x1: string; x2: string }[] = [];
  let startIdx: number | null = null;
  data.forEach((p, i) => {
    if (p.mode === 'conventional' && startIdx === null) startIdx = i;
    if ((p.mode !== 'conventional' || i === data.length - 1) && startIdx !== null) {
      bands.push({ x1: data[startIdx].t, x2: p.t });
      startIdx = null;
    }
  });
  const by = m.building_by_mode;

  return (
    <div className="h-full overflow-y-auto p-2 grid grid-cols-[1.35fr_1fr] gap-2" data-testid="meter-panel">
      <div className="bg-slate-900/60 border border-slate-800 rounded-lg p-2.5 flex flex-col min-h-[230px]">
        <div className="flex items-baseline justify-between">
          <h4 className="text-[11px] font-semibold text-slate-200">Building power (kW) — grey bands: AI switched off</h4>
          <span className="flex gap-3">
            <span className="flex items-center gap-1 text-[9.5px] text-slate-400"><span className="w-3 h-[3px] rounded" style={{ background: COLORS.ai }} />under AI</span>
            <span className="flex items-center gap-1 text-[9.5px] text-slate-400"><span className="w-3 h-[3px] rounded" style={{ background: COLORS.baseline }} />under AI off</span>
          </span>
        </div>
        <div className="text-[9.5px] text-slate-500 mb-1">Both lines are the same building at the same minutes: one copy is the building (follows the switch), the other its digital twin running the other mode.</div>
        <div className="flex-1 min-h-[170px]">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={data} margin={{ top: 6, right: 8, left: -14, bottom: 0 }}>
              <CartesianGrid stroke={COLORS.grid} vertical={false} />
              {bands.map((b, i) => <ReferenceArea key={i} x1={b.x1} x2={b.x2} fill="#64748b" fillOpacity={0.18} strokeOpacity={0} />)}
              <XAxis dataKey="t" tick={axis} minTickGap={40} />
              <YAxis tick={axis} />
              <Tooltip {...tip} />
              <Line type="monotone" dataKey="ai_power_kw" name="under AI" stroke={COLORS.ai} strokeWidth={2} dot={false} isAnimationActive={false} />
              <Line type="monotone" dataKey="conv_power_kw" name="under AI off" stroke={COLORS.baseline} strokeWidth={2} dot={false} isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
        <div className="grid grid-cols-3 gap-2 mt-1.5 text-[10.5px]">
          <div className="bg-slate-800/50 rounded px-2 py-1"><div className="text-slate-500">Meter total</div><div className="text-white font-bold">{fx(m.total_kwh, 1, ' kWh')}</div></div>
          <div className="bg-slate-800/50 rounded px-2 py-1"><div className="text-slate-500">Avg power while AI on</div><div className="text-white font-bold">{fx(by.ai.avg_kw, 1, ' kW')} <span className="text-slate-500 font-normal">({span(by.ai.minutes)})</span></div></div>
          <div className="bg-slate-800/50 rounded px-2 py-1"><div className="text-slate-500">Avg power while AI off</div><div className="text-white font-bold">{fx(by.conventional.avg_kw, 1, ' kW')} <span className="text-slate-500 font-normal">({span(by.conventional.minutes)})</span></div></div>
        </div>
      </div>

      <div className="space-y-2 min-w-0">
        <div className="bg-slate-900/60 border border-slate-800 rounded-lg p-2.5">
          <h4 className="text-[11px] font-semibold text-slate-200 mb-1">Switch periods (building meter)</h4>
          <table className="w-full text-[10.5px]">
            <thead className="text-slate-500">
              <tr><th className="text-left font-normal">AI</th><th className="text-left font-normal">from – to</th><th className="text-right font-normal">used</th><th className="text-right font-normal">other mode, same minutes</th><th className="text-right font-normal">AI saves</th></tr>
            </thead>
            <tbody>
              {[...m.segments].reverse().slice(0, 8).map((s, i) => (
                <tr key={`${s.start}-${i}`} className="border-t border-slate-800">
                  <td className="py-0.5"><span className={`inline-flex items-center gap-0.5 px-1 rounded text-[9.5px] font-bold ${s.mode === 'ai' ? 'bg-emerald-900/70 text-emerald-200' : 'bg-slate-700 text-slate-200'}`}><Power size={9} />{s.mode === 'ai' ? 'ON' : 'OFF'}</span></td>
                  <td className="text-slate-400 font-mono">{t5(s.start)} – {s.end ? s.end.slice(11, 16) : 'now'} <span className="text-slate-600">({span(s.minutes)})</span></td>
                  <td className="text-right text-white font-mono">{fx(s.kwh, 1)} kWh</td>
                  <td className="text-right text-slate-400 font-mono">{fx(s.other_kwh, 1)} kWh</td>
                  <td className={`text-right font-mono font-semibold ${isNum(s.ai_saving_pct) ? (s.ai_saving_pct >= 0 ? 'text-emerald-400' : 'text-orange-300') : 'text-slate-500'}`}>{isNum(s.ai_saving_pct) ? `${s.ai_saving_pct.toFixed(1)}%` : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="text-[9.5px] text-slate-500 mt-1">Turn AI off for a while, then on: each period shows what the building used and what the other mode used over exactly the same minutes (same weather and people).</div>
        </div>

        {m.same_hours && m.same_hours.some((r) => r.ai_minutes && r.conv_minutes) && (
          <div className="bg-slate-900/60 border border-slate-800 rounded-lg p-2.5">
            <h4 className="text-[11px] font-semibold text-slate-200 mb-1">Same hours of the day, building meter (different days)</h4>
            <div className="grid grid-cols-6 gap-1 text-[10px]">
              {m.same_hours.filter((r) => r.ai_minutes && r.conv_minutes).slice(0, 12).map((r) => (
                <div key={r.hour} className="bg-slate-800/50 rounded px-1.5 py-1">
                  <div className="text-slate-500">{String(r.hour).padStart(2, '0')}:00</div>
                  <div className="text-sky-300">on {fx(r.ai_avg_kw, 0)} kW</div>
                  <div className="text-orange-300">off {fx(r.conv_avg_kw, 0)} kW</div>
                </div>
              ))}
            </div>
            <div className="text-[9.5px] text-slate-500 mt-1">Like a real building&apos;s before/after check: weather and people differ between days, so the twin comparison above is the fair one.</div>
          </div>
        )}

        <div className="bg-slate-900/60 border border-slate-800 rounded-lg p-2.5" data-testid="real-meter">
          <h4 className="text-[11px] font-semibold text-slate-200 mb-1 flex items-center gap-1"><Cpu size={12} className="text-cyan-300" />Real room meter — {real?.room_name ?? 'Office A'} (INA226, measured)</h4>
          {!real ? <div className="text-[11px] text-slate-500">No real room.</div> : (
            <>
              <div className="flex gap-4 text-[11px]">
                <span>now <b className="text-white">{isNum(real.power_w) ? `${real.power_w.toFixed(2)} W` : '—'}</b></span>
                <span>total <b className="text-white">{fx(real.total_wh, 3, ' Wh')}</b></span>
                <span>AI on avg <b className="text-sky-300">{fx(real.by_mode.ai.avg_w, 2, ' W')}</b></span>
                <span>AI off avg <b className="text-orange-300">{fx(real.by_mode.conventional.avg_w, 2, ' W')}</b></span>
              </div>
              <div className="text-[9.5px] text-slate-500 mt-1">The same switch drives the board: its fan (AC), LED (lights) and damper get AI or schedule decisions, and the board measures what that draws. A real room cannot run both modes at once, so compare its periods.</div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
