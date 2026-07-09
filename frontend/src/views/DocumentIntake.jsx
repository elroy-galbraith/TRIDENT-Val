import React, { useEffect, useState } from 'react'
import {
  Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { api, pct } from '../api.js'
import { Spinner } from '../components/shared.jsx'
import { logger } from '../logger.js'

function Metric({ label, value, accent }) {
  return (
    <div className="border border-line rounded-sm p-4">
      <div className="label">{label}</div>
      <div className={`figure text-2xl font-semibold mt-1 ${accent || 'text-tealdeep'}`}>{value}</div>
    </div>
  )
}

function accuracyColor(a) {
  if (a == null) return '#90A19A'
  return a >= 0.9 ? '#2E7D4F' : a >= 0.75 ? '#C77D0A' : '#B3352C'
}

function AccuracyDashboard({ data }) {
  if (!data) return <Spinner label="Loading accuracy dashboard…" />
  if (data.runs_scored === 0) {
    return (
      <div className="card p-6 text-center text-sm text-inkmute">
        No extraction runs yet — generate a document below and run extraction to populate this dashboard.
      </div>
    )
  }
  return (
    <div className="space-y-4">
      <div className="grid sm:grid-cols-4 gap-4">
        <Metric label="Overall Field Accuracy" value={pct(data.overall_accuracy)} accent="text-tealdeep" />
        <Metric label="Clean Documents" value={pct(data.clean_accuracy)} accent="text-ok" />
        <Metric label="Degraded Documents" value={pct(data.degraded_accuracy)}
          accent={data.degraded_accuracy != null && data.degraded_accuracy < 0.85 ? 'text-flag' : 'text-ok'} />
        <Metric label="Open Triage Items" value={data.triage_queue_size} accent="text-flag" />
      </div>
      <div className="card p-5">
        <div className="label mb-2">Per-Field Accuracy ({data.runs_scored} run{data.runs_scored === 1 ? '' : 's'} scored)</div>
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={data.per_field} layout="vertical" margin={{ left: 40 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#DDE3E0" horizontal={false} />
            <XAxis type="number" domain={[0, 1]} tickFormatter={(v) => `${Math.round(v * 100)}%`}
              tick={{ fontSize: 11, fill: '#5B6B77' }} />
            <YAxis type="category" dataKey="field" width={110} tick={{ fontSize: 11, fill: '#5B6B77' }} />
            <Tooltip formatter={(v, _n, p) => [`${(v * 100).toFixed(0)}% (n=${p.payload.n})`, 'Accuracy']} />
            <Bar dataKey="accuracy" radius={[0, 3, 3, 0]}>
              {data.per_field.map((f) => <Cell key={f.field} fill={accuracyColor(f.accuracy)} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

function GenerateForm({ onGenerated }) {
  const [pidsText, setPidsText] = useState('')
  const [style, setStyle] = useState('legacy_urar')
  const [degrade, setDegrade] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  const submit = async () => {
    const pids = pidsText.split(/[\s,]+/).map((s) => parseInt(s, 10)).filter((n) => !isNaN(n))
    if (pids.length === 0) { setError('Enter at least one PID'); return }
    setSubmitting(true)
    setError(null)
    try {
      const r = await api.generateDocuments(pids, style, degrade)
      logger.track('document-intake', `Generated ${r.documents.length} synthetic document(s).`, r)
      setPidsText('')
      onGenerated()
    } catch (e) {
      setError(e.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="card p-5 space-y-3">
      <div className="label">Generate Synthetic Documents</div>
      <p className="text-xs text-inkmute max-w-2xl leading-relaxed">
        Renders a synthetic valuation-report PDF from an existing property's own record — the
        Ames fields printed on the document double as the answer key extraction is scored
        against. Optionally degrades it (skew, scan noise, low-quality re-encode) to simulate
        an old paper file.
      </p>
      <div className="grid sm:grid-cols-3 gap-3">
        <label className="text-sm space-y-1 block sm:col-span-1">
          <span className="text-inkmute text-xs">Property PID(s), comma/space-separated</span>
          <input value={pidsText} onChange={(e) => setPidsText(e.target.value)}
            placeholder="526301100, 526350040"
            className="w-full border border-line rounded-sm px-2 py-1.5" />
        </label>
        <label className="text-sm space-y-1 block">
          <span className="text-inkmute text-xs">Template style</span>
          <select value={style} onChange={(e) => setStyle(e.target.value)}
            className="w-full border border-line rounded-sm px-2 py-1.5 bg-white">
            <option value="legacy_urar">Legacy surveyor form (URAR-style)</option>
            <option value="modern">Modern valuation summary</option>
          </select>
        </label>
        <label className="text-sm flex items-center gap-2 mt-5">
          <input type="checkbox" checked={degrade} onChange={(e) => setDegrade(e.target.checked)} />
          <span>Degrade (simulate an old scanned document)</span>
        </label>
      </div>
      {error && <div className="text-sm text-flag">{error}</div>}
      <button onClick={submit} disabled={submitting}
        className="bg-ink hover:bg-black text-white text-sm font-medium px-4 py-2 rounded-sm disabled:opacity-50">
        {submitting ? 'Generating…' : 'Generate'}
      </button>
    </div>
  )
}

function DocumentList({ refreshKey, canExtract, onExtracted }) {
  const [data, setData] = useState(null)
  const [page, setPage] = useState(1)
  const [extractingId, setExtractingId] = useState(null)
  const [runByDoc, setRunByDoc] = useState({})
  const [expanded, setExpanded] = useState(null)
  const [runDetail, setRunDetail] = useState(null)

  useEffect(() => {
    setData(null)
    api.documents({ page, page_size: 10 }).then(setData)
  }, [page, refreshKey])

  const extract = async (docId) => {
    setExtractingId(docId)
    try {
      const run = await api.runExtraction(docId)
      setRunByDoc((m) => ({ ...m, [docId]: run }))
      logger.track('document-intake', `Ran extraction for document ${docId}: ${Math.round((run.overall_field_accuracy || 0) * 100)}% accuracy.`)
      onExtracted()
    } catch (e) {
      setRunByDoc((m) => ({ ...m, [docId]: { error: e.message } }))
    } finally {
      setExtractingId(null)
    }
  }

  const viewRun = async (docId) => {
    if (expanded === docId) { setExpanded(null); return }
    setExpanded(docId)
    setRunDetail(null)
    const run = runByDoc[docId]
    if (run?.run_id) {
      const detail = await api.extractionRun(run.run_id)
      setRunDetail(detail)
    }
  }

  if (!data) return <Spinner label="Loading documents…" />

  return (
    <div className="card p-5">
      <div className="label mb-2">Synthetic Document Corpus</div>
      {data.items.length === 0 ? (
        <div className="text-sm text-inkmute py-6 text-center">
          No synthetic documents yet — generate one above, or run
          <code className="mx-1 text-xs bg-paper px-1 py-0.5 rounded-sm">python scripts/generate_synthetic_reports.py</code>
          for a full demo corpus.
        </div>
      ) : (
        <>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-inkmute border-b border-line">
                <th className="py-1.5 pr-3">Doc</th><th className="py-1.5 pr-3">PID</th>
                <th className="py-1.5 pr-3">Style</th><th className="py-1.5 pr-3">Degraded</th>
                <th className="py-1.5 pr-3">Last Extraction</th><th className="py-1.5">Action</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((d) => {
                const run = runByDoc[d.id]
                return (
                  <React.Fragment key={d.id}>
                    <tr className="border-b border-line last:border-0">
                      <td className="py-1.5 pr-3 figure">#{d.id}</td>
                      <td className="py-1.5 pr-3 figure">{d.pid}</td>
                      <td className="py-1.5 pr-3 text-xs">{d.style}</td>
                      <td className="py-1.5 pr-3 text-xs">{d.degraded ? 'Yes' : 'No'}</td>
                      <td className="py-1.5 pr-3 text-xs">
                        {run?.error ? <span className="text-flag">Failed: {run.error.slice(0, 60)}</span>
                          : run ? `${pct(run.overall_field_accuracy)} accuracy` : '—'}
                      </td>
                      <td className="py-1.5 flex gap-2">
                        {canExtract && (
                          <button onClick={() => extract(d.id)} disabled={extractingId === d.id}
                            className="text-xs bg-ink hover:bg-black text-white px-2 py-1 rounded-sm disabled:opacity-50">
                            {extractingId === d.id ? 'Extracting…' : 'Run Extraction'}
                          </button>
                        )}
                        {run?.run_id && (
                          <button onClick={() => viewRun(d.id)} className="text-xs text-teal hover:underline">
                            {expanded === d.id ? 'Hide' : 'View'} fields
                          </button>
                        )}
                      </td>
                    </tr>
                    {expanded === d.id && (
                      <tr>
                        <td colSpan={6} className="pb-3">
                          {!runDetail ? <Spinner label="Loading fields…" /> : (
                            <table className="w-full text-xs border border-line rounded-sm overflow-hidden">
                              <thead>
                                <tr className="text-left text-inkmute bg-paper border-b border-line">
                                  <th className="py-1 px-2">Field</th><th className="py-1 px-2">Extracted</th>
                                  <th className="py-1 px-2">Ground Truth</th><th className="py-1 px-2">Match</th>
                                  <th className="py-1 px-2">Confidence</th><th className="py-1 px-2">Triage</th>
                                </tr>
                              </thead>
                              <tbody>
                                {runDetail.fields?.map((f) => (
                                  <tr key={f.id} className="border-b border-line last:border-0">
                                    <td className="py-1 px-2">{f.field_name}</td>
                                    <td className="py-1 px-2 figure">{f.extracted_value ?? '—'}</td>
                                    <td className="py-1 px-2 figure">{f.ground_truth_value}</td>
                                    <td className={`py-1 px-2 font-semibold ${f.match ? 'text-ok' : f.match === false ? 'text-flag' : 'text-inkmute'}`}>
                                      {f.match === true ? 'Yes' : f.match === false ? 'No' : 'N/A'}
                                    </td>
                                    <td className="py-1 px-2 figure">{f.confidence != null ? pct(f.confidence, 0) : '—'}</td>
                                    <td className="py-1 px-2">
                                      {f.routed_to_triage ? (f.triage_resolved ? 'Resolved' : 'Flagged') : '—'}
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          )}
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                )
              })}
            </tbody>
          </table>
          <div className="flex justify-between items-center mt-3 text-sm">
            <button disabled={page <= 1} onClick={() => setPage((p) => p - 1)}
              className="px-3 py-1 border border-line rounded-sm disabled:opacity-40">← Prev</button>
            <span className="text-inkmute">
              Page {data.page} of {Math.max(1, Math.ceil(data.total / data.page_size))} ({data.total.toLocaleString()})
            </span>
            <button disabled={page * data.page_size >= data.total} onClick={() => setPage((p) => p + 1)}
              className="px-3 py-1 border border-line rounded-sm disabled:opacity-40">Next →</button>
          </div>
        </>
      )}
    </div>
  )
}

function TriageQueue({ refreshKey, canResolve, onResolved }) {
  const [data, setData] = useState(null)
  const [page, setPage] = useState(1)
  const [showResolved, setShowResolved] = useState(false)
  const [resolutionById, setResolutionById] = useState({})

  const load = () => {
    setData(null)
    const params = { page, page_size: 10 }
    if (!showResolved) params.resolved = false
    api.extractionTriage(params).then(setData)
  }
  useEffect(load, [page, showResolved, refreshKey])

  const resolve = async (id) => {
    const resolution = resolutionById[id]
    if (!resolution) return
    await api.resolveExtractionTriage(id, resolution)
    logger.track('document-intake', `Resolved extraction triage field #${id}.`)
    load()
    onResolved()
  }

  return (
    <div className="card p-5">
      <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
        <div>
          <div className="label">Extraction Triage Queue</div>
          <p className="text-xs text-inkmute mt-1">
            Fields the model was unsure about, or got wrong — flagged for human review rather
            than silently trusted.
          </p>
        </div>
        <label className="text-xs flex items-center gap-1.5">
          <input type="checkbox" checked={showResolved} onChange={(e) => { setShowResolved(e.target.checked); setPage(1) }} />
          Show resolved
        </label>
      </div>
      {!data ? <Spinner label="Loading triage queue…" /> : data.items.length === 0 ? (
        <div className="text-sm text-inkmute py-6 text-center">
          {showResolved ? 'No triaged fields at all.' : 'No open triage items — nice.'}
        </div>
      ) : (
        <>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-inkmute border-b border-line">
                <th className="py-1.5 pr-3">PID</th><th className="py-1.5 pr-3">Field</th>
                <th className="py-1.5 pr-3">Extracted</th><th className="py-1.5 pr-3">Truth</th>
                <th className="py-1.5 pr-3">Confidence</th><th className="py-1.5">Action</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((it) => (
                <tr key={it.id} className="border-b border-line last:border-0">
                  <td className="py-1.5 pr-3 figure">{it.pid}</td>
                  <td className="py-1.5 pr-3">{it.field_name}</td>
                  <td className="py-1.5 pr-3 figure">{it.extracted_value ?? '—'}</td>
                  <td className="py-1.5 pr-3 figure">{it.ground_truth_value}</td>
                  <td className="py-1.5 pr-3 figure">{it.confidence != null ? pct(it.confidence, 0) : '—'}</td>
                  <td className="py-1.5">
                    {it.triage_resolved ? (
                      <span className="text-xs text-ok">Resolved: {it.triage_resolution}</span>
                    ) : canResolve ? (
                      <div className="flex gap-1.5 items-center">
                        <input placeholder="resolution" value={resolutionById[it.id] || ''}
                          onChange={(e) => setResolutionById((m) => ({ ...m, [it.id]: e.target.value }))}
                          className="text-xs border border-line rounded-sm px-1.5 py-1 w-32" />
                        <button onClick={() => resolve(it.id)}
                          className="text-xs bg-ink hover:bg-black text-white px-2 py-1 rounded-sm">
                          Resolve
                        </button>
                      </div>
                    ) : <span className="text-xs text-inkmute">Unresolved</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="flex justify-between items-center mt-3 text-sm">
            <button disabled={page <= 1} onClick={() => setPage((p) => p - 1)}
              className="px-3 py-1 border border-line rounded-sm disabled:opacity-40">← Prev</button>
            <span className="text-inkmute">
              Page {data.page} of {Math.max(1, Math.ceil(data.total / data.page_size))} ({data.total.toLocaleString()})
            </span>
            <button disabled={page * data.page_size >= data.total} onClick={() => setPage((p) => p + 1)}
              className="px-3 py-1 border border-line rounded-sm disabled:opacity-40">Next →</button>
          </div>
        </>
      )}
    </div>
  )
}

export default function DocumentIntake({ user }) {
  const [accuracy, setAccuracy] = useState(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const canWrite = user?.role === 'Underwriter' || user?.role === 'Admin'

  const loadAccuracy = () => { api.extractionAccuracy().then(setAccuracy) }
  useEffect(() => { loadAccuracy() }, [refreshKey])

  const bump = () => setRefreshKey((k) => k + 1)

  return (
    <div className="space-y-4">
      <div className="card p-4 border-teal/40 bg-teal/5 text-sm leading-relaxed">
        <span className="font-semibold">Synthetic documents, disclosed.</span> Every document
        on this page is generated from the public Ames Housing dataset — never a real
        appraisal, survey, or valuation — so extraction accuracy can be measured against a
        known answer key. This is stated on every generated PDF as well.
      </div>

      <div className="card p-6">
        <div className="label">Document Intake</div>
        <h1 className="text-2xl font-semibold mt-1">Extraction Accuracy</h1>
        <p className="text-sm text-inkmute mt-3 max-w-3xl leading-relaxed">
          Docling extracts layout/OCR text from a (possibly degraded, scan-simulated) valuation
          report PDF; an LLM then structures that text into named fields with a confidence per
          field. Because every document was generated from a known property record, extraction
          can be scored exactly — and low-confidence or wrong fields route to human triage
          instead of being silently trusted.
        </p>
      </div>

      <AccuracyDashboard data={accuracy} />
      <GenerateForm onGenerated={bump} />
      <DocumentList refreshKey={refreshKey} canExtract={canWrite} onExtracted={bump} />
      <TriageQueue refreshKey={refreshKey} canResolve={canWrite} onResolved={bump} />
    </div>
  )
}
