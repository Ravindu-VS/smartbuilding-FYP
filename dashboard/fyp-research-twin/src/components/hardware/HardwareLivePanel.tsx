'use client';

import React from 'react';
import { hardwareRoom, useBuildingStore } from '../../store/useBuildingStore';
import { EDGE_URL, useNow } from '../../hooks/useSSE';

/**
 * Office A (the hardware room). Shows the ESP32's readings only while the edge
 * brain reports the board as connected; otherwise it says NOT CONNECTED and shows
 * no values. The decision shown is the one the edge brain sent back to the board.
 */

const fmt = (v: number | null | undefined, digits: number) =>
  v === null || v === undefined || Number.isNaN(v) ? '—' : v.toFixed(digits);

function ago(seconds: number | null) {
  if (seconds === null) return '—';
  if (seconds < 60) return `${seconds.toFixed(1)} s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  return `${(seconds / 3600).toFixed(1)} h ago`;
}

export default function HardwareLivePanel() {
  const room = useBuildingStore((s) => hardwareRoom(s));
  const hw = useBuildingStore((s) => s.hardware);
  const link = useBuildingStore((s) => s.link);
  const now = useNow(500);

  // Age of the board's last reading now = age when the server sent it + time since we received it
  const ageNow = hw && hw.age_s !== null && link.lastMessageAt !== null
    ? hw.age_s + Math.max(0, now - link.lastMessageAt) / 1000
    : null;

  const status: 'no-link' | 'never' | 'lost' | 'test' | 'live' =
    !link.connected ? 'no-link'
      : !hw || hw.state === 'never_connected' ? 'never'
      : !hw.connected ? 'lost'
      : hw.real_board ? 'live' : 'test';

  const pill = {
    'no-link': ['EDGE BRAIN OFFLINE', 'bg-red-500/20 text-red-300 border-red-500/40'],
    never: ['NOT CONNECTED', 'bg-red-500/20 text-red-300 border-red-500/40'],
    lost: ['NOT CONNECTED', 'bg-red-500/20 text-red-300 border-red-500/40'],
    test: ['TEST SENDER', 'bg-amber-500/20 text-amber-300 border-amber-500/40'],
    live: ['CONNECTED', 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'],
  }[status];

  const live = status === 'live' || status === 'test';
  const s = live && room ? room.sensors : null;
  const ai = live ? room?.ai ?? null : null;
  const control = live ? room?.control ?? null : null;
  const applied = live ? room?.device_state ?? null : null;
  const presence = live ? room?.presence ?? null : null;
  const power = live ? room?.energy?.measured_power_watts ?? null : null;
  const health = live ? room?.sensor_health ?? null : null;
  const co2Label = s?.CO2_source === 'mq2_estimate' ? 'CO₂ est. (MQ-2, uncalibrated)'
    : s?.CO2_source === 'scd41_ndir' ? 'CO₂ (SCD41)' : 'CO₂';

  return (
    <div className={`rounded-xl border m-3 ${live ? (status === 'live' ? 'border-emerald-500/50' : 'border-amber-500/50') : 'border-red-500/40'} bg-slate-900/90`}>
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700/50">
        <div className="flex items-center gap-2">
          <div className={`w-2.5 h-2.5 rounded-full ${status === 'live' ? 'bg-emerald-400 animate-pulse' : status === 'test' ? 'bg-amber-400' : 'bg-red-500'}`} />
          <div>
            <div className="text-white font-bold text-sm tracking-wide">{room?.display_name ?? 'Office A'} — hardware room</div>
            <div className="text-[10px] text-slate-500 font-mono">{room?.room_id ?? 'f2_office_a'} · ESP32-S3</div>
          </div>
        </div>
        <span className={`text-[10px] font-mono px-2 py-0.5 rounded-full border ${pill[1]}`} data-testid="board-status">{pill[0]}</span>
      </div>

      {!live && (
        <div className="px-4 py-3 text-xs text-slate-300 space-y-1.5" data-testid="board-offline">
          {status === 'no-link' ? (
            <p>No data from the edge brain ({link.error ?? 'not connected'}). Start it with <code className="text-cyan-300">python raspberry_pi\edge_brain.py</code>.</p>
          ) : status === 'never' ? (
            <p>No reading has arrived from the ESP32 since the edge brain started.</p>
          ) : (
            <p>The ESP32 stopped sending. Last reading {ago(ageNow)}{hw?.last_seen ? ` (${new Date(hw.last_seen).toLocaleTimeString()})` : ''}.</p>
          )}
          {status !== 'no-link' && (
            <p className="text-slate-500">Check the board is powered, on the same Wi-Fi, and posting to <code className="text-cyan-300">{EDGE_URL.replace('127.0.0.1', '<this PC IP>')}/api/hardware/sensor-data</code>. Shown as not connected after {hw?.timeout_s ?? 10} s without a reading.</p>
          )}
        </div>
      )}

      {status === 'test' && (
        <div className="mx-4 mt-3 px-3 py-2 rounded bg-amber-950/40 border border-amber-800/60 text-[11px] text-amber-300" data-testid="test-sender-warning">
          Readings come from a test sender ({hw?.sender}), not from the real board.
        </div>
      )}

      <div className="px-4 py-3">
        <div className="text-[10px] uppercase text-slate-500 font-bold mb-2 tracking-widest">Sensor readings</div>
        <div className="grid grid-cols-2 gap-2">
          <SensorCard label="Temperature" value={fmt(s?.Temperature, 1)} unit="°C" testId="hw-temp" />
          <SensorCard label="Humidity" value={fmt(s?.Humidity, 0)} unit="%" testId="hw-hum" />
          <SensorCard label="Light" value={fmt(s?.Light, 0)} unit="lux" testId="hw-lux" />
          <SensorCard label={co2Label} value={fmt(s?.CO2, 0)} unit="ppm" testId="hw-co2" />
          <SensorCard label={`Presence${presence?.source ? ` (${presence.source})` : ''}`}
            value={presence?.fused_presence === null || presence?.fused_presence === undefined ? '—' : presence.fused_presence ? 'Yes' : 'No'}
            unit="" testId="hw-presence" />
          <SensorCard label="Pressure" value={fmt(s?.Pressure_hPa ?? null, 0)} unit="hPa" testId="hw-pressure" />
        </div>
      </div>

      <div className="px-4 py-3 border-t border-slate-700/30">
        <div className="text-[10px] uppercase text-slate-500 font-bold mb-2 tracking-widest">Edge AI (Random Forest)</div>
        <div className="flex justify-between text-[11px] mb-1">
          <span className="text-slate-400">Occupancy probability</span>
          <span className="font-bold text-white" data-testid="hw-prob">{ai ? `${(ai.occupancy_probability * 100).toFixed(1)}%` : '—'}</span>
        </div>
        <div className="h-2 bg-slate-800 rounded-full overflow-hidden">
          <div className="h-full rounded-full bg-indigo-500 transition-all duration-500" style={{ width: `${ai ? Math.min(100, ai.occupancy_probability * 100) : 0}%` }} />
        </div>
        <div className="text-[10px] text-slate-500 mt-1">{ai ? `Predicted: ${ai.predicted_occupancy ? 'occupied' : 'empty'}${ai.method !== 'random_forest' ? ` (${ai.method})` : ''}` : 'No prediction without board data'}</div>
      </div>

      <div className="px-4 py-3 border-t border-slate-700/30">
        <div className="text-[10px] uppercase text-slate-500 font-bold mb-2 tracking-widest">Decision sent to the board</div>
        <div className="grid grid-cols-3 gap-2 text-center">
          <Badge label="Mode" value={control?.control_mode} testId="hw-mode" />
          <Badge label={`Light${control ? ` (${control.light_level}/255)` : ''}`} value={control?.light_action} testId="hw-light-action" />
          <Badge label={`Fan${control ? ` (${control.fan_speed}/255)` : ''}`} value={control?.hvac_action} testId="hw-hvac-action" />
        </div>
        <div className="text-[10px] text-slate-500 mt-2" data-testid="hw-applied">
          {applied
            ? `Board reports applied: fan ${applied.hvac_speed ?? '—'}/255, light ${applied.light_level ?? '—'}/255, servo ${applied.servo_angle ?? '—'}° (sent with its next reading)`
            : 'Board actuator state: —'}
        </div>
      </div>

      <div className="px-4 py-3 border-t border-slate-700/30 flex items-center justify-between">
        <div>
          <div className="text-[10px] uppercase text-slate-500 font-bold tracking-widest">Board power</div>
          <div className="text-sm font-bold text-white" data-testid="hw-power">
            {power !== null ? `${power.toFixed(2)} W measured (INA226)` : live ? 'not measured (no INA226 reading)' : '—'}
          </div>
        </div>
      </div>

      {health && Object.keys(health).length > 0 && (
        <div className="px-4 pb-3 flex flex-wrap gap-1">
          {Object.entries(health).map(([name, ok]) => (
            <span key={name} className={`text-[9px] font-mono px-1.5 py-0.5 rounded border ${ok ? 'border-emerald-700 text-emerald-300' : 'border-slate-700 text-slate-500 line-through'}`}>{name}</span>
          ))}
        </div>
      )}

      <div className="px-4 py-2 bg-slate-950/50 rounded-b-xl flex items-center justify-between text-[10px] text-slate-500 font-mono">
        <span data-testid="hw-age">Last reading: {link.connected ? ago(ageNow) : '—'}</span>
        <span>{hw && link.connected ? `${hw.readings_received} readings${hw.mean_interval_s ? ` · every ${hw.mean_interval_s.toFixed(1)} s` : ''}` : ''}</span>
      </div>
    </div>
  );
}

function SensorCard({ label, value, unit, testId }: { label: string; value: string; unit: string; testId: string }) {
  return (
    <div className="bg-slate-800/50 rounded-lg px-2.5 py-2">
      <div className="text-sm font-bold text-cyan-300" data-testid={testId}>
        {value} {value !== '—' && unit && <span className="text-[10px] text-slate-400">{unit}</span>}
      </div>
      <div className="text-[9px] text-slate-500 uppercase leading-tight">{label}</div>
    </div>
  );
}

function Badge({ label, value, testId }: { label: string; value: string | null | undefined; testId: string }) {
  const v = value ?? '—';
  const color = v === 'ON' || v === 'NORMAL' || v === 'OCCUPIED' ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30'
    : v === 'DIM' || v === 'LOW' || v === 'STANDBY' ? 'bg-amber-500/20 text-amber-300 border-amber-500/30'
    : v === '—' ? 'bg-slate-800 text-slate-500 border-slate-700' : 'bg-slate-700/50 text-slate-300 border-slate-600/30';
  return (
    <div className="flex flex-col items-center gap-1">
      <span className={`text-[11px] font-bold px-2 py-1 rounded-md border ${color}`} data-testid={testId}>{v}</span>
      <span className="text-[9px] text-slate-500 uppercase">{label}</span>
    </div>
  );
}
