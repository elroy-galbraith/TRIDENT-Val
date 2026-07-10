import React, { useEffect, useState } from 'react'
import { api, ltvTier, tierColor, pct } from '../api.js'

export const FALLBACK_IMG =
  'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><rect width="100%25" height="100%25" fill="%23DDE3E0"/><text x="50%25" y="50%25" font-family="sans-serif" font-size="16" fill="%235B6B77" text-anchor="middle">Residential asset</text></svg>'

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

const sourceSystemStyle = {
  'core_banking': 'bg-tealdeep/10 text-tealdeep border-tealdeep/30',
  'valuation_vendor': 'bg-teal/10 text-teal border-teal/30',
  'valuations_team': 'bg-amber/10 text-amber border-amber/30',
}
const sourceSystemLabel = {
  'core_banking': 'Core Banking',
  'valuation_vendor': 'Valuation Vendor',
  'valuations_team': 'Valuations Team',
}

export function SourceSystemBadge({ source }) {
  return (
    <span className={`inline-block px-2 py-0.5 text-[11px] font-medium border rounded-sm ${sourceSystemStyle[source] || ''}`}>
      {sourceSystemLabel[source] || source}
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

// Labeled image carousel — no third-party slider dependency, just prev/next + dot controls.
// `index`/`onIndexChange` are optional: pass both to drive the carousel from an external
// control (e.g. a thumbnail rail) instead of its own internal state.
export function Carousel({ images, className = '', imgClassName = 'h-64',
  index: controlledIndex, onIndexChange, showDots = true }) {
  const [internalIndex, setInternalIndex] = useState(0)
  const list = images || []

  if (list.length === 0) {
    return (
      <div className={`${imgClassName} ${className} flex items-center justify-center bg-line/40 text-inkmute text-sm rounded-sm border border-line`}>
        No photos available
      </div>
    )
  }

  const rawIndex = controlledIndex != null ? controlledIndex : internalIndex
  const index = ((rawIndex % list.length) + list.length) % list.length
  const img = list[index]
  const go = (n) => {
    const next = ((n % list.length) + list.length) % list.length
    if (onIndexChange) onIndexChange(next)
    else setInternalIndex(next)
  }

  return (
    <div className={className}>
      <div className="relative">
        <img
          key={img.url}
          src={img.url}
          alt={img.label || ''}
          onError={(e) => { e.currentTarget.onerror = null; e.currentTarget.src = FALLBACK_IMG }}
          className={`w-full ${imgClassName} object-cover rounded-sm border border-line`}
        />
        {list.length > 1 && (
          <>
            <button type="button" onClick={() => go(index - 1)} aria-label="Previous photo"
              className="absolute left-1.5 top-1/2 -translate-y-1/2 w-7 h-7 rounded-full bg-ink/60 hover:bg-ink/80 text-white text-base leading-none flex items-center justify-center">‹</button>
            <button type="button" onClick={() => go(index + 1)} aria-label="Next photo"
              className="absolute right-1.5 top-1/2 -translate-y-1/2 w-7 h-7 rounded-full bg-ink/60 hover:bg-ink/80 text-white text-base leading-none flex items-center justify-center">›</button>
            <div className="absolute top-2 right-2 bg-ink/60 text-white text-[11px] px-1.5 py-0.5 rounded-sm figure">
              {index + 1}/{list.length}
            </div>
          </>
        )}
        {img.label && (
          <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-ink/80 to-transparent text-white text-xs px-2.5 py-2 rounded-b-sm">
            {img.label}
          </div>
        )}
      </div>
      {showDots && list.length > 1 && (
        <div className="flex justify-center gap-1.5 mt-2">
          {list.map((im, idx) => (
            <button key={idx} type="button" onClick={() => go(idx)}
              aria-label={`Go to photo ${idx + 1}${im.label ? `: ${im.label}` : ''}`}
              className={`h-1.5 rounded-full transition-all ${idx === index ? 'w-4 bg-teal' : 'w-1.5 bg-line'}`} />
          ))}
        </div>
      )}
    </div>
  )
}

// Simple centered overlay modal — click the backdrop or the × to close. No focus-trap/portal
// library; scoped to the one in-app use case so far (viewing a PDF without leaving the tab).
export function Modal({ title, onClose, children, wide = false }) {
  return (
    <div className="fixed inset-0 z-50 bg-ink/60 flex items-center justify-center p-4"
      onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()}
        className={`bg-white rounded-sm shadow-lg w-full ${wide ? 'max-w-4xl' : 'max-w-lg'} max-h-[90vh] flex flex-col`}>
        <div className="flex items-center justify-between px-4 py-2.5 border-b border-line">
          <div className="text-sm font-medium">{title}</div>
          <button onClick={onClose} aria-label="Close" className="text-inkmute hover:text-ink text-lg leading-none px-1">×</button>
        </div>
        <div className="flex-1 overflow-auto">{children}</div>
      </div>
    </div>
  )
}

const healthChipStyle = {
  ok: 'bg-ok/10 text-ok border-ok/30',
  warn: 'bg-amber/10 text-amber border-amber/30',
  bad: 'bg-flag/10 text-flag border-flag/30',
}

function HealthChip({ label, tier, detail }) {
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 text-[11px] font-medium border rounded-sm ${healthChipStyle[tier]}`}
      title={detail || ''}>
      {label}
    </span>
  )
}

// Surfaces the health of everything the ingestion/extraction demos depend on but this app
// doesn't control: the standalone vendor_api service, LLM key configuration, and whether
// Docling is importable/warmed. Polls once on mount — good enough for "is today's demo going
// to work," not a live monitoring dashboard.
export function PipelineHealthStrip() {
  const [health, setHealth] = useState(null)

  useEffect(() => { api.pipelineHealth().then(setHealth).catch(() => setHealth(null)) }, [])

  if (!health) return null

  const docling = health.docling
  const doclingTier = !docling.importable ? 'bad' : docling.warm ? 'ok' : 'warn'
  const doclingLabel = !docling.importable ? 'Docling: unavailable'
    : docling.warm ? 'Docling: warm' : 'Docling: cold (first use will be slow)'

  return (
    <div className="flex flex-wrap gap-2 items-center text-xs">
      <span className="text-inkmute">Pipeline health:</span>
      <HealthChip label={`Vendor API: ${health.vendor_api.reachable ? 'reachable' : 'unreachable'}`}
        tier={health.vendor_api.reachable ? 'ok' : 'bad'}
        detail={health.vendor_api.error || health.vendor_api.base_url} />
      <HealthChip label={`Extraction LLM: ${health.extraction_llm_configured ? 'configured' : 'not configured'}`}
        tier={health.extraction_llm_configured ? 'ok' : 'bad'}
        detail={health.extraction_llm_model || 'set REPORT_LLM_PROVIDER_API_KEY or EXTRACTION_LLM_PROVIDER_API_KEY'} />
      <HealthChip label={`Report LLM: ${health.report_llm_configured ? 'configured' : 'not configured'}`}
        tier={health.report_llm_configured ? 'ok' : 'warn'}
        detail="Used for AI-drafted report narrative sections" />
      <HealthChip label={doclingLabel} tier={doclingTier}
        detail={docling.import_error || docling.warm_error || ''} />
    </div>
  )
}
