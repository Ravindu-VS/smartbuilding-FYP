'use client';

import React, { useState, useEffect } from 'react';
import { useBuildingStore } from '../../store/useBuildingStore';
import { Play, Square, FastForward } from 'lucide-react';

export default function DemoController() {
  const [demoStep, setDemoStep] = useState(0);
  const toggleDemoMode = useBuildingStore((state) => state.toggleDemoMode);
  const demoMode = useBuildingStore((state) => state.demoMode);

  // The 10-step sequence for the Viva demonstration
  const runDemoSequence = async () => {
    toggleDemoMode(true);
    setDemoStep(1); // Building starts idle
    
    // Grab the set function from store secretly
    const setStore = useBuildingStore.setState;

    // Step 1: Idle
    setStore((state) => ({
      rooms: {
        ...state.rooms,
        'f2_office_a': {
          ...state.rooms['f2_office_a'],
          sensors: { ...state.rooms['f2_office_a']?.sensors, occupancy: 0, temperature: 22 },
          control: { ...state.rooms['f2_office_a']?.control, hvac: 'OFF', light: 'OFF' }
        }
      }
    }));
    
    await new Promise(r => setTimeout(r, 4000));
    setDemoStep(2); // Detection
    
    setStore((state) => ({
      rooms: {
        ...state.rooms,
        'f2_office_a': {
          ...state.rooms['f2_office_a'],
          sensors: { ...state.rooms['f2_office_a']?.sensors, occupancy: 1, temperature: 26 },
        }
      }
    }));

    await new Promise(r => setTimeout(r, 4000));
    setDemoStep(3); // AI Inference
    
    setStore((state) => ({
      rooms: {
        ...state.rooms,
        'f2_office_a': {
          ...state.rooms['f2_office_a'],
          ai: { ...state.rooms['f2_office_a']?.ai, occupancy_probability: 0.97 },
        }
      }
    }));

    await new Promise(r => setTimeout(r, 4000));
    setDemoStep(4); // AI Reasoning & Actuation
    
    setStore((state) => ({
      rooms: {
        ...state.rooms,
        'f2_office_a': {
          ...state.rooms['f2_office_a'],
          control: { ...state.rooms['f2_office_a']?.control, hvac: 'NORMAL', light: 'ON' }
        }
      }
    }));

    await new Promise(r => setTimeout(r, 4000));
    setDemoStep(5); // Stabilization & Savings
    
    setStore((state) => {
      const newState = {
        system: {
          ...state.system!,
          percentage_saved: 18.5
        },
        rooms: {
          ...state.rooms,
          'f2_office_a': {
            ...state.rooms['f2_office_a'],
            sensors: { ...state.rooms['f2_office_a']?.sensors, temperature: 23 },
            control: { ...state.rooms['f2_office_a']?.control, hvac: 'ECO', light: 'DIM' }
          }
        }
      };
      
      // Notify iframe to update visuals
      const iframe = document.querySelector('iframe');
      if (iframe && iframe.contentWindow) {
        iframe.contentWindow.postMessage({ type: 'DEMO_OVERRIDE', payload: newState.rooms['f2_office_a'] }, '*');
      }
      
      return newState;
    });

    await new Promise(r => setTimeout(r, 4000));
    setDemoStep(0);
    toggleDemoMode(false);
    
    const iframe = document.querySelector('iframe');
    if (iframe && iframe.contentWindow) {
      iframe.contentWindow.postMessage({ type: 'DEMO_END' }, '*');
    }
  };

  return (
    <div className="absolute bottom-6 left-6 bg-slate-900/90 backdrop-blur border border-slate-700 rounded-xl p-4 shadow-2xl z-50 flex items-center gap-4">
      <div className="text-sm font-bold text-white uppercase tracking-wider">Viva Demo Mode</div>
      
      {!demoMode ? (
        <button 
          onClick={runDemoSequence}
          className="bg-indigo-600 hover:bg-indigo-500 text-white px-4 py-2 rounded flex items-center gap-2 transition-colors"
        >
          <Play size={16} /> Start Sequence
        </button>
      ) : (
        <div className="flex items-center gap-4">
          <div className="text-cyan-400 font-mono text-xs flex items-center gap-2 bg-cyan-950/30 px-3 py-1 rounded">
            <FastForward size={14} className="animate-pulse" />
            Executing Step {demoStep}/5
          </div>
          <button 
            onClick={() => { toggleDemoMode(false); setDemoStep(0); }}
            className="bg-red-600 hover:bg-red-500 text-white px-3 py-1.5 rounded flex items-center gap-2 transition-colors text-xs"
          >
            <Square size={14} /> Stop
          </button>
        </div>
      )}
    </div>
  );
}
