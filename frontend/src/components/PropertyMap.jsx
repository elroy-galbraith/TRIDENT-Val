import React, { useMemo } from 'react'
import { CircleMarker, MapContainer, Popup, TileLayer } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import { ltvTier, tierColor, usd, pct } from '../api.js'
import { StatusBadge } from './shared.jsx'

const MIN_R = 3.5
const MAX_R = 13
const SUBJECT_R = MAX_R + 6

function radiusScale(value, min, max) {
  if (max === min) return (MIN_R + MAX_R) / 2
  const t = (value - min) / (max - min)
  return MIN_R + t * (MAX_R - MIN_R)
}

export default function PropertyMap({ points, center, zoom = 13, height = 480, subjectPid, onOpen }) {
  const { min, max } = useMemo(() => {
    if (!points.length) return { min: 0, max: 0 }
    let minVal = Infinity
    let maxVal = -Infinity
    for (const p of points) {
      if (p.avm_value < minVal) minVal = p.avm_value
      if (p.avm_value > maxVal) maxVal = p.avm_value
    }
    return { min: minVal, max: maxVal }
  }, [points])

  return (
    <MapContainer center={center} zoom={zoom} preferCanvas style={{ height, width: '100%' }}>
      <TileLayer
        attribution="&copy; OpenStreetMap contributors"
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      {points.map((p) => {
        const tier = ltvTier(p.ltv)
        const isSubject = p.pid === subjectPid
        return (
          <CircleMarker
            key={p.pid}
            center={[p.lat, p.lng]}
            radius={isSubject ? SUBJECT_R : radiusScale(p.avm_value, min, max)}
            pathOptions={{
              color: isSubject ? '#16232E' : tierColor[tier],
              fillColor: tierColor[tier],
              fillOpacity: isSubject ? 0.9 : 0.55,
              weight: isSubject ? 3 : 1,
            }}
          >
            <Popup>
              <div className="space-y-1 text-sm min-w-[180px]">
                <div className="flex items-center justify-between gap-2">
                  <span className="figure font-semibold">
                    PID {p.pid}{isSubject && <span className="text-inkmute font-normal"> · subject</span>}
                  </span>
                  <StatusBadge status={p.audit_status} />
                </div>
                <div className="text-xs text-inkmute">{p.neighborhood} · {p.bldg_type}</div>
                <div className="flex items-baseline justify-between pt-1">
                  <span className="figure font-semibold text-tealdeep">{usd(p.avm_value)}</span>
                  <span className="figure text-xs" style={{ color: tierColor[tier] }}>LTV {pct(p.ltv)}</span>
                </div>
                {onOpen && !isSubject && (
                  <button
                    onClick={(e) => { e.stopPropagation(); onOpen(p.pid) }}
                    className="text-teal hover:underline text-xs pt-1"
                  >
                    Open in Portfolio →
                  </button>
                )}
              </div>
            </Popup>
          </CircleMarker>
        )
      })}
    </MapContainer>
  )
}
