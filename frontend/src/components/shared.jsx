import React from 'react'
import { ltvTier, tierColor, pct } from '../api.js'

const statusStyle = {
  'Approved': 'bg-ok/10 text-ok border-ok/30',
  'Pending Review': 'bg-amber/10 text-amber border-amber/30',
  'Flagged: High Variance': 'bg-flag/10 text-flag border-flag/30',
}

export function StatusBadge({ status }) {
  return (
    <span className={`inline-block px-2 py-0.5 text-[11px] font-medium border rounded-sm ${statusStyle[status] || ''}`}>
      {status}
    </span>
  )
}

const modelStatusStyle = {
  'Champion': 'bg-tealdeep/10 text-tealdeep border-tealdeep/30',
  'Challenger': 'bg-amber/10 text-amber border-amber/30',
  'Retired': 'bg-inkmute/10 text-inkmute border-inkmute/30',
}

export function ModelStatusBadge({ status }) {
  return (
    <span className={`inline-block px-2 py-0.5 text-[11px] font-semibold border rounded-sm ${modelStatusStyle[status] || ''}`}>
      {status}
    </span>
  )
}

export function LtvChip({ ltv }) {
  const tier = ltvTier(ltv)
  return (
    <span className="figure text-[12px] font-semibold" style={{ color: tierColor[tier] }}>
      LTV {pct(ltv)}
    </span>
  )
}

export function Spinner({ label = 'Loading…' }) {
  return <div className="py-16 text-center text-inkmute text-sm">{label}</div>
}
