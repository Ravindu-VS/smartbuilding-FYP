'use client';

import React from 'react';
import { Lightbulb, Snowflake, Wind, ShieldCheck, ShieldAlert, Brain } from 'lucide-react';
import type { ControlDecision, Reasoning, TimelineEvent } from '../../types/building';
import { acLabel, fx, isNum } from '../../lib/format';

function State({ icon, label, value, on }: { icon: React.ReactNode; label: string; value: string; on: boolean }) {
  return (
    <div className={`rounded-lg border px-2 py-1.5 ${on ? 'border-sky-700 bg-sky-950/40' : 'border-slate-700 bg-slate-800/40'}`}>
      <div className="flex items-center gap-1 text-[9.5px] uppercase tracking-wide text-slate-400">{icon}{label}</div>
      <div className={`text-[13px] font-bold ${on ? 'text-white' : 'text-slate-400'}`} data-testid={`decision-${label.toLowerCase().replace(/\s/g, '-')}`}>{value}</div>
    </div>
  );
}

/** The controller's own cost J for each option (lower is better); the chosen one is highlighted. */
function OptionBars({ title, options, chosen, detail }: {
  title: string; options: Record<string, number>; chosen: string; detail?: Record<string, string>;
}) {
  const entries = Object.entries(options);
  if (!entries.length) return null;
  const max = Math.max(...entries.map(([, v]) => v), 1e-6);
  const best = entries.reduce((a, b) => (b[1] < a[1] ? b : a))[0];
  return (
    <div>
      <div className="text-[9.5px] uppercase tracking-wide text-slate-500 mb-1">{title}</div>
      <div className="space-y-[3px]">
        {entries.map(([k, v]) => (
          <div key={k} className="flex items-center gap-1.5 text-[10.5px]" title={detail?.[k]}>
            <span className={`w-[70px] shrink-0 text-right ${k === chosen ? 'text-white font-semibold' : 'text-slate-400'}`}>{k === 'ECO' ? 'OFF' : k === 'LOW 27' ? 'SET-BACK 27' : k.replace('NORMAL', 'ON')}</span>
            <div className="flex-1 h-[9px] bg-slate-800/60 rounded-sm overflow-hidden">
              <div className={`h-full rounded-sm ${k === chosen ? 'bg-sky-500' : 'bg-slate-600'}`} style={{ width: `${Math.max(2, (v / max) * 100)}%` }} />
            </div>
            <span className={`w-9 text-right font-mono ${k === best ? 'text-emerald-300' : 'text-slate-500'}`}>{v.toFixed(2)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

const chosenAcKey = (c: ControlDecision) => (c.hvac_action === 'NORMAL' && isNum(c.setpoint_c) ? `NORMAL ${c.setpoint_c.toFixed(0)}` : c.hvac_action === 'LOW' ? 'LOW 27' : 'ECO');

export default function DecisionCard({ control, lastEvent, hardware }: {
  control: ControlDecision | null; lastEvent: TimelineEvent | null; hardware?: boolean;
}) {
  if (!control) return <div className="text-[11px] text-slate-500">No decision (no data).</div>;
  const r: Reasoning | null | undefined = control.reasoning;
  const why = lastEvent?.why ?? [];
  const safety = control.safety_notes ?? [];
  const acDetail: Record<string, string> = {};
  if (r?.ac_options) {
    for (const [k, o] of Object.entries(r.ac_options)) {
      acDetail[k] = `energy ${o.kwh.toFixed(2)} kWh + re-cooling later ${o.recovery_kwh.toFixed(2)} kWh, discomfort ${o.discomfort_h.toFixed(2)} h, ${o.t_end.toFixed(1)} °C in 30 min`;
    }
  }
  return (
    <div className="space-y-2.5">
      <div className="grid grid-cols-3 gap-1.5">
        <State icon={<Lightbulb size={11} />} label={hardware ? 'LED' : 'Lights'} value={control.light_action} on={control.light_action !== 'OFF'} />
        <State icon={<Snowflake size={11} />} label={hardware ? 'Fan (AC)' : 'AC'} value={acLabel(control.hvac_action, control.setpoint_c)} on={control.hvac_action !== 'ECO'} />
        <State icon={<Wind size={11} />} label={hardware ? 'Damper' : 'Fresh air'} value={control.vent_boost ? 'BOOST' : 'normal'} on={!!control.vent_boost} />
      </div>

      <div className={`flex items-start gap-1.5 text-[10.5px] px-2 py-1.5 rounded border ${safety.some((n) => /^R[123]/.test(n)) ? 'border-amber-700 bg-amber-950/40 text-amber-200' : 'border-slate-700 bg-slate-800/30 text-slate-400'}`} data-testid="safety">
        {safety.length ? <ShieldAlert size={12} className="mt-0.5 shrink-0" /> : <ShieldCheck size={12} className="mt-0.5 shrink-0 text-emerald-400" />}
        <span>{safety.length ? safety.join(' · ') : 'Safety layer: proposal accepted unchanged (set-point 22–27 °C, equipment cooling, heat guard, CO₂ rule)'}</span>
      </div>

      {why.length > 0 && (
        <div>
          <div className="flex items-center gap-1 text-[9.5px] uppercase tracking-wide text-slate-500 mb-1"><Brain size={11} />Why — last change {lastEvent?.sim_time ? `at ${lastEvent.sim_time.slice(11, 16)}` : lastEvent?.real_time ? `at ${lastEvent.real_time.slice(11, 19)}` : ''}</div>
          <div className="text-[11px] text-slate-100 font-semibold mb-0.5">{lastEvent?.summary}</div>
          <ul className="text-[10.5px] text-slate-300 space-y-0.5 list-disc pl-4" data-testid="decision-why">
            {why.map((w, i) => <li key={i}>{w}</li>)}
          </ul>
          {lastEvent?.outcome && (
            <div className="mt-1 text-[10.5px] text-slate-400 border-l-2 border-emerald-700 pl-2">
              15 min later: {fx(lastEvent.outcome.temperature as number, 1, ' °C')}
              {isNum(lastEvent.expected?.t_pred as number) ? ` (predicted ${fx(lastEvent.expected!.t_pred as number, 1, ' °C')})` : ''}
              {isNum(lastEvent.outcome.power_w as number) ? ` · ${fx(lastEvent.outcome.power_w as number, 0, ' W')}` : ''}
              {isNum(lastEvent.outcome.pmv as number) ? ` · PMV ${fx(lastEvent.outcome.pmv as number, 2)}` : ''}
              {typeof lastEvent.outcome.note === 'string' ? ` · ${lastEvent.outcome.note}` : ''}
            </div>
          )}
        </div>
      )}

      {r && (
        <div className="space-y-2 pt-1 border-t border-slate-800">
          <div className="text-[10px] text-slate-400">
            Cost J = energy + 3 × P(occupied) × discomfort + 0.1 × switching (weights tuned in the thesis). Right now:
            P {fx(r.p_now, 2)} now, {fx(r.p_future, 2)} over the next 30 min
            {isNum(r.p_prior) && r.p_prior > (r.p_ac ?? 0) + 0.05 ? ` (learned routine ${r.p_prior.toFixed(2)})` : ''}; comfortable set-point for this room {fx(r.t_hold, 1, ' °C')}.
          </div>
          <OptionBars title="Air conditioning options — J over the next 30 min" options={Object.fromEntries(Object.entries(r.ac_options).map(([k, o]) => [k, o.J]))} chosen={chosenAcKey(control)} detail={acDetail} />
          <OptionBars title="Lighting options — J" options={r.J_light_options} chosen={control.light_action} />
        </div>
      )}
    </div>
  );
}
