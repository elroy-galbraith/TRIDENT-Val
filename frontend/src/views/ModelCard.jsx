import React, { useEffect, useState } from 'react'
import {
  Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { api, pct, usd } from '../api.js'
import { Spinner } from '../components/shared.jsx'
import { setChartSummary } from '../copilot.js'

// Inline "term" — click to reveal a one-sentence, non-technical definition. Keeps jargon
// (MAPE, R², SHAP, holdout) explained in place instead of assuming the reader already knows it.
function Term({ define, children }) {
  const [open, setOpen] = useState(false)
  const id = React.useId()
  return (
    <span className="relative inline-block">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}
        aria-describedby={open ? id : undefined}
        className="underline decoration-dotted decoration-inkmute underline-offset-2 text-tealdeep font-medium">
        {children}
      </button>
      {open && (
        <span role="tooltip" id={id}
          className="absolute z-10 left-0 top-full mt-1 w-64 text-xs leading-relaxed bg-ink text-white rounded-sm p-2.5 shadow-lg">
          {define}
        </span>
      )}
    </span>
  )
}

function Metric({ label, value, note }) {
  return (
    <div className="border border-line rounded-sm p-4">
      <div className="label">{label}</div>
      <div className="figure text-2xl font-semibold mt-1 text-tealdeep">{value}</div>
      <div className="text-xs text-inkmute mt-1 leading-relaxed">{note}</div>
    </div>
  )
}

function Section({ title, subtitle, children }) {
  return (
    <div className="card p-5">
      <div className="label mb-1">{title}</div>
      {subtitle && <div className="text-xs text-inkmute mb-3">{subtitle}</div>}
      {children}
    </div>
  )
}

