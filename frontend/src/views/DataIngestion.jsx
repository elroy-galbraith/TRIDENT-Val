import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import { PipelineHealthStrip, Spinner, SourceSystemBadge } from '../components/shared.jsx'
import { logger } from '../logger.js'

const SOURCES = [
  { id: 'core_banking', label: 'Core Banking', description: 'SFTP-style CSV drop of loan/account fields.' },
  { id: 'valuation_vendor', label: 'Valuation Vendor', description: 'Mock paginated JSON API from a valuation vendor.' },
  { id: 'valuations_team', label: 'Valuations Team', description: 'Manual review spreadsheet, merged headers + notes.' },
]

function timeAgo(iso) {
  if (!iso) return 'never'
  return new Date(iso).toLocaleString()
}

function SourceCard({ source, latestRun, canSync, onSync, syncing }) {
  return (
    <div className="card p-5">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="label">{source.label}</div>
          <p className="text-xs text-inkmute mt-1 max-w-xs">{source.description}</p>
        </div>
        <SourceSystemBadge source={source.id} />
      </div>
      <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
        <div>
          <div className="text-inkmute text-xs">Last sync</div>
          <div className="figure">{timeAgo(latestRun?.completed_at)}</div>
        </div>
        <div>
          <div className="text-inkmute text-xs">Status</div>
          <div className="figure capitalize">{latestRun?.status || '—'}</div>
        </div>
        <div>
          <div className="text-inkmute text-xs">Loaded</div>
          <div className="figure font-semibold text-ok">{latestRun?.records_loaded ?? '—'}</div>
        </div>
        <div>
          <div className="text-inkmute text-xs">Quarantined</div>
          <div className="figure font-semibold text-flag">{latestRun?.records_quarantined ?? '—'}</div>
        </div>
      </div>
      {canSync && (
        <button onClick={() => onSync(source.id)} disabled={syncing}
          className="mt-4 w-full bg-ink hover:bg-black text-white text-sm font-medium px-3 py-1.5 rounded-sm disabled:opacity-50">
          {syncing ? 'Syncing…' : 'Sync Now'}
        </button>
      )}
    </div>
  )
}

