// Calls to the edge brain's control API. Every action changes the simulation on the
// edge brain; the dashboard then shows the result from the next streamed state.
import { EDGE_URL } from '../hooks/useSSE';
import type { BuildingConfig, HistoryPoint, SeriesPoint, TimelineEvent, Comparison, ModelsStatus, ProvenanceStatus } from '../types/building';

async function post<T = unknown>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`${EDGE_URL}${path}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((data as { message?: string; error?: string }).message || (data as { error?: string }).error || `HTTP ${r.status}`);
  return data as T;
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${EDGE_URL}${path}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return (await r.json()) as T;
}

export const api = {
  control: (action: string, extra: Record<string, unknown> = {}) => post('/api/simulation/control', { action, ...extra }),
  setController: (controller: string) => post('/api/simulation/controller', { controller }),
  setAi: (enabled: boolean) => post('/api/ai', { enabled }),
  meter: () => get<import('../types/building').Meter>('/api/meter'),
  scenario: (kind: string, room_id: string | null, value: number, minutes: number) =>
    post<{ scenario: { id: number; label: string } }>('/api/scenario', { kind, room_id, value, minutes }),
  clearScenarios: () => post('/api/scenario', { action: 'clear' }),
  calibrateLed: (room_id?: string) => post('/api/hardware/calibrate-led', { room_id }),
  override: (body: { room_id: string; fan_speed?: number; light_level?: number; servo_angle?: number; minutes?: number; reason?: string; clear?: boolean }) =>
    post('/api/hardware/override', body),
  config: () => get<BuildingConfig>('/api/building/config'),
  timeline: (q: { after?: number; room_id?: string; limit?: number; kinds?: string }) => {
    const p = new URLSearchParams();
    if (q.after) p.set('after', String(q.after));
    if (q.room_id) p.set('room_id', q.room_id);
    if (q.limit) p.set('limit', String(q.limit));
    if (q.kinds) p.set('kinds', q.kinds);
    return get<TimelineEvent[]>(`/api/timeline?${p.toString()}`);
  },
  history: (roomId: string) => get<Record<string, HistoryPoint[]>>(`/api/rooms/history?room_id=${encodeURIComponent(roomId)}`),
  models: () => get<ModelsStatus>('/api/models'),
  provenance: () => get<ProvenanceStatus>('/api/provenance'),
  mqtt: () => get<Record<string, unknown>>('/api/hardware/mqtt'),
  analytics: () => get<{ comparison: Comparison; series: SeriesPoint[]; meter: import('../types/building').Meter }>('/api/analytics'),
};
