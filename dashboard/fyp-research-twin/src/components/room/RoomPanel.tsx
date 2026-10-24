'use client';

import React, { useEffect, useRef, useState } from 'react';
import { X, Users, Thermometer, Droplets, Sun, Wind, Radio, Cpu, Zap, Scale, Sliders, History, ListChecks, Building2 } from 'lucide-react';
import { backendIsCurrent, senderLabel, useBuildingStore } from '../../store/useBuildingStore';
import { api } from '../../lib/api';
import { acLabel, fx, isNum, TYPE_LABEL } from '../../lib/format';
import type { HistoryPoint, RoomState, TimelineEvent } from '../../types/building';
import DecisionCard from './DecisionCard';
import ScenarioControls from './ScenarioControls';
import RoomHistoryChart from './RoomHistoryChart';
import HardwareRoomPanel from './HardwareRoomPanel';

function Section({ icon, title, children, right }: { icon: React.ReactNode; title: string; children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <section className="px-3 py-2.5 border-b border-slate-800">
      <div className="flex items-center justify-between mb-2">
        <h3 className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-slate-400">{icon}{title}</h3>
        {right}
      </div>
      {children}
    </section>
  );
}

function Reading({ icon, label, value, sub, testId }: { icon: React.ReactNode; label: string; value: string; sub?: string; testId?: string }) {
  return (
    <div className="bg-slate-800/50 rounded-lg px-2 py-1.5 min-w-0">
      <div className="flex items-center gap-1 text-[9.5px] uppercase text-slate-500">{icon}{label}</div>
      <div className="text-[14px] font-bold text-cyan-200 leading-tight" data-testid={testId}>{value}</div>
      {sub && <div className="text-[9.5px] text-slate-500 truncate">{sub}</div>}
    </div>
  );
}

function CompareRow({ label, ai, base, better }: { label: string; ai: string; base: string; better: boolean | null }) {
  return (
    <div className="grid grid-cols-[1fr_76px_76px] items-center text-[11px] py-0.5">
      <span className="text-slate-400">{label}</span>
      <span className={`text-right font-mono font-semibold ${better === null ? 'text-white' : better ? 'text-emerald-300' : 'text-orange-300'}`}>{ai}</span>
      <span className="text-right font-mono text-slate-400">{base}</span>
    </div>
  );
}

/** Fetch the selected room's recent decisions and history from the edge brain (throttled). */
function useRoomDetails(roomId: string | null, seq: number | undefined) {
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [history, setHistory] = useState<HistoryPoint[]>([]);
  const last = useRef(0);
  const lastRoom = useRef<string | null>(null);
  useEffect(() => {
    if (!roomId) return;
    const changed = lastRoom.current !== roomId;
    if (changed) {
      lastRoom.current = roomId;
      setEvents([]);
      setHistory([]);
      api.control('watch', { room_id: roomId }).catch(() => {});
    }
    const now = Date.now();
    if (!changed && now - last.current < 1500) return;
    last.current = now;
    let alive = true;
    Promise.all([api.timeline({ room_id: roomId, limit: 25 }), api.history(roomId)])
      .then(([ev, h]) => { if (alive) { setEvents(ev); setHistory(h[roomId] ?? []); } })
      .catch(() => {});
    return () => { alive = false; };
  }, [roomId, seq]);
  return { events, history };
}

function EventList({ events }: { events: TimelineEvent[] }) {
  const rows = [...events].reverse().filter((e) => e.kind !== 'system').slice(0, 12);
  if (!rows.length) return <div className="text-[11px] text-slate-500">No decisions for this room yet.</div>;
  return (
    <ul className="space-y-1">
      {rows.map((e) => (
        <li key={e.seq} className="text-[10.5px] leading-snug">
          <span className="font-mono text-slate-500 mr-1.5">{e.sim_time ? e.sim_time.slice(11, 16) : e.real_time?.slice(11, 19)}</span>
          <span className={e.kind === 'decision' ? 'text-sky-200' : e.kind === 'scenario' ? 'text-amber-200' : 'text-slate-300'}>{e.summary}</span>
        </li>
      ))}
    </ul>
  );
}

