import React, { useEffect, useMemo, useState } from 'react'
import { api, tierColor, usd } from '../api.js'
import { Spinner } from '../components/shared.jsx'
import PropertyMap from '../components/PropertyMap.jsx'

const AMES_CENTER = [42.0308, -93.6319]

export default function MapView({ onOpen, height = 560 }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [statusFilter, setStatusFilter] = useState('')

  useEffect(() => {
    let active = true
    api.map()
      .then((res) => { if (active) setData(res) })
      .catch((e) => { if (active) setErr(e.message) })
    return () => { active = false }
  }, [])

  const points = useMemo(() => {
    if (!data) return []
    return statusFilter ? data.points.filter((p) => p.audit_status === statusFilter) : data.points
  }, [data, statusFilter])

  const totalValue = useMemo(() => points.reduce((sum, p) => sum + p.avm_value, 0), [points])

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
          aria-label="Filter map by audit status"
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

      <div className="card overflow-hidden">
        <PropertyMap points={points} center={AMES_CENTER} zoom={13} height={height} onOpen={onOpen} />
      </div>
      <div className="text-[11px] text-inkmute">
        Property coordinates are synthetically placed within their Ames Housing dataset neighborhood for visualization only — not surveyed addresses.
      </div>
    </div>
  )
}
