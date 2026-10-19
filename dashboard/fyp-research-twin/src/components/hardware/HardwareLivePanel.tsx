'use client';

import React, { useEffect, useState } from 'react';
import { useBuildingStore } from '../../store/useBuildingStore';

/**
 * HardwareLivePanel — Room 101 Live Sensor Telemetry
 * 
 * Shows real-time data from the physical ESP32 prototype.
 * This is the most important viva component — it proves the
 * cyber-physical loop is working.
 * 
 * Data flow: ESP32 → MQTT/REST → Backend → SSE → This Panel
 */

interface HardwareLivePanelProps {
  className?: string;
}

export default function HardwareLivePanel({ className = '' }: HardwareLivePanelProps) {
  const room101 = useBuildingStore((state) => state.rooms['f2_office_a']);
  const isConnected = useBuildingStore((state) => state.isConnected);
  const [pulseActive, setPulseActive] = useState(false);
  const [lastOccupancy, setLastOccupancy] = useState(0);

  // Pulse effect when occupancy changes
  useEffect(() => {
    const currentOcc = room101?.ground_truth?.true_occupancy ?? 0;
    if (currentOcc !== lastOccupancy) {
      setPulseActive(true);
      setLastOccupancy(currentOcc);
      const timer = setTimeout(() => setPulseActive(false), 1500);
      return () => clearTimeout(timer);
    }
  }, [room101?.ground_truth?.true_occupancy, lastOccupancy]);

  if (!room101) {
    return (
      <div className={`bg-slate-900/80 backdrop-blur-md rounded-xl border border-slate-700/50 p-4 ${className}`}>
        <div className="text-slate-400 text-sm">Waiting for Room 101 data...</div>
      </div>
    );
  }

  const isLive = room101.isLive || room101.source === 'hardware';
  const sensors = room101.sensors || {};
  const ai = room101.ai || {};
  const control = room101.control || {};
  const energy = room101.energy || {};
  const deviceState = room101.device_state || {};

  const probability = (ai.occupancy_probability ?? 0) * 100;
  const edgeProb = (sensors.edge_occupancy_probability ?? ai.occupancy_probability ?? 0) * 100;
  const trueOcc = room101.ground_truth?.true_occupancy ?? 0;

  return (
    <div className={`relative overflow-hidden rounded-xl border ${
      isLive 
        ? 'border-emerald-500/50 bg-slate-900/90' 
        : 'border-slate-700/50 bg-slate-900/80'
    } backdrop-blur-md ${className}`}>

      {/* Pulse overlay on occupancy change */}
      {pulseActive && (
        <div className="absolute inset-0 bg-emerald-500/10 animate-pulse rounded-xl pointer-events-none z-10" />
      )}

      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700/50">
        <div className="flex items-center gap-2">
          <div className={`w-2.5 h-2.5 rounded-full ${
            isLive ? 'bg-emerald-400 animate-pulse' : 'bg-amber-400'
          }`} />
          <span className="text-white font-bold text-sm tracking-wide">
            ROOM 101 {isLive ? '— LIVE HARDWARE' : '— SIMULATION'}
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          {isLive && (
            <span className="text-[10px] font-mono bg-emerald-500/20 text-emerald-300 px-2 py-0.5 rounded-full border border-emerald-500/30">
              ESP32-S3
            </span>
          )}
          <span className={`text-[10px] font-mono px-2 py-0.5 rounded-full ${
            isConnected ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30' 
                       : 'bg-red-500/20 text-red-300 border border-red-500/30'
          }`}>
            {isConnected ? 'CONNECTED' : 'OFFLINE'}
          </span>
        </div>
      </div>

      {/* Sensor Grid */}
      <div className="px-4 py-3">
        <div className="text-[10px] uppercase text-slate-500 font-bold mb-2 tracking-widest">
          Sensor Readings
        </div>
        <div className="grid grid-cols-2 gap-2">
          <SensorCard
            label="Temperature"
            value={sensors.temperature?.toFixed(1) ?? '—'}
            unit="°C"
            icon="🌡️"
            color={sensors.temperature > 26 ? 'text-amber-400' : 'text-cyan-400'}
          />
          <SensorCard
            label="Humidity"
            value={sensors.humidity?.toFixed(0) ?? '—'}
            unit="%"
            icon="💧"
            color="text-blue-400"
          />
          <SensorCard
            label="Light Level"
            value={sensors.light?.toFixed(0) ?? '—'}
            unit="lux"
            icon="☀️"
            color="text-yellow-400"
          />
          <SensorCard
            label="CO₂"
            value={sensors.co2?.toFixed(0) ?? '—'}
            unit="ppm"
            icon="🌿"
            color={sensors.co2 > 800 ? 'text-red-400' : 'text-green-400'}
          />
        </div>
      </div>

      {/* Edge AI Section */}
      <div className="px-4 py-3 border-t border-slate-700/30">
        <div className="text-[10px] uppercase text-slate-500 font-bold mb-2 tracking-widest">
          Edge AI Inference
        </div>
        <div className="flex items-center gap-4">
          {/* Probability gauge */}
          <div className="flex-1">
            <div className="flex justify-between text-[11px] mb-1">
              <span className="text-slate-400">Occupancy Probability</span>
              <span className={`font-bold ${probability > 70 ? 'text-emerald-400' : probability > 35 ? 'text-amber-400' : 'text-slate-400'}`}>
                {edgeProb.toFixed(1)}%
              </span>
            </div>
            <div className="h-2 bg-slate-800 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-700 ${
                  probability > 70 ? 'bg-emerald-500' : probability > 35 ? 'bg-amber-500' : 'bg-slate-600'
                }`}
                style={{ width: `${Math.min(edgeProb, 100)}%` }}
              />
            </div>
            <div className="flex justify-between text-[9px] mt-1 text-slate-600">
              <span>0%</span>
              <span>35%</span>
              <span>70%</span>
              <span>100%</span>
            </div>
          </div>

          {/* Occupancy result */}
          <div className="flex flex-col items-center gap-1 min-w-[56px]">
            <div className={`text-2xl font-black ${trueOcc > 0 ? 'text-emerald-400' : 'text-slate-500'}`}>
              {trueOcc}
            </div>
            <div className="text-[9px] text-slate-500 uppercase font-bold">Occupants</div>
          </div>
        </div>
      </div>

      {/* AI Control Decisions */}
      <div className="px-4 py-3 border-t border-slate-700/30">
        <div className="text-[10px] uppercase text-slate-500 font-bold mb-2 tracking-widest">
          AI Control Decisions
        </div>
        <div className="grid grid-cols-3 gap-2">
          <DecisionBadge
            label="Lighting"
            value={control.light_action || control.light || 'OFF'}
            active={deviceState.light_on}
          />
          <DecisionBadge
            label="HVAC"
            value={control.hvac_action || control.hvac || 'OFF'}
            active={deviceState.hvac_mode !== 'off'}
          />
          <DecisionBadge
            label="Mode"
            value={control.control_mode || '—'}
            active={true}
            variant="info"
          />
        </div>
      </div>

      {/* Energy */}
      <div className="px-4 py-3 border-t border-slate-700/30">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-[10px] uppercase text-slate-500 font-bold tracking-widest">Power</div>
            <div className="text-lg font-bold text-white">
              {(energy.estimated_power_watts ?? 0).toFixed(0)}
              <span className="text-xs text-slate-400 ml-1">W</span>
            </div>
          </div>
          {energy.optimization && (
            <div className="text-right">
              <div className="text-[10px] uppercase text-emerald-500 font-bold tracking-widest">Saved</div>
              <div className="text-lg font-bold text-emerald-400">
                {(energy.optimization.percentage_saved ?? 0).toFixed(1)}
                <span className="text-xs text-emerald-500/70 ml-0.5">%</span>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Source & Timestamp */}
      <div className="px-4 py-2 bg-slate-950/50 flex items-center justify-between text-[10px] text-slate-500">
        <span>Source: {isLive ? 'ESP32-S3 Hardware' : 'Simulation'}</span>
        <span>{room101.timestamp?.split('T')[1]?.slice(0, 8) ?? '—'}</span>
      </div>
    </div>
  );
}

// ─── Sub-components ───

function SensorCard({ label, value, unit, icon, color }: { 
  label: string; value: string; unit: string; icon: string; color: string;
}) {
  return (
    <div className="bg-slate-800/50 rounded-lg p-2.5 flex items-center gap-2.5">
      <span className="text-lg">{icon}</span>
      <div>
        <div className={`text-sm font-bold ${color}`}>
          {value} <span className="text-[10px] text-slate-400">{unit}</span>
        </div>
        <div className="text-[9px] text-slate-500 uppercase">{label}</div>
      </div>
    </div>
  );
}

function DecisionBadge({ label, value, active, variant = 'default' }: {
  label: string; value: string; active: boolean; variant?: string;
}) {
  const colorMap: Record<string, string> = {
    'ON': 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
    'OFF': 'bg-slate-700/50 text-slate-400 border-slate-600/30',
    'COOLING': 'bg-cyan-500/20 text-cyan-300 border-cyan-500/30',
    'HEATING': 'bg-orange-500/20 text-orange-300 border-orange-500/30',
    'ECO': 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
    'VENTILATION': 'bg-blue-500/20 text-blue-300 border-blue-500/30',
    'NORMAL': 'bg-blue-500/20 text-blue-300 border-blue-500/30',
    'DIM': 'bg-amber-500/20 text-amber-300 border-amber-500/30',
  };
  
  const colors = variant === 'info' 
    ? 'bg-indigo-500/20 text-indigo-300 border-indigo-500/30'
    : colorMap[value.toUpperCase()] || 'bg-slate-700/50 text-slate-400 border-slate-600/30';

  return (
    <div className="flex flex-col items-center gap-1">
      <span className={`text-[11px] font-bold px-2.5 py-1 rounded-md border ${colors}`}>
        {value}
      </span>
      <span className="text-[9px] text-slate-500 uppercase">{label}</span>
    </div>
  );
}
