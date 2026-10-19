'use client';

import React, { useCallback, useEffect, useRef } from 'react';
import { useBuildingStore } from '../../store/useBuildingStore';
import { TwinSyncReport } from '../../types/building';

/**
 * Hosts the Three.js building (public/3d-twin) in an iframe and forwards every
 * edge brain payload to it, so the 3D view and the panels show the same state.
 * The 3D view has no connection of its own; it reports back how many of the
 * backend's rooms it found in its model (TWIN_SYNC_REPORT).
 */
export default function VanillaTwinWrapper() {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const raw = useBuildingStore((s) => s.raw);
  const linkConnected = useBuildingStore((s) => s.link.connected);
  const linkError = useBuildingStore((s) => s.link.error);
  const setTwinSync = useBuildingStore((s) => s.setTwinSync);

  const post = useCallback((msg: unknown) => {
    iframeRef.current?.contentWindow?.postMessage(msg, window.location.origin);
  }, []);

  const sendState = useCallback(() => {
    const { raw: payload } = useBuildingStore.getState();
    if (payload) {
      post({ type: 'SYNC_STATE', rooms: payload.rooms, system: payload.system, hardware: payload.hardware, seq: payload.seq });
    }
  }, [post]);

  const sendLink = useCallback(() => {
    const { link } = useBuildingStore.getState();
    post({ type: 'LINK_STATUS', ok: link.connected, detail: link.error ?? '' });
  }, [post]);

  useEffect(() => { sendState(); }, [raw, sendState]);
  useEffect(() => { sendLink(); }, [linkConnected, linkError, sendLink]);

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (event.source !== iframeRef.current?.contentWindow || !event.data) return;
      if (event.data.type === 'TWIN_READY') {
        sendLink();
        sendState();
      } else if (event.data.type === 'TWIN_SYNC_REPORT') {
        const { matched, received, modelRooms, unmatched, seq } = event.data;
        setTwinSync({ matched, received, modelRooms, unmatched: unmatched ?? [], seq: seq ?? null } as TwinSyncReport);
      }
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [sendLink, sendState, setTwinSync]);

  return (
    <iframe
      ref={iframeRef}
      src="/3d-twin/index.html"
      className="w-full h-full border-none"
      title="3D digital twin"
    />
  );
}
