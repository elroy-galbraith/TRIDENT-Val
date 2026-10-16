import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Spinner } from '../components/shared.jsx'
import { fmtNum } from '../components/ListingsShell.jsx'

function Bars({ title, rows, onPick, max = 12 }) {
  const top = Math.max(1, ...rows.map((r) => r.count))
  return (
    <div className="card p-4">
      <div className="label mb-2">{title}</div>
      <div className="space-y-1">
        {rows.slice(0, max).map((r) => (
          <button key={r.value} disabled={!onPick || r.value === '(missing)'} onClick={() => onPick?.(r.value)}
            className="w-full flex items-center gap-2 text-xs text-left enabled:hover:bg-line/40 rounded-sm">
            <span className="w-40 truncate" title={r.value}>{r.value}</span>
            <span className="flex-1 h-2 bg-line/50 rounded-sm">
              <span className="block h-2 bg-teal rounded-sm" style={{ width: `${(r.count / top) * 100}%` }} />
            </span>
            <span className="figure w-10 text-right">{r.count}</span>
          </button>
        ))}
        {rows.length > max && <div className="text-[11px] text-inkmute">+ {rows.length - max} more</div>}
      </div>
    </div>
  )
}

export default function ListingsQuality({ onFilter }) {
  const [s, setS] = useState(null)
  const [err, setErr] = useState(null)
  useEffect(() => { api.listingsSummary().then(setS).catch((e) => setErr(e.message)) }, [])
  if (err) return <div className="card p-4 text-sm text-flag">Could not load listings: {err}</div>
  if (!s) return <Spinner label="Loading listings quality…" />

  const types = [...new Set(s.property_by_listing_type.map((m) => m.listing_type))]
  const ptypes = [...new Set(s.property_by_listing_type.map((m) => m.property_type))]
  const cell = (p, l) => s.property_by_listing_type.find((m) => m.property_type === p && m.listing_type === l)?.count

  return (
    <div className="space-y-4">
      <div className="card p-5">
        <div className="label">Scraped listings · data validation</div>
        <h1 className="text-2xl font-semibold mt-1">{s.total.toLocaleString()} listing observations</h1>
        <p className="text-xs text-inkmute mt-1">Source: {s.source}. Read-only. Click a bar to open the grid filtered by it.</p>
        <div className="flex flex-wrap gap-6 mt-3 text-sm">
          <span>Parse errors: <b className="figure">{s.quality_flags.with_parse_errors}</b></span>
          <span>Missing required: <b className="figure">{s.quality_flags.with_missing_required}</b></span>
          <span>Marked duplicate: <b className="figure">{s.quality_flags.marked_duplicate}</b></span>
        </div>
      </div>

      <div className="grid lg:grid-cols-2 gap-4">
        <div className="card p-4">
          <div className="label mb-2">Fill rate per field (click to list rows missing it)</div>
          <div className="space-y-1">
            {s.fill_rates.map((f) => (
              <button key={f.field} disabled={f.rate >= 1 || f.field.startsWith('images')}
                onClick={() => onFilter({ missing_field: f.field })}
                className="w-full flex items-center gap-2 text-xs text-left enabled:hover:bg-line/40 rounded-sm">
                <span className="w-48 truncate figure">{f.field}</span>
                <span className="flex-1 h-2 bg-line/50 rounded-sm">
                  <span className="block h-2 rounded-sm"
                    style={{ width: `${f.rate * 100}%`, background: f.rate === 0 ? '#B3352C' : f.rate < 0.5 ? '#C77D0A' : '#0F6E6E' }} />
                </span>
                <span className="figure w-24 text-right">{(f.rate * 100).toFixed(1)}% · {f.count}</span>
              </button>
            ))}
          </div>
        </div>
        <div className="space-y-4">
          <div className="card p-4">
            <div className="label mb-2">Parser gaps (raw text present, parsed value missing)</div>
            <table className="w-full text-xs">
              <tbody>
                {s.parse_gaps.map((g) => (
                  <tr key={g.pair} className="border-t border-line first:border-0">
                    <td className="py-1 figure">{g.pair}</td>
                    <td className={`py-1 text-right figure ${g.raw_present_parsed_missing ? 'text-flag font-semibold' : 'text-inkmute'}`}>
                      {g.raw_present_parsed_missing}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="card p-4">
            <div className="label mb-2">Asking price by currency (not comparable across currencies)</div>
            <table className="w-full text-xs figure">
              <thead className="text-inkmute text-left"><tr><th>Cur.</th><th>n</th><th>Min</th><th>Median</th><th>Max</th></tr></thead>
              <tbody>
                {s.price_by_currency.map((p) => (
                  <tr key={p.currency} className="border-t border-line">
                    <td className="py-1">{p.currency}</td><td>{p.count}</td>
                    <td>{fmtNum(p.min)}</td><td>{fmtNum(p.p50)}</td><td>{fmtNum(p.max)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
        <Bars title="amount_parse_status" rows={s.amount_parse_status} onPick={(v) => onFilter({ amount_parse_status: v })} />
        <Bars title="Currency" rows={s.currency} onPick={(v) => onFilter({ currency: v })} />
        <Bars title="currency_source" rows={s.currency_source} />
        <Bars title="geo_source" rows={s.geo_source} />
        <Bars title="geo_precision" rows={s.geo_precision} onPick={(v) => onFilter({ geo_precision: v })} />
        <Bars title="Parish" rows={s.parish} onPick={(v) => onFilter({ parish: v })} />
        <Bars title="Property type" rows={s.property_type} onPick={(v) => onFilter({ property_type: v })} />
        <Bars title="Listing type" rows={s.listing_type} onPick={(v) => onFilter({ listing_type: v })} />
        <Bars title="parser_version" rows={s.parser_version} />
        <Bars title="http_status" rows={s.http_status} />
        <Bars title="robots_allowed" rows={s.robots_allowed} />
      </div>

      <div className="card p-4 overflow-x-auto">
        <div className="label mb-2">Property type × listing type</div>
        <table className="text-xs figure">
          <thead><tr><th className="text-left pr-4 text-inkmute">property_type_raw</th>
            {types.map((t) => <th key={t} className="px-3 text-right text-inkmute">{t}</th>)}</tr></thead>
          <tbody>
            {ptypes.map((p) => (
              <tr key={p} className="border-t border-line">
                <td className="py-1 pr-4">{p}</td>
                {types.map((t) => (
                  <td key={t} className="px-3 text-right">
                    {cell(p, t) ? (
                      <button className="text-teal hover:underline"
                        onClick={() => onFilter({ property_type: p, listing_type: t })}>{cell(p, t)}</button>
                    ) : <span className="text-inkmute">·</span>}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid lg:grid-cols-2 gap-4">
        <div className="card p-4 overflow-x-auto">
          <div className="label mb-2">Rows per scrape run</div>
          <table className="w-full text-xs">
            <thead className="text-inkmute text-left"><tr><th>scrape_run_id</th><th>rows</th><th>first fetch</th><th>last fetch</th></tr></thead>
            <tbody>
              {s.rows_per_run.map((r) => (
                <tr key={r.scrape_run_id} className="border-t border-line">
                  <td className="py-1"><button className="text-teal hover:underline figure" onClick={() => onFilter({ scrape_run_id: r.scrape_run_id })}>{r.scrape_run_id}</button></td>
                  <td className="figure">{r.count}</td>
                  <td className="figure">{String(r.first_fetched_at).slice(0, 19).replace('T', ' ')}</td>
                  <td className="figure">{String(r.last_fetched_at).slice(0, 19).replace('T', ' ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Bars title="Rows per fetch date" rows={s.rows_per_fetch_date.map((d) => ({ value: d.fetched_date, count: d.count }))} />
      </div>
    </div>
  )
}
