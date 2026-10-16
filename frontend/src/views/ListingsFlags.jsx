import React, { useCallback, useEffect, useState } from 'react'
import { api } from '../api.js'
import { Spinner } from '../components/shared.jsx'

export const REASON_LABEL = {
  wrong_value: 'Wrong value', not_parsed: 'Not parsed', wrong_unit: 'Wrong unit',
  wrong_currency: 'Wrong currency', wrong_category: 'Wrong category', other: 'Other',
}

const cell = (v) => (v == null || v === '' ? <span className="text-inkmute">—</span> : String(v))

export default function ListingsFlags({ user, onOpen }) {
  const [meta, setMeta] = useState(null)
  const [f, setF] = useState({ status: 'open', field: '', reason: '' })
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const isAdmin = user?.role === 'Admin'

  useEffect(() => { api.listingFlagsMeta().then(setMeta).catch(() => {}) }, [])
  const load = useCallback(() => {
    const params = Object.fromEntries(Object.entries(f).filter(([, v]) => v))
    api.listingFlags(params).then(setData).catch((e) => setErr(e.message))
  }, [f])
  useEffect(load, [load])

  const act = async (fn) => { try { await fn(); load() } catch (e) { setErr(e.message) } }
  const resolve = (x) => {
    const note = window.prompt('Resolution note (e.g. the parser fix):', '')
    if (note !== null) act(() => api.resolveListingFlag(x.id, note))
  }
  const del = (x) => { if (window.confirm(`Delete flag #${x.id}?`)) act(() => api.deleteListingFlag(x.id)) }

  const sel = 'border border-line rounded-sm px-2 py-1 bg-white text-sm'
  return (
    <div className="space-y-4">
      <div className="card p-5">
        <div className="label">Bad-parse flags</div>
        <h1 className="text-xl font-semibold mt-1">Fields reviewers marked as wrongly parsed</h1>
        <p className="text-xs text-inkmute mt-1">
          Flags are stored in TRIDENT-Val's own database — nothing is written back to the listings table or storage.
          Raise one from a listing's inspector (Parsed vs raw → ⚑). Export the CSV to turn open flags into parser fixes.
        </p>
        <div className="flex flex-wrap items-center gap-3 mt-3">
          <select className={sel} value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}>
            <option value="open">Open</option><option value="resolved">Resolved</option><option value="">All statuses</option>
          </select>
          <select className={sel} value={f.field} onChange={(e) => setF({ ...f, field: e.target.value })}>
            <option value="">All fields</option>
            {(meta?.fields || []).map((x) => <option key={x}>{x}</option>)}
          </select>
          <select className={sel} value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })}>
            <option value="">All reasons</option>
            {(meta?.reasons || []).map((x) => <option key={x} value={x}>{REASON_LABEL[x] || x}</option>)}
          </select>
          <a className="ml-auto text-sm text-teal hover:underline"
            href={api.listingFlagsExportUrl({ status: f.status, ...(f.field && { field: f.field }), ...(f.reason && { reason: f.reason }) })}>
            Export CSV ↓
          </a>
        </div>
      </div>

      {err && <div className="card p-3 text-sm text-flag">{err}</div>}
      {!data ? <Spinner label="Loading flags…" /> : (
        <div className="card p-4 overflow-x-auto">
          <div className="label mb-2">{data.total} flag{data.total === 1 ? '' : 's'}</div>
          {data.items.length === 0 ? (
            <div className="text-sm text-inkmute py-4">No flags match. Open a listing and use ⚑ next to a field to raise one.</div>
          ) : (
            <table className="w-full text-sm">
              <thead className="text-inkmute text-xs text-left"><tr>
                <th className="py-1">#</th><th>Listing</th><th>Field</th><th>Reason</th><th>Raw → parsed</th><th>Expected</th>
                <th>Note</th><th>By</th><th>Status</th><th /></tr></thead>
              <tbody>
                {data.items.map((x) => (
                  <tr key={x.id} className="border-t border-line align-top">
                    <td className="py-1.5 figure text-xs">{x.id}</td>
                    <td><button className="text-teal hover:underline figure text-xs" onClick={() => onOpen(x.record_id)}>{x.site_listing_ref || x.record_id.slice(0, 10)}</button></td>
                    <td>{x.field}</td>
                    <td className="text-xs">{REASON_LABEL[x.reason] || x.reason}</td>
                    <td className="figure text-xs max-w-[14rem] break-words">{cell(x.raw_value)} → {cell(x.parsed_value)}</td>
                    <td className="figure text-xs">{cell(x.expected_value)}</td>
                    <td className="text-xs max-w-xs break-words">{cell(x.note)}</td>
                    <td className="text-xs">{x.created_by}<div className="text-inkmute figure">{(x.created_at || '').slice(0, 16).replace('T', ' ')}</div></td>
                    <td className="text-xs">
                      {x.status === 'open' ? <span className="text-amber">open</span> : (
                        <span className="text-ok" title={x.resolution_note || ''}>resolved<div className="text-inkmute">{x.resolved_by}</div></span>
                      )}
                    </td>
                    <td className="text-xs whitespace-nowrap space-x-2">
                      {isAdmin && x.status === 'open' && <button className="text-teal hover:underline" onClick={() => resolve(x)}>Resolve</button>}
                      {isAdmin && <button className="text-flag hover:underline" onClick={() => del(x)}>Delete</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}
