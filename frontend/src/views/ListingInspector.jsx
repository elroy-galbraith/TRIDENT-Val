import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Carousel, FALLBACK_IMG, Spinner } from '../components/shared.jsx'
import { fmtPrice } from '../components/ListingsShell.jsx'

const statusStyle = {
  parsed: 'bg-ok/10 text-ok border-ok/30',
  unparsed: 'bg-flag/10 text-flag border-flag/30',
  derived: 'bg-amber/10 text-amber border-amber/30',
  raw_only: 'bg-inkmute/10 text-inkmute border-inkmute/30',
  missing: 'bg-line/40 text-inkmute border-line',
}
const statusText = { parsed: 'parsed', unparsed: 'raw not parsed', derived: 'no raw text', raw_only: 'raw only', missing: 'missing' }

const show = (v) => (v == null || v === '' ? <span className="text-inkmute">—</span> : String(v))

function Link({ href }) {
  if (!href) return <span className="text-inkmute">—</span>
  return /^https?:/.test(href)
    ? <a href={href} target="_blank" rel="noopener noreferrer" className="text-teal hover:underline break-all">{href} ↗</a>
    : <span className="figure break-all" title="Private GCS object (not browser-openable)">{href}</span>
}

export default function ListingInspector({ recordId, onBack }) {
  const [d, setD] = useState(null)
  const [err, setErr] = useState(null)
  const [photo, setPhoto] = useState(0)
  useEffect(() => { setD(null); api.listing(recordId).then(setD).catch((e) => setErr(e.message)) }, [recordId])
  if (err) return <div className="card p-4 text-sm text-flag">Could not load listing: {err}</div>
  if (!d) return <Spinner label="Loading listing…" />

  const { summary: s, provenance: p, quality: q, record: r } = d
  const images = d.images.map((i) => ({ url: i.source_url, label: i.caption_raw }))
  const prov = [
    ['site_listing_ref', p.site_listing_ref], ['scrape_run_id', p.scrape_run_id],
    ['fetched_at', p.fetched_at], ['http_status', p.http_status],
    ['parser_version', p.parser_version], ['scraper_version', p.scraper_version],
    ['robots_allowed', p.robots_allowed == null ? null : String(p.robots_allowed)],
    ['record_id', r.record.record_id],
  ]

  return (
    <div className="space-y-4">
      <button onClick={onBack} className="text-sm text-teal hover:underline">← Back to listings</button>
      <div className="card p-5">
        <div className="label">{s.property_type_raw} · {s.listing_type_raw}</div>
        <h1 className="text-xl font-semibold mt-1">{s.title}</h1>
        <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1 mt-2">
          <span className="figure text-2xl font-semibold text-tealdeep">{fmtPrice(s.amount, s.currency)}</span>
          <span className="text-sm text-inkmute">{s.community}, {s.parish_raw}</span>
          <span className="text-xs text-inkmute figure">{s.latitude?.toFixed(5)}, {s.longitude?.toFixed(5)} · geo {s.geo_precision || '—'}</span>
        </div>
        <div className="flex flex-wrap gap-x-6 gap-y-1 mt-3 text-sm">
          <span>Listing page: <Link href={p.listing_url} /></span>
          {p.canonical_url && p.canonical_url !== p.listing_url && <span>Canonical: <Link href={p.canonical_url} /></span>}
        </div>
      </div>

      <div className="grid lg:grid-cols-3 gap-4 items-start">
        <div className="card p-5 lg:col-span-2">
          <div className="label mb-2">Parsed vs raw</div>
          <table className="w-full text-sm">
            <thead className="text-inkmute text-xs text-left">
              <tr><th className="py-1 w-32">Field</th><th>Raw (as scraped)</th><th>Parsed</th><th className="w-32">Status</th></tr>
            </thead>
            <tbody>
              {d.comparison.map((c) => (
                <tr key={c.field} className="border-t border-line align-top">
                  <td className="py-1.5 font-medium">{c.field}</td>
                  <td className="figure text-xs break-words max-w-[16rem]">{show(c.raw)}</td>
                  <td className="figure text-xs">{show(c.parsed)}{c.parsed != null && c.extra ? ` ${c.extra}` : ''}</td>
                  <td><span className={`inline-block px-2 py-0.5 text-[11px] border rounded-sm ${statusStyle[c.status]}`}>{statusText[c.status]}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
          {r.attributes?.features_raw?.length > 0 && (
            <div className="mt-3 text-xs text-inkmute">Features: {r.attributes.features_raw.join(' · ')}</div>
          )}
        </div>

        <div className="space-y-4">
          <div className="card p-5">
            <div className="label mb-2">Provenance</div>
            <dl className="text-xs space-y-1">
              {prov.map(([k, v]) => (
                <div key={k} className="flex gap-2"><dt className="w-32 text-inkmute flex-none">{k}</dt><dd className="figure break-all">{show(v)}</dd></div>
              ))}
              <div className="flex gap-2"><dt className="w-32 text-inkmute flex-none">snapshot_uri</dt><dd><Link href={p.snapshot_uri} /></dd></div>
              <div className="flex gap-2"><dt className="w-32 text-inkmute flex-none">raw_payload_uri</dt><dd><Link href={p.raw_payload_uri} /></dd></div>
            </dl>
          </div>
          <div className="card p-5">
            <div className="label mb-2">Quality flags</div>
            <dl className="text-xs space-y-1">
              {['parse_errors', 'missing_required', 'pii_redacted'].map((k) => (
                <div key={k} className="flex gap-2"><dt className="w-32 text-inkmute flex-none">{k}</dt>
                  <dd className={`figure ${k !== 'pii_redacted' && q[k]?.length ? 'text-flag' : ''}`}>{q[k]?.length ? q[k].join(', ') : 'none'}</dd></div>
              ))}
              <div className="flex gap-2"><dt className="w-32 text-inkmute flex-none">duplicate_of</dt><dd className="figure">{show(q.duplicate_of)}</dd></div>
            </dl>
          </div>
        </div>
      </div>

      <div className="card p-5">
        <div className="label mb-2">Photos ({images.length})</div>
        {images.length === 0 ? <div className="text-sm text-inkmute">No images recorded.</div> : (
          <div className="flex flex-col md:flex-row gap-4">
            <Carousel images={images} index={photo} onIndexChange={setPhoto} showDots={false}
              className="md:w-[440px] flex-none" imgClassName="h-72" />
            <div className="flex-1 grid grid-cols-[repeat(auto-fill,minmax(110px,1fr))] gap-2 content-start">
              {d.images.map((im, idx) => (
                <button key={im.source_url} type="button" onClick={() => setPhoto(idx)}
                  className={`text-left rounded-sm overflow-hidden border ${idx === photo ? 'border-teal ring-1 ring-teal' : 'border-line hover:border-teal/50'}`}>
                  <img src={im.source_url} alt="" loading="lazy" referrerPolicy="no-referrer"
                    onError={(e) => { e.currentTarget.onerror = null; e.currentTarget.src = FALLBACK_IMG }}
                    className="w-full h-16 object-cover" />
                  <div className="text-[10px] px-1.5 py-1 text-inkmute figure">#{im.order_index}{im.is_primary ? ' · primary' : ''} · {im.download_status}</div>
                </button>
              ))}
            </div>
          </div>
        )}
        <div className="text-[11px] text-inkmute mt-2">Images are hotlinked from the source site's CDN; none have been downloaded to storage.</div>
      </div>

      {r.listing?.description && (
        <div className="card p-5">
          <div className="label mb-2">Description (raw)</div>
          <p className="text-sm leading-relaxed whitespace-pre-line">{r.listing.description}</p>
        </div>
      )}
    </div>
  )
}
