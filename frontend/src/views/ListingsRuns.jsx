import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Spinner } from '../components/shared.jsx'
import { fmtNum, fmtPrice } from '../components/ListingsShell.jsx'

const val = (v) => (v == null || v === '' ? <span className="text-inkmute">∅</span> : String(typeof v === 'number' ? v.toLocaleString() : v))
const short = (id) => (id.length > 34 ? `${id.slice(0, 31)}…` : id)

function Stat({ label, value, tone, active, onClick }) {
  const cls = active ? 'border-teal ring-1 ring-teal' : 'border-line'
  const inner = (
    <>
      <div className="label">{label}</div>
      <div className={`figure text-2xl font-semibold ${tone || ''}`}>{fmtNum(value)}</div>
    </>
  )
  return onClick
    ? <button onClick={onClick} className={`card p-3 text-left border ${cls}`}>{inner}</button>
    : <div className="card p-3">{inner}</div>
}

function ListingRows({ items, onOpen }) {
  if (!items.length) return <div className="text-sm text-inkmute p-4">None.</div>
  return (
    <table className="w-full text-sm">
      <thead className="text-inkmute text-xs text-left"><tr>
        <th className="py-1">Ref</th><th>Title</th><th>Type</th><th className="text-right">Price</th><th>Fetched</th></tr></thead>
      <tbody>
        {items.map((i) => (
          <tr key={i.record_id} className="border-t border-line hover:bg-line/30 cursor-pointer" onClick={() => onOpen(i.record_id)}>
            <td className="py-1.5 figure text-xs">{i.site_listing_ref}</td>
            <td className="max-w-xs truncate">{i.title}</td>
            <td className="text-xs">{i.property_type_raw}</td>
            <td className="figure text-right">{fmtPrice(i.amount, i.currency)}</td>
            <td className="figure text-xs">{(i.fetched_at || '').slice(0, 16).replace('T', ' ')}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Changed({ items, onOpenA, onOpenB }) {
  if (!items.length) return <div className="text-sm text-inkmute p-4">No field differences among listings present in both runs.</div>
  return (
    <div className="divide-y divide-line">
      {items.map((c) => (
        <div key={c.key} className="py-2.5">
          <div className="flex flex-wrap items-baseline gap-x-3 text-sm">
            <span className="figure text-xs font-medium">{c.key}</span>
            <span className="truncate max-w-md">{c.title}</span>
            {c.parser_version_changed && (
              <span className="text-[11px] px-1.5 border border-amber/40 bg-amber/10 text-amber rounded-sm"
                title="The two observations were parsed by different parser versions, so a change may be a parser change rather than a change on the site">
                parser {c.parser_version_a} → {c.parser_version_b}
              </span>
            )}
            <span className="ml-auto text-xs space-x-3">
              <button className="text-teal hover:underline" onClick={() => onOpenA(c.record_id_a)}>open A</button>
              <button className="text-teal hover:underline" onClick={() => onOpenB(c.record_id_b)}>open B</button>
            </span>
          </div>
          <table className="text-xs mt-1">
            <tbody>
              {c.changes.map((ch) => (
                <tr key={ch.field}>
                  <td className="pr-4 text-inkmute w-32">{ch.field}</td>
                  <td className="figure pr-2 text-flag line-through decoration-flag/40">{val(ch.before)}</td>
                  <td className="pr-2 text-inkmute">→</td>
                  <td className="figure text-ok">{val(ch.after)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  )
}

export default function ListingsRuns({ onOpen }) {
  const [ov, setOv] = useState(null)
  const [err, setErr] = useState(null)
  const [a, setA] = useState('')
  const [b, setB] = useState('')
  const [diff, setDiff] = useState(null)
  const [dErr, setDErr] = useState(null)
  const [tab, setTab] = useState('changed')

  useEffect(() => {
    api.listingsRuns().then((o) => {
      setOv(o)
      const pick = o.best_pair || (o.runs.length >= 2 ? { run_a: o.runs[0].scrape_run_id, run_b: o.runs[1].scrape_run_id } : null)
      if (pick) { setA(pick.run_a); setB(pick.run_b) }
    }).catch((e) => setErr(e.message))
  }, [])

  useEffect(() => {
    setDiff(null); setDErr(null)
    if (a && b && a !== b) api.listingsRunDiff(a, b).then(setDiff).catch((e) => setDErr(e.message))
  }, [a, b])

  if (err) return <div className="card p-4 text-sm text-flag">Could not load runs: {err}</div>
  if (!ov) return <Spinner label="Loading scrape runs…" />

  const runLabel = (r) => `${short(r.scrape_run_id)} · ${r.listings} listings · ${(r.first_fetched_at || '').slice(0, 10)}`
  const c = diff?.counts

  return (
    <div className="space-y-4">
      <div className="card p-5">
        <div className="label">Scrape runs · does the same listing recur?</div>
        <h1 className="text-xl font-semibold mt-1">
          {ov.runs.length} run{ov.runs.length === 1 ? '' : 's'}, {fmtNum(ov.distinct_listings)} distinct listings, {fmtNum(ov.observations)} observations
        </h1>
        <p className="text-xs text-inkmute mt-1">
          Listings are matched across runs by MLS ref (<span className="figure">site_listing_ref</span>, falling back to canonical URL);
          <span className="figure"> record_id</span> is per observation and is not used. Read-only.
        </p>
        <table className="w-full text-sm mt-3">
          <thead className="text-inkmute text-xs text-left"><tr>
            <th className="py-1">Run</th><th>First fetched</th><th>Parser</th><th className="text-right">Listings</th></tr></thead>
          <tbody>
            {ov.runs.map((r) => (
              <tr key={r.scrape_run_id} className="border-t border-line">
                <td className="py-1 figure text-xs">{r.scrape_run_id}</td>
                <td className="figure text-xs">{(r.first_fetched_at || '').slice(0, 16).replace('T', ' ')}</td>
                <td className="figure text-xs">{r.parser_versions.join(', ')}</td>
                <td className="figure text-right">{fmtNum(r.listings)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="flex flex-wrap gap-x-6 gap-y-1 mt-3 text-sm">
          {ov.listings_by_run_count.map((h) => (
            <span key={h.runs}><b className="figure">{fmtNum(h.listings)}</b> listing{h.listings === 1 ? '' : 's'} seen in {h.runs} run{h.runs === 1 ? '' : 's'}</span>
          ))}
        </div>
      </div>

      {ov.runs.length < 2 && (
        <div role="note" className="card p-4 text-sm border-amber/40 bg-amber/10">
          <b>Only one scrape run is loaded</b>, so there is nothing to compare: each listing has exactly one observation.
          Once a second run lands in the table this tab will diff the two.
        </div>
      )}
      {ov.runs.length >= 2 && !ov.comparable && (
        <div role="note" className="card p-4 text-sm border-amber/40 bg-amber/10">
          <b>These runs do not overlap.</b> No listing appears in more than one run, so every listing will show as
          “only in A” or “only in B” and there are no field-level changes to show. Differences between runs here reflect
          which listings were crawled, not changes to listings.
        </div>
      )}
      {ov.comparable && ov.listings_in_multiple_runs < 0.1 * ov.distinct_listings && (
        <div role="note" className="card p-4 text-sm border-amber/40 bg-amber/10">
          <b>Little overlap:</b> only {fmtNum(ov.listings_in_multiple_runs)} of {fmtNum(ov.distinct_listings)} listings
          ({Math.round((100 * ov.listings_in_multiple_runs) / ov.distinct_listings)}%) appear in more than one run. Most runs are
          sub-samples or earlier test batches, so “only in A/B” mostly reflects crawl scope, not listings appearing or disappearing.
          {ov.best_pair && <> Best-overlapping pair is preselected ({fmtNum(ov.best_pair.shared)} shared).</>}
        </div>
      )}

      {ov.runs.length >= 2 && (
        <div className="card p-4">
          <div className="grid md:grid-cols-2 gap-3">
            {[['Run A (before)', a, setA], ['Run B (after)', b, setB]].map(([lab, v, set]) => (
              <label key={lab} className="text-sm">
                <span className="label block mb-1">{lab}</span>
                <select value={v} onChange={(e) => set(e.target.value)} className="w-full border border-line rounded-sm px-2 py-1.5 bg-white figure text-xs">
                  {ov.runs.map((r) => <option key={r.scrape_run_id} value={r.scrape_run_id}>{runLabel(r)}</option>)}
                </select>
              </label>
            ))}
          </div>
          {a === b && <div className="text-sm text-flag mt-2">Pick two different runs.</div>}
        </div>
      )}

      {dErr && <div className="card p-4 text-sm text-flag">Could not diff runs: {dErr}</div>}
      {a && b && a !== b && !diff && !dErr && <Spinner label="Diffing runs…" />}
      {diff && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <Stat label="Only in A" value={c.only_a} tone="text-flag" active={tab === 'only_a'} onClick={() => setTab('only_a')} />
            <Stat label="Only in B" value={c.only_b} tone="text-ok" active={tab === 'only_b'} onClick={() => setTab('only_b')} />
            <Stat label="In both" value={c.both} />
            <Stat label="…with changes" value={c.both_changed} tone="text-amber" active={tab === 'changed'} onClick={() => setTab('changed')} />
            <Stat label="…unchanged" value={c.both_unchanged} />
          </div>
          {c.both === 0 && (
            <div role="note" className="text-sm text-inkmute">
              These two runs share no listings, so there are no before/after changes to show.
            </div>
          )}
          {c.unkeyed_a + c.unkeyed_b > 0 && (
            <div className="text-xs text-flag">{c.unkeyed_a + c.unkeyed_b} observations have neither an MLS ref nor a canonical URL and cannot be matched.</div>
          )}
          {diff.field_change_counts.length > 0 && (
            <div className="card p-4">
              <div className="label mb-2">Fields that changed (listings affected)</div>
              <div className="flex flex-wrap gap-2">
                {diff.field_change_counts.map((f) => (
                  <span key={f.field} className="text-xs border border-line rounded-sm px-2 py-1">{f.field} <b className="figure">{f.count}</b></span>
                ))}
              </div>
              {c.parser_version_differs > 0 && (
                <div className="text-[11px] text-inkmute mt-2">{c.parser_version_differs} of the shared listings were parsed by different parser versions in A and B; those differences may be parser changes.</div>
              )}
            </div>
          )}
          <div className="card p-4">
            <div className="label mb-2">
              {{ changed: 'Changed between A and B', only_a: 'Only in run A', only_b: 'Only in run B' }[tab]}
              {diff.truncated && <span className="text-flag normal-case"> · list truncated</span>}
            </div>
            {tab === 'changed' && <Changed items={diff.changed} onOpenA={onOpen} onOpenB={onOpen} />}
            {tab === 'only_a' && <ListingRows items={diff.only_a} onOpen={onOpen} />}
            {tab === 'only_b' && <ListingRows items={diff.only_b} onOpen={onOpen} />}
          </div>
        </>
      )}
    </div>
  )
}