function SimulatedRoom({ r, events, history, disabled }: { r: RoomState; events: TimelineEvent[]; history: HistoryPoint[]; disabled: boolean }) {
  const p = r.ai?.occupancy_probability;
  const truth = r.ground_truth?.true_occupancy ?? null;
  const lastDecision = [...events].reverse().find((e) => e.kind === 'decision' || e.kind === 'assessment') ?? null;
  const e = r.energy;
  const daylight = r.comfort?.daylight_lux;
  const pir = r.sensors.PIR_seconds_since_motion;
  const pmvBetter = (x: number | null | undefined, y: number | null | undefined) =>
    isNum(x) && isNum(y) && Math.abs(Math.abs(x) - Math.abs(y)) > 0.05 ? Math.abs(x) < Math.abs(y) : null;
  return (
    <>
      <Section icon={<Users size={12} />} title="Right now" right={<span className="text-[10px] text-slate-500 font-mono">{r.timestamp?.slice(11, 16)}</span>}>
        <div className="flex items-center gap-3 mb-2">
          <div className="text-center">
            <div className="text-[22px] font-bold text-white leading-none" data-testid="room-truth">{truth ?? '—'}</div>
            <div className="text-[9.5px] text-slate-500">people (truth)</div>
          </div>
          <div className="flex-1">
            <div className="flex justify-between text-[10.5px]">
              <span className="text-slate-400">AI estimate P(occupied)</span>
              <span className="font-bold text-white" data-testid="room-prob">{fx(p, 2)}</span>
            </div>
            <div className="h-2 bg-slate-800 rounded-full overflow-hidden mt-0.5">
              <div className="h-full bg-sky-500 transition-all duration-500" style={{ width: `${isNum(p) ? p * 100 : 0}%` }} />
            </div>
            <div className="text-[9.5px] text-slate-500 mt-0.5">
              PIR + CO₂ fusion · Random Forest says {fx(r.ai?.random_forest_probability, 2)}
              {isNum(truth) && isNum(p) && ((truth > 0) !== (p >= 0.5)) ? <span className="text-orange-300"> · disagrees with truth</span> : null}
            </div>
          </div>
        </div>
        <div className="grid grid-cols-3 gap-1.5">
          <Reading icon={<Thermometer size={10} />} label="Air" value={fx(r.sensors.Temperature, 1, ' °C')} sub={`operative ${fx(r.comfort?.operative_c, 1, ' °C')}`} testId="room-temp" />
          <Reading icon={<Droplets size={10} />} label="Humidity" value={fx(r.sensors.Humidity, 0, ' %')} />
          <Reading icon={<Sun size={10} />} label="Light" value={fx(r.sensors.Light, 0, ' lux')} sub={`daylight ${fx(daylight, 0)}`} />
          <Reading icon={<Wind size={10} />} label="CO₂" value={fx(r.sensors.CO2, 0, ' ppm')} />
          <Reading icon={<Radio size={10} />} label="PIR" value={pir == null ? 'none' : pir < 90 ? 'motion' : `${Math.round(pir / 60)} min`} sub="since last motion" />
          <Reading icon={<Scale size={10} />} label="Comfort" value={`PMV ${fx(r.comfort?.pmv, 2)}`} sub={isNum(r.comfort?.pmv) ? (Math.abs(r.comfort!.pmv!) <= 0.5 ? 'comfortable' : r.comfort!.pmv! > 0 ? 'too warm' : 'too cool') : ''} />
        </div>
        <div className="mt-1.5 flex flex-wrap gap-1 text-[9.5px]" data-testid="room-provenance">
          <span className="px-1.5 py-0.5 rounded border border-slate-600 text-slate-300" title="Values computed by the simulator (5R1C physics, synthetic climate)">readings: simulated</span>
          <span className="px-1.5 py-0.5 rounded border border-sky-700 text-sky-300" title="Occupancy probability is a model estimate">P(occupied): estimate</span>
          {r.prediction?.temperature_30min && (
            <span className="px-1.5 py-0.5 rounded border border-violet-700 text-violet-300" data-testid="room-forecast"
              title={`${r.prediction.temperature_30min.model}, made ${r.prediction.temperature_30min.made_at}`}>
              forecast {fx(r.prediction.temperature_30min.predicted_c, 1, ' °C')} at {r.prediction.temperature_30min.for_time.slice(11, 16)} (prediction)
            </span>
          )}
        </div>
      </Section>

      <Section icon={<Zap size={12} />} title={r.control?.mode === 'conventional' ? 'Control now: conventional (AI off)' : 'AI decision'}>
        {r.control?.mode === 'conventional' && (
          <div className="mb-2 text-[10.5px] px-2 py-1.5 rounded border border-orange-800/70 bg-orange-950/30 text-orange-200">
            AI control is OFF: this room follows its time schedule ({r.control.reason}).
          </div>
        )}
        <DecisionCard control={r.control} lastEvent={lastDecision} />
        {r.control?.ai_would && (
          <div className="mt-2 rounded-lg border border-sky-800/70 bg-sky-950/30 p-2" data-testid="ai-would">
            <div className="text-[9.5px] uppercase tracking-wide text-sky-300 mb-0.5">What the AI would do now</div>
            <div className="text-[12px] text-white font-semibold">lights {r.control.ai_would.light_action} · AC {acLabel(r.control.ai_would.hvac_action, r.control.ai_would.setpoint_c)}</div>
            <div className="text-[10px] text-slate-400">{r.control.ai_would.reason}</div>
            <div className="text-[9.5px] text-slate-500">({r.control.ai_would.basis})</div>
          </div>
        )}
      </Section>

      <Section icon={<Scale size={12} />} title="AI on vs AI off" right={<span className="text-[9.5px] text-slate-500">this room, same minutes &amp; people</span>}>
        {r.modes ? (
          <>
            <div className="grid grid-cols-[1fr_76px_76px] text-[9.5px] uppercase text-slate-500 pb-0.5">
              <span /><span className="text-right">AI on{r.modes.ai.copy === 'building' ? ' ●' : ''}</span><span className="text-right">AI off{r.modes.conventional.copy === 'building' ? ' ●' : ''}</span>
            </div>
            <CompareRow label="Lights / AC now" ai={`${r.modes.ai.light_action} · ${acLabel(r.modes.ai.hvac_action, r.modes.ai.setpoint_c).replace('SET-BACK 27°C', '27°C')}`} base={`${r.modes.conventional.light_action} · ${acLabel(r.modes.conventional.hvac_action, r.modes.conventional.setpoint_c).replace('SET-BACK 27°C', '27°C')}`} better={null} />
            <CompareRow label="Power now" ai={fx(r.modes.ai.power_w, 0, ' W')} base={fx(r.modes.conventional.power_w, 0, ' W')} better={Math.abs(r.modes.ai.power_w - r.modes.conventional.power_w) > 20 ? r.modes.ai.power_w < r.modes.conventional.power_w : null} />
            <CompareRow label="Energy so far" ai={fx(r.modes.ai.energy_wh / 1000, 2, ' kWh')} base={fx(r.modes.conventional.energy_wh / 1000, 2, ' kWh')} better={Math.abs(r.modes.ai.energy_wh - r.modes.conventional.energy_wh) > 10 ? r.modes.ai.energy_wh < r.modes.conventional.energy_wh : null} />
            <CompareRow label="Temperature" ai={fx(r.modes.ai.temperature, 1, ' °C')} base={fx(r.modes.conventional.temperature, 1, ' °C')} better={null} />
            <CompareRow label="Comfort (PMV)" ai={fx(r.modes.ai.pmv, 2)} base={fx(r.modes.conventional.pmv, 2)} better={pmvBetter(r.modes.ai.pmv, r.modes.conventional.pmv)} />
            <div className="text-[9.5px] text-slate-500 mt-1">● = the building (follows the AI switch); the other column is its digital twin running the other mode with the same weather, people and sensor noise.
              {e ? ` Now: AC + fans ${fx(e.hvac_w, 0, ' W')}, lighting ${fx(e.lighting_w, 0, ' W')}, plug ${fx(e.plug_w, 0, ' W')}.` : ''}</div>
          </>
        ) : <div className="text-[11px] text-slate-500">—</div>}
      </Section>

      <Section icon={<Sliders size={12} />} title="Change conditions">
        <ScenarioControls room={r} disabled={disabled} />
      </Section>

      <Section icon={<History size={12} />} title="Last 24 h">
        <RoomHistoryChart data={history} />
      </Section>

      <Section icon={<ListChecks size={12} />} title="Decisions in this room">
        <EventList events={events} />
      </Section>
    </>
  );
}

