import React, { useEffect, useState } from 'react'
import { api, ltvTier, tierColor, usd } from '../api.js'
import { LtvChip, Spinner, StatusBadge } from '../components/shared.jsx'

const FALLBACK_IMG =
  'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><rect width="100%25" height="100%25" fill="%23DDE3E0"/><text x="50%25" y="50%25" font-family="sans-serif" font-size="16" fill="%235B6B77" text-anchor="middle">Residential asset</text></svg>'

function Card({ p, onOpen }) {
  const tier = ltvTier(p.ltv)
  return (
    <button
      onClick={() => onOpen(p.pid)}
      className="card text-left overflow-hidden hover:shadow-md hover:border-teal transition-all"
      style={{ borderTopWidth: 3, borderTopColor: tierColor[tier] }}
    >
      <div className="relative">
        <img
          src={p.image_url || FALLBACK_IMG}
          onError={(e) => { e.currentTarget.src = FALLBACK_IMG }}
          alt={`${p.bldg_type} in ${p.neighborhood}`}
          className="w-full h-40 object-cover"
          loading="lazy"
        />
        <div className="absolute top-2 right-2"><StatusBadge status={p.audit_status} /></div>
      </div>
      <div className="p-4 space-y-2">
        <div className="flex items-baseline justify-between">
          <div className="figure text-xl font-semibold text-tealdeep">{usd(p.avm_value)}</div>
          <LtvChip ltv={p.ltv} />
        </div>
        <div className="text-sm font-medium">{p.neighborhood} · {p.bldg_type} · {p.house_style}</div>
        <div className="text-xs text-inkmute">
          {p.beds} bd · {p.baths} ba · {p.total_sqft.toLocaleString()} sq ft total · Built {p.year_built}
        </div>
        <div className="flex justify-between text-xs text-inkmute pt-1 border-t border-line">
          <span className="figure">PID {p.pid}</span>
          <span className="figure">Loan {usd(p.loan_balance)}</span>
        </div>
      </div>
    </button>
  )
}

export default function PortfolioGrid({ onOpen, initialStatus }) {
  const [opts, setOpts] = useState(null)
  const [filters, setFilters] = useState({
    neighborhood: '', bldg_type: '', audit_status: initialStatus || '', search: '', sort: 'ltv_desc',
  })
  const [page, setPage] = useState(1)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => { api.filters().then(setOpts) }, [])
  useEffect(() => {
    setLoading(true)
    const params = { page, page_size: 24, sort: filters.sort }
    for (const k of ['neighborhood', 'bldg_type', 'audit_status', 'search'])
      if (filters[k]) params[k] = filters[k]
    api.properties(params).then((d) => { setData(d); setLoading(false) })
  }, [filters, page])

  const set = (k) => (e) => { setPage(1); setFilters((f) => ({ ...f, [k]: e.target.value })) }
  const pages = data ? Math.ceil(data.total / data.page_size) : 1

  return (
    <div className="space-y-4">
      <div className="card p-3 flex flex-wrap gap-2 items-center">
        <input
          value={filters.search} onChange={set('search')} placeholder="Search PID or neighborhood"
          aria-label="Search by PID or neighborhood"
          className="border border-line rounded-sm px-3 py-1.5 text-sm w-56 focus:outline-none focus:border-teal"
        />
        <select value={filters.neighborhood} onChange={set('neighborhood')} aria-label="Filter by neighborhood" className="border border-line rounded-sm px-2 py-1.5 text-sm bg-white">
          <option value="">All neighborhoods</option>
          {opts?.neighborhoods.map((n) => <option key={n}>{n}</option>)}
        </select>
        <select value={filters.bldg_type} onChange={set('bldg_type')} aria-label="Filter by property type" className="border border-line rounded-sm px-2 py-1.5 text-sm bg-white">
          <option value="">All property types</option>
          {opts?.bldg_types.map((n) => <option key={n}>{n}</option>)}
        </select>
        <select value={filters.audit_status} onChange={set('audit_status')} aria-label="Filter by audit status" className="border border-line rounded-sm px-2 py-1.5 text-sm bg-white">
          <option value="">All audit statuses</option>
          {opts?.audit_statuses.map((n) => <option key={n}>{n}</option>)}
        </select>
        <select value={filters.sort} onChange={set('sort')} aria-label="Sort portfolio grid" className="border border-line rounded-sm px-2 py-1.5 text-sm bg-white ml-auto">
          <option value="ltv_desc">Highest LTV first</option>
          <option value="ltv_asc">Lowest LTV first</option>
          <option value="value_desc">Highest value first</option>
          <option value="value_asc">Lowest value first</option>
          <option value="pid">PID</option>
        </select>
        <a href={api.exportUrl} aria-label="Download portfolio as CSV" className="text-sm text-teal hover:underline px-2">Download CSV</a>
      </div>

      {loading ? <Spinner label="Loading inventory…" /> : (
        <>
          <div className="text-xs text-inkmute">{data.total.toLocaleString()} assets match</div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {data.items.map((p) => <Card key={p.pid} p={p} onOpen={onOpen} />)}
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
