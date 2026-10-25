import { useEffect, useState } from 'react';
import { STALE_AFTER_MS, useBuildingStore } from '../store/useBuildingStore';
import { BuildingStatePayload } from '../types/building';

// Address of the edge brain. Set NEXT_PUBLIC_EDGE_URL (e.g. http://192.168.1.20:8001)
// when the edge brain runs on a Raspberry Pi instead of this computer.
export const EDGE_URL = (process.env.NEXT_PUBLIC_EDGE_URL || 'http://127.0.0.1:8001').replace(/\/$/, '');

/** A page more than this far behind the edge brain drops its queued updates and reconnects. */
const BACKLOG_MS = 5000;

/**
 * One SSE connection to the edge brain for the whole page. The 3D view receives the
 * same payloads from the page (VanillaTwinWrapper), so everything shows the same state.
 * The link counts as connected only while messages keep arriving.
 */
export function useSSE(url: string = `${EDGE_URL}/api/stream`) {
  const updateFromSSE = useBuildingStore((s) => s.updateFromSSE);
  const setLink = useBuildingStore((s) => s.setLink);

  useEffect(() => {
    let active = true;
    let es: EventSource | null = null;
    let reconnect: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      if (!active) return;
      const source = new EventSource(url);
      es = source;
      // Each message is a full snapshot (~100 kB). If this page is busy (slow device, software WebGL), messages
      // queue up in the connection and the page shows ever older states. Detect it from the edge brain's send
      // time (clock offset taken from this connection's fastest message) and reconnect to skip the backlog.
      let offset: number | null = null;
      source.onmessage = (event) => {
        if (!active || es !== source) return;
        let payload: BuildingStatePayload;
        try {
          payload = JSON.parse(event.data) as BuildingStatePayload;
        } catch {
          setLink({ error: 'unreadable message from the edge brain' });
          return;
        }
        const sent = payload.timestamp ? Date.parse(payload.timestamp) : NaN;
        if (Number.isFinite(sent)) {
          const d = Date.now() - sent;
          offset = offset === null ? d : Math.min(offset, d);
          if (d - offset > BACKLOG_MS) {
            source.close();
            setLink({ error: `${Math.round((d - offset) / 1000)} s behind the edge brain: skipped the queued updates` });
            connect();
            return;
          }
        }
        updateFromSSE(payload);
      };
      source.onerror = () => {
        if (!active || es !== source) return;
        setLink({ connected: false, error: `cannot reach ${url}` });
        es?.close();
        reconnect = setTimeout(connect, 3000);
      };
    };
    connect();

    // Watchdog: no message for STALE_AFTER_MS -> not live (backend stopped or tick loop stalled).
    // If this timer itself fired late, the tab was frozen (busy main thread, background tab), not the backend:
    // the messages that arrived meanwhile are still queued, so skip that tick and judge on the next one.
    let lastTick = Date.now();
    const watchdog = setInterval(() => {
      const now = Date.now();
      const frozen = now - lastTick > 1500;
      lastTick = now;
      if (frozen) return;
      const { link } = useBuildingStore.getState();
      if (link.connected && (link.lastMessageAt === null || Date.now() - link.lastMessageAt > STALE_AFTER_MS)) {
        setLink({ connected: false, error: `no data for more than ${STALE_AFTER_MS / 1000} s` });
      }
    }, 500);

    return () => {
      active = false;
      es?.close();
      if (reconnect) clearTimeout(reconnect);
      clearInterval(watchdog);
    };
  }, [url, updateFromSSE, setLink]);
}

/** Re-render every `ms` so "x s ago" labels stay current. */
export function useNow(ms = 500) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(t);
  }, [ms]);
  return now;
}
