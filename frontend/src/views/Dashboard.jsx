import React, { useEffect, useState } from 'react'
import {
  Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { api, pct, usd } from '../api.js'
import { Spinner } from '../components/shared.jsx'
import { setChartSummary } from '../copilot.js'
import MapView from './MapView.jsx'

const bucketColor = { '<60%': '#2E7D4F', '60-80%': '#C77D0A', '>80%': '#B3352C' }

function Banner({ label, value, sub, accent }) {
  return (
    <div className="card p-5">
      <div className="label">{label}</div>
      <div className={`figure text-3xl mt-2 font-semibold ${accent || ''}`}>{value}</div>
      {sub && <div className="text-xs text-inkmute mt-1">{sub}</div>}
    </div>
  )
}

export default function Dashboard({ onTriage, onOpen }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)

  useEffect(() => {
    api.summary().then((d) => {
      setData(d)
      setChartSummary('ltv_distribution', d.ltv_distribution)
      setChartSummary('neighborhood_concentration', d.neighborhood_concentration)
    }).catch((e) => setErr(e.message))
  }, [])

  if (err) return <div className="py-16 text-center text-flag text-sm">Couldn't load portfolio summary: {err}</div>
  if (!data) return <Spinner label="Scoring portfolio…" />

  const equity = data.total_valuation - data.total_exposure
  const geo = data.neighborhood_concentration.slice(0, 12)

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <Banner
          label="Total Portfolio Exposure"
          value={usd(data.total_exposure)}
          sub={`vs ${usd(data.total_valuation)} aggregate AVM valuation`}
        />
        <Banner
          label="System-Wide Average LTV"
          value={pct(data.avg_ltv)}
          sub={`${data.asset_count.toLocaleString()} residential assets`}
          accent={data.avg_ltv >= 0.8 ? 'text-flag' : data.avg_ltv >= 0.6 ? 'text-amber' : 'text-ok'}
        />
        <Banner
          label="Portfolio Equity Cushion"
          value={usd(equity)}
          sub={`${pct(equity / data.total_valuation)} of aggregate valuation`}
          accent="text-teal"
        />
        <button onClick={onTriage} className="card p-5 text-left hover:border-flag transition-colors group">
          <div className="label">Triage Queue Status</div>
          <div className="figure text-3xl mt-2 font-semibold text-flag">{data.triage_flagged}</div>
          <div className="text-xs text-inkmute mt-1">
            Flagged: High Variance · {data.triage_pending} pending review
            <span className="text-teal group-hover:underline ml-1">Open queue →</span>
          </div>
        </button>
      </div>

      <div className="grid lg:grid-cols-2 gap-4">
        <div className="card p-5">
          <div className="label mb-1">LTV Distribution</div>
          <div className="text-xs text-inkmute mb-4">Assets grouped into standard risk buckets</div>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={data.ltv_distribution}>
              <CartesianGrid strokeDasharray="3 3" stroke="#DDE3E0" vertical={false} />
              <XAxis dataKey="bucket" tick={{ fontSize: 12, fill: '#5B6B77' }} />
              <YAxis tick={{ fontSize: 12, fill: '#5B6B77' }} />
              <Tooltip formatter={(v) => [v.toLocaleString(), 'Assets']} />
              <Bar dataKey="count" radius={[3, 3, 0, 0]}>
                {data.ltv_distribution.map((b) => (
                  <Cell key={b.bucket} fill={bucketColor[b.bucket]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="card p-5">
          <div className="label mb-1">Geographic Concentration</div>
          <div className="text-xs text-inkmute mb-4">Loan exposure by Ames neighborhood (top 12)</div>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={geo} layout="vertical" margin={{ left: 24 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#DDE3E0" horizontal={false} />
              <XAxis type="number" tickFormatter={(v) => `$${(v / 1e6).toFixed(0)}M`} tick={{ fontSize: 11, fill: '#5B6B77' }} />
              <YAxis type="category" dataKey="neighborhood" width={64} tick={{ fontSize: 11, fill: '#16232E' }} />
              <Tooltip formatter={(v, n, p) => [usd(v), `Exposure (${p.payload.count} assets)`]} />
              <Bar dataKey="exposure" fill="#0E7C7B" radius={[0, 3, 3, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div>
        <div className="label mb-1">Portfolio Map</div>
        <div className="text-xs text-inkmute mb-3">Full geographic distribution of the book, sized by AVM value and colored by LTV risk tier.</div>
        <MapView onOpen={onOpen} height={480} />
      </div>
    </div>
  )
}