export default function ModelCard({ onBrowse }) {
  const [spec, setSpec] = useState(null)
  const [summary, setSummary] = useState(null)
  const [importance, setImportance] = useState(null)
  const [err, setErr] = useState(null)
  const [selected, setSelected] = useState(null)

  useEffect(() => {
    let active = true
    Promise.all([api.spec(), api.summary(), api.importance()])
      .then(([s, sm, imp]) => {
        if (!active) return
        setSpec(s); setSummary(sm); setImportance(imp)
        setSelected(imp.drivers[0]?.feature ?? null)
        setChartSummary('model_global_importance', imp.drivers)
      })
      .catch((e) => { if (active) setErr(e.message) })
    return () => { active = false }
  }, [])

  if (err) return <div className="py-16 text-center text-flag text-sm">Couldn't load the model card: {err}</div>
  if (!spec || !summary || !importance) return <Spinner label="Loading model card…" />

  const topDrivers = importance.drivers.slice(0, 12).map((d) => ({ ...d, chartLabel: d.label }))
  const activeDriver = importance.drivers.find((d) => d.feature === selected) || importance.drivers[0]
  const nInputs = spec.features.length
  const nCategorical = Object.keys(spec.categorical).length
  const nOrdinal = Object.keys(spec.ordinal).length

  return (
    <div className="space-y-4">
      <div className="card p-6">
        <div className="label">Model Card</div>
        <h1 className="text-2xl font-semibold mt-1">TRIDENT-Val Automated Valuation Model</h1>
        <p className="text-sm text-inkmute mt-3 max-w-3xl leading-relaxed">
          This page explains — in plain language, no data-science background required — how the
          AVM behind this portfolio produces its property value estimates: what it learned from,
          how accurate it has measured out to be, which factors move its numbers the most, and
          where its limits are. It's written for auditors and risk reviewers, not modelers.
        </p>
      </div>

      <Section title="What Does It Do?">
        <p className="text-sm leading-relaxed">
          The AVM estimates a home's market value from {nInputs} physical characteristics — size,
          room counts, quality ratings, age, and neighborhood — without ever seeing a photo, a
          listing description, or a human appraiser's opinion. Feed it the same inputs twice and
          it returns the same number twice: every estimate is a reproducible calculation, not a
          judgment call.
        </p>
        <p className="text-sm leading-relaxed mt-3">
          Under the hood it's a{' '}
          <Term define="Hundreds of small decision trees, built one after another. Each new tree focuses on correcting the errors the trees before it made, and the trees' outputs are added together for the final number.">
            gradient-boosted tree ensemble
          </Term>{' '}
          (an algorithm called LightGBM) trained to predict{' '}
          <span className="figure">{spec.target}</span>. It's a supervised model — it learned by
          studying thousands of past home sales where the true price was already known, not by
          reasoning from first principles about what a house "should" be worth.
        </p>
      </Section>

      <Section title="How Accurate Is It?">
        <div className="grid sm:grid-cols-3 gap-4 mb-4">
          <Metric label="Median error (MAPE)" value={pct(spec.holdout_mape)}
            note="On a typical holdout home, the estimate lands within this percentage of the actual recorded sale price." />
          <Metric label="Variance explained (R²)" value={spec.holdout_r2.toFixed(2)}
            note="Share of the price differences across holdout homes the model accounts for. 1.00 would be a perfect fit." />
          <Metric label="Live error band" value="±5%"
            note="Every estimate shown in this app ships with this band, e.g. a $300,000 estimate is reported as $285,000–$315,000." />
        </div>
        <p className="text-sm leading-relaxed">
          These numbers come from a{' '}
          <Term define="Before training, a slice of the historical sales was set aside and hidden from the model. Accuracy is measured only on that hidden slice afterward — the same discipline as grading a student on questions they've never seen the answer key for.">
            holdout test
          </Term>: roughly one in five historical sales were withheld from training and scored
          only afterward, so these figures describe genuine out-of-sample performance rather than
          how well the model memorized its own training data.
        </p>
      </Section>

      <Section title="What Was It Trained On?">
        <p className="text-sm leading-relaxed">
          The{' '}
          <Term define="Compiled by Dr. Dean De Cock (Truman State University, 2011) as a modern, well-documented public dataset for teaching and benchmarking regression models.">
            Ames Housing Dataset
          </Term>: {summary.asset_count.toLocaleString()} residential property sales recorded in
          Ames, Iowa between 2006 and 2010. It's a fixed, public, zero-scrape academic dataset —
          nothing here was pulled live from the web or from any bank's real loan book — chosen for
          this proof-of-concept because it's realistic, well-documented, and fully reproducible.
        </p>
        <p className="text-sm text-inkmute mt-3 leading-relaxed">
          Auditor note: because the training data is Ames-specific and frozen at 2006–2010 sale
          prices, the accuracy figures above describe performance on that population — they are
          not a guarantee for any other market, time period, or property type.
        </p>
      </Section>

      <Section title="What Goes Into an Estimate?"
        subtitle={`${nInputs} inputs, grouped into three families`}>
        <div className="grid sm:grid-cols-3 gap-4 text-sm">
          <div>
            <div className="font-semibold text-tealdeep mb-1">Structure &amp; size</div>
            <div className="text-inkmute leading-relaxed">
              {spec.numeric.length} measurements — square footage, room counts, garage capacity,
              lot size, fireplaces, and similar.
            </div>
          </div>
          <div>
            <div className="font-semibold text-tealdeep mb-1">Quality &amp; condition</div>
            <div className="text-inkmute leading-relaxed">
              {nOrdinal} rated scores — kitchen, exterior, basement, and heating quality, plus
              overall quality/condition and functional deductions.
            </div>
          </div>
          <div>
            <div className="font-semibold text-tealdeep mb-1">Location &amp; type</div>
            <div className="text-inkmute leading-relaxed">
              {nCategorical} categories — neighborhood, zoning, building type, house style, and
              central air.
            </div>
          </div>
        </div>
      </Section>

      <Section title="What Drives the Model's Valuations?"
        subtitle={`Average dollar impact per factor, computed across all ${importance.sample_size.toLocaleString()} properties in the portfolio using the same explainability engine (TreeSHAP) behind every individual property's Inspector page. Click a bar for a plain-English explanation.`}>
        <ResponsiveContainer width="100%" height={360}>
          <BarChart data={topDrivers} layout="vertical" margin={{ left: 8, right: 24 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#DDE3E0" horizontal={false} />
            <XAxis type="number" tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`}
              tick={{ fontSize: 11, fill: '#5B6B77' }} />
            <YAxis type="category" dataKey="chartLabel" width={150}
              tick={{ fontSize: 11, fill: '#16232E' }} />
            <Tooltip formatter={(v) => [usd(v), 'Avg. price effect (magnitude)']} />
            <Bar dataKey="mean_abs_impact_usd" radius={[0, 3, 3, 0]} cursor="pointer"
              onClick={(d) => setSelected(d.feature)}>
              {topDrivers.map((d) => (
                <Cell key={d.feature} fill={d.feature === activeDriver?.feature ? '#0A5958' : '#0E7C7B'} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
        {activeDriver && (
          <div className="mt-1 p-3 bg-paper rounded-sm border border-line text-sm">
            <span className="font-semibold">{activeDriver.label}: </span>
            <span className="text-inkmute">{activeDriver.explanation}</span>
            <div className="text-xs text-inkmute mt-2">
              Moves the estimate by an average of{' '}
              <span className="figure font-semibold text-ink">{usd(activeDriver.mean_abs_impact_usd)}</span>{' '}
              in either direction across the portfolio — on net,{' '}
              {activeDriver.mean_signed_impact_usd >= 0 ? 'pushing estimates up' : 'pulling estimates down'}{' '}
              by <span className="figure">{usd(Math.abs(activeDriver.mean_signed_impact_usd))}</span> on
              average.
            </div>
          </div>
        )}
      </Section>

      <Section title="Limitations &amp; Appropriate Use">
        <ul className="text-sm leading-relaxed space-y-2 list-disc pl-5">
          <li>
            Trained on Ames, Iowa sales from 2006–2010 — not localized to any specific bank's
            actual markets. Treat estimates as directional in a real deployment, not a substitute
            for local comparables.
          </li>
          <li>
            It's a static snapshot: the model doesn't know about interest rates, inflation, or
            market conditions that changed after its training data was collected. It needs
            periodic retraining to stay current.
          </li>
          <li>
            It only knows what's in its {nInputs} inputs. Quality/condition fields are ordinal
            ratings entered at assessment time, not independently verified by an inspector.
          </li>
          <li>
            Every output is a point estimate plus a statistical error band — not a certified
            appraisal. Estimates feed this app's audit triage queue; they don't replace human
            underwriter review.
          </li>
          <li>
            This is a proof-of-concept sandbox: no fairness or disparate-impact audit has been run
            on it, and it is not approved for standalone credit decisions.
          </li>
        </ul>
      </Section>

      <div className="card p-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="label">See It Applied to a Single Property</div>
          <div className="text-sm text-inkmute mt-1">
            Every asset in the portfolio has its own value-driver breakdown — open any property's
            Inspector to see these same explanations applied to one specific home.
          </div>
        </div>
        {onBrowse && (
          <button onClick={onBrowse}
            className="shrink-0 bg-teal hover:bg-tealdeep text-white text-sm font-medium px-4 py-2 rounded-sm">
            Browse Portfolio →
          </button>
        )}
      </div>
    </div>
  )
}
