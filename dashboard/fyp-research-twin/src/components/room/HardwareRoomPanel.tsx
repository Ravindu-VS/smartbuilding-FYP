'use client';

import React, { useState } from 'react';
import { Cpu, Zap, History, ListChecks, Gauge, Loader2 } from 'lucide-react';
import { senderLabel, useBuildingStore } from '../../store/useBuildingStore';
import { EDGE_URL, useNow } from '../../hooks/useSSE';
import { api } from '../../lib/api';
import { acLabel, fx, isNum } from '../../lib/format';
import type { HistoryPoint, RoomState, TimelineEvent } from '../../types/building';
import DecisionCard from './DecisionCard';
import RoomHistoryChart from './RoomHistoryChart';

/**
 * Office A, the real room. Values are shown only while the edge brain reports the
 * ESP32 as connected; otherwise NOT CONNECTED and no values. The decision shown is the
 * one returned to the board with its last reading (same AI as the simulated rooms).
 */

function ago(seconds: number | null) {
  if (!isNum(seconds)) return '—';
  if (seconds < 60) return `${seconds.toFixed(1)} s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  return `${(seconds / 3600).toFixed(1)} h ago`;
}

function Card({ label, value, unit, testId }: { label: string; value: string; unit: string; testId: string }) {
  return (
    <div className="bg-slate-800/50 rounded-lg px-2 py-1.5">
      <div className="text-[13px] font-bold text-cyan-200" data-testid={testId}>
        {value} {value !== '—' && unit && <span className="text-[10px] text-slate-400">{unit}</span>}
      </div>
      <div className="text-[9px] text-slate-500 uppercase leading-tight">{label}</div>
    </div>
  );
}

function Section({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <section className="px-3 py-2.5 border-b border-slate-800">
      <h3 className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-2">{icon}{title}</h3>
      {children}
    </section>
  );
}

export default function HardwareRoomPanel({ room, events, history }: { room: RoomState; events: TimelineEvent[]; history: HistoryPoint[] }) {
  const link = useBuildingStore((s) => s.link);
  const hw = room.hardware ?? null;
  const now = useNow(500);
  const [cal, setCal] = useState<string | null>(null);
  const ageNow = hw && isNum(hw.age_s) && link.lastMessageAt !== null ? hw.age_s + Math.max(0, now - link.lastMessageAt) / 1000 : null;
  const status: 'never' | 'lost' | 'test' | 'live' = !hw || hw.state === 'never_connected' ? 'never' : !hw.connected ? 'lost' : hw.real_board ? 'live' : 'test';
  const live = status === 'live' || status === 'test';
  const s = live ? room.sensors : null;
  const presence = live ? room.presence ?? null : null;
  const applied = live ? room.device_state ?? null : null;
  const control = live ? room.control : null;
  const power = live ? room.energy?.measured_power_watts ?? null : null;
  const lastDecision = [...events].reverse().find((e) => e.kind === 'decision') ?? null;
  const pill = { never: 'NOT CONNECTED', lost: 'NOT CONNECTED', test: senderLabel(hw), live: 'CONNECTED' }[status];

  return (
    <div>
      <div className="px-3 py-2 border-b border-slate-800 flex items-center justify-between">
        <span className="text-[10.5px] text-slate-400 flex items-center gap-1"><Cpu size={12} />ESP32-S3 sensor node</span>
        <span className={`text-[10px] font-mono px-2 py-0.5 rounded-full border ${status === 'live' ? 'border-emerald-600 text-emerald-300 bg-emerald-950/40' : status === 'test' ? 'border-amber-600 text-amber-300 bg-amber-950/40' : 'border-red-700 text-red-300 bg-red-950/40'}`} data-testid="board-status">{pill}</span>
      </div>

      {!live && (
        <div className="px-3 py-3 text-[11px] text-slate-300 space-y-1.5 border-b border-slate-800" data-testid="board-offline">
          {status === 'never' ? <p>No reading has arrived from the ESP32 since the edge brain started.</p>
            : <p>The ESP32 stopped sending. Last reading {ago(ageNow)}{hw?.last_seen ? ` (${new Date(hw.last_seen).toLocaleTimeString()})` : ''}.</p>}
          <p className="text-slate-500">Check the board is powered, on the same Wi-Fi, and posting to <code className="text-cyan-300">{EDGE_URL.replace('127.0.0.1', '<this PC IP>')}/api/hardware/sensor-data</code>. Shown as not connected after {hw?.timeout_s ?? 10} s without a reading. The 25 simulated rooms keep running.</p>
        </div>
      )}
      {status === 'test' && (
        <div className="mx-3 mt-2 px-2 py-1.5 rounded bg-amber-950/40 border border-amber-800/60 text-[10.5px] text-amber-300" data-testid="test-sender-warning">
          {hw?.sender === 'virtual_board'
            ? <>Readings come from the virtual board ({hw?.sender_detail === 'uci_replay' ? 'replay of the public UCI office dataset, with modelled PIR, mmWave, MQ-2 and INA226' : hw?.sender_detail === 'room_model' ? 'Office A simulated by the digital twin, driven by these decisions' : hw?.sender_detail ?? 'emulated'}), not from the real board. Stored as synthetic.</>
            : <>Readings come from a test sender ({hw?.sender}), not from the real board.</>}
        </div>
      )}

      <Section icon={<Gauge size={12} />} title="Sensor readings">
        <div className="grid grid-cols-3 gap-1.5">
          <Card label="Temperature" value={fx(s?.Temperature, 1)} unit="°C" testId="hw-temp" />
          <Card label="Humidity" value={fx(s?.Humidity, 0)} unit="%" testId="hw-hum" />
          <Card label="Light" value={fx(s?.Light, 0)} unit="lux" testId="hw-lux" />
          <Card label="CO₂ (SCD41)" value={fx(s?.CO2, 0)} unit="ppm" testId="hw-co2" />
          <Card label={`Presence${presence?.source ? ` (${presence.source})` : ''}`} value={presence?.fused_presence == null ? '—' : presence.fused_presence ? 'Yes' : 'No'} unit="" testId="hw-presence" />
          <Card label="Pressure" value={fx(s?.Pressure_hPa ?? null, 0)} unit="hPa" testId="hw-pressure" />
        </div>
        {s?.CO2_rejected && <div className="text-[10px] text-amber-300 mt-1">CO₂ value not used: {s.CO2_rejected}</div>}
        {live && room.ai && (
          <div className="mt-2">
            <div className="flex justify-between text-[10.5px]"><span className="text-slate-400">AI estimate P(occupied) — PIR{presence?.source?.includes('mmwave') ? '/mmWave' : ''} + CO₂</span><span className="font-bold text-white" data-testid="hw-prob">{fx(room.ai.occupancy_probability, 2)}</span></div>
            <div className="h-2 bg-slate-800 rounded-full overflow-hidden mt-0.5"><div className="h-full bg-sky-500 transition-all" style={{ width: `${room.ai.occupancy_probability * 100}%` }} /></div>
            <div className="text-[9.5px] text-slate-500 mt-0.5">Random Forest (original model) says {fx(room.ai.random_forest_probability, 2)} · {room.ai.co2_used ? 'CO₂ used' : 'no CO₂ evidence'}</div>
          </div>
        )}
      </Section>

      <Section icon={<Zap size={12} />} title={control?.mode === 'manual' ? 'Manual override sent to the board' : control?.mode === 'conventional' ? 'Decision sent to the board (AI off)' : 'AI decision sent to the board'}>
        {control?.mode === 'manual' && control.manual_override && (
          <div className="mb-2 text-[10.5px] px-2 py-1.5 rounded border border-amber-700 bg-amber-950/30 text-amber-200" data-testid="manual-override">
            Manual override until {control.manual_override.until.slice(11, 16)} ({control.manual_override.reason}); the AI is bypassed.
          </div>
        )}
        {control && control.previous_command_verified === false && (
          <div className="mb-2 text-[10.5px] text-orange-300" data-testid="verify-mismatch">The board reported different fan/LED levels than the last command.</div>
        )}
        {control ? (
          <>
            {control.mode === 'conventional' && (
              <div className="mb-2 text-[10.5px] px-2 py-1.5 rounded border border-orange-800/70 bg-orange-950/30 text-orange-200">
                AI control is OFF: the board follows the conventional schedule ({control.reason}).
              </div>
            )}
            <DecisionCard control={control} lastEvent={lastDecision} hardware />
            {control.ai_would && (
              <div className="mt-2 rounded-lg border border-sky-800/70 bg-sky-950/30 p-2">
                <div className="text-[9.5px] uppercase tracking-wide text-sky-300 mb-0.5">What the AI would do now</div>
                <div className="text-[12px] text-white font-semibold">LED {control.ai_would.light_action} · fan {acLabel(control.ai_would.hvac_action, control.ai_would.setpoint_c)}</div>
                <div className="text-[10px] text-slate-400">{control.ai_would.reason}</div>
              </div>
            )}
            <div className="grid grid-cols-3 gap-1.5 mt-2 text-center text-[10.5px]">
              <div className="rounded border border-slate-700 py-1"><div className="text-slate-500 text-[9px] uppercase">Fan PWM</div><div className="font-mono text-white" data-testid="hw-hvac-action">{control.fan_speed}/255</div></div>
              <div className="rounded border border-slate-700 py-1"><div className="text-slate-500 text-[9px] uppercase">LED PWM</div><div className="font-mono text-white" data-testid="hw-light-action">{control.light_level}/255</div></div>
              <div className="rounded border border-slate-700 py-1"><div className="text-slate-500 text-[9px] uppercase">Servo</div><div className="font-mono text-white">{control.servo_angle}°</div></div>
            </div>
            <div className="text-[10px] text-slate-500 mt-1.5" data-testid="hw-applied">
              {applied ? `Board reports applied: fan ${applied.hvac_speed ?? '—'}/255, LED ${applied.light_level ?? '—'}/255, servo ${applied.servo_angle ?? '—'}° (reported with its next reading)` : 'Board actuator state: —'}
            </div>
          </>
        ) : <div className="text-[11px] text-slate-500">No decision without board data.</div>}
      </Section>

      <Section icon={<Zap size={12} />} title="Board energy meter and calibration">
        <div className="text-[12px] font-bold text-white" data-testid="hw-power">
          {isNum(power) ? `${power.toFixed(2)} W measured (INA226)` : live ? 'not measured (no INA226 reading)' : '—'}
        </div>
        {room.meter && (
          <div className="mt-1.5">
            <div className="grid grid-cols-3 gap-1 text-[10px]">
              <div className="bg-slate-800/50 rounded px-1.5 py-1"><div className="text-slate-500">total</div><div className="text-white font-mono">{fx(room.meter.total_wh, 3, ' Wh')}</div></div>
              <div className="bg-slate-800/50 rounded px-1.5 py-1"><div className="text-slate-500">avg, AI on</div><div className="text-sky-300 font-mono">{fx(room.meter.by_mode.ai.avg_w, 2, ' W')}</div></div>
              <div className="bg-slate-800/50 rounded px-1.5 py-1"><div className="text-slate-500">avg, AI off</div><div className="text-orange-300 font-mono">{fx(room.meter.by_mode.conventional.avg_w, 2, ' W')}</div></div>
            </div>
            <ul className="mt-1 space-y-0.5">
              {[...room.meter.segments].reverse().slice(0, 4).map((sg, i) => (
                <li key={`${sg.start}-${i}`} className="text-[10px] font-mono text-slate-400">
                  <span className={sg.mode === 'ai' ? 'text-sky-300' : 'text-orange-300'}>AI {sg.mode === 'ai' ? 'ON ' : 'OFF'}</span> {sg.start.slice(11, 19)}–{sg.end ? sg.end.slice(11, 19) : 'now'} · {fx(sg.wh, 4, ' Wh')} · {sg.avg_w !== null ? `${sg.avg_w.toFixed(2)} W avg` : 'no INA226 data'}
                </li>
              ))}
            </ul>
          </div>
        )}
        <div className="flex items-center justify-between mt-2">
          <div className="text-[10.5px] text-slate-400">
            LED at the light sensor: {hw?.led_calibration_lux ? <span className="text-white font-semibold">{hw.led_calibration_lux.toFixed(0)} lux at full</span> : <span className="text-amber-300">not calibrated (design 400 lux assumed)</span>}
            {hw?.led_calibration && !['none', 'done'].includes(hw.led_calibration) && <span className="text-sky-300"> · measuring…</span>}
          </div>
          <button
            className="px-2 py-1 rounded-md text-[11px] font-semibold bg-sky-700 hover:bg-sky-600 text-white disabled:opacity-40 flex items-center gap-1"
            disabled={!live || !!cal}
            title="Turns the LED off for one reading and fully on for the next, and stores the difference (keep the room light steady)"
            onClick={async () => { setCal('…'); try { await api.calibrateLed(room.room_id); } catch (e) { alert(e instanceof Error ? e.message : String(e)); } finally { setCal(null); } }}
          >
            {cal ? <Loader2 size={12} className="animate-spin" /> : null}Calibrate LED
          </button>
        </div>
        {room.sensor_health && Object.keys(room.sensor_health).length > 0 && live && (
          <div className="flex flex-wrap gap-1 mt-2">
            {Object.entries(room.sensor_health).map(([name, ok]) => (
              <span key={name} className={`text-[9px] font-mono px-1.5 py-0.5 rounded border ${ok ? 'border-emerald-700 text-emerald-300' : 'border-slate-700 text-slate-500 line-through'}`}>{name}</span>
            ))}
          </div>
        )}
        <div className="mt-2 text-[10px] text-slate-500 font-mono flex justify-between">
          <span data-testid="hw-age">Last reading: {link.connected ? ago(ageNow) : '—'}</span>
          <span>{hw && link.connected ? `${hw.readings_received} readings${isNum(hw.mean_interval_s) ? ` · every ${hw.mean_interval_s.toFixed(1)} s` : ''}` : ''}</span>
        </div>
      </Section>

      <Section icon={<History size={12} />} title="Recent readings">
        <RoomHistoryChart data={history} hardware />
      </Section>
      <Section icon={<ListChecks size={12} />} title="Decisions in this room">
        {events.length === 0 ? <div className="text-[11px] text-slate-500">No decisions yet.</div> : (
          <ul className="space-y-1">
            {[...events].reverse().slice(0, 12).map((e) => (
              <li key={e.seq} className="text-[10.5px]"><span className="font-mono text-slate-500 mr-1.5">{e.real_time?.slice(11, 19) ?? e.sim_time?.slice(11, 16)}</span><span className="text-sky-200">{e.summary}</span></li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}