export default function RoomPanel() {
  const raw = useBuildingStore((s) => s.raw);
  const link = useBuildingStore((s) => s.link);
  const rooms = useBuildingStore((s) => s.rooms);
  const selected = useBuildingStore((s) => s.selectedRoom);
  const selectRoom = useBuildingStore((s) => s.selectRoom);
  const live = link.connected && backendIsCurrent(raw);
  const r = selected ? rooms[selected] : undefined;
  const { events, history } = useRoomDetails(live && r ? r.room_id : null, raw?.seq);
  const learning = raw?.clock?.phase === 'learning';

  return (
    <aside className="w-[392px] shrink-0 border-l border-slate-800 bg-slate-900/50 flex flex-col min-h-0" data-testid="room-panel">
      {!r ? (
        <div className="p-4 text-[12px] text-slate-400 space-y-3">
          <div className="flex items-center gap-2 text-slate-200 font-semibold"><Building2 size={15} />Select a room</div>
          <p>Click a room in the 3D building or in the list on the left to see its live readings, the AI&apos;s decision and why it
            made it, and how it compares with the conventional schedule.</p>
          <p>Then change its conditions — add people, empty it, add heat, a CO₂ source or open a window — and watch the AI respond
            in the simulation.</p>
          <p className="text-slate-500">Office A is the real room: its values come from the ESP32 board.</p>
        </div>
      ) : (
        <>
          <div className="px-3 py-2.5 border-b border-slate-800 flex items-start gap-2">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1.5">
                {r.room_number != null && <span className="text-[11px] font-mono px-1 rounded bg-slate-800 text-slate-300" data-testid="room-number">Room {r.room_number}</span>}
                <h2 className="text-[15px] font-bold text-white truncate" data-testid="room-name">{r.display_name}</h2>
                {r.source === 'hardware'
                  ? <span className={`text-[9.5px] px-1.5 py-0.5 rounded border ${r.hardware?.connected ? (r.hardware.real_board ? 'border-emerald-600 text-emerald-300' : 'border-amber-600 text-amber-300') : 'border-red-700 text-red-300'}`}><Cpu size={10} className="inline mr-0.5" />{r.hardware?.connected ? (r.hardware.real_board ? 'LIVE ESP32' : senderLabel(r.hardware)) : 'BOARD NOT CONNECTED'}</span>
                  : <span className="text-[9.5px] px-1.5 py-0.5 rounded border border-slate-600 text-slate-300">SIMULATED</span>}
              </div>
              <div className="text-[10.5px] text-slate-500">
                {TYPE_LABEL[r.room_type] ?? r.room_type} · floor {r.floor_id} · {fx(r.area_m2, 0, ' m²')} · up to {r.ground_truth?.max_occupancy ?? '—'} people
              </div>
            </div>
            <button onClick={() => selectRoom(null)} className="p-1 rounded hover:bg-slate-800 text-slate-400" title="Close"><X size={15} /></button>
          </div>
          <div className="flex-1 overflow-y-auto min-h-0">
            {r.source === 'hardware'
              ? <HardwareRoomPanel room={r} events={events} history={history} />
              : <SimulatedRoom r={r} events={events} history={history} disabled={!live || learning} />}
          </div>
        </>
      )}
    </aside>
  );
}
