import React, { useEffect, useMemo, useState } from 'react'
import { CircleMarker, MapContainer, Popup, TileLayer } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import { api, ltvTier, tierColor, usd, pct } from '../api.js'
import { Spinner, StatusBadge } from '../components/shared.jsx'

const AMES_CENTER = [42.0308, -93.6319]
const MIN_R = 3.5
const MAX_R = 13

function radiusScale(value, min, max) {
  if (max === min) return (MIN_R + MAX_R) / 2
  const t = (value - min) / (max - min)
  return MIN_R + t * (MAX_R - MIN_R)
}

export default function MapView({ onOpen }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [statusFilter, setStatusFilter] = useState('')

  useEffect(() => { api.map().then(setData).catch((e) => setErr(e.message)) }, [])

  const points = useMemo(() => {
    if (!data) return []
    return statusFilter ? data.points.filter((p) => p.audit_status === statusFilter) : data.points
  }, [data, statusFilter])

  const { min, max, totalValue } = useMemo(() => {
    if (!points.length) return { min: 0, max: 0, totalValue: 0 }
    const values = points.map((p) => p.avm_value)
    return {
      min: Math.min(...values),
      max: Math.max(...values),
      totalValue: values.reduce((a, b) => a + b, 0),
    }
  }, [points])

  if (err) return <div className="py-16 text-center text-flag text-sm">Couldn't load portfolio map: {err}</div>
  if (!data) return <Spinner label="Plotting portfolio…" />

  return (
    <div className="space-y-4">
      <div className="card p-3 flex flex-wrap items-center gap-3">
        <div className="text-xs text-inkmute">
          <span className="figure font-semibold text-ink">{points.length.toLocaleString()}</span> assets shown ·{' '}
          <span className="figure font-semibold text-ink">{usd(totalValue)}</span> aggregate AVM value
        </div>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="border border-line rounded-sm px-2 py-1.5 text-sm bg-white ml-auto"
        >
          <option value="">All audit statuses</option>
          <option value="Approved">Approved</option>
          <option value="Pending Review">Pending Review</option>
          <option value="Flagged: High Variance">Flagged: High Variance</option>
        </select>
        <div className="flex items-center gap-3 text-xs text-inkmute">
          {[
            ['low', 'LTV < 60%'],
            ['mid', 'LTV 60-80%'],
            ['high', 'LTV > 80%'],
          ].map(([tier, label]) => (
            <span key={tier} className="flex items-center gap-1">
              <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ background: tierColor[tier] }} />
              {label}
            </span>
          ))}
          <span className="pl-2 border-l border-line">Pin size ∝ AVM value</span>
        </div>
      </div>

      <div className="card overflow-hidden" style={{ height: 560 }}>
        <MapContainer center={AMES_CENTER} zoom={13} preferCanvas style={{ height: '100%', width: '100%' }}>
          <TileLayer
            attribution="&copy; OpenStreetMap contributors"
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          {points.map((p) => {
            const tier = ltvTier(p.ltv)
            return (
              <CircleMarker
                key={p.pid}
                center={[p.lat, p.lng]}
                radius={radiusScale(p.avm_value, min, max)}
                pathOptions={{
                  color: tierColor[tier],
                  fillColor: tierColor[tier],
                  fillOpacity: 0.55,
                  weight: 1,
                }}
              >
                <Popup>
                  <div className="space-y-1 text-sm min-w-[180px]">
                    <div className="flex items-center justify-between gap-2">
                      <span className="figure font-semibold">PID {p.pid}</span>
                      <StatusBadge status={p.audit_status} />
                    </div>
                    <div className="text-xs text-inkmute">{p.neighborhood} · {p.bldg_type}</div>
                    <div className="flex items-baseline justify-between pt-1">
                      <span className="figure font-semibold text-tealdeep">{usd(p.avm_value)}</span>
                      <span className="figure text-xs" style={{ color: tierColor[tier] }}>LTV {pct(p.ltv)}</span>
                    </div>
                    <button
                      onClick={() => onOpen(p.pid)}
                      className="text-teal hover:underline text-xs pt-1"
                    >
                      Open in Portfolio →
                    </button>
                  </div>
                </Popup>
              </CircleMarker>
            )
          })}
        </MapContainer>
      </div>
      <div className="text-[11px] text-inkmute">
        Property coordinates are synthetically placed within their Ames Housing dataset neighborhood for visualization only — not surveyed addresses.
      </div>
    </div>
  )
}
