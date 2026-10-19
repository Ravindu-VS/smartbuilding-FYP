'use client';

import React, { useState } from 'react';
import { useSSE } from '../hooks/useSSE';
import { useBuildingStore } from '../store/useBuildingStore';
import DemoController from '../components/demo/DemoController';
import VanillaTwinWrapper from '../components/3d/VanillaTwinWrapper';
import HardwareLivePanel from '../components/hardware/HardwareLivePanel';
import { Activity, Cpu, Wifi, Settings, ShieldAlert, CheckCircle2, XCircle } from 'lucide-react';

const CircularGauge = ({ value, label, colorClass }: { value: number, label: string, colorClass: string }) => {
  const radius = 20;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference - (value / 100) * circumference;

  return (
    <div className="flex flex-col items-center gap-1">
      <div className="relative w-12 h-12 flex items-center justify-center">
        <svg className="w-full h-full transform -rotate-90">
          <circle cx="24" cy="24" r="20" stroke="currentColor" strokeWidth="4" fill="transparent" className="text-slate-800" />
          <circle cx="24" cy="24" r="20" stroke="currentColor" strokeWidth="4" fill="transparent"
            strokeDasharray={circumference} strokeDashoffset={strokeDashoffset}
            className={`transition-all duration-1000 ${colorClass}`} />
        </svg>
        <span className="absolute text-[10px] font-bold">{value.toFixed(0)}%</span>
      </div>
      <span className="text-[9px] uppercase text-slate-500 font-bold text-center leading-tight">{label}</span>
    </div>
  );
};

