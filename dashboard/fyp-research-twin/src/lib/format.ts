// Safe number formatting: anything that is not a finite number is shown as "—".
export const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);

export const fx = (v: unknown, digits: number, suffix = ''): string =>
  isNum(v) ? `${v.toFixed(digits)}${suffix}` : '—';

export const kw = (w: unknown, digits = 1) => (isNum(w) ? `${(w / 1000).toFixed(digits)} kW` : '—');

export const pct = (v: unknown, digits = 0) => (isNum(v) ? `${v.toFixed(digits)}%` : '—');

export const signed = (v: unknown, digits = 1, suffix = '') =>
  isNum(v) ? `${v > 0 ? '+' : ''}${v.toFixed(digits)}${suffix}` : '—';

export const acLabel = (hvac: string | null | undefined, sp: number | null | undefined) =>
  !hvac ? '—' : hvac === 'NORMAL' && isNum(sp) ? `ON ${sp.toFixed(0)}°C` : hvac === 'LOW' ? 'SET-BACK 27°C' : hvac === 'ECO' ? 'OFF' : hvac;

export const simClock = (iso: string | null | undefined) => (iso ? iso.slice(11, 16) : '--:--');

// Chart colours (dataviz reference palette, dark steps; validated on the slate surface).
export const COLORS = {
  ai: '#3987e5',          // series 1: the AI controller
  baseline: '#d95926',    // series 2: the conventional schedule
  grid: '#1e293b',
  axis: '#64748b',
  text: '#cbd5e1',
  muted: '#94a3b8',
};

export const TYPE_LABEL: Record<string, string> = {
  office: 'Office', executive: 'Office', meeting: 'Meeting', kitchen: 'Kitchen', bathroom: 'Restroom',
  lobby: 'Lobby', shop: 'Shop', gym: 'Gym', lounge: 'Lounge', corridor: 'Corridor', server: 'Server room',
  residential: 'Residential',
};
