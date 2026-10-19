import { useEffect, useRef } from 'react';
import { useBuildingStore } from '../store/useBuildingStore';
import { BuildingStatePayload } from '../types/building';

export function useSSE(url: string = 'http://127.0.0.1:8001/api/stream') {
  const updateFromSSE = useBuildingStore((state) => state.updateFromSSE);
  const setConnectionStatus = useBuildingStore((state) => state.setConnectionStatus);
  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    let isSubscribed = true;

    const connect = () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }

      console.log(`[SSE] Connecting to ${url}...`);
      const es = new EventSource(url);
      eventSourceRef.current = es;

      es.onopen = () => {
        console.log('[SSE] Connected');
        if (isSubscribed) setConnectionStatus(true);
      };

      es.onmessage = (event) => {
        if (!isSubscribed) return;
        try {
          const data = JSON.parse(event.data) as BuildingStatePayload;
          
          if (data.message === 'Waiting for simulation connection') {
            console.warn('[SSE] Backend is waiting for simulation...');
            setConnectionStatus(false);
            return;
          }
          
          updateFromSSE(data);
        } catch (err) {
          console.error('[SSE] Failed to parse message', err);
        }
      };

      es.onerror = (err) => {
        console.error('[SSE] Error', err);
        if (isSubscribed) setConnectionStatus(false);
        es.close();
        
        // Auto-reconnect after 3 seconds
        if (isSubscribed) {
          reconnectTimeoutRef.current = setTimeout(() => {
            connect();
          }, 3000);
        }
      };
    };

    connect();

    return () => {
      isSubscribed = false;
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
    };
  }, [url, updateFromSSE, setConnectionStatus]);
}
