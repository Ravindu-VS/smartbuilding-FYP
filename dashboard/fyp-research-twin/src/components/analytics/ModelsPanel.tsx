'use client';

// Models & data: what the running system uses, how the candidates compare in shadow mode, drift,
// and where every number comes from. All values come from /api/models and /api/provenance.
import React, { useEffect, useState } from 'react';
import { api } from '../../lib/api';
import { fx } from '../../lib/format';
import { useBuildingStore } from '../../store/useBuildingStore';
import type { ModelsStatus, ProvenanceStatus } from '../../types/building';

const pct = (v: number | null | undefined) => (v == null ? '—' : `${(v * 100).toFixed(1)} %`);

function Box({ title, children, testId }: { title: string; children: React.ReactNode; testId?: string }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-2.5 min-w-0" data-testid={testId}>
      <div className="text-[10.5px] uppercase tracking-wide text-slate-400 font-semibold mb-1.5">{title}</div>
      {children}
    </div>
  );
}

export default function ModelsPanel() {
  const live = useBuildingStore((s) => s.link.connected);
  const [m, setM] = useState<ModelsStatus | null>(null);
  const [p, setP] = useState<ProvenanceStatus | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!live) return;
    let stop = false;
    const load = () => Promise.all([api.models(), api.provenance()])
      .then(([a, b]) => { if (!stop) { setM(a); setP(b); setErr(null); } })
      .catch((e) => { if (!stop) setErr(String(e)); });
    load();
    const id = setInterval(load, 15000);
    return () => { stop = true; clearInterval(id); };
  }, [live]);

  if (!live) return <div className="p-3 text-[12px] text-slate-500">Edge brain not connected.</div>;
  if (err) return <div className="p-3 text-[12px] text-red-300" data-testid="models-error">Could not read model status: {err}</div>;
  if (!m || !p) return <div className="p-3 text-[12px] text-slate-500">Loading…</div>;
  const sh = m.live?.shadow;
  const th = m.live?.thermal;
  const drift = m.live?.drift.real_room_inputs_vs_occupancy_rf_training;
  const sim = p.rooms.filter((r) => r.source === 'simulated').length;
  const hw = p.rooms.filter((r) => r.source === 'hardware');
  return (
    <div className="h-full overflow-y-auto p-2 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-2 text-[11px] text-slate-300" data-testid="models-panel">
      <Box title="Models in the running system" testId="models-live">
        {m.live ? m.live.models.map((x) => (
          <div key={x.task} className="flex items-center justify-between gap-2 py-0.5">
            <span className="truncate">{x.task}</span>
            <span className={`font-mono text-[10px] px-1 rounded border ${x.loaded ? (x.role === 'shadow' ? 'border-violet-700 text-violet-300' : 'border-emerald-700 text-emerald-300') : 'border-red-700 text-red-300'}`}
              title={x.error ?? `trained on ${x.provenance_of_training_data} data, ${x.trained_utc}`}>
              {x.loaded ? `${x.version} · ${x.role}` : 'not loaded'}
            </span>
          </div>
        )) : <div className="text-red-300">{m.live_error}</div>}
        <div className="text-[10px] text-slate-500 mt-1">Random Forest in use: {m.random_forest_source ?? '—'}</div>
        <div className="text-[10px] text-slate-500">Controllers: {m.controllers.map((c) => `${c.id}${c.available ? '' : ' (not approved)'}`).join(', ')}</div>
      </Box>
      <Box title="Shadow mode: learned fusion vs live estimator" testId="models-shadow">
        {sh && sh.compared_room_steps > 0 ? (
          <>
            <table className="w-full text-[10.5px]"><thead><tr className="text-slate-500"><th className="text-left font-normal">vs simulated truth</th><th>F1</th><th>precision</th><th>recall</th></tr></thead>
              <tbody>
                <tr><td>candidate {sh.version}</td><td className="text-center">{fx(sh.candidate_vs_truth.f1, 3)}</td><td className="text-center">{fx(sh.candidate_vs_truth.precision, 3)}</td><td className="text-center">{fx(sh.candidate_vs_truth.recall, 3)}</td></tr>
                <tr><td>live (rule-based)</td><td className="text-center">{fx(sh.active_vs_truth.f1, 3)}</td><td className="text-center">{fx(sh.active_vs_truth.precision, 3)}</td><td className="text-center">{fx(sh.active_vs_truth.recall, 3)}</td></tr>
              </tbody></table>
            <div className="text-[10px] text-slate-500 mt-1">agreement {pct(sh.agreement_with_active)} over {sh.compared_room_steps.toLocaleString()} room-minutes. {sh.note}.</div>
          </>
        ) : <div className="text-slate-500">No comparisons yet (starts when measurement runs).</div>}
      </Box>
      <Box title="Forecast accuracy and input drift" testId="models-thermal">
        <div>30-min temperature forecast ({th?.version ?? '—'}): live MAE <b className="text-white">{fx(th?.live_mae_c, 2, ' °C')}</b> over {th?.scored ?? 0} forecasts</div>
        <div className="text-[10px] text-slate-500">{th?.basis}</div>
        <div className="mt-1.5">Room {hw[0]?.room_number ?? 101} inputs vs RF training data: <b className="text-white">{drift?.status ?? '—'}</b>{drift?.max_psi != null ? ` (max PSI ${fx(drift.max_psi, 2)}, ${drift.rows} readings)` : ''}</div>
        <div className="text-[10px] text-slate-500">PSI &lt; 0.10 stable · 0.10–0.25 moderate · &gt; 0.25 significant. Drift is a warning; it never changes control.</div>
      </Box>
      <Box title="Where the numbers come from" testId="models-provenance">
        <div>{sim} rooms <b>simulated</b> (synthetic) · Room {hw.map((h) => h.room_number).join(', ')} <b>measured</b> only while its board is connected</div>
        <div className="text-[10px] text-slate-500">{p.weather}</div>
        <div className="mt-1">Registry: {Object.entries(m.registry).map(([t, e]) => `${t} ${e.active ?? 'none active'}`).join(' · ')}</div>
        <div className="mt-1 text-[10px] text-slate-500">Datasets: {Object.values(p.datasets).map((d) => `${d.name} (${d.licence.split(' (')[0]})`).join('; ')}</div>
        {p.store && <div className="text-[10px] text-slate-500">Store schema v{p.store.schema_version}: {Object.entries(p.store.tables).map(([k, v]) => `${k} ${v}`).join(', ')}</div>}
      </Box>
    </div>
  );
}
