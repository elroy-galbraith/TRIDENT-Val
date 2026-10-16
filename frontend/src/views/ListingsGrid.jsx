import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import { FALLBACK_IMG, Spinner } from '../components/shared.jsx'
import { fmtNum, fmtPrice } from '../components/ListingsShell.jsx'

const SELECTS = [
  ['parish', 'All parishes'], ['property_type', 'All property types'], ['listing_type', 'All listing types'],
  ['currency', 'All currencies'], ['amount_parse_status', 'Any parse status'],
  ['geo_precision', 'Any geo precision'], ['scrape_run_id', 'All scrape runs'],
]
const SORTS = { price_desc: 'Highest price', price_asc: 'Lowest price', area_desc: 'Largest floor area', fetched_desc: 'Newest fetch' }

function Card({ it, onOpen }) {
  return (
    <button onClick={() => onOpen(it.record_id)}
      className="card text-left overflow-hidden hover:shadow-md hover:border-teal transition-all"
      style={{ borderTopWidth: 3, borderTopColor: it.has_parse_errors ? '#B3352C' : '#0F6E6E' }}>
      <img src={it.primary_image_url || FALLBACK_IMG} alt="" loading="lazy" referrerPolicy="no-referrer"
        onError={(e) => { e.currentTarget.onerror = null; e.currentTarget.src = FALLBACK_IMG }}
        className="w-full h-36 object-cover" />
      <div className="p-3 space-y-1.5">
        <div className="figure text-lg font-semibold text-tealdeep">{fmtPrice(it.amount, it.currency)}</div>
        <div className="text-sm font-medium truncate" title={it.title}>{it.title}</div>
        <div className="text-xs text-inkmute">{it.property_type_raw} · {it.listing_type_raw}</div>
        <div className="text-xs text-inkmute">{it.community}, {it.parish_raw}</div>
        <div className="text-xs text-inkmute">
          {it.bedrooms ?? '—'} bd · {it.bathrooms ?? '—'} ba · {it.floor_area != null ? `${fmtNum(it.floor_area)} ${it.floor_area_unit || ''}` : '— area'}
        </div>
        <div className="flex justify-between text-[11px] text-inkmute pt-1 border-t border-line">
          <span className="figure">{it.site_listing_ref}</span>
          <span>{it.image_count} photo{it.image_count === 1 ? '' : 's'}</span>
        </div>
      </div>
    </button>
  )
}

export default function ListingsGrid({ onOpen, initialFilters }) {
  const [opts, setOpts] = useState(null)
  const [filters, setFilters] = useState({ search: '', sort: 'price_desc', ...initialFilters })
  const [page, setPage] = useState(1)
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)

  useEffect(() => { api.listingsFilters().then(setOpts).catch((e) => setErr(e.message)) }, [])
  useEffect(() => {
    const params = { page, page_size: 24 }
    for (const [k, v] of Object.entries(filters)) if (v) params[k] = v
    setData(null)
    api.listings(params).then(setData).catch((e) => setErr(e.message))
  }, [filters, page])

  const set = (k) => (e) => { setPage(1); setFilters((f) => ({ ...f, [k]: e.target.value })) }
  const active = Object.entries(filters).filter(([k, v]) => v && k !== 'sort')
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1
  if (err) return <div className="card p-4 text-sm text-flag">Could not load listings: {err}</div>

  return (
    <div className="space-y-4">
      <div className="card p-3 flex flex-wrap gap-2 items-center">
        <input value={filters.search} onChange={set('search')} placeholder="Search title, community, MLS ref"
          aria-label="Search listings"
          className="border border-line rounded-sm px-3 py-1.5 text-sm w-56 focus:outline-none focus:border-teal" />
        {SELECTS.map(([k, ph]) => (
          <select key={k} value={filters[k] || ''} onChange={set(k)} aria-label={ph}
            className="border border-line rounded-sm px-2 py-1.5 text-sm bg-white max-w-[12rem]">
            <option value="">{ph}</option>
            {opts?.[k]?.map((o) => <option key={o}>{o}</option>)}
          </select>
        ))}
        <select value={filters.missing_field || ''} onChange={set('missing_field')} aria-label="Missing field"
          className="border border-line rounded-sm px-2 py-1.5 text-sm bg-white">
          <option value="">Any completeness</option>
          {opts?.missing_field.map((o) => <option key={o} value={o}>Missing {o}</option>)}
        </select>
        {active.length > 0 && (
          <button onClick={() => { setPage(1); setFilters({ search: '', sort: filters.sort }) }}
            className="px-3 py-1.5 border border-line rounded-sm text-sm bg-white hover:border-teal">Clear filters</button>
        )}
        <select value={filters.sort} onChange={set('sort')} aria-label="Sort listings"
          className="border border-line rounded-sm px-2 py-1.5 text-sm bg-white ml-auto">
          {Object.entries(SORTS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
      </div>
      {!data ? <Spinner label="Loading listings…" /> : (
        <>
          <div className="text-xs text-inkmute">{data.total.toLocaleString()} listings match</div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {data.items.map((it) => <Card key={it.record_id} it={it} onOpen={onOpen} />)}
          </div>
          <div className="flex items-center justify-center gap-3 py-3 text-sm">
            <button disabled={page <= 1} onClick={() => setPage(page - 1)} aria-label="Previous page"
              className="px-3 py-1 border border-line rounded-sm disabled:opacity-40 bg-white">← Prev</button>
            <span className="figure text-inkmute">Page {page} / {pages}</span>
            <button disabled={page >= pages} onClick={() => setPage(page + 1)} aria-label="Next page"
              className="px-3 py-1 border border-line rounded-sm disabled:opacity-40 bg-white">Next →</button>
          </div>
        </>
      )}
    </div>
  )
}
