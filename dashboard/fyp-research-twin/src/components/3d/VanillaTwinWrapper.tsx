'use client';

import React, { useEffect, useRef } from 'react';
import { useBuildingStore } from '../../store/useBuildingStore';

export default function VanillaTwinWrapper() {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const rooms = useBuildingStore((state) => state.rooms);
  const system = useBuildingStore((state) => state.system);
  const isDemo = useBuildingStore((state) => state.demoMode);

  // Sync state to iframe continuously
  useEffect(() => {
    if (!iframeRef.current || !iframeRef.current.contentWindow) return;
    
    // Convert Next.js room format ('f2_office_a') to legacy app.js format ('2_office_a') if necessary
    // Wait, the Next.js backend sends 'f2_office_a', which we store.
    // Legacy app.js expects `this.liveData['2_office_a']`
    
    // We send a generic SYNC_STATE message containing all room data
    iframeRef.current.contentWindow.postMessage({
      type: 'SYNC_STATE',
      payload: rooms,
      system: system,
      isDemo
    }, '*');
  }, [rooms, system, isDemo]);

  return (
    <iframe 
      ref={iframeRef}
      src="/3d-twin/index.html" 
      className="w-full h-full border-none"
      title="Vanilla 3D Twin"
    />
  );
}
