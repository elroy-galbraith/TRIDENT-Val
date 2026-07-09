import React, { useEffect, useMemo, useState } from 'react'
import { api, pct, usd } from '../api.js'
import { Carousel, LtvChip, ModelStatusBadge, Spinner, StatusBadge } from '../components/shared.jsx'
import PropertyMap from '../components/PropertyMap.jsx'
import { logger } from '../logger.js'

const QUAL_OPTS = [
  { v: 5, label: 'Excellent' }, { v: 4, label: 'Good' }, { v: 3, label: 'Typical/Average' },
  { v: 2, label: 'Fair' }, { v: 1, label: 'Poor' },
]
const FUNC_OPTS = [
  { v: 8, label: 'Typical' }, { v: 7, label: 'Minor Deductions 1' }, { v: 6, label: 'Minor Deductions 2' },
  { v: 5, label: 'Moderate' }, { v: 4, label: 'Major Deductions 1' }, { v: 3, label: 'Major Deductions 2' },
  { v: 2, label: 'Severely Damaged' }, { v: 1, label: 'Salvage Only' },
]

const SECTIONS = {
  Structure: ['gr_liv_area', 'total_bsmt_sf', 'first_flr_sf', 'garage_area', 'garage_cars',
    'lot_area', 'full_bath', 'half_bath', 'bedroom_abvgr', 'totrms_abvgrd', 'fireplaces', 'mas_vnr_area'],
  Quality: ['overall_qual', 'overall_cond', 'kitchen_qual', 'exter_qual', 'bsmt_qual', 'heating_qc', 'functional'],
  'External Factors': ['neighborhood', 'ms_zoning', 'bldg_type', 'house_style', 'central_air',
    'year_built', 'year_remod_add'],
}

function Contribution({ item, positive }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-line last:border-0">
      <div>
        <div className="text-sm">{item.label}</div>
        <div className="text-xs text-inkmute figure">{String(item.value)}</div>
      </div>
      <div className={`figure text-sm font-semibold ${positive ? 'text-ok' : 'text-flag'}`}>
        {positive ? '+' : '−'}{usd(Math.abs(item.impact_usd))}
      </div>
    </div>
  )
}

