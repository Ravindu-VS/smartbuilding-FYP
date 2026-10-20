'use client';

import React, { useState } from 'react';
import {
  Building2, Layers, DoorOpen, ChevronRight, CornerLeftUp, Users, Wind, Tag, Thermometer, Sun, Moon, Sunset,
  Camera, RotateCcw, Eye, Gauge, Play, Pause, Maximize2, Minimize2, Cpu, ScanEye,
} from 'lucide-react';
import { useBuildingStore, type Overlay, type TwinLighting, type TwinMode } from '../../store/useBuildingStore';
import { FLOOR_NAMES, FLOOR_SHORT } from '../../lib/floors';

/**
 * The 3D view's navigation (building / floor / room, breadcrumb, floor pills, room
 * picker) and its scene toolbar (layers, overlay, lighting, camera, quality, tour,
 * presentation). Everything here only changes what the 3D view shows.
 */

const glass = 'bg-slate-950/80 backdrop-blur-md border border-slate-700/70 shadow-lg shadow-black/40';

export const PRESETS: Record<TwinMode, { id: string; label: string }[]> = {
  building: [{ id: 'hero', label: 'Hero (south-west)' }, { id: 'street', label: 'Street level' }, { id: 'corner', label: 'South-east corner' }, { id: 'garden', label: 'Garden (north)' }, { id: 'aerial', label: 'Aerial' }],
  floor: [{ id: 'iso', label: 'Isometric' }, { id: 'top', label: 'Plan (top)' }, { id: 'low', label: 'Low angle' }, { id: 'east', label: 'From the east' }],
  room: [{ id: 'overview', label: 'Cutaway overview' }, { id: 'side', label: 'Cutaway side' }, { id: 'top', label: 'Top' }, { id: 'eye', label: 'Eye level (inside)' }],
};

const OVERLAYS: { id: Overlay; label: string }[] = [
  { id: 'none', label: 'Normal' },
  { id: 'comfort', label: 'Comfort (PMV)' },
  { id: 'temperature', label: 'Temperature' },
  { id: 'power', label: 'Power density' },
  { id: 'estimate', label: 'AI vs truth' },
];

const LIGHTING: { id: TwinLighting; label: string }[] = [
  { id: 'live', label: 'Live (sim clock)' }, { id: 'day', label: 'Day' }, { id: 'golden', label: 'Golden hour' }, { id: 'night', label: 'Night' },
];

function IconToggle({ on, onClick, title, children, testId }: { on: boolean; onClick: () => void; title: string; children: React.ReactNode; testId?: string }) {
  return (
    <button onClick={onClick} title={title} data-testid={testId}
      className={`h-7 w-7 flex items-center justify-center rounded-md border transition-colors ${on ? 'border-sky-500 bg-sky-900/70 text-white' : 'border-slate-700 bg-slate-900/80 text-slate-400 hover:text-white'}`}>
      {children}
    </button>
  );
}

