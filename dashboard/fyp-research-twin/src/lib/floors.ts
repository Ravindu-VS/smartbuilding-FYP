// Floor names used by the navigation, the 3D view and the panels.
export const FLOOR_NAMES: Record<number, string> = {
  0: 'Ground · Retail & Lobby', 1: 'Level 1 · Health & Recreation', 2: 'Level 2 · Offices',
  3: 'Level 3 · Apartments', 4: 'Level 4 · Penthouse',
};

export const FLOOR_SHORT: Record<number, string> = { 0: 'G', 1: 'L1', 2: 'L2', 3: 'L3', 4: 'L4' };

export const floorName = (f: number | null | undefined) => (f === null || f === undefined ? '' : FLOOR_NAMES[f] ?? `Floor ${f}`);
