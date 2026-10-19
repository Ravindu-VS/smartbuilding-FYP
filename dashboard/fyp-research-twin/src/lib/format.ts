// Safe number formatting: anything that is not a finite number is shown as "—".
export const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);

export const fx = (v: unknown, digits: number, suffix = ''): string =>
  isNum(v) ? `${v.toFixed(digits)}${suffix}` : '—';
