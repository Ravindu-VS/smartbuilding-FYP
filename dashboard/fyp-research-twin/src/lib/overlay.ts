// Room colours for the 3D overlays and their legends (one function for both, so the
// legend always matches the building). Values come from the streamed room state.
import type { RoomState } from '../types/building';
import type { Overlay } from '../store/useBuildingStore';
import { isNum } from './format';

type RGB = [number, number, number];
const hex = (h: string): RGB => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
const toHex = (c: RGB) => '#' + c.map((v) => Math.round(v).toString(16).padStart(2, '0')).join('');
const mix = (a: string, b: string, t: number) => {
  const A = hex(a), B = hex(b), k = Math.max(0, Math.min(1, t));
  return toHex([A[0] + (B[0] - A[0]) * k, A[1] + (B[1] - A[1]) * k, A[2] + (B[2] - A[2]) * k]);
};

const COOL = '#3987e5';
const WARM = '#e66767';
const MID = '#475569';
const NODATA = '#1e293b';

function diverging(v: number, mid: number, span: number) {
  const t = (v - mid) / span;
  return t < 0 ? mix(MID, COOL, -t) : mix(MID, WARM, t);
}

function sequential(v: number, max: number) {
  const t = Math.max(0, Math.min(1, v / max));
  return t < 0.5 ? mix('#1e293b', '#3987e5', t * 2) : mix('#3987e5', '#cde2fb', (t - 0.5) * 2);
}

export const ESTIMATE_COLORS = { tp: '#3987e5', tn: '#475569', fp: '#d95926', fn: '#e66767' };

export function roomColor(r: RoomState, overlay: Overlay): string | null {
  if (overlay === 'none') return null;
  if (overlay === 'comfort') {
    const p = r.comfort?.pmv;
    return isNum(p) ? diverging(p, 0, 1.5) : NODATA;
  }
  if (overlay === 'temperature') {
    const t = r.sensors?.Temperature;
    return isNum(t) ? diverging(t, 25, 4) : NODATA;
  }
  if (overlay === 'power') {
    const w = r.energy?.power_w ?? r.energy?.measured_power_watts;
    const a = r.area_m2;
    return isNum(w) && isNum(a) && a > 0 ? sequential(w / a, 60) : NODATA;
  }
  if (overlay === 'estimate') {
    const truth = r.ground_truth?.true_occupancy;
    const p = r.ai?.occupancy_probability;
    if (!isNum(truth) || !isNum(p)) return NODATA;
    const occ = truth > 0, pred = p >= 0.5;
    return occ && pred ? ESTIMATE_COLORS.tp : !occ && !pred ? ESTIMATE_COLORS.tn : pred ? ESTIMATE_COLORS.fp : ESTIMATE_COLORS.fn;
  }
  return null;
}

export interface LegendSpec {
  title: string;
  note: string;
  stops?: { color: string; label: string }[];
  gradient?: { from: string; mid?: string; to: string; labels: [string, string, string] };
}

export const LEGENDS: Record<Exclude<Overlay, 'none'>, LegendSpec> = {
  comfort: {
    title: 'Thermal comfort (PMV, ISO 7730)',
    note: 'Simulator truth: air and radiant temperature, humidity, activity of the room type, clo 0.5. Comfortable: |PMV| ≤ 0.5.',
    gradient: { from: diverging(-1.5, 0, 1.5), mid: MID, to: diverging(1.5, 0, 1.5), labels: ['−1.5 cool', '0 neutral', '+1.5 warm'] },
  },
  temperature: {
    title: 'Air temperature (sensor reading)',
    note: 'Simulated sensor with noise and lag; Office A from the ESP32 when connected.',
    gradient: { from: diverging(21, 25, 4), mid: MID, to: diverging(29, 25, 4), labels: ['21 °C', '25 °C', '29 °C'] },
  },
  power: {
    title: 'Electric power density (W/m²)',
    note: 'AC + fans + lighting + plug loads from the physics model. Office A: power measured on the board.',
    gradient: { from: sequential(0, 60), mid: sequential(30, 60), to: sequential(60, 60), labels: ['0', '30', '60 W/m²'] },
  },
  estimate: {
    title: 'AI estimate vs simulator truth',
    note: 'Live check of the PIR+CO₂ estimator (P ≥ 0.5 = occupied) against the simulated head count.',
    stops: [
      { color: ESTIMATE_COLORS.tp, label: 'Occupied, detected' },
      { color: ESTIMATE_COLORS.tn, label: 'Empty, detected' },
      { color: ESTIMATE_COLORS.fp, label: 'False alarm' },
      { color: ESTIMATE_COLORS.fn, label: 'Missed people' },
    ],
  },
};
