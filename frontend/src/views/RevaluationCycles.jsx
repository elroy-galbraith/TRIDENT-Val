import React, { useEffect, useState } from 'react'
import {
  Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { api, pct, usd } from '../api.js'
import { Spinner, StatusBadge } from '../components/shared.jsx'
import { logger } from '../logger.js'

const bucketColor = { '<60%': '#2E7D4F', '60-80%': '#C77D0A', '>80%': '#B3352C' }

const SCENARIO_OPTIONS = [
  { value: 'organic', label: 'Standard Quarterly Cycle (auto market drift)' },
  { value: 'broad_stress', label: 'Broad Market Stress (uniform shock)' },
  { value: 'targeted_stress', label: 'Concentrated Neighborhood Shock' },
  { value: 'custom', label: 'Custom (per-neighborhood)' },
]

const FLAG_REASON_LABELS = {
  value_drop_gt_10pct: 'Value dropped >10%',
  ltv_crossed_80: 'LTV newly crossed 80%',
  ltv_remains_gte_80: 'LTV remains ≥80%',
}

function flagLabels(reasons) {
  return (reasons || []).map((r) => FLAG_REASON_LABELS[r] || r).join(', ')
}

function Metric({ label, value, accent }) {
  return (
    <div className="border border-line rounded-sm p-4">
      <div className="label">{label}</div>
      <div className={`figure text-2xl font-semibold mt-1 ${accent || 'text-tealdeep'}`}>{value}</div>
    </div>
  )
}

function RunForm({ neighborhoods, onRun, onCancel }) {
  const [scenarioType, setScenarioType] = useState('organic')
  const [asOfDate, setAsOfDate] = useState(() => new Date().toISOString().slice(0, 10))
  const [scenarioName, setScenarioName] = useState('')
  const [broadShockPct, setBroadShockPct] = useState(-10)
  const [targetNeighborhood, setTargetNeighborhood] = useState(neighborhoods[0] || '')
  const [targetShockPct, setTargetShockPct] = useState(-15)
  const [customAdjustments, setCustomAdjustments] = useState({})
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  // neighborhoods loads asynchronously in the parent and can still be [] when this form first
  // mounts, in which case the useState initializer above never sees a real default — sync it
  // once the list arrives so a submit without touching the dropdown doesn't send an empty value.
  useEffect(() => {
    if (neighborhoods.length > 0 && !targetNeighborhood) setTargetNeighborhood(neighborhoods[0])
  }, [neighborhoods, targetNeighborhood])

  const submit = async () => {
    setSubmitting(true)
    setError(null)
    const body = {
      as_of_date: asOfDate, scenario_type: scenarioType,
      scenario_name: scenarioName || undefined, notes,
    }
    if (scenarioType === 'broad_stress') body.broad_shock_pct = broadShockPct / 100
    if (scenarioType === 'targeted_stress') {
      body.target_neighborhood = targetNeighborhood
      body.target_shock_pct = targetShockPct / 100
    }
    if (scenarioType === 'custom') {
      body.custom_adjustments = Object.fromEntries(
        Object.entries(customAdjustments)
          .filter(([, v]) => v !== '' && v != null && !isNaN(Number(v)))
          .map(([k, v]) => [k, Number(v) / 100]))
    }
    try {
      const r = await api.runRevaluation(body)
      logger.track('revaluations', `Ran revaluation cycle #${r.run_id} (${r.scenario_name}).`, r)
      onRun(r.run_id)
    } catch (e) {
      setError(e.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="card p-5 space-y-4">
      <div className="label">New Revaluation Cycle</div>
      <div className="grid sm:grid-cols-2 gap-4">
        <label className="text-sm space-y-1 block">
          <span className="text-inkmute">As-of date</span>
          <input type="date" value={asOfDate} onChange={(e) => setAsOfDate(e.target.value)}
            className="w-full border border-line rounded-sm px-2 py-1.5 bg-white" />
        </label>
        <label className="text-sm space-y-1 block">
          <span className="text-inkmute">Scenario</span>
          <select value={scenarioType} onChange={(e) => setScenarioType(e.target.value)}
            className="w-full border border-line rounded-sm px-2 py-1.5 bg-white">
            {SCENARIO_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </label>
      </div>

      {scenarioType === 'broad_stress' && (
        <label className="text-sm space-y-1 block max-w-xs">
          <span className="text-inkmute">Uniform shock, all neighborhoods (%)</span>
          <input type="number" step="0.5" value={broadShockPct}
            onChange={(e) => setBroadShockPct(+e.target.value)}
            className="w-full border border-line rounded-sm px-2 py-1.5" />
        </label>
      )}

      {scenarioType === 'targeted_stress' && (
        <div className="grid sm:grid-cols-2 gap-4 max-w-lg">
          <label className="text-sm space-y-1 block">
            <span className="text-inkmute">Target neighborhood</span>
            <select value={targetNeighborhood} onChange={(e) => setTargetNeighborhood(e.target.value)}
              className="w-full border border-line rounded-sm px-2 py-1.5 bg-white">
              {neighborhoods.map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
          <label className="text-sm space-y-1 block">
            <span className="text-inkmute">Shock (%)</span>
            <input type="number" step="0.5" value={targetShockPct}
              onChange={(e) => setTargetShockPct(+e.target.value)}
              className="w-full border border-line rounded-sm px-2 py-1.5" />
          </label>
        </div>
      )}

      {scenarioType === 'custom' && (
        <div>
          <div className="text-xs text-inkmute mb-2">Per-neighborhood adjustment (%), blank = 0%</div>
          <div className="grid sm:grid-cols-3 gap-2 max-h-56 overflow-auto pr-1">
            {neighborhoods.map((n) => (
              <label key={n} className="text-xs flex items-center justify-between gap-2 border border-line rounded-sm px-2 py-1">
                <span>{n}</span>
                <input type="number" step="0.5" value={customAdjustments[n] ?? ''}
                  onChange={(e) => setCustomAdjustments((c) => ({ ...c, [n]: e.target.value }))}
                  className="w-16 border border-line rounded-sm px-1 py-0.5 text-right" />
              </label>
            ))}
          </div>
        </div>
      )}

      <div className="grid sm:grid-cols-2 gap-4">
        <label className="text-sm space-y-1 block">
          <span className="text-inkmute">Scenario name (optional)</span>
          <input value={scenarioName} onChange={(e) => setScenarioName(e.target.value)}
            placeholder="Defaults to a name per scenario type"
            className="w-full border border-line rounded-sm px-2 py-1.5" />
        </label>
        <label className="text-sm space-y-1 block">
          <span className="text-inkmute">Notes (optional)</span>
          <input value={notes} onChange={(e) => setNotes(e.target.value)}
            className="w-full border border-line rounded-sm px-2 py-1.5" />
        </label>
      </div>

      {error && <div className="text-sm text-flag">{error}</div>}

      <div className="flex gap-2">
        <button onClick={submit} disabled={submitting}
          className="bg-ink hover:bg-black text-white text-sm font-medium px-4 py-2 rounded-sm disabled:opacity-50">
          {submitting ? 'Running cycle…' : 'Run Cycle'}
        </button>
        <button onClick={onCancel} disabled={submitting}
          className="px-4 py-2 text-sm border border-line rounded-sm">
          Cancel
        </button>
      </div>
    </div>
  )
}

function RunDetail({ runId, onOpen }) {
  const [detail, setDetail] = useState(null)
  const [flagged, setFlagged] = useState(null)
  const [page, setPage] = useState(1)
  const [err, setErr] = useState(null)

  useEffect(() => {
    setDetail(null)
    setPage(1)
    api.revaluation(runId).then(setDetail).catch((e) => setErr(e.message))
  }, [runId])

  useEffect(() => {
    setFlagged(null)
    api.revaluationFlagged(runId, { page, page_size: 10 }).then(setFlagged).catch((e) => setErr(e.message))
  }, [runId, page])

  if (err) return <div className="text-sm text-flag py-4">{err}</div>
  if (!detail) return <Spinner label="Loading cycle detail…" />

  const adjustments = Object.entries(detail.index_adjustments)
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <div className="label">Cycle #{detail.run_id} · {detail.scenario_name}</div>
          <div className="text-xs text-inkmute mt-1">
            As of {detail.as_of_date?.slice(0, 10)} · {detail.asset_count.toLocaleString()} assets revalued · run by {detail.created_by || '—'}
          </div>
        </div>
        <a href={api.revaluationReportUrl(detail.run_id)} target="_blank" rel="noopener noreferrer"
          onClick={() => logger.track('revaluations', `Exported cycle report for run ${detail.run_id}.`)}
          aria-label="Export revaluation cycle report as PDF"
          className="text-sm text-teal hover:underline">
          Export Cycle Report ↗
        </a>
      </div>

      <div className="grid sm:grid-cols-3 gap-4">
        <Metric label="Assets Revalued" value={detail.asset_count.toLocaleString()} />
        <Metric label="Avg. Value Movement" accent={detail.avg_value_delta_pct < 0 ? 'text-flag' : 'text-ok'}
          value={`${detail.avg_value_delta_pct >= 0 ? '+' : ''}${pct(detail.avg_value_delta_pct)}`} />
        <Metric label="Newly Flagged" accent="text-flag" value={detail.flagged_count.toLocaleString()} />
      </div>

      <div className="card p-5">
        <div className="label mb-2">Market Index Adjustments Applied</div>
        <div className="overflow-auto max-h-64">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-inkmute border-b border-line">
                <th className="py-1.5 pr-3">Neighborhood</th><th className="py-1.5">Adjustment</th>
              </tr>
            </thead>
            <tbody>
              {adjustments.map(([n, v]) => (
                <tr key={n} className="border-b border-line last:border-0">
                  <td className="py-1.5 pr-3">{n}</td>
                  <td className={`py-1.5 figure font-semibold ${v < 0 ? 'text-flag' : v > 0 ? 'text-ok' : 'text-inkmute'}`}>
                    {v >= 0 ? '+' : ''}{pct(v)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="grid lg:grid-cols-2 gap-4">
        <div className="card p-5">
          <div className="label mb-1">LTV Distribution — Before</div>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={detail.ltv_distribution_before}>
              <CartesianGrid strokeDasharray="3 3" stroke="#DDE3E0" vertical={false} />
              <XAxis dataKey="bucket" tick={{ fontSize: 12, fill: '#5B6B77' }} />
              <YAxis tick={{ fontSize: 12, fill: '#5B6B77' }} />
              <Tooltip formatter={(v) => [v.toLocaleString(), 'Assets']} />
              <Bar dataKey="count" radius={[3, 3, 0, 0]}>
                {detail.ltv_distribution_before.map((b) => <Cell key={b.bucket} fill={bucketColor[b.bucket]} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="card p-5">
          <div className="label mb-1">LTV Distribution — After</div>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={detail.ltv_distribution_after}>
              <CartesianGrid strokeDasharray="3 3" stroke="#DDE3E0" vertical={false} />
              <XAxis dataKey="bucket" tick={{ fontSize: 12, fill: '#5B6B77' }} />
              <YAxis tick={{ fontSize: 12, fill: '#5B6B77' }} />
              <Tooltip formatter={(v) => [v.toLocaleString(), 'Assets']} />
              <Bar dataKey="count" radius={[3, 3, 0, 0]}>
                {detail.ltv_distribution_after.map((b) => <Cell key={b.bucket} fill={bucketColor[b.bucket]} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="card p-5">
        <div className="label mb-2">Largest Movers</div>
        <div className="overflow-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-inkmute border-b border-line">
                <th className="py-1.5 pr-3">PID</th><th className="py-1.5 pr-3">Neighborhood</th>
                <th className="py-1.5 pr-3">Prior Value</th><th className="py-1.5 pr-3">New Value</th>
                <th className="py-1.5 pr-3">Movement</th><th className="py-1.5">Flags</th>
              </tr>
            </thead>
            <tbody>
              {detail.top_movers.map((m) => (
                <tr key={m.pid} onClick={() => onOpen && onOpen(m.pid)}
                  className="border-b border-line last:border-0 cursor-pointer hover:bg-paper">
                  <td className="py-1.5 pr-3 figure">{m.pid}</td>
                  <td className="py-1.5 pr-3">{m.neighborhood || '—'}</td>
                  <td className="py-1.5 pr-3 figure">{usd(m.prior_value)}</td>
                  <td className="py-1.5 pr-3 figure">{usd(m.new_value)}</td>
                  <td className={`py-1.5 pr-3 figure font-semibold ${m.value_delta_pct < 0 ? 'text-flag' : 'text-ok'}`}>
                    {m.value_delta_pct >= 0 ? '+' : ''}{pct(m.value_delta_pct)}
                  </td>
                  <td className="py-1.5 text-xs">{m.flagged ? flagLabels(m.flag_reasons) : ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card p-5">
        <div className="flex items-center justify-between mb-2">
          <div>
            <div className="label">Triage Queue Refilled This Cycle</div>
            <div className="text-xs text-inkmute mt-1">
              {flagged ? `${flagged.total.toLocaleString()} assets` : '…'} flagged for a value drop
              beyond 10% or an LTV breach at/above 80% — each requires an underwriter decision.
            </div>
          </div>
        </div>
        {!flagged ? <Spinner label="Loading queue…" /> : flagged.items.length === 0 ? (
          <div className="text-sm text-inkmute py-6 text-center">
            No assets were flagged by this cycle.
          </div>
        ) : (
          <>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-inkmute border-b border-line">
                  <th className="py-1.5 pr-3">PID</th><th className="py-1.5 pr-3">Neighborhood</th>
                  <th className="py-1.5 pr-3">Movement</th><th className="py-1.5 pr-3">New LTV</th>
                  <th className="py-1.5 pr-3">Reason</th><th className="py-1.5">Audit status</th>
                </tr>
              </thead>
              <tbody>
                {flagged.items.map((it) => (
                  <tr key={it.pid} onClick={() => onOpen && onOpen(it.pid)}
                    className="border-b border-line last:border-0 cursor-pointer hover:bg-paper">
                    <td className="py-1.5 pr-3 figure">{it.pid}</td>
                    <td className="py-1.5 pr-3">{it.neighborhood}</td>
                    <td className={`py-1.5 pr-3 figure font-semibold ${it.value_delta_pct < 0 ? 'text-flag' : 'text-ok'}`}>
                      {it.value_delta_pct >= 0 ? '+' : ''}{pct(it.value_delta_pct)}
                    </td>
                    <td className="py-1.5 pr-3 figure">{pct(it.new_ltv)}</td>
                    <td className="py-1.5 pr-3 text-xs">{flagLabels(it.flag_reasons)}</td>
                    <td className="py-1.5"><StatusBadge status={it.audit_status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="flex justify-between items-center mt-3 text-sm">
              <button disabled={page <= 1} onClick={() => setPage((p) => p - 1)}
                className="px-3 py-1 border border-line rounded-sm disabled:opacity-40">← Prev</button>
              <span className="text-inkmute">
                Page {flagged.page} of {Math.max(1, Math.ceil(flagged.total / flagged.page_size))}
              </span>
              <button disabled={page * flagged.page_size >= flagged.total} onClick={() => setPage((p) => p + 1)}
                className="px-3 py-1 border border-line rounded-sm disabled:opacity-40">Next →</button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

export default function RevaluationCycles({ user, onOpen }) {
  const [runs, setRuns] = useState(null)
  const [neighborhoods, setNeighborhoods] = useState([])
  const [showForm, setShowForm] = useState(false)
  const [selectedRun, setSelectedRun] = useState(null)
  const [err, setErr] = useState(null)

  const canRun = user?.role === 'Underwriter' || user?.role === 'Admin'

  useEffect(() => {
    api.revaluations().then((d) => {
      setRuns(d.items)
      setSelectedRun((prev) => prev ?? d.items[0]?.run_id ?? null)
    }).catch((e) => setErr(e.message))
  }, [])

  useEffect(() => { api.filters().then((f) => setNeighborhoods(f.neighborhoods)) }, [])

  const handleRun = (runId) => {
    setShowForm(false)
    setSelectedRun(runId)
    api.revaluations().then((d) => setRuns(d.items)).catch((e) => setErr(e.message))
  }

  if (err) return <div className="py-16 text-center text-flag text-sm">{err}</div>
  if (!runs) return <Spinner label="Loading revaluation cycles…" />

  return (
    <div className="space-y-4">
      <div className="card p-6">
        <div className="label">Collateral Monitoring</div>
        <h1 className="text-2xl font-semibold mt-1">Revaluation Cycles</h1>
        <p className="text-sm text-inkmute mt-3 max-w-3xl leading-relaxed">
          Run a periodic collateral revaluation: neighborhood-level market index adjustments are
          applied to every asset's currently booked AVM value, LTV is refreshed, and assets whose
          value dropped sharply or whose LTV breached 80% flow straight into the triage queue —
          the operating loop between full model-backed revaluations.
        </p>
        {canRun && !showForm && (
          <button onClick={() => setShowForm(true)}
            className="mt-4 bg-ink hover:bg-black text-white text-sm font-medium px-4 py-2 rounded-sm">
            Run New Cycle
          </button>
        )}
      </div>

      {showForm && (
        <RunForm neighborhoods={neighborhoods} onRun={handleRun} onCancel={() => setShowForm(false)} />
      )}

      <div className="card p-5">
        <div className="label mb-2">Cycle History</div>
        {runs.length === 0 ? (
          <div className="text-sm text-inkmute py-6 text-center">
            No revaluation cycles have been run yet.
          </div>
        ) : (
          <div className="overflow-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-inkmute border-b border-line">
                  <th className="py-1.5 pr-3">Cycle</th><th className="py-1.5 pr-3">As of</th>
                  <th className="py-1.5 pr-3">Scenario</th><th className="py-1.5 pr-3">Assets</th>
                  <th className="py-1.5 pr-3">Avg. movement</th><th className="py-1.5 pr-3">Flagged</th>
                  <th className="py-1.5">Run by</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.run_id} onClick={() => setSelectedRun(r.run_id)}
                    className={`border-b border-line last:border-0 cursor-pointer hover:bg-paper ${
                      selectedRun === r.run_id ? 'bg-paper' : ''}`}>
                    <td className="py-1.5 pr-3 figure">#{r.run_id}</td>
                    <td className="py-1.5 pr-3">{r.as_of_date?.slice(0, 10)}</td>
                    <td className="py-1.5 pr-3">{r.scenario_name}</td>
                    <td className="py-1.5 pr-3 figure">{r.asset_count.toLocaleString()}</td>
                    <td className={`py-1.5 pr-3 figure font-semibold ${r.avg_value_delta_pct < 0 ? 'text-flag' : 'text-ok'}`}>
                      {r.avg_value_delta_pct >= 0 ? '+' : ''}{pct(r.avg_value_delta_pct)}
                    </td>
                    <td className="py-1.5 pr-3 figure">{r.flagged_count.toLocaleString()}</td>
                    <td className="py-1.5">{r.created_by || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {selectedRun && <RunDetail key={selectedRun} runId={selectedRun} onOpen={onOpen} />}
    </div>
  )
}