export function TwinNavigator({ post }: { post: (msg: unknown) => void }) {
  const view = useBuildingStore((s) => s.twinView);
  const rooms = useBuildingStore((s) => s.rooms);
  const selectedRoom = useBuildingStore((s) => s.selectedRoom);
  const selectedFloor = useBuildingStore((s) => s.selectedFloor);
  const request = useBuildingStore((s) => s.requestTwinView);
  const selectFloor = useBuildingStore((s) => s.selectFloor);
  const presentation = useBuildingStore((s) => s.presentation);
  const floor = view.floor ?? selectedFloor;
  const roomList = Object.values(rooms).filter((r) => r.floor_id === floor);
  const room = view.room ? rooms[view.room] : null;

  const go = (mode: TwinMode) => {
    if (mode === 'building') request({ mode });
    else if (mode === 'floor') request({ mode, floor });
    else {
      const target = (selectedRoom && rooms[selectedRoom]) ? selectedRoom
        : (roomList.find((r) => r.source === 'hardware') ?? roomList[0])?.room_id;
      if (target) request({ mode, room: target });
    }
  };
  const up = () => (view.mode === 'room' ? request({ mode: 'floor', floor: view.floor }) : request({ mode: 'building' }));
  const btn = (m: TwinMode) => `flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11.5px] font-semibold transition-colors ${view.mode === m ? 'bg-sky-600 text-white' : 'text-slate-300 hover:text-white hover:bg-slate-800'}`;

  return (
    <div className={`absolute left-2 ${presentation ? 'top-16' : 'top-2'} z-20 flex flex-col gap-1.5 max-w-[calc(100%-360px)]`} data-testid="twin-nav">
      <div className={`${glass} rounded-xl p-1 flex items-center gap-1`}>
        <button className={btn('building')} onClick={() => go('building')} data-testid="view-building"><Building2 size={13} />Building</button>
        <button className={btn('floor')} onClick={() => go('floor')} data-testid="view-floor"><Layers size={13} />Floor</button>
        <button className={btn('room')} onClick={() => go('room')} data-testid="view-room"><DoorOpen size={13} />Room</button>
        {view.mode !== 'building' && (
          <button onClick={up} title="Up one level (Esc)" className="ml-1 h-7 w-7 flex items-center justify-center rounded-md border border-slate-700 text-slate-300 hover:text-white" data-testid="view-up"><CornerLeftUp size={13} /></button>
        )}
      </div>
      <div className={`${glass} rounded-xl px-2.5 py-1.5 flex items-center gap-1 text-[11px] text-slate-300 flex-wrap`} data-testid="breadcrumb">
        <button className="hover:text-white font-semibold" onClick={() => request({ mode: 'building' })}>Smart Hub</button>
        {view.mode !== 'building' && view.floor !== null && <>
          <ChevronRight size={12} className="text-slate-600" />
          <button className="hover:text-white" onClick={() => request({ mode: 'floor', floor: view.floor })}>{FLOOR_NAMES[view.floor] ?? `Floor ${view.floor}`}</button>
        </>}
        {view.mode === 'room' && room && <>
          <ChevronRight size={12} className="text-slate-600" />
          <span className="text-white font-semibold flex items-center gap-1">{room.display_name}{room.source === 'hardware' && <Cpu size={11} className="text-cyan-300" />}</span>
        </>}
      </div>
      <div className={`${glass} rounded-xl p-1 flex items-center gap-1`}>
        {[4, 3, 2, 1, 0].map((f) => (
          <button key={f} title={FLOOR_NAMES[f]} data-testid={`pill-floor-${f}`}
            onClick={() => { selectFloor(f); request({ mode: 'floor', floor: f }); }}
            className={`min-w-[30px] h-6 px-1.5 rounded-md text-[10.5px] font-bold ${view.mode !== 'building' && view.floor === f ? 'bg-sky-600 text-white' : 'text-slate-400 hover:text-white hover:bg-slate-800'}`}>{FLOOR_SHORT[f]}</button>
        ))}
        {view.mode === 'building' && (
          <div className="flex items-center gap-0.5 ml-1 pl-1.5 border-l border-slate-700" title="Reveal a floor from the outside (hides the floors above it)">
            <ScanEye size={13} className="text-slate-400 mr-0.5" />
            <select value={view.isolated ?? ''} data-testid="reveal-floor"
              onChange={(e) => post({ type: 'UI_COMMAND', action: 'isolateFloor', payload: e.target.value === '' ? null : Number(e.target.value) })}
              className="bg-slate-900 border border-slate-700 rounded-md text-[11px] px-1 py-0.5 text-slate-200">
              <option value="">all floors</option>
              {[4, 3, 2, 1, 0].map((f) => <option key={f} value={f}>reveal {FLOOR_SHORT[f]}</option>)}
            </select>
          </div>
        )}
        {view.mode === 'room' && (
          <select value={view.room ?? ''} onChange={(e) => request({ mode: 'room', room: e.target.value })}
            className="ml-1 bg-slate-900 border border-slate-700 rounded-md text-[11px] px-1 py-0.5 text-slate-200 max-w-[150px]" data-testid="room-picker">
            {roomList.map((r) => <option key={r.room_id} value={r.room_id}>{r.display_name}{r.source === 'hardware' ? ' (LIVE)' : ''}</option>)}
          </select>
        )}
      </div>
    </div>
  );
}

