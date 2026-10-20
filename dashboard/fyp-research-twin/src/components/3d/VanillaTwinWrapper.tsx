'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { backendIsCurrent, useBuildingStore, type TwinView } from '../../store/useBuildingStore';
import { LEGENDS, roomColor } from '../../lib/overlay';
import type { TwinSyncReport } from '../../types/building';
import { TwinNavigator, TwinToolbar } from './TwinControls';
import TwinContext from './TwinContext';
import PresentationHud from './PresentationHud';

/**
 * Hosts the Three.js digital twin (public/twin3d) in an iframe and forwards the edge
 * brain's building configuration and every state update to it, so the 3D view and the
 * panels always show the same data. The twin has three levels — building, floor and
 * room — navigated from here or by clicking in 3D. Selecting a room anywhere in the
 * dashboard selects it in 3D (and follows it in floor and room views).
 */
export default function VanillaTwinWrapper() {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const configSent = useRef(false);
  const raw = useBuildingStore((s) => s.raw);
  const config = useBuildingStore((s) => s.config);
  const linkConnected = useBuildingStore((s) => s.link.connected);
  const linkError = useBuildingStore((s) => s.link.error);
  const selectedRoom = useBuildingStore((s) => s.selectedRoom);
  const overlay = useBuildingStore((s) => s.overlay);
  const selectRoom = useBuildingStore((s) => s.selectRoom);
  const setTwinSync = useBuildingStore((s) => s.setTwinSync);
  const twinRequest = useBuildingStore((s) => s.twinRequest);
  const layers = useBuildingStore((s) => s.twinLayers);
  const lighting = useBuildingStore((s) => s.twinLighting);
  const quality = useBuildingStore((s) => s.twinQuality);
  const presentation = useBuildingStore((s) => s.presentation);
  const setPresentation = useBuildingStore((s) => s.setPresentation);
  const tour = useBuildingStore((s) => s.tour);
  const setTour = useBuildingStore((s) => s.setTour);
  const twinView = useBuildingStore((s) => s.twinView);
  const [ready, setReady] = useState(false);
  const current = backendIsCurrent(raw);

  const post = useCallback((msg: unknown) => {
    iframeRef.current?.contentWindow?.postMessage(msg, window.location.origin);
  }, []);

  const sendState = useCallback(() => {
    const { raw: payload, overlay: ov } = useBuildingStore.getState();
    if (!payload || !backendIsCurrent(payload)) return;
    const colors: Record<string, string> = {};
    if (ov !== 'none') for (const r of payload.rooms) { const c = roomColor(r, ov); if (c) colors[r.room_id] = c; }
    post({ type: 'SYNC_STATE', rooms: payload.rooms, system: payload.system, hardware: payload.hardware, clock: payload.clock, ai_enabled: payload.ai_enabled, seq: payload.seq });
    post({ type: 'UI_COMMAND', action: 'setOverlay', payload: { mode: ov, colors } });
  }, [post]);

  const sendLink = useCallback(() => {
    const { link, raw: r } = useBuildingStore.getState();
    const old = link.connected && r !== null && !backendIsCurrent(r);
    post({ type: 'LINK_STATUS', ok: link.connected && !old, detail: old ? 'an older edge brain version is running on port 8001' : (link.error ?? '') });
  }, [post]);

  const sendSettings = useCallback(() => {
    const s = useBuildingStore.getState();
    post({ type: 'UI_COMMAND', action: 'setLayers', payload: s.twinLayers });
    post({ type: 'UI_COMMAND', action: 'setLighting', payload: s.twinLighting });
    if (s.twinQuality !== 'high') post({ type: 'UI_COMMAND', action: 'setQuality', payload: s.twinQuality });
    post({ type: 'UI_COMMAND', action: 'setPresentation', payload: s.presentation });
  }, [post]);

  // configuration once (the twin builds the building from it), then state and settings
  useEffect(() => {
    if (ready && config && !configSent.current) {
      configSent.current = true;
      post({ type: 'CONFIG', config });
      sendState();
    }
  }, [ready, config, post, sendState]);
  useEffect(() => { if (ready) sendState(); }, [raw, overlay, ready, sendState]);
  useEffect(() => { if (ready) sendLink(); }, [linkConnected, linkError, current, ready, sendLink]);
  useEffect(() => { if (ready) post({ type: 'UI_COMMAND', action: 'setLayers', payload: layers }); }, [layers, ready, post]);
  useEffect(() => { if (ready) post({ type: 'UI_COMMAND', action: 'setLighting', payload: lighting }); }, [lighting, ready, post]);
  useEffect(() => { if (ready) post({ type: 'UI_COMMAND', action: 'setQuality', payload: quality }); }, [quality, ready, post]);
  useEffect(() => { if (ready) post({ type: 'UI_COMMAND', action: 'setPresentation', payload: presentation }); }, [presentation, ready, post]);
  useEffect(() => { if (ready) post({ type: 'UI_COMMAND', action: 'tour', payload: tour }); }, [tour, ready, post]);

  // navigation requests from the dashboard (toolbar, breadcrumb, building list, demo)
  useEffect(() => {
    if (!ready || !twinRequest) return;
    const v = twinRequest.view;
    post({ type: 'UI_COMMAND', action: 'setView', payload: { mode: v.mode, floor: v.floor ?? null, room: v.room ?? null, eye: !!v.eye, preset: twinRequest.preset } });
  }, [twinRequest, ready, post]);

  // a room selected anywhere is highlighted in 3D; floor and room views follow it
  useEffect(() => {
    if (!ready) return;
    post({ type: 'UI_COMMAND', action: 'selectRoom', payload: selectedRoom });
    const { twinView: tv, rooms, requestTwinView, twinRequest: pending } = useBuildingStore.getState();
    const r = selectedRoom ? rooms[selectedRoom] : null;
    if (!r) return;
    // a view change for this room is already on its way (e.g. double-click in the list)
    if (pending && pending.view.mode === 'room' && pending.view.room === selectedRoom) return;
    if (tv.mode === 'room' && tv.room !== selectedRoom) requestTwinView({ mode: 'room', room: selectedRoom });
    else if (tv.mode === 'floor' && tv.floor !== r.floor_id) requestTwinView({ mode: 'floor', floor: r.floor_id });
  }, [selectedRoom, ready, post]);

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (event.source !== iframeRef.current?.contentWindow || !event.data) return;
      const d = event.data;
      if (d.type === 'TWIN_READY') {
        if (!d.hasConfig) configSent.current = false;
        setReady(true);
        sendLink();
        sendSettings();
      } else if (d.type === 'ROOM_SELECTED') {
        selectRoom(d.room_id ?? null);
      } else if (d.type === 'VIEW_CHANGED') {
        useBuildingStore.getState().setTwinView({ mode: d.mode, floor: d.floor ?? null, room: d.room ?? null, eye: !!d.eye, preset: d.preset, isolated: d.isolated ?? null } as TwinView);
        if (d.floor !== null && d.floor !== undefined) useBuildingStore.getState().selectFloor(d.floor);
      } else if (d.type === 'TWIN_SYNC_REPORT') {
        const { matched, received, modelRooms, unmatched, seq } = d;
        setTwinSync({ matched, received, modelRooms, unmatched: unmatched ?? [], seq: seq ?? null } as TwinSyncReport);
      } else if (d.type === 'TWIN_STATS') {
        useBuildingStore.getState().setTwinStats({ fps: d.fps, calls: d.calls, triangles: d.triangles, quality: d.quality, auto: !!d.auto });
        if (d.auto && useBuildingStore.getState().twinQuality === 'high') useBuildingStore.getState().setTwinQuality('balanced');
      } else if (d.type === 'TOUR_STEP') {
        if (d.index < 0 && useBuildingStore.getState().tour) setTour(false);
      }
    };
    window.addEventListener('message', onMessage);
    // in case the twin finished loading before this listener existed
    iframeRef.current?.contentWindow?.postMessage({ type: 'PING' }, window.location.origin);
    return () => window.removeEventListener('message', onMessage);
  }, [sendLink, sendSettings, setTwinSync, selectRoom, setTour]);

  // Esc: leave presentation, otherwise go up one level
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'SELECT' || t.tagName === 'TEXTAREA')) return;
      const s = useBuildingStore.getState();
      if (s.presentation) { setPresentation(false); return; }
      if (s.twinView.mode === 'room') s.requestTwinView({ mode: 'floor', floor: s.twinView.floor });
      else if (s.twinView.mode === 'floor') s.requestTwinView({ mode: 'building' });
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [setPresentation]);

  const clock = current ? raw!.clock : null;
  const legend = overlay !== 'none' ? LEGENDS[overlay] : null;

  return (
    <div className={presentation ? 'fixed inset-0 z-[60] bg-slate-950' : 'relative w-full h-full'} data-testid="twin-viewport">
      <iframe ref={iframeRef} src="/twin3d/index.html?embedded=1" className="absolute inset-0 w-full h-full border-none" title="3D digital twin"
        onLoad={() => iframeRef.current?.contentWindow?.postMessage({ type: 'PING' }, window.location.origin)} />
      {presentation && <PresentationHud />}
      <TwinNavigator post={post} />
      <TwinToolbar post={post} />
      <TwinContext />

      <div className="absolute bottom-2 right-2 z-10 flex flex-col items-end gap-1.5 pointer-events-none">
        {layers.airflow && twinView.mode !== 'building' && (
          <div className="w-[260px] bg-slate-950/90 border border-slate-700 rounded-lg p-2 pointer-events-auto" data-testid="airflow-legend">
            <div className="text-[11px] font-semibold text-slate-100">Airflow — qualitative, not CFD</div>
            <div className="grid grid-cols-3 gap-1 mt-1 text-[10px] text-slate-300">
              <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full bg-[#2fa8ff]" />supply</span>
              <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full bg-[#ff9d5c]" />return</span>
              <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full bg-[#22c55e]" />fresh air</span>
            </div>
            <div className="text-[9.5px] text-slate-500 mt-1 leading-snug">How much air moves follows each AC&apos;s real state: cooling output in the simulated rooms, fan PWM on the live room&apos;s board. AC off or ECO: no supply air.</div>
          </div>
        )}
        {legend && (
          <div className="w-[260px] bg-slate-950/90 border border-slate-700 rounded-lg p-2 pointer-events-auto" data-testid="legend">
            <div className="text-[11px] font-semibold text-slate-100">{legend.title}</div>
            {legend.gradient && (
              <>
                <div className="h-2.5 rounded mt-1" style={{ background: `linear-gradient(to right, ${legend.gradient.from}, ${legend.gradient.mid ?? legend.gradient.from}, ${legend.gradient.to})` }} />
                <div className="flex justify-between text-[9.5px] text-slate-400 mt-0.5">{legend.gradient.labels.map((l) => <span key={l}>{l}</span>)}</div>
              </>
            )}
            {legend.stops && (
              <div className="grid grid-cols-2 gap-1 mt-1">
                {legend.stops.map((s) => <span key={s.label} className="flex items-center gap-1 text-[10px] text-slate-300"><span className="w-3 h-3 rounded-sm" style={{ background: s.color }} />{s.label}</span>)}
              </div>
            )}
            <div className="text-[9.5px] text-slate-500 mt-1 leading-snug">{legend.note}{overlay === 'temperature' ? ' Each room shows its average temperature (one value per room, not a spatial field).' : ''}</div>
          </div>
        )}
      </div>

      {clock?.phase === 'learning' && (
        <div className={`absolute ${presentation ? 'top-[136px]' : 'top-[124px]'} left-1/2 -translate-x-1/2 z-10 w-[min(520px,60%)] bg-violet-950/90 border border-violet-700 rounded-lg px-3 py-2`} data-testid="learning-banner">
          <div className="text-[12px] text-violet-100 font-semibold">The AI is learning this building&apos;s weekly routine</div>
          <div className="text-[10.5px] text-violet-200/80">Simulated week {clock.date} — day {Math.min(clock.learning_days, Math.floor(clock.learning_progress * clock.learning_days) + 1)} of {clock.learning_days}. Same method as the thesis experiments; the result is cached for the next start.</div>
          <div className="h-1.5 bg-violet-900 rounded-full overflow-hidden mt-1.5"><div className="h-full bg-violet-400 transition-all" style={{ width: `${clock.learning_progress * 100}%` }} /></div>
        </div>
      )}
      {clock && clock.fast_forward_minutes > 0 && (
        <div className={`absolute ${presentation ? 'top-[72px]' : 'top-2'} left-1/2 -translate-x-1/2 z-10 bg-sky-950/90 border border-sky-700 rounded-lg px-3 py-1.5 text-[11px] text-sky-100`} data-testid="ff-banner">
          Fast-forwarding: {Math.round(clock.fast_forward_minutes)} simulated min to go
          {clock.fast_forward_total_minutes > 0 ? ` (${Math.round(100 * (1 - clock.fast_forward_minutes / clock.fast_forward_total_minutes))}%)` : ''}
        </div>
      )}
      {current && raw!.ai_enabled === false && clock?.phase === 'running' && !(clock.fast_forward_minutes > 0) && (
        <div className={`absolute ${presentation ? 'top-[72px]' : 'top-2'} left-1/2 -translate-x-1/2 z-10 bg-orange-950/90 border border-orange-600 rounded-full px-3 py-1 text-[11px] font-semibold text-orange-100`} data-testid="ai-off-banner">
          AI OFF — every room on conventional schedule control
        </div>
      )}
      {clock && !clock.running && clock.phase === 'running' && (
        <div className={`absolute ${presentation ? 'top-[108px]' : 'top-10'} left-1/2 -translate-x-1/2 z-10 bg-slate-900/90 border border-slate-600 rounded-lg px-3 py-1.5 text-[11px] text-slate-200`}>Simulation paused</div>
      )}
    </div>
  );
}
