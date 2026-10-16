import React, { useEffect, useMemo, useState } from 'react'
import { Bar, BarChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api.js'
import { Spinner } from '../components/shared.jsx'
import { fmtNum } from '../components/ListingsShell.jsx'

const compact = (n) => {
  if (n == null) return '—'
  const a = Math.abs(n)
  if (a >= 1e9) return `${+(n / 1e9).toPrecision(3)}B`
  if (a >= 1e6) return `${+(n / 1e6).toPrecision(3)}M`
  if (a >= 1e3) return `${+(n / 1e3).toPrecision(3)}k`
  return `${+n.toPrecision(3)}`
}

const METRICS = [
  { id: 'price', title: 'Asking price', hint: 'log scale · one chart per currency' },
  { id: 'price_per_area', title: 'Price per floor-area unit', hint: 'only sqft / sqm rows, never converted or mixed' },
  { id: 'floor_area', title: 'Floor area', hint: 'log scale · one chart per unit' },
  { id: 'lot_size', title: 'Lot size', hint: 'log scale · one chart per unit' },
]

function Histogram({ facet, title }) {
  const { bins, fences } = facet
  const data = bins.map((b) => ({ label: `${compact(b.lo)}–${compact(b.hi)}`, count: b.count, lo: b.lo, hi: b.hi }))
  const unitLabel = facet.metric === 'price' ? facet.facet : facet.metric === 'price_per_area' ? facet.facet : facet.unit
  const outlierBins = (v) => data.findIndex((d) => v >= d.lo && v <= d.hi)
  return (
    <div className="card p-3">
      <div className="flex items-baseline justify-between gap-2">
        <div className="text-sm font-semibold">{title} <span className="text-teal">· {unitLabel}</span></div>
        <div className="text-[11px] text-inkmute figure">n={facet.n} · median {compact(facet.median)}</div>
      </div>
      <div className="text-[11px] text-inkmute mb-1">
        range {compact(facet.min)} – {compact(facet.max)}
        {fences ? ` · fences ${compact(fences.low)} – ${compact(fences.high)}` : ' · too few rows to fence'}
        {facet.non_positive > 0 && ` · ${facet.non_positive} ≤0 excluded`}
      </div>
      <div style={{ height: 190 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: -12 }}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="label" tick={{ fontSize: 9 }} interval={Math.ceil(data.length / 6) - 1} />
            <YAxis allowDecimals={false} tick={{ fontSize: 10 }} />
            <Tooltip formatter={(v) => [v, 'listings']} labelFormatter={(l) => `${l} ${unitLabel}`} />
            <Bar dataKey="count" fill="#0E7C7B" />
            {fences && [fences.low, fences.high].map((v, i) => {
              const idx = outlierBins(v)
              return idx >= 0 ? <ReferenceLine key={i} x={data[idx].label} stroke="#B3352C" strokeDasharray="4 3" /> : null
            })}
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

function Heat({ mix, totals, onFilter }) {
  const ptypes = totals.map((t) => t.property_type)
  const ltypes = [...new Set(mix.map((m) => m.listing_type))].sort()
  const cell = (p, l) => mix.find((m) => m.property_type === p && m.listing_type === l)?.count || 0
  const max = Math.max(1, ...mix.map((m) => m.count))
  const total = totals.reduce((a, t) => a + t.count, 0)
  return (
    <div className="card p-4 space-y-3">
      <div>
        <div className="text-sm font-semibold">Property type × listing type</div>
        <div className="text-xs text-inkmute">
          Click a cell, row or column total to open the grid pre-filtered. This is a mixed bag — check the
          share column before reading any "average" listing.
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="text-sm w-full">
          <thead>
            <tr className="text-left text-xs text-inkmute">
              <th className="py-1 pr-3">Property type</th>
              {ltypes.map((l) => (
                <th key={l} className="py-1 px-2 text-center">
                  <button className="hover:underline" onClick={() => onFilter({ listing_type: l })}>{l}</button>
                </th>
              ))}
              <th className="py-1 px-2 text-right">Total</th>
              <th className="py-1 pl-3 w-48">Share of crawl</th>
            </tr>
          </thead>
          <tbody>
            {totals.map((t) => (
              <tr key={t.property_type} className="border-t border-line">
                <td className="py-1 pr-3">
                  <button className="hover:underline text-left" onClick={() => onFilter({ property_type: t.property_type })}>
                    {t.property_type}
                  </button>
                </td>
                {ltypes.map((l) => {
                  const c = cell(t.property_type, l)
                  return (
                    <td key={l} className="p-0.5 text-center">
                      <button disabled={!c} aria-label={`${t.property_type} ${l}: ${c}`}
                        onClick={() => onFilter({ property_type: t.property_type, listing_type: l })}
                        className="figure w-full py-1.5 rounded-sm disabled:text-inkmute/40 hover:ring-1 hover:ring-teal"
                        style={{ background: c ? `rgba(14,124,123,${0.12 + 0.75 * (c / max)})` : 'transparent',
                                 color: c / max > 0.55 ? '#fff' : undefined }}>
                        {c || '·'}
                      </button>
                    </td>
                  )
                })}
                <td className="px-2 text-right figure">{t.count}</td>
                <td className="pl-3">
                  <div className="flex items-center gap-2">
                    <div className="h-2 bg-teal/70" style={{ width: `${(100 * t.count) / total}%`, minWidth: 2 }} />
                    <span className="text-xs text-inkmute figure">{((100 * t.count) / total).toFixed(0)}%</span>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function Outliers({ items, rule, onOpen }) {
  const [metric, setMetric] = useState('')
  const shown = items.filter((o) => !metric || o.metric === metric)
  const metrics = [...new Set(items.map((o) => o.metric))]
  return (
    <div className="card p-4 space-y-2">
      <div className="flex flex-wrap items-baseline gap-3">
        <div className="text-sm font-semibold">Statistical outliers ({items.length})</div>
        <select value={metric} onChange={(e) => setMetric(e.target.value)} aria-label="Outlier metric"
          className="border border-line rounded-sm px-2 py-1 text-xs bg-white">
          <option value="">All metrics</option>
          {metrics.map((m) => <option key={m}>{m}</option>)}
        </select>
      </div>
      <div className="text-xs text-inkmute">Rule: {rule}. A flag means "look at the record", not "wrong".</div>
      <div className="overflow-x-auto max-h-80 overflow-y-auto">
        <table className="text-sm w-full">
          <thead className="text-left text-xs text-inkmute sticky top-0 bg-white">
            <tr><th className="py-1">Metric</th><th>Facet</th><th className="text-right">Value</th><th className="text-right">Fence</th>
              <th className="px-2">Severity</th><th>Listing</th></tr>
          </thead>
          <tbody>
            {shown.map((o, i) => (
              <tr key={`${o.record_id}-${o.metric}-${i}`} className="border-t border-line">
                <td className="py-1">{o.metric}</td>
                <td>{o.facet}</td>
                <td className="text-right figure">{fmtNum(o.value)}</td>
                <td className="text-right figure text-inkmute">{o.side === 'high' ? '>' : '<'} {fmtNum(o.fence)}</td>
                <td className={`px-2 ${o.severity === 'extreme' ? 'text-flag font-medium' : 'text-amber'}`}>{o.severity}</td>
                <td>
                  <button className="text-teal hover:underline text-left" onClick={() => onOpen(o.record_id)}>
                    {o.title || o.record_id}
                  </button>
                  <span className="text-xs text-inkmute"> · {o.property_type_raw}{o.metric !== 'price' && o.amount != null ? ` · ${o.currency} ${fmtNum(o.amount)}` : ''}</span>
                </td>
              </tr>
            ))}
            {shown.length === 0 && <tr><td colSpan={6} className="py-3 text-inkmute">No outliers flagged.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default function ListingsDistributions({ onFilter, onOpen }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [latest, setLatest] = useState(true)
  useEffect(() => {
    setData(null)
    api.listingsDistributions(latest ? { latest_only: true } : {}).then(setData).catch((e) => setErr(e.message))
  }, [latest])
  const byMetric = useMemo(() => {
    const m = {}
    for (const f of data?.facets || []) (m[f.metric] ||= []).push(f)
    return m
  }, [data])
  if (err) return <div className="card p-4 text-sm text-flag">Could not load distributions: {err}</div>
  if (!data) return <Spinner label="Computing distributions…" />
  const house = data.property_type_totals.find((t) => t.property_type === 'House')?.count || 0

  return (
    <div className="space-y-5">
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={latest} onChange={(e) => setLatest(e.target.checked)} />
        Latest observation per MLS ref only
        <span className="text-xs text-inkmute">
          ({latest ? `${data.duplicates_excluded} repeat observations excluded` : 'repeat observations of the same listing are counted multiple times'})
        </span>
      </label>
      <div className="text-sm text-inkmute">
        {data.total.toLocaleString()} listings · only <b className="text-ink">{house}</b> are houses
        ({((100 * house) / data.total).toFixed(0)}%); the rest is land, commercial, resort and other.
        Histograms use log-spaced bins; red dashed lines mark the outlier fences.
      </div>

      <Heat mix={data.property_by_listing_type} totals={data.property_type_totals} onFilter={onFilter} />

      {METRICS.map((m) => (
        <section key={m.id} className="space-y-2">
          <h3 className="text-sm font-semibold">{m.title} <span className="font-normal text-inkmute">· {m.hint}</span></h3>
          {m.id === 'price_per_area' && data.price_per_area_skipped_incomparable_unit > 0 && (
            <div className="text-xs text-inkmute">
              {data.price_per_area_skipped_incomparable_unit} listing(s) skipped: floor-area unit is not sqft/sqm.
            </div>
          )}
          {(byMetric[m.id] || []).length === 0 ? <div className="text-xs text-inkmute">No data.</div> : (
            <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-3">
              {byMetric[m.id].map((f) => <Histogram key={f.facet} facet={f} title={m.title} />)}
            </div>
          )}
        </section>
      ))}

      <section className="space-y-2">
        <h3 className="text-sm font-semibold">Bedrooms <span className="font-normal text-inkmute">· {data.bedrooms_missing} listings have no bedroom count</span></h3>
        <div className="card p-3" style={{ height: 220 }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data.bedrooms} margin={{ top: 4, right: 8, bottom: 0, left: -12 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="bedrooms" tick={{ fontSize: 11 }} />
              <YAxis allowDecimals={false} tick={{ fontSize: 10 }} />
              <Tooltip formatter={(v) => [v, 'listings']} labelFormatter={(l) => `${l} bedrooms`} />
              <Bar dataKey="count" fill="#0A5958" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </section>

      <Outliers items={data.outliers} rule={data.outlier_rule} onOpen={onOpen} />
    </div>
  )
}