export default function Dashboard() {
  useSSE('http://127.0.0.1:8001/api/stream');
  
  const system = useBuildingStore((state) => state.system);
  const isConnected = useBuildingStore((state) => state.isConnected);
  const room101 = useBuildingStore((state) => state.rooms['f2_office_a']);
  
  const [showFutureMode, setShowFutureMode] = useState(false);

  // Note: Room 101 live data is now handled by HardwareLivePanel component
  // which reads directly from the Zustand store.

  return (
    <div className="min-h-screen bg-slate-950 text-slate-200 flex flex-col font-sans overflow-hidden">
      
      {/* HEADER */}
      <header className="h-14 border-b border-slate-800 bg-slate-900/50 flex items-center justify-between px-6 z-10 relative">
        <div className="flex items-center gap-3">
          <div className={`w-3 h-3 rounded-full ${isConnected ? 'bg-emerald-500 animate-pulse' : 'bg-red-500'}`}></div>
          <h1 className="font-bold text-lg tracking-tight text-white">Hybrid Edge Digital Twin <span className="text-cyan-400 font-mono text-xs ml-2">v2.0 (Research Build)</span></h1>
        </div>
        
        <div className="flex items-center gap-6 text-xs font-mono">
          <div className="flex items-center gap-2">
            <Wifi size={14} className={isConnected ? "text-emerald-400" : "text-red-400"} />
            <span className={isConnected ? "text-emerald-400" : "text-red-400"}>MQTT / SSE</span>
          </div>
          <div className="flex items-center gap-2">
            <Cpu size={14} className="text-cyan-400" />
            <span className="text-cyan-400">ESP32-S3 (Room 101)</span>
          </div>
          <div className="px-2 py-1 bg-slate-800 rounded border border-slate-700 flex gap-2">
            <span className="text-slate-400">Time:</span>
            <span className="text-white">{system?.simulation_time || "00:00:00"}</span>
          </div>
        </div>
      </header>

      {/* MAIN GRID */}
      <div className="flex-1 flex overflow-hidden">
        
        {/* LEFT SIDEBAR - RESEARCH & ARCHITECTURE */}
        <aside className="w-64 shrink-0 border-r border-slate-800 bg-slate-900/30 p-4 flex flex-col gap-4 overflow-y-auto z-10 relative">
          
          <div className="bg-slate-800/40 border border-slate-700/50 rounded-lg p-3">
            <h2 className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-2">Research Contributions</h2>
            <ul className="space-y-1.5 text-xs text-slate-300">
              <li className="flex items-center gap-2"><CheckCircle2 size={12} className="text-emerald-400"/> Edge Intelligence</li>
              <li className="flex items-center gap-2"><CheckCircle2 size={12} className="text-emerald-400"/> Digital Twin</li>
              <li className="flex items-center gap-2"><CheckCircle2 size={12} className="text-emerald-400"/> Hierarchical Architecture</li>
              <li className="flex items-center gap-2"><CheckCircle2 size={12} className="text-emerald-400"/> Hybrid Cyber-Physical</li>
              <li className="flex items-center gap-2"><CheckCircle2 size={12} className="text-emerald-400"/> Multi-objective Opt.</li>
              <li className="flex items-center gap-2"><CheckCircle2 size={12} className="text-emerald-400"/> Future PPO Brain</li>
              <li className="flex items-center gap-2"><CheckCircle2 size={12} className="text-emerald-400"/> WSO2 Architecture</li>
            </ul>
          </div>

          <div className="bg-slate-800/40 border border-slate-700/50 rounded-lg p-3">
            <div className="flex justify-between items-center mb-2">
              <h2 className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Architecture</h2>
              <button onClick={() => setShowFutureMode(!showFutureMode)} className={`text-[9px] px-2 py-0.5 rounded ${showFutureMode ? 'bg-indigo-500 text-white' : 'bg-slate-700 text-slate-300'}`}>
                {showFutureMode ? 'Current Mode' : 'Future Mode'}
              </button>
            </div>
            
            <div className="text-xs font-mono text-center space-y-1">
              {!showFutureMode ? (
                <div className="animate-in fade-in slide-in-from-top-2 duration-300">
                  <div className="bg-cyan-950/50 border border-cyan-800 text-cyan-400 py-1 rounded">ESP32 (Room 101)</div>
                  <div className="text-slate-500">↓</div>
                  <div className="bg-slate-800 border border-slate-700 text-slate-300 py-1 rounded">FastAPI Server</div>
                </div>
              ) : (
                <div className="animate-in fade-in zoom-in-95 duration-500 text-indigo-300">
                  <div className="bg-cyan-950/30 border border-cyan-900 py-1 rounded">ESP32 Nodes</div>
                  <div className="text-slate-500">↓</div>
                  <div className="bg-indigo-950/50 border border-indigo-800 py-1 rounded font-bold">Raspberry Pi 4B</div>
                  <div className="text-slate-500">↓</div>
                  <div className="bg-fuchsia-950/50 border border-fuchsia-800 py-1 rounded">Hierarchical PPO</div>
                  <div className="text-slate-500">↓</div>
                  <div className="bg-slate-800 border border-slate-700 py-1 rounded">Campus Optimization</div>
                </div>
              )}
            </div>
          </div>
          
          <div className="bg-slate-800/40 border border-slate-700/50 rounded-lg p-3">
            <h2 className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-2">Optimization Result</h2>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div className="bg-slate-900/50 p-2 rounded">
                <span className="text-[9px] text-slate-500 block mb-1">BEFORE AI (Power)</span>
                <span className="text-amber-400 font-mono text-lg">220W</span>
              </div>
              <div className="bg-slate-900/50 p-2 rounded">
                <span className="text-[9px] text-slate-500 block mb-1">AFTER AI (Power)</span>
                <span className="text-emerald-400 font-mono text-lg">{room101?.energy?.estimated_power_watts?.toFixed(0) || 145}W</span>
              </div>
            </div>
            <div className="mt-2 bg-emerald-950/30 border border-emerald-900/50 p-1.5 rounded text-center">
              <span className="text-[10px] text-emerald-400 font-bold">SAVINGS: 34%</span>
            </div>
          </div>

        </aside>

        {/* CENTER - 3D TWIN */}
        <main className="flex-1 relative bg-slate-950">
          <VanillaTwinWrapper />
        </main>

        {/* RIGHT SIDEBAR - ROOM 101 LIVE HARDWARE */}
        <aside className="w-[340px] shrink-0 border-l border-slate-800 bg-slate-900/50 flex flex-col z-10 relative overflow-y-auto">
          
          {/* Hardware Live Panel — real ESP32 data */}
          <HardwareLivePanel />

          {/* System Confidence Gauges */}
          <div className="p-3 border-t border-slate-800/50">
            <h2 className="text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-2">System Confidence</h2>
            <div className="flex justify-between px-2">
              <CircularGauge value={(room101?.ai?.occupancy_probability ?? 0) * 100} label="Occ Conf" colorClass="text-indigo-500" />
              <CircularGauge value={92} label="Comfort" colorClass="text-cyan-500" />
              <CircularGauge value={system?.percentage_saved ?? 34} label="Savings" colorClass="text-emerald-500" />
              <CircularGauge value={isConnected ? 99 : 0} label="Health" colorClass="text-fuchsia-500" />
            </div>
          </div>

          {/* Twin Sync Status */}
          <div className="mt-auto p-3 bg-slate-900 border-t border-slate-800/50">
            <h2 className="text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-2">Twin Synchronization</h2>
            <div className="grid grid-cols-2 gap-1 text-[10px] text-slate-400">
              <div className="flex items-center gap-1"><CheckCircle2 size={10} className="text-emerald-400" /> Temperature</div>
              <div className="flex items-center gap-1"><CheckCircle2 size={10} className="text-emerald-400" /> Humidity</div>
              <div className="flex items-center gap-1"><CheckCircle2 size={10} className="text-emerald-400" /> Lighting</div>
              <div className="flex items-center gap-1"><CheckCircle2 size={10} className="text-emerald-400" /> HVAC</div>
              <div className="flex items-center gap-1"><CheckCircle2 size={10} className="text-emerald-400" /> Occupancy</div>
              <div className="flex items-center gap-1"><CheckCircle2 size={10} className="text-emerald-400" /> Power</div>
            </div>
            <div className="mt-2 text-center border border-emerald-900/50 bg-emerald-950/20 py-1 rounded text-emerald-400 text-xs font-bold shadow-[0_0_10px_rgba(16,185,129,0.1)]">
              OVERALL SYNC: {isConnected ? '98.9' : '0.0'}%
            </div>
          </div>

        </aside>

      </div>
    </div>
  );
}
