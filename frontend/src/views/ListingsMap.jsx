import React, { useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'
import PropertyMap from '../components/PropertyMap.jsx'
import { Spinner } from '../components/shared.jsx'
import { fmtPrice } from '../components/ListingsShell.jsx'

const FILTERS = [['parish', 'All parishes'], ['property_type', 'All property types'],
  ['listing_type', 'All listing types'], ['currency', 'All currencies'], ['geo_precision', 'Any geo precision']]
const PALETTE = ['#0E7C7B', '#C77D0A', '#B3352C', '#3A6EA5', '#7A5C9E', '#5B8C3A', '#C2578A', '#8C6A3F', '#4A9CA6']
const BAND_COLORS = ['#9CC9C8', '#4FA3A2', '#0E7C7B', '#0A3F3E']
const CENTER = [18.15, -77.3]
const PROBLEM_LABEL = {
  lat_lon_swapped: 'latitude/longitude look swapped', longitude_sign_lost: 'longitude sign lost',
  outside_jamaica: 'outside Jamaica', null_island: '(0, 0)',
}

const quartileOf = (sorted, v) => {
  const i = sorted.findIndex((x) => v <= x)
  return Math.min(3, Math.floor(((i < 0 ? sorted.length - 1 : i) / sorted.length) * 4))
}

export default function ListingsMap({ onOpen, initialFilters }) {
  const [opts, setOpts] = useState(null)
  const [filters, setFilters] = useState({ ...initialFilters })
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [colorBy, setColorBy] = useState('property_type')
  const [source, setSource] = useState('')
  const [onlyCluster, setOnlyCluster] = useState(null)
  const [latest, setLatest] = useState(true)

  useEffect(() => { api.listingsFilters().then(setOpts).catch((e) => setErr(e.message)) }, [])
  useEffect(() => {
    const params = latest ? { latest_only: true } : {}
    for (const [k, v] of Object.entries(filters)) if (v && k !== 'sort') params[k] = v
    setData(null); setOnlyCluster(null)
    api.listingsGeo(params).then(setData).catch((e) => setErr(e.message))
  }, [filters, latest])

  const sources = useMemo(() => Object.keys(data?.geo_source || {}), [data])
  const typeColor = useMemo(() => {
    const types = [...new Set((data?.points || []).map((p) => p.property_type_raw || '(missing)'))].sort()
    return Object.fromEntries(types.map((t, i) => [t, PALETTE[i % PALETTE.length]]))
  }, [data])
  const bands = useMemo(() => {
    const by = {}
    for (const p of data?.points || []) if (p.amount != null) (by[p.currency] ||= []).push(p.amount)
    for (const c of Object.keys(by)) by[c].sort((a, b) => a - b)
    return by
  }, [data])

  const visible = useMemo(() => (data?.points || []).filter((p) => !p.problem
    && (!source || p.geo_source === source)
    && (!onlyCluster || onlyCluster.record_ids.includes(p.record_id))), [data, source, onlyCluster])
  const points = useMemo(() => visible.map((p) => ({ ...p, pid: p.record_id, lat: p.latitude, lng: p.longitude })), [visible])

  const pointStyle = (p) => {
    const color = colorBy === 'property_type'
      ? typeColor[p.property_type_raw || '(missing)']
      : p.amount != null && bands[p.currency] ? BAND_COLORS[quartileOf(bands[p.currency], p.amount)] : '#9AA5AD'
    const shared = p.shared_count >= (data?.min_cluster || 3)
    return { color, stroke: shared ? '#B3352C' : color, weight: shared ? 2 : 1,
             radius: shared ? Math.min(14, 5 + Math.log2(p.shared_count)) : 5, fillOpacity: 0.6 }
  }
  const renderPopup = (p) => (
    <div className="space-y-1 text-sm min-w-[180px]">
      <div className="font-semibold">{p.title}</div>
      <div className="text-xs text-inkmute">{p.property_type_raw} · {p.listing_type_raw}</div>
      <div className="figure text-tealdeep font-semibold">{fmtPrice(p.amount, p.currency)}</div>
      <div className="text-xs text-inkmute">{p.community}, {p.parish_raw}</div>
      <div className="text-xs text-inkmute">precision: {p.geo_precision || '—'} · source: {p.geo_source || '—'}</div>
      {p.shared_count > 1 && <div className="text-xs text-flag">{p.shared_count} listings share these exact coordinates</div>}
      <button onClick={() => onOpen(p.record_id)} className="text-teal hover:underline text-xs pt-1">Open in inspector →</button>
    </div>
  )

  const set = (k) => (e) => setFilters((f) => ({ ...f, [k]: e.target.value }))
  if (err) return <div className="card p-4 text-sm text-flag">Could not load map data: {err}</div>
  const legend = colorBy === 'property_type' ? Object.entries(typeColor)
    : BAND_COLORS.map((c, i) => [`quartile ${i + 1}${i === 0 ? ' (lowest)' : i === 3 ? ' (highest)' : ''}`, c])

  return (
    <div className="space-y-3">
      <div className="card p-3 flex flex-wrap gap-2 items-center">
        {FILTERS.map(([k, ph]) => (
          <select key={k} value={filters[k] || ''} onChange={set(k)} aria-label={ph}
            className="border border-line rounded-sm px-2 py-1.5 text-sm bg-white max-w-[12rem]">
            <option value="">{ph}</option>
            {opts?.[k]?.map((o) => <option key={o}>{o}</option>)}
          </select>
        ))}
        <select value={source} onChange={(e) => setSource(e.target.value)} aria-label="Geo source"
          className="border border-line rounded-sm px-2 py-1.5 text-sm bg-white">
          <option value="">Any geo source</option>
          {sources.map((s) => <option key={s}>{s}</option>)}
        </select>
        <label className="flex items-center gap-1.5 text-sm" title="Collapse repeat observations of the same MLS ref">
          <input type="checkbox" checked={latest} onChange={(e) => setLatest(e.target.checked)} />Latest observation only
        </label>
        <div className="flex border border-line rounded-sm overflow-hidden text-sm ml-auto" role="group" aria-label="Colour by">
          {[['property_type', 'Property type'], ['price', 'Price band']].map(([id, l]) => (
            <button key={id} onClick={() => setColorBy(id)}
              className={`px-3 py-1.5 ${colorBy === id ? 'bg-teal text-white' : 'bg-white text-inkmute'}`}>{l}</button>
          ))}
        </div>
      </div>

      {!data ? <Spinner label="Loading map data…" /> : (
        <div className="grid lg:grid-cols-[1fr_22rem] gap-4">
          <div className="space-y-2">
            <div className="card overflow-hidden">
              <PropertyMap points={points} center={CENTER} zoom={9} height={560}
                pointStyle={pointStyle} renderPopup={renderPopup} />
            </div>
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-inkmute">
              {colorBy === 'price' && <span>Price quartile within each currency (never compared across currencies) ·</span>}
              {legend.map(([l, c]) => (
                <span key={l} className="inline-flex items-center gap-1">
                  <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ background: c }} />{l}
                </span>
              ))}
              <span className="inline-flex items-center gap-1">
                <span className="inline-block w-2.5 h-2.5 rounded-full border-2 border-flag" />shared coordinates (larger = more)
              </span>
            </div>
          </div>

          <aside className="space-y-3 text-sm">
            <div className="card p-3 space-y-1">
              <div className="font-semibold">Geometry check</div>
              <div className="text-xs text-inkmute">
                {data.with_coordinates} of {data.total} listings have coordinates ({data.without_coordinates} do not).
                Showing {points.length} pins inside Jamaica's box.{data.duplicates_excluded > 0 && ` ${data.duplicates_excluded} repeat observations of the same MLS ref are collapsed.`}
              </div>
              <div className="text-xs text-inkmute">
                Precision: {Object.entries(data.geo_precision).map(([k, v]) => `${k} ${v}`).join(' · ') || '—'}
              </div>
              <div className="text-xs text-inkmute">
                Source: {Object.entries(data.geo_source).map(([k, v]) => `${k} ${v}`).join(' · ') || '—'}
              </div>
            </div>

            <div className="card p-3 space-y-1">
              <div className="font-semibold">Outside Jamaica ({data.outside_bbox.length})</div>
              {data.outside_bbox.length === 0 ? <div className="text-xs text-inkmute">None.</div> : (
                <ul className="max-h-48 overflow-y-auto divide-y divide-line">
                  {data.outside_bbox.map((p) => (
                    <li key={p.record_id} className="py-1">
                      <button onClick={() => onOpen(p.record_id)} className="text-teal hover:underline text-left text-xs">{p.title}</button>
                      <div className="text-[11px] text-inkmute figure">
                        {p.latitude}, {p.longitude} · {PROBLEM_LABEL[p.problem]} · listed in {p.parish_raw || '—'}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="card p-3 space-y-1">
              <div className="font-semibold">Shared coordinates ({data.clusters.length} clusters, {data.points_in_clusters} listings)</div>
              <div className="text-xs text-inkmute">
                ≥{data.min_cluster} different MLS refs at the identical point — usually a parish/community centroid fallback, not a real address.
              </div>
              {onlyCluster && (
                <button onClick={() => setOnlyCluster(null)} className="text-xs text-teal hover:underline">Show all pins</button>
              )}
              <ul className="max-h-72 overflow-y-auto divide-y divide-line">
                {data.clusters.map((c) => (
                  <li key={`${c.latitude},${c.longitude}`} className="py-1.5">
                    <button onClick={() => setOnlyCluster(onlyCluster === c ? null : c)}
                      className={`text-left w-full text-xs ${onlyCluster === c ? 'font-semibold' : ''}`}>
                      <span className="figure">{c.latitude}, {c.longitude}</span>
                      <span className="text-flag font-medium"> · {c.count} listings{c.observations > c.count ? ` (${c.observations} obs.)` : ''}</span>
                      <div className="text-[11px] text-inkmute">
                        {c.communities.slice(0, 3).join(', ')}{c.communities.length > 3 ? ` +${c.communities.length - 3}` : ''}
                        {c.parishes.length > 1 ? ` · spans ${c.parishes.length} parishes` : ` · ${c.parishes[0]}`}
                      </div>
                      <div className="text-[11px] text-inkmute">
                        {Object.entries(c.geo_precision).map(([k, v]) => `${k} ${v}`).join(', ')} ·{' '}
                        {Object.entries(c.property_types).map(([k, v]) => `${k} ${v}`).join(', ')}
                      </div>
                    </button>
                  </li>
                ))}
                {data.clusters.length === 0 && <li className="py-1 text-xs text-inkmute">None.</li>}
              </ul>
            </div>
          </aside>
        </div>
      )}
    </div>
  )
}