export function TwinToolbar({ post }: { post: (msg: unknown) => void }) {
  const view = useBuildingStore((s) => s.twinView);
  const layers = useBuildingStore((s) => s.twinLayers);
  const setLayers = useBuildingStore((s) => s.setTwinLayers);
  const overlay = useBuildingStore((s) => s.overlay);
  const setOverlay = useBuildingStore((s) => s.setOverlay);
  const lighting = useBuildingStore((s) => s.twinLighting);
  const setLighting = useBuildingStore((s) => s.setTwinLighting);
  const quality = useBuildingStore((s) => s.twinQuality);
  const setQuality = useBuildingStore((s) => s.setTwinQuality);
  const stats = useBuildingStore((s) => s.twinStats);
  const presentation = useBuildingStore((s) => s.presentation);
  const setPresentation = useBuildingStore((s) => s.setPresentation);
  const tour = useBuildingStore((s) => s.tour);
  const setTour = useBuildingStore((s) => s.setTour);
  const request = useBuildingStore((s) => s.requestTwinView);
  const [presetOpen, setPresetOpen] = useState(false);
  const LightIcon = lighting === 'night' ? Moon : lighting === 'golden' ? Sunset : Sun;

  return (
    <div className={`absolute right-2 ${presentation ? 'top-16' : 'top-2'} z-20 flex flex-col items-end gap-1.5`} data-testid="twin-toolbar">
      <div className={`${glass} rounded-xl p-1 flex items-center gap-1`}>
        <IconToggle on={layers.people} onClick={() => setLayers({ people: !layers.people })} title="People (simulated occupancy; presence for the live room)" testId="layer-people"><Users size={14} /></IconToggle>
        <IconToggle on={layers.airflow} onClick={() => setLayers({ airflow: !layers.airflow })} title="Airflow (qualitative — not CFD; follows each AC's real state)" testId="layer-airflow"><Wind size={14} /></IconToggle>
        <IconToggle on={overlay === 'temperature'} onClick={() => setOverlay(overlay === 'temperature' ? 'none' : 'temperature')} title="Temperature (room average, one value per room)" testId="layer-temperature"><Thermometer size={14} /></IconToggle>
        <IconToggle on={layers.labels} onClick={() => setLayers({ labels: !layers.labels })} title="Labels and room cards" testId="layer-labels"><Tag size={14} /></IconToggle>
        <span className="w-px h-5 bg-slate-700 mx-0.5" />
        <select value={overlay} onChange={(e) => setOverlay(e.target.value as Overlay)} title="Colour the rooms by…"
          className="h-7 bg-slate-900 border border-slate-700 rounded-md text-[11px] px-1 text-slate-200" data-testid="overlay">
          {OVERLAYS.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
        </select>
        <div className="flex items-center h-7 bg-slate-900 border border-slate-700 rounded-md pl-1.5" title="Lighting of the picture only — the simulation clock and weather are unchanged">
          <LightIcon size={13} className="text-amber-300" />
          <select value={lighting} onChange={(e) => setLighting(e.target.value as TwinLighting)}
            className="bg-transparent text-[11px] px-1 text-slate-200 outline-none" data-testid="lighting">
            {LIGHTING.map((l) => <option key={l.id} value={l.id} className="bg-slate-900">{l.label}</option>)}
          </select>
        </div>
      </div>
      <div className={`${glass} rounded-xl p-1 flex items-center gap-1 relative`}>
        {view.mode === 'room' && (
          <IconToggle on={view.eye} onClick={() => request({ mode: 'room', room: view.room, eye: !view.eye })} title={view.eye ? 'Back to the cutaway overview' : 'Eye level: stand inside the room'} testId="eye-level"><Eye size={14} /></IconToggle>
        )}
        <IconToggle on={presetOpen} onClick={() => setPresetOpen(!presetOpen)} title="Camera views" testId="camera-presets"><Camera size={14} /></IconToggle>
        <IconToggle on={false} onClick={() => post({ type: 'UI_COMMAND', action: 'resetCamera' })} title="Reset the camera for this view" testId="camera-reset"><RotateCcw size={14} /></IconToggle>
        <span className="w-px h-5 bg-slate-700 mx-0.5" />
        <IconToggle on={tour} onClick={() => setTour(!tour)} title={tour ? 'Stop the auto tour' : 'Auto tour: building → floor → live room → rooms (stops when you move the camera)'} testId="tour">{tour ? <Pause size={14} /> : <Play size={14} />}</IconToggle>
        <button onClick={() => setQuality(quality === 'high' ? 'balanced' : 'high')} data-testid="quality"
          title={`Rendering quality: ${quality}${stats?.auto ? ' (lowered automatically for this GPU)' : ''}. Click to switch.`}
          className="h-7 px-1.5 flex items-center gap-1 rounded-md border border-slate-700 bg-slate-900/80 text-[10.5px] text-slate-300 hover:text-white">
          <Gauge size={13} />{quality === 'high' ? 'High' : 'Fast'}{stats ? <span className="text-slate-500 font-mono">{stats.fps}fps</span> : null}
        </button>
        <IconToggle on={presentation} onClick={() => setPresentation(!presentation)} title={presentation ? 'Leave presentation mode (Esc)' : 'Presentation mode: full screen, large labels'} testId="presentation">
          {presentation ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
        </IconToggle>
        {presetOpen && (
          <div className={`${glass} absolute right-0 top-9 rounded-lg p-1 w-[170px] z-30`}>
            {PRESETS[view.mode].map((p) => (
              <button key={p.id} onClick={() => { setPresetOpen(false); if (p.id === 'eye') request({ mode: 'room', room: view.room, eye: true }); else post({ type: 'UI_COMMAND', action: 'cameraPreset', payload: p.id }); }}
                className={`w-full text-left px-2 py-1 rounded text-[11px] ${view.preset === p.id ? 'bg-sky-900/70 text-white' : 'text-slate-300 hover:bg-slate-800 hover:text-white'}`}>{p.label}</button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