export default function Inspector({ pid, onBack, onOpen, user }) {
  const [prop, setProp] = useState(null)
  const [err, setErr] = useState(null)
  const [scenario, setScenario] = useState(null)
  const [result, setResult] = useState(null)       // latest what-if valuation
  const [running, setRunning] = useState(false)
  const [notes, setNotes] = useState('')
  const [status, setStatus] = useState('')
  const [saved, setSaved] = useState(false)
  const [comps, setComps] = useState(null)
  const [valuations, setValuations] = useState(null)
  const [decisionRationale, setDecisionRationale] = useState('')
  const [manualValue, setManualValue] = useState('')
  const [decisionBusy, setDecisionBusy] = useState(false)
  const [decisionSaved, setDecisionSaved] = useState(false)

  const loadValuations = () => api.propertyValuations(pid).then(setValuations).catch(() => setValuations(null))

  useEffect(() => {
    setProp(null); setResult(null); setValuations(null); setDecisionRationale('')
    api.property(pid).then((p) => {
      setProp(p)
      setScenario({ ...p.features })
      setNotes(p.underwriter_notes || '')
      setStatus(p.audit_status)
    }).catch((e) => setErr(e.message))
    loadValuations()
  }, [pid])

  useEffect(() => {
    let active = true
    setComps(null)
    api.comps(pid).then((res) => { if (active) setComps(res) }).catch(() => { if (active) setComps(null) })
    return () => { active = false }
  }, [pid])

  const baseline = prop?.baseline_valuation
  const active = result || baseline
  const delta = useMemo(() => {
    if (!result || !baseline) return null
    const d = result.estimated_market_value - baseline.estimated_market_value
    return { usd: d, pct: d / baseline.estimated_market_value }
  }, [result, baseline])

  if (err) return <div className="py-16 text-center text-flag text-sm">{err}</div>
  if (!prop || !scenario) return <Spinner label="Loading asset file…" />

  const setF = (k, v) => setScenario((s) => ({ ...s, [k]: v }))
  const recalc = async () => {
    setRunning(true)
    try {
      const changed = Object.keys(scenario).filter((k) => scenario[k] !== prop.features[k])
      const r = await api.valuate(scenario)
      logger.track('inspector', `Ran scenario re-valuation for PID ${pid}: ${usd(r.estimated_market_value)}.`,
        { changed_features: changed, estimated_market_value: r.estimated_market_value }, pid)
      setResult(r)
    } finally { setRunning(false) }
  }
  const resetScenario = () => { setScenario({ ...prop.features }); setResult(null) }
  const canWriteAudit = user.role === 'Underwriter' || user.role === 'Admin'
  const saveAudit = async () => {
    const r = await api.updateAudit(pid, { audit_status: status, underwriter_notes: notes })
    logger.track('inspector', `Saved audit decision for PID ${pid}: ${r.audit_status}.`,
      { audit_status: r.audit_status, notes_length: notes.length }, pid)
    setStatus(r.audit_status); setSaved(true); setTimeout(() => setSaved(false), 2000)
  }

  const submitTriageDecision = async (decision, modelId) => {
    if (!decisionRationale.trim()) { window.alert('A rationale is required for the audit ledger.'); return }
    if (decision === 'manual') {
      const val = +manualValue
      if (!manualValue || isNaN(val) || val <= 0) {
        window.alert('Enter a valid positive manual override value.')
        return
      }
    }
    setDecisionBusy(true)
    try {
      const body = { decision, rationale: decisionRationale }
      if (decision === 'challenger') body.model_id = modelId
      if (decision === 'manual') body.manual_value = +manualValue
      const r = await api.triageDecision(pid, body)
      logger.track('inspector', `Triage decision for PID ${pid}: ${decision} -> ${usd(r.avm_value)}.`,
        { decision, resolved_model_id: r.resolved_model_id, avm_value: r.avm_value, rationale: decisionRationale }, pid)
      setStatus(r.audit_status)
      setDecisionRationale(''); setManualValue('')
      setDecisionSaved(true); setTimeout(() => setDecisionSaved(false), 2000)
      const [p] = await Promise.all([api.property(pid), loadValuations()])
      setProp(p)
    } catch (e) {
      window.alert(`Decision failed: ${e.message}`)
    } finally {
      setDecisionBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <button onClick={onBack} aria-label="Back to portfolio" className="text-sm text-teal hover:underline">← Back to portfolio</button>
        <a href={api.assetReportUrl(pid)} target="_blank" rel="noopener noreferrer"
          onClick={() => logger.track('inspector', `Exported underwriter decision report for PID ${pid}.`, null, pid)}
          aria-label="Export underwriter decision report as PDF"
          className="text-sm text-teal hover:underline">
          Export Decision Report ↗
        </a>
      </div>

      {/* Header strip */}
      <div className="card p-5 flex flex-wrap gap-6 items-center">
        {prop.images?.[0]?.url && (
          <img src={prop.images[0].url} alt="" className="w-28 h-20 object-cover rounded-sm border border-line"
            onError={(e) => { e.currentTarget.style.display = 'none' }} />
        )}
        <div>
          <div className="label">Asset File</div>
          <div className="text-lg font-semibold">{prop.neighborhood} · {prop.bldg_type} · {prop.house_style}</div>
          <div className="text-xs text-inkmute figure">PID {prop.pid} · Built {prop.year_built} · {prop.total_sqft.toLocaleString()} sq ft total</div>
        </div>
        <div className="ml-auto flex gap-8 text-right">
          <div>
            <div className="label">AVM Value (booked)</div>
            <div className="figure text-xl font-semibold text-tealdeep">{usd(prop.avm_value)}</div>
          </div>
          <div>
            <div className="label">Loan Balance</div>
            <div className="figure text-xl font-semibold">{usd(prop.loan_balance)}</div>
            <LtvChip ltv={prop.ltv} />
          </div>
          <div>
            <div className="label">Baseline Sale · Variance</div>
            <div className="figure text-xl font-semibold">{usd(prop.sale_price)}</div>
            <div className={`figure text-xs font-semibold ${Math.abs(prop.avm_variance_pct) > 0.15 ? 'text-flag' : 'text-inkmute'}`}>
              AVM {prop.avm_variance_pct >= 0 ? '+' : ''}{pct(prop.avm_variance_pct)} vs sale
            </div>
          </div>
        </div>
      </div>

      {prop.images && prop.images.length > 0 && (
        <div className="card p-5">
          <div className="label mb-2">Property Photos</div>
          <Carousel images={prop.images} className="max-w-md" imgClassName="h-64" />
        </div>
      )}

      <div className="grid lg:grid-cols-3 gap-4 items-start">
        {/* Scenario engine */}
        <div className="card p-5 space-y-4 lg:col-span-1">
          <div>
            <div className="label">Interactive Scenario Panel</div>
            <div className="text-xs text-inkmute mt-1">Override value drivers and recalculate against the live AVM.</div>
          </div>

          <div>
            <div className="flex justify-between text-sm mb-1">
              <span>Overall Quality</span>
              <span className="figure font-semibold">{scenario.overall_qual}/10</span>
            </div>
            <input type="range" min="1" max="10" value={scenario.overall_qual} aria-label="Overall quality, 1 to 10"
              onChange={(e) => setF('overall_qual', +e.target.value)} className="w-full accent-teal" />
          </div>

          <div>
            <div className="flex justify-between text-sm mb-1">
              <span>Above Ground Living Area</span>
              <span className="figure font-semibold">{scenario.gr_liv_area.toLocaleString()} sq ft</span>
            </div>
            <input type="range" min="400" max="4500" step="10" value={scenario.gr_liv_area}
              aria-label="Above ground living area in square feet"
              onChange={(e) => setF('gr_liv_area', +e.target.value)} className="w-full accent-teal" />
          </div>

          <div>
            <div className="text-sm mb-1">Kitchen Quality</div>
            <select value={scenario.kitchen_qual} onChange={(e) => setF('kitchen_qual', +e.target.value)}
              aria-label="Kitchen quality" className="w-full border border-line rounded-sm px-2 py-1.5 text-sm bg-white">
              {QUAL_OPTS.map((o) => <option key={o.v} value={o.v}>{o.label}</option>)}
            </select>
          </div>

          <div>
            <div className="text-sm mb-1">Functional Deficiency</div>
            <select value={scenario.functional} onChange={(e) => setF('functional', +e.target.value)}
              aria-label="Functional deficiency rating" className="w-full border border-line rounded-sm px-2 py-1.5 text-sm bg-white">
              {FUNC_OPTS.map((o) => <option key={o.v} value={o.v}>{o.label}</option>)}
            </select>
          </div>

          <div className="flex gap-2 pt-1">
            <button onClick={recalc} disabled={running} aria-label="Recalculate valuation with current scenario"
              className="flex-1 bg-teal hover:bg-tealdeep text-white text-sm font-medium py-2 rounded-sm disabled:opacity-50">
              {running ? 'Scoring…' : 'Recalculate valuation'}
            </button>
            <button onClick={resetScenario} aria-label="Reset scenario to original property values"
              className="px-3 border border-line rounded-sm text-sm bg-white">Reset</button>
          </div>

          {/* Delta meter */}
          <div className={`rounded-sm border p-4 text-center ${!delta ? 'border-line bg-paper' :
            delta.usd >= 0 ? 'border-ok/40 bg-ok/5' : 'border-flag/40 bg-flag/5'}`}>
            <div className="label">Scenario Delta</div>
            {delta ? (
              <>
                <div className={`figure text-2xl font-bold ${delta.usd >= 0 ? 'text-ok' : 'text-flag'}`}>
                  {delta.usd >= 0 ? '+' : '−'}{usd(Math.abs(delta.usd))} ({delta.usd >= 0 ? '+' : ''}{pct(delta.pct)})
                </div>
                <div className="figure text-xs text-inkmute mt-1">
                  New estimate {usd(result.estimated_market_value)} · band {usd(result.value_low)}–{usd(result.value_high)}
                </div>
              </>
            ) : (
              <div className="text-sm text-inkmute">Adjust drivers and recalculate to see the valuation shift.</div>
            )}
          </div>
        </div>

        {/* SHAP widget + audit */}
        <div className="space-y-4 lg:col-span-1">
          <div className="card p-5">
            <div className="label">Explainable AI — Value Drivers</div>
            <div className="text-xs text-inkmute mt-1 mb-2">
              Contributions from model <span className="figure">{prop.resolved_model_id || active.model_id}</span> for
              the {result ? 'current scenario' : 'baseline'} estimate of{' '}
              <span className="figure font-semibold text-ink">{usd(active.estimated_market_value)}</span> (±5%).
            </div>
            {active.top_drivers.map((d) => <Contribution key={d.feature} item={d} positive />)}
            <div className="h-2" />
            {active.top_detractors.map((d) => <Contribution key={d.feature} item={d} positive={false} />)}
          </div>

          {valuations && valuations.items.length > 1 && (
            <div className="card p-5 space-y-3">
              <div className="label">Model Comparison &amp; Triage Decision</div>
              <div className="space-y-2">
                {valuations.items.map((v) => (
                  <div key={v.model_id} className={`flex items-center justify-between rounded-sm border p-2.5 ${
                    v.is_booked ? 'border-teal bg-teal/5' : 'border-line'}`}>
                    <div className="flex items-center gap-2">
                      <ModelStatusBadge status={v.status} />
                      <span className="text-sm">{v.model_name}</span>
                      {v.is_booked && <span className="text-[11px] text-teal font-semibold">BOOKED</span>}
                    </div>
                    <span className="figure text-sm font-semibold">{usd(v.estimated_value)}</span>
                  </div>
                ))}
                {valuations.resolved_model_id == null && (
                  <div className="flex items-center justify-between rounded-sm border border-amber bg-amber/5 p-2.5">
                    <span className="text-sm">Manual override (no model)</span>
                    <span className="figure text-sm font-semibold">{usd(valuations.booked_value)}</span>
                  </div>
                )}
              </div>

              {canWriteAudit ? (
                <div className="space-y-2 pt-1 border-t border-line">
                  <textarea value={decisionRationale} onChange={(e) => setDecisionRationale(e.target.value)}
                    rows={2} placeholder="Rationale for this decision — logged to the audit ledger"
                    aria-label="Triage decision rationale" data-page-agent-not-interactive
                    className="w-full border border-line rounded-sm px-3 py-2 text-sm focus:outline-none focus:border-teal" />
                  <div className="flex flex-wrap gap-2">
                    {valuations.items.map((v) => (
                      <button key={v.model_id} disabled={decisionBusy || v.is_booked}
                        data-page-agent-not-interactive
                        onClick={() => submitTriageDecision(v.status === 'Champion' ? 'champion' : 'challenger', v.model_id)}
                        className="px-3 py-1.5 text-sm border border-line rounded-sm bg-white hover:border-teal disabled:opacity-40 disabled:cursor-not-allowed">
                        Book {v.status.toLowerCase()} ({usd(v.estimated_value)})
                      </button>
                    ))}
                  </div>
                  <div className="flex gap-2 items-center">
                    <input type="number" value={manualValue} onChange={(e) => setManualValue(e.target.value)}
                      placeholder="Manual value ($)" aria-label="Manual override value" data-page-agent-not-interactive
                      className="flex-1 border border-line rounded-sm px-3 py-1.5 text-sm" />
                    <button disabled={decisionBusy} onClick={() => submitTriageDecision('manual')}
                      data-page-agent-not-interactive
                      className="px-3 py-1.5 text-sm border border-line rounded-sm bg-white hover:border-teal disabled:opacity-40">
                      {decisionSaved ? 'Saved ✓' : 'Book manual value'}
                    </button>
                  </div>
                </div>
              ) : (
                <div className="text-xs text-inkmute pt-1 border-t border-line">
                  Read-only — the {user.role} role cannot resolve model disagreements.
                </div>
              )}
            </div>
          )}

          <div className="card p-5 space-y-3">
            <div className="label">Audit Lifecycle</div>
            <div className="flex items-center gap-2">
              <StatusBadge status={status} />
            </div>
            <select value={status} onChange={(e) => setStatus(e.target.value)}
              aria-label="Audit status" data-page-agent-not-interactive disabled={!canWriteAudit}
              className="w-full border border-line rounded-sm px-2 py-1.5 text-sm bg-white disabled:opacity-60 disabled:cursor-not-allowed">
              <option>Approved</option>
              <option>Pending Review</option>
              <option>Flagged: High Variance</option>
            </select>
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={4}
              placeholder="Underwriter notes — shared risk commentary ledger"
              aria-label="Underwriter audit notes" data-page-agent-not-interactive disabled={!canWriteAudit}
              className="w-full border border-line rounded-sm px-3 py-2 text-sm focus:outline-none focus:border-teal disabled:opacity-60 disabled:cursor-not-allowed" />
            <button onClick={saveAudit} data-page-agent-not-interactive disabled={!canWriteAudit}
              className="w-full bg-ink hover:bg-black text-white text-sm font-medium py-2 rounded-sm disabled:opacity-50 disabled:cursor-not-allowed">
              {saved ? 'Saved ✓' : 'Save audit decision'}
            </button>
            {!canWriteAudit && (
              <div className="text-xs text-inkmute">Read-only — the {user.role} role cannot modify audit decisions.</div>
            )}
          </div>
        </div>

        {/* Glass-box matrix */}
        <div className="card p-5 lg:col-span-1">
          <div className="label mb-2">Glass-Box Feature Matrix</div>
          {Object.entries(SECTIONS).map(([section, keys]) => (
            <div key={section} className="mb-4">
              <div className="text-xs font-semibold text-tealdeep uppercase tracking-wide mb-1">{section}</div>
              <table className="w-full text-sm">
                <tbody>
                  {keys.map((k) => (
                    <tr key={k} className="border-b border-line last:border-0">
                      <td className="py-1 text-inkmute">{prop.feature_labels[k] || k}</td>
                      <td className="py-1 text-right figure">
                        {typeof scenario[k] === 'number' ? scenario[k].toLocaleString() : String(scenario[k])}
                        {scenario[k] !== prop.features[k] && <span className="text-amber ml-1" title="Scenario override">●</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      </div>

      {/* Location & comparables */}
      <div className="card p-5">
        <div className="label">Location &amp; Comparable Properties</div>
        <div className="text-xs text-inkmute mt-1 mb-3">
          Subject asset (outlined) against the {comps?.comps.length ?? '…'} nearest comps by neighborhood, size, quality, and vintage.
        </div>
        {!comps ? <Spinner label="Finding comparables…" /> : (
          <div className="grid lg:grid-cols-3 gap-4">
            <div className="lg:col-span-2 rounded-sm overflow-hidden border border-line">
              <PropertyMap
                points={[comps.subject, ...comps.comps]}
                center={[comps.subject.lat, comps.subject.lng]}
                zoom={15}
                height={320}
                subjectPid={prop.pid}
                onOpen={onOpen}
              />
            </div>
            <div className="space-y-2 overflow-auto" style={{ maxHeight: 320 }}>
              {comps.comps.map((c) => (
                <button key={c.pid} onClick={() => onOpen && onOpen(c.pid)}
                  className="w-full text-left border border-line rounded-sm p-2 hover:border-teal transition-colors">
                  <div className="flex items-baseline justify-between">
                    <span className="figure text-sm font-semibold text-tealdeep">{usd(c.avm_value)}</span>
                    <span className="text-xs text-inkmute">{c.neighborhood}</span>
                  </div>
                  <div className="text-xs text-inkmute">
                    {c.gr_liv_area?.toLocaleString()} sq ft · Qual {c.overall_qual} · Built {c.year_built}
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
