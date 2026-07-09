import React, { useEffect, useState } from 'react'
import {
  CartesianGrid, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis,
} from 'recharts'
import { api, pct, usd } from '../api.js'
import { ModelStatusBadge, Spinner, StatusBadge } from '../components/shared.jsx'
import { logger } from '../logger.js'
import { setChartSummary } from '../copilot.js'

const THRESHOLDS = [0.05, 0.10, 0.20, 0.30]

function Metric({ label, value }) {
  return (
    <div className="border border-line rounded-sm p-4">
      <div className="label">{label}</div>
      <div className="figure text-2xl font-semibold mt-1 text-tealdeep">{value}</div>
    </div>
  )
}

export default function ModelCompare({ user, onOpen }) {
  const [models, setModels] = useState(null)
  const [championId, setChampionId] = useState(null)
  const [challengerId, setChallengerId] = useState(null)
  const [compare, setCompare] = useState(null)
  const [threshold, setThreshold] = useState(0.10)
  const [page, setPage] = useState(1)
  const [disagreements, setDisagreements] = useState(null)
  const [err, setErr] = useState(null)
  const [promoting, setPromoting] = useState(false)

  const loadRegistry = () => {
    api.models().then((m) => {
      setModels(m.items)
      setChampionId(m.items.find((x) => x.status === 'Champion')?.id ?? null)
      setChallengerId(m.items.find((x) => x.status === 'Challenger')?.id ?? null)
    }).catch((e) => setErr(e.message))
  }

  useEffect(loadRegistry, [])

  useEffect(() => {
    if (!championId || !challengerId) return
    let active = true
    setCompare(null)
    api.compareModels({ champion: championId, challenger: challengerId })
      .then((d) => {
        if (!active) return
        setCompare(d)
        setChartSummary('model_compare_scatter', d.points.slice(0, 200))
      })
      .catch((e) => { if (active) setErr(e.message) })
    return () => { active = false }
  }, [championId, challengerId])

  useEffect(() => {
    if (!championId || !challengerId) return
    let active = true
    setDisagreements(null)
    api.disagreements({ champion: championId, challenger: challengerId, threshold, page, page_size: 10 })
      .then((d) => { if (active) setDisagreements(d) })
      .catch((e) => { if (active) setErr(e.message) })
    return () => { active = false }
  }, [championId, challengerId, threshold, page])

  const promote = async () => {
    const target = models.find((m) => m.id === challengerId)
    const rationale = window.prompt(
      `Promote "${target.name}" to champion? This re-books the whole portfolio's AVM value ` +
      `from this model. Enter a rationale for the audit ledger:`)
    if (!rationale) return
    setPromoting(true)
    try {
      const r = await api.promoteModel(challengerId, rationale)
      logger.track('model_compare', `Promoted model '${challengerId}' to champion.`,
        { previous_champion: r.previous_champion, assets_rebooked: r.assets_rebooked })
      loadRegistry()
    } catch (e) {
      window.alert(`Promotion failed: ${e.message}`)
    } finally {
      setPromoting(false)
    }
  }

  if (err) return <div className="py-16 text-center text-flag text-sm">{err}</div>
  if (!models) return <Spinner label="Loading model registry…" />
  if (!championId || !challengerId) {
    return (
      <div className="card p-6 text-sm text-inkmute">
        Need at least one champion and one challenger registered to compare. Run
        scripts/train_model.py and scripts/seed_db.py to register more models.
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="card p-6">
        <div className="label">Champion vs. Challenger</div>
        <h1 className="text-2xl font-semibold mt-1">Model Comparison &amp; Disagreement Triage</h1>
        <p className="text-sm text-inkmute mt-3 max-w-3xl leading-relaxed">
          The champion values every asset in the portfolio; the challenger scores the same
          portfolio in shadow, never booked. Where the two disagree beyond a threshold, that's a
          signal worth a human look — the triage queue below, not a vote on which model is
          "right."
        </p>
        {compare && (
          <div className="flex gap-3 mt-4 items-center flex-wrap text-sm">
            <div className="flex items-center gap-2">
              <ModelStatusBadge status="Champion" />
              <span className="font-medium">{compare.champion.name}</span>
            </div>
            <span className="text-inkmute">vs.</span>
            <div className="flex items-center gap-2">
              <ModelStatusBadge status="Challenger" />
              <span className="font-medium">{compare.challenger.name}</span>
            </div>
            {user?.role === 'Admin' && (
              <button onClick={promote} disabled={promoting}
                className="ml-auto bg-ink hover:bg-black text-white text-sm font-medium px-4 py-2 rounded-sm disabled:opacity-50">
                {promoting ? 'Promoting…' : 'Promote challenger to champion'}
              </button>
            )}
          </div>
        )}
      </div>

      {!compare ? <Spinner label="Comparing models…" /> : (
        <>
          <div className="grid sm:grid-cols-4 gap-4">
            <Metric label="Champion MAPE" value={pct(compare.overall.mape_champion)} />
            <Metric label="Challenger MAPE" value={pct(compare.overall.mape_challenger)} />
            <Metric label="Mean divergence" value={pct(compare.overall.mean_abs_divergence_pct)} />
            <Metric label="Agree within 10%" value={pct(compare.overall.agreement_within_10pct_share)} />
          </div>

          <div className="card p-5">
            <div className="label mb-1">Agreement Scatter</div>
            <div className="text-xs text-inkmute mb-3">
              Each point is one property. Points on the diagonal agree; distance from it is
              divergence.
            </div>
            <ResponsiveContainer width="100%" height={360}>
              <ScatterChart margin={{ top: 8, right: 24, bottom: 8, left: 8 }}>
                <CartesianGrid stroke="#DDE3E0" />
                <XAxis type="number" dataKey="champion_value" name="Champion"
                  tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 11, fill: '#5B6B77' }} />
                <YAxis type="number" dataKey="challenger_value" name="Challenger"
                  tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 11, fill: '#5B6B77' }} />
                <Tooltip formatter={(v, n) => [usd(v), n]} labelFormatter={() => ''} />
                <Scatter data={compare.points} fill="#0E7C7B" fillOpacity={0.45} />
              </ScatterChart>
            </ResponsiveContainer>
          </div>

          <div className="card p-5">
            <div className="label mb-2">Per-Neighborhood Error &amp; Bias</div>
            <div className="overflow-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-inkmute border-b border-line">
                    <th className="py-1.5 pr-3">Neighborhood</th>
                    <th className="py-1.5 pr-3">n</th>
                    <th className="py-1.5 pr-3">Champion MAPE</th>
                    <th className="py-1.5 pr-3">Challenger MAPE</th>
                    <th className="py-1.5 pr-3">Champion bias</th>
                    <th className="py-1.5">Challenger bias</th>
                  </tr>
                </thead>
                <tbody>
                  {compare.segment_breakdown.map((s) => (
                    <tr key={s.neighborhood} className="border-b border-line last:border-0">
                      <td className="py-1.5 pr-3">{s.neighborhood}</td>
                      <td className="py-1.5 pr-3 figure">{s.n}</td>
                      <td className="py-1.5 pr-3 figure">{pct(s.mape_champion)}</td>
                      <td className="py-1.5 pr-3 figure">{pct(s.mape_challenger)}</td>
                      <td className="py-1.5 pr-3 figure">{s.bias_champion >= 0 ? '+' : ''}{pct(s.bias_champion)}</td>
                      <td className="py-1.5 figure">{s.bias_challenger >= 0 ? '+' : ''}{pct(s.bias_challenger)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="card p-5">
            <div className="flex items-center justify-between flex-wrap gap-2 mb-2">
              <div>
                <div className="label">Disagreement Queue</div>
                <div className="text-xs text-inkmute mt-1">
                  {disagreements ? `${disagreements.total.toLocaleString()} assets` : '…'} diverge
                  beyond the threshold — this is where a disagreement becomes a triage decision.
                </div>
              </div>
              <div className="flex items-center gap-2 text-sm">
                <span className="text-inkmute">Threshold</span>
                <select value={threshold} onChange={(e) => { setThreshold(+e.target.value); setPage(1) }}
                  className="border border-line rounded-sm px-2 py-1 text-sm bg-white">
                  {THRESHOLDS.map((t) => <option key={t} value={t}>{pct(t, 0)}</option>)}
                </select>
              </div>
            </div>
            {!disagreements ? <Spinner label="Loading queue…" /> : disagreements.items.length === 0 ? (
              <div className="text-sm text-inkmute py-6 text-center">
                No properties diverge beyond {pct(threshold, 0)}.
              </div>
            ) : (
              <>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-inkmute border-b border-line">
                      <th className="py-1.5 pr-3">PID</th>
                      <th className="py-1.5 pr-3">Neighborhood</th>
                      <th className="py-1.5 pr-3">Champion</th>
                      <th className="py-1.5 pr-3">Challenger</th>
                      <th className="py-1.5 pr-3">Divergence</th>
                      <th className="py-1.5">Audit status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {disagreements.items.map((it) => (
                      <tr key={it.pid} onClick={() => onOpen && onOpen(it.pid)}
                        className="border-b border-line last:border-0 cursor-pointer hover:bg-paper">
                        <td className="py-1.5 pr-3 figure">{it.pid}</td>
                        <td className="py-1.5 pr-3">{it.neighborhood}</td>
                        <td className="py-1.5 pr-3 figure">{usd(it.champion_value)}</td>
                        <td className="py-1.5 pr-3 figure">{usd(it.challenger_value)}</td>
                        <td className={`py-1.5 pr-3 figure font-semibold ${
                          Math.abs(it.divergence_pct) > 0.2 ? 'text-flag' : 'text-amber'}`}>
                          {it.divergence_pct >= 0 ? '+' : ''}{pct(it.divergence_pct)}
                        </td>
                        <td className="py-1.5"><StatusBadge status={it.audit_status} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div className="flex justify-between items-center mt-3 text-sm">
                  <button disabled={page <= 1} onClick={() => setPage((p) => p - 1)}
                    className="px-3 py-1 border border-line rounded-sm disabled:opacity-40">← Prev</button>
                  <span className="text-inkmute">
                    Page {disagreements.page} of {Math.max(1, Math.ceil(disagreements.total / disagreements.page_size))}
                  </span>
                  <button disabled={page * disagreements.page_size >= disagreements.total}
                    onClick={() => setPage((p) => p + 1)}
                    className="px-3 py-1 border border-line rounded-sm disabled:opacity-40">Next →</button>
                </div>
              </>
            )}
          </div>
        </>
      )}
    </div>
  )
}