function RunHistory({ runs }) {
  return (
    <div className="card p-5">
      <div className="label mb-2">Sync History</div>
      {runs.length === 0 ? (
        <div className="text-sm text-inkmute py-6 text-center">No syncs have run yet.</div>
      ) : (
        <div className="overflow-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-inkmute border-b border-line">
                <th className="py-1.5 pr-3">Run</th><th className="py-1.5 pr-3">Source</th>
                <th className="py-1.5 pr-3">Completed</th><th className="py-1.5 pr-3">Seen</th>
                <th className="py-1.5 pr-3">Loaded</th><th className="py-1.5 pr-3">Quarantined</th>
                <th className="py-1.5 pr-3">Schema drift</th><th className="py-1.5">By</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.run_id} className="border-b border-line last:border-0">
                  <td className="py-1.5 pr-3 figure">#{r.run_id}</td>
                  <td className="py-1.5 pr-3"><SourceSystemBadge source={r.source_system} /></td>
                  <td className="py-1.5 pr-3">{timeAgo(r.completed_at)}</td>
                  <td className="py-1.5 pr-3 figure">{r.records_seen}</td>
                  <td className="py-1.5 pr-3 figure text-ok">{r.records_loaded}</td>
                  <td className="py-1.5 pr-3 figure text-flag">{r.records_quarantined}</td>
                  <td className="py-1.5 pr-3 text-xs">
                    {r.schema_columns_added?.length
                      ? <span className="text-amber font-medium">+{r.schema_columns_added.join(', ')}</span>
                      : '—'}
                  </td>
                  <td className="py-1.5">{r.triggered_by || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function ProvenanceGrid({ refreshKey }) {
  const [data, setData] = useState(null)
  const [page, setPage] = useState(1)
  const [sourceFilter, setSourceFilter] = useState('')
  const [expanded, setExpanded] = useState(null)

  useEffect(() => {
    setData(null)
    const params = { page, page_size: 10 }
    if (sourceFilter) params.source_system = sourceFilter
    api.ingestionRecords(params).then(setData)
  }, [page, sourceFilter, refreshKey])

  return (
    <div className="card p-5">
      <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
        <div className="label">Provenance</div>
        <select value={sourceFilter} onChange={(e) => { setSourceFilter(e.target.value); setPage(1) }}
          className="text-xs border border-line rounded-sm px-2 py-1 bg-white">
          <option value="">All sources</option>
          {SOURCES.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
        </select>
      </div>
      {!data ? <Spinner label="Loading provenance…" /> : data.items.length === 0 ? (
        <div className="text-sm text-inkmute py-6 text-center">No provenance records yet — run a sync.</div>
      ) : (
        <>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-inkmute border-b border-line">
                <th className="py-1.5 pr-3">PID</th><th className="py-1.5 pr-3">Source</th>
                <th className="py-1.5 pr-3">Source Record ID</th><th className="py-1.5 pr-3">Loaded</th>
                <th className="py-1.5">Raw payload</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((r, i) => (
                <React.Fragment key={`${r.pid}-${r.source_system}`}>
                  <tr className="border-b border-line last:border-0">
                    <td className="py-1.5 pr-3 figure">{r.pid}</td>
                    <td className="py-1.5 pr-3"><SourceSystemBadge source={r.source_system} /></td>
                    <td className="py-1.5 pr-3 figure text-xs">{r.source_record_id}</td>
                    <td className="py-1.5 pr-3 text-xs">{timeAgo(r.loaded_at)}</td>
                    <td className="py-1.5">
                      <button onClick={() => setExpanded(expanded === i ? null : i)}
                        className="text-teal hover:underline text-xs">
                        {expanded === i ? 'Hide' : 'View'} JSON
                      </button>
                    </td>
                  </tr>
                  {expanded === i && (
                    <tr>
                      <td colSpan={5} className="pb-2">
                        <pre className="text-[11px] bg-paper border border-line rounded-sm p-2 overflow-auto max-h-40">
                          {JSON.stringify(r.raw_payload, null, 2)}
                        </pre>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              ))}
            </tbody>
          </table>
          <div className="flex justify-between items-center mt-3 text-sm">
            <button disabled={page <= 1} onClick={() => setPage((p) => p - 1)}
              className="px-3 py-1 border border-line rounded-sm disabled:opacity-40">← Prev</button>
            <span className="text-inkmute">
              Page {data.page} of {Math.max(1, Math.ceil(data.total / data.page_size))} ({data.total.toLocaleString()} records)
            </span>
            <button disabled={page * data.page_size >= data.total} onClick={() => setPage((p) => p + 1)}
              className="px-3 py-1 border border-line rounded-sm disabled:opacity-40">Next →</button>
          </div>
        </>
      )}
    </div>
  )
}

function QuarantinePanel({ canResolve, refreshKey }) {
  const [data, setData] = useState(null)
  const [page, setPage] = useState(1)
  const [showResolved, setShowResolved] = useState(false)
  const [notesById, setNotesById] = useState({})
  const [expandedId, setExpandedId] = useState(null)

  const load = () => {
    setData(null)
    const params = { page, page_size: 10 }
    if (!showResolved) params.resolved = false
    api.ingestionQuarantine(params).then(setData)
  }

  useEffect(load, [page, showResolved, refreshKey])

  const resolve = async (id) => {
    try {
      await api.resolveQuarantine(id, notesById[id] || '')
      logger.track('ingestion', `Resolved quarantined record #${id}.`)
      load()
    } catch (e) {
      logger.error('ingestion', `Failed to resolve quarantine #${id}: ${e.message}`)
    }
  }

  return (
    <div className="card p-5">
      <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
        <div>
          <div className="label">Quarantine</div>
          <p className="text-xs text-inkmute mt-1 max-w-2xl">
            Malformed rows from any source are held here with a reason, never silently
            dropped — click <span className="font-medium">View record</span> to see exactly
            what was submitted. Resolving is a human attestation of what you did about it
            (e.g. "corrected in the source spreadsheet, will re-sync"); it doesn't
            auto-correct or re-ingest the row — fix it upstream and run a new sync to load
            the corrected version.
          </p>
        </div>
        <label className="text-xs flex items-center gap-1.5">
          <input type="checkbox" checked={showResolved} onChange={(e) => { setShowResolved(e.target.checked); setPage(1) }} />
          Show resolved
        </label>
      </div>
      {!data ? <Spinner label="Loading quarantine…" /> : data.items.length === 0 ? (
        <div className="text-sm text-inkmute py-6 text-center">
          {showResolved ? 'No quarantined records at all.' : 'No unresolved quarantined records — nice.'}
        </div>
      ) : (
        <>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-inkmute border-b border-line">
                <th className="py-1.5 pr-3">Source</th><th className="py-1.5 pr-3">Reason</th>
                <th className="py-1.5 pr-3">Detail</th><th className="py-1.5 pr-3">Record</th>
                <th className="py-1.5">Action</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((q) => (
                <React.Fragment key={q.id}>
                  <tr className="border-b border-line last:border-0 align-top">
                    <td className="py-1.5 pr-3"><SourceSystemBadge source={q.source_system} /></td>
                    <td className="py-1.5 pr-3 text-xs font-medium text-flag">{q.reason_code}</td>
                    <td className="py-1.5 pr-3 text-xs max-w-sm">{q.reason_detail}</td>
                    <td className="py-1.5 pr-3">
                      <button onClick={() => setExpandedId(expandedId === q.id ? null : q.id)}
                        className="text-teal hover:underline text-xs">
                        {expandedId === q.id ? 'Hide' : 'View'} record
                      </button>
                    </td>
                    <td className="py-1.5">
                      {q.resolved ? (
                        <span className="text-xs text-ok">Resolved by {q.resolved_by}</span>
                      ) : canResolve ? (
                        <div className="flex gap-1.5 items-center">
                          <input placeholder="notes (optional)" value={notesById[q.id] || ''}
                            onChange={(e) => setNotesById((n) => ({ ...n, [q.id]: e.target.value }))}
                            className="text-xs border border-line rounded-sm px-1.5 py-1 w-32" />
                          <button onClick={() => resolve(q.id)}
                            className="text-xs bg-ink hover:bg-black text-white px-2 py-1 rounded-sm">
                            Resolve
                          </button>
                        </div>
                      ) : <span className="text-xs text-inkmute">Unresolved</span>}
                    </td>
                  </tr>
                  {expandedId === q.id && (
                    <tr>
                      <td colSpan={5} className="pb-3">
                        <pre className="text-[11px] bg-paper border border-line rounded-sm p-2 overflow-auto max-h-40">
                          {JSON.stringify(q.raw_record, null, 2)}
                        </pre>
                        {q.resolved && q.resolution_notes && (
                          <div className="text-xs text-inkmute mt-1">Resolution notes: {q.resolution_notes}</div>
                        )}
                      </td>
                    </tr>
                  )}
                </React.Fragment>
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

export default function DataIngestion({ user }) {
  const [runs, setRuns] = useState(null)
  const [syncingSource, setSyncingSource] = useState(null)
  const [err, setErr] = useState(null)
  const [partialFailure, setPartialFailure] = useState(null)
  const [refreshKey, setRefreshKey] = useState(0)

  const canSync = user?.role === 'Underwriter' || user?.role === 'Admin'

  const loadRuns = () => { api.ingestionRuns().then((d) => setRuns(d.items)).catch((e) => setErr(e.message)) }
  useEffect(() => { loadRuns() }, [])

  const latestRunBySource = (sourceId) => runs?.find((r) => r.source_system === sourceId)

  const doSync = async (sourceId) => {
    setSyncingSource(sourceId)
    setPartialFailure(null)
    try {
      const r = await api.ingestionSync(sourceId)
      logger.track('ingestion', `Ran ingestion sync for ${sourceId}.`, r)
      // A sync against "all" sources isolates failures per source rather than aborting the
      // whole batch (see backend/app/main.py) — one down source (e.g. vendor_api not
      // running) still shows up here even though the others succeeded.
      if (r.failures?.length) {
        setPartialFailure(`Sync failed for: ${r.failures.join(', ')} — check that service is reachable.`)
      }
      await loadRuns()
      setRefreshKey((k) => k + 1)  // provenance + quarantine panels don't poll on their own
    } catch (e) {
      setErr(e.message)
    } finally {
      setSyncingSource(null)
    }
  }

  if (err) return <div className="py-16 text-center text-flag text-sm">{err}</div>
  if (!runs) return <Spinner label="Loading data ingestion…" />

  const driftRuns = runs.filter((r) => r.schema_columns_added?.length)

  return (
    <div className="space-y-4">
      <div className="card p-6">
        <div className="label">Multi-Source Ingestion</div>
        <h1 className="text-2xl font-semibold mt-1">Data Ingestion</h1>
        <p className="text-sm text-inkmute mt-3 max-w-3xl leading-relaxed">
          Three fake source systems mirror what a bank's data estate actually looks like: a
          core-banking-style CSV drop, a mock valuation-vendor API, and a valuations-team
          spreadsheet. A <span className="font-medium">dlt</span> pipeline lands each into a
          canonical provenance ledger — malformed rows are quarantined with a reason instead of
          silently dropped, and a source can add a new column without breaking anything.
        </p>
        <div className="mt-3"><PipelineHealthStrip /></div>
        {canSync && (
          <button onClick={() => doSync('all')} disabled={syncingSource !== null}
            className="mt-4 bg-ink hover:bg-black text-white text-sm font-medium px-4 py-2 rounded-sm disabled:opacity-50">
            {syncingSource === 'all' ? 'Syncing all sources…' : 'Sync All Sources'}
          </button>
        )}
      </div>

      {partialFailure && (
        <div className="card p-4 border-flag/40 bg-flag/5 text-sm text-flag">
          {partialFailure}
        </div>
      )}

      {driftRuns.length > 0 && (
        <div className="card p-4 border-amber/40 bg-amber/5 text-sm">
          <span className="font-semibold text-amber">Schema drift detected: </span>
          {driftRuns.map((r) => (
            <span key={r.run_id} className="mr-3">
              <SourceSystemBadge source={r.source_system} /> added{' '}
              <span className="figure">{r.schema_columns_added.join(', ')}</span> (run #{r.run_id})
            </span>
          ))}
          — nothing broke; the new column just flowed through.
        </div>
      )}

      <div className="grid sm:grid-cols-3 gap-4">
        {SOURCES.map((s) => (
          <SourceCard key={s.id} source={s} latestRun={latestRunBySource(s.id)} canSync={canSync}
            onSync={doSync} syncing={syncingSource === s.id || syncingSource === 'all'} />
        ))}
      </div>

      <RunHistory runs={runs} />
      <ProvenanceGrid refreshKey={refreshKey} />
      <QuarantinePanel canResolve={canSync} refreshKey={refreshKey} />
    </div>
  )
}
