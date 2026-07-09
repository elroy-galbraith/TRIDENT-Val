import React from 'react'

const TOC = [
  { id: 'what-is-it', label: 'What is TRIDENT-Val?' },
  { id: 'how-it-works', label: 'How it works' },
  { id: 'features', label: 'Features tour' },
  { id: 'roles', label: 'Roles & permissions' },
  { id: 'getting-started', label: 'Getting started' },
]

// Feature cards shown to every signed-in user; `roles` gates which roles see the card
// (matches the RBAC gating in tabsForRole() in App.jsx) and `view` is passed straight
// to the App-level navigate() callback via onNavigate.
const FEATURES = [
  {
    view: 'dashboard', title: 'Risk Overview', roles: null,
    body: 'Portfolio-wide exposure, average LTV, equity cushion, and a live count of properties waiting in the disagreement triage queue.',
  },
  {
    view: 'portfolio', title: 'Portfolio', roles: null,
    body: 'Every booked property as a filterable, sortable grid. Click any card to open its full valuation Inspector.',
  },
  {
    view: 'map', title: 'Map', roles: null,
    body: 'The same portfolio plotted geographically, so concentration risk in a neighborhood is visible at a glance.',
  },
  {
    view: 'revaluations', title: 'Revaluation Cycles', roles: null,
    body: 'Simulate collateral monitoring over time — organic drift, a broad market shock, a targeted neighborhood shock, or a custom scenario — and watch LTV and the triage queue update.',
  },
  {
    view: 'model-card', title: 'Model Card', roles: null,
    body: 'A plain-language record for each registered model: what it does, holdout accuracy, training data provenance, feature importance, and appropriate use — the model risk inventory.',
  },
  {
    view: 'compare', title: 'Compare', roles: null,
    body: 'Champion vs. challenger, side by side: agreement scatter plot, error and bias by neighborhood, and the queue of properties where the two models disagree.',
  },
  {
    view: 'my-queue', title: 'My Queue', roles: ['Underwriter', 'Admin'],
    body: 'Triage and audit items assigned to you — book the champion value, book the challenger, or override with a documented rationale.',
  },
  {
    view: 'manager', title: 'Manager', roles: ['Admin'],
    body: 'A rollup view across underwriters and queues, plus the authority to promote a challenger model to champion — a portfolio-wide re-booking event.',
  },
]

export default function About({ user, onNavigate }) {
  const visibleFeatures = FEATURES.filter((f) => !f.roles || f.roles.includes(user?.role))

  return (
    <div className="space-y-10">
      {/* Hero */}
      <div className="card p-8">
        <div className="label mb-2">PoC Sandbox · Welcome</div>
        <h1 className="text-2xl font-semibold text-ink">Welcome to TRIDENT-Val</h1>
        <p className="mt-3 max-w-3xl text-sm leading-relaxed text-inkmute">
          TRIDENT-Val is a demo of how a bank's model-risk-management function might run a
          residential collateral valuation system day to day. Two automated valuation models —
          a "champion" and a "challenger" — score every property in a simulated mortgage
          portfolio. Where they disagree, the case routes to a human for review. Every decision
          is logged to an audit ledger, and reports are structured against real-world appraisal
          standards (IVS 103 / RICS Red Book VPS&nbsp;6).
        </p>
        <div className="mt-5 flex flex-wrap gap-3">
          <button onClick={() => onNavigate('dashboard')}
            className="px-4 py-2 text-sm font-medium rounded-sm bg-ink hover:bg-black text-white">
            Go to Risk Overview →
          </button>
          <button onClick={() => onNavigate('portfolio')}
            className="px-4 py-2 text-sm font-medium rounded-sm border border-line hover:border-teal hover:text-teal">
            Browse the portfolio →
          </button>
        </div>
      </div>

      {/* Table of contents */}
      <nav aria-label="On this page" className="card p-4">
        <div className="label mb-2">On this page</div>
        <div className="flex flex-wrap gap-x-5 gap-y-1.5 text-sm">
          {TOC.map((t) => (
            <a key={t.id} href={`#${t.id}`} className="text-teal hover:underline underline-offset-2">
              {t.label}
            </a>
          ))}
        </div>
      </nav>

      {/* What is it */}
      <section id="what-is-it" className="card p-6 scroll-mt-4">
        <h2 className="text-base font-semibold text-ink">What is TRIDENT-Val?</h2>
        <p className="mt-2 text-sm leading-relaxed text-inkmute">
          TRIDENT-Val stands in for a bank's Automated Valuation Model (AVM) &amp; Risk Triage
          Engine — the system that values the homes securing a mortgage portfolio and flags
          collateral risk before it becomes a problem. It's built for the people who would sit
          around that system in a real institution: model validators, underwriters, and
          portfolio risk managers.
        </p>
        <ul className="mt-3 space-y-1.5 text-sm text-inkmute list-disc pl-5">
          <li>
            A portfolio of {' '}
            <span className="text-ink font-medium">2,930 simulated properties</span>, drawn from
            the Ames Housing Dataset (De Cock, 2011), each carrying a simulated loan balance.
          </li>
          <li>
            A <span className="text-ink font-medium">LightGBM "champion" model</span> (holdout
            MAPE 7.9%, R² 0.94) whose valuation is the one actually booked onto every asset.
          </li>
          <li>
            A <span className="text-ink font-medium">Ridge linear "challenger" model</span> that
            scores every property in the shadows, for comparison and eventual promotion.
          </li>
          <li>
            An <span className="text-ink font-medium">audit ledger</span> that records every
            triage decision, override, and model promotion with a rationale.
          </li>
          <li>
            An <span className="text-ink font-medium">AI copilot</span> (open it any time from
            the header) that can read and drive the UI in plain English — it narrates, it never
            computes the numbers itself, and it can't write to the audit ledger.
          </li>
        </ul>
      </section>

      {/* How it works */}
      <section id="how-it-works" className="card p-6 scroll-mt-4">
        <h2 className="text-base font-semibold text-ink">How it works</h2>
        <p className="mt-2 text-sm leading-relaxed text-inkmute">
          This is the champion/challenger governance loop that drives everything else in the app:
        </p>
        <ol className="mt-4 space-y-3">
          {[
            ['Score', 'Both models value every property. The champion’s value is booked; the challenger scores the same property in shadow.'],
            ['Compare', 'Wherever the two models disagree beyond a threshold, the property is routed to the disagreement triage queue.'],
            ['Triage', 'An Underwriter reviews the case in the Inspector — the glass-box valuation matrix, SHAP/coefficient explainability, and a what-if panel — then books the champion value, books the challenger, or overrides with a documented rationale.'],
            ['Monitor', 'A Revaluation Cycle re-runs the market (organic drift, a stress scenario, or a custom shock), refreshing booked values, LTV, and the queue.'],
            ['Govern', 'If the challenger consistently outperforms, an Admin can promote it to champion — re-booking the whole portfolio — from the Model Card or Compare view.'],
          ].map(([step, body], i) => (
            <li key={step} className="flex gap-4">
              <div className="figure shrink-0 w-7 h-7 rounded-full bg-ink text-white text-xs flex items-center justify-center font-semibold">
                {i + 1}
              </div>
              <div>
                <div className="text-sm font-medium text-ink">{step}</div>
                <div className="text-sm text-inkmute leading-relaxed">{body}</div>
              </div>
            </li>
          ))}
        </ol>
      </section>

      {/* Features tour */}
      <section id="features" className="scroll-mt-4">
        <h2 className="text-base font-semibold text-ink mb-3">Features tour</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {visibleFeatures.map((f) => (
            <button key={f.view} onClick={() => onNavigate(f.view)}
              className="text-left card p-4 hover:border-teal transition-colors">
              <div className="text-sm font-semibold text-ink">{f.title}</div>
              <p className="mt-1.5 text-xs leading-relaxed text-inkmute">{f.body}</p>
              <div className="mt-2.5 text-xs font-medium text-teal">Open {f.title} →</div>
            </button>
          ))}
        </div>
        <p className="mt-3 text-xs text-inkmute">
          Every property card also opens a per-property <span className="text-ink font-medium">Inspector</span>{' '}
          — click any property in the Portfolio or Map view to reach it. From there you can also
          export a server-rendered PDF report (Underwriter Decision Report, Portfolio Review
          Summary, or Revaluation Cycle Report).
        </p>
      </section>

      {/* Roles */}
      <section id="roles" className="card p-6 scroll-mt-4">
        <h2 className="text-base font-semibold text-ink">Roles &amp; permissions</h2>
        <p className="mt-2 text-sm text-inkmute">
          You're signed in as <span className="text-ink font-medium">{user?.username}</span>,
          with the <span className="text-ink font-medium">{user?.role}</span> role. What each
          role can do:
        </p>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left label border-b border-line">
                <th className="py-2 pr-4">Role</th>
                <th className="py-2 pr-4">Can do</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              <tr>
                <td className="py-2.5 pr-4 font-medium text-ink align-top">Viewer</td>
                <td className="py-2.5 pr-4 text-inkmute">Read-only access to the portfolio, map, model cards, comparisons, and revaluation history.</td>
              </tr>
              <tr>
                <td className="py-2.5 pr-4 font-medium text-ink align-top">Underwriter</td>
                <td className="py-2.5 pr-4 text-inkmute">Everything a Viewer can do, plus working the triage queue in My Queue: booking a value or overriding it with a rationale, all logged to the audit ledger.</td>
              </tr>
              <tr>
                <td className="py-2.5 pr-4 font-medium text-ink align-top">Admin</td>
                <td className="py-2.5 pr-4 text-inkmute">Everything an Underwriter can do, plus the Manager rollup view and promoting a challenger model to champion.</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      {/* Getting started */}
      <section id="getting-started" className="card p-6 scroll-mt-4">
        <h2 className="text-base font-semibold text-ink">Getting started</h2>
        <ol className="mt-3 space-y-2 text-sm text-inkmute list-decimal pl-5">
          <li>Start on <button onClick={() => onNavigate('dashboard')} className="text-teal hover:underline underline-offset-2">Risk Overview</button> to see overall portfolio health and the size of the triage queue.</li>
          <li>Open a property from <button onClick={() => onNavigate('portfolio')} className="text-teal hover:underline underline-offset-2">Portfolio</button> or <button onClick={() => onNavigate('map')} className="text-teal hover:underline underline-offset-2">Map</button> to inspect its valuation, explainability, and audit history.</li>
          {(user?.role === 'Underwriter' || user?.role === 'Admin') && (
            <li>Check <button onClick={() => onNavigate('my-queue')} className="text-teal hover:underline underline-offset-2">My Queue</button> for cases assigned to you and work through the triage decisions.</li>
          )}
          <li>Run a scenario in <button onClick={() => onNavigate('revaluations')} className="text-teal hover:underline underline-offset-2">Revaluation Cycles</button> to see how a market shock ripples through LTV and the queue.</li>
          <li>Read the <button onClick={() => onNavigate('model-card')} className="text-teal hover:underline underline-offset-2">Model Card</button> and <button onClick={() => onNavigate('compare')} className="text-teal hover:underline underline-offset-2">Compare</button> views to understand what each model does and where they disagree.</li>
          <li>Ask the <span className="text-ink font-medium">AI Copilot</span> (bottom-right, or the "✦ Copilot" button in the header) to explain a screen or walk you through a task in plain English.</li>
        </ol>
        <p className="mt-4 text-xs text-inkmute border-t border-line pt-3">
          Sandbox data: Ames Housing Dataset (De Cock, 2011). Loan balances and audit states are
          programmatically simulated. Not for production credit decisions. You can return to
          this page anytime from the "About" tab in the header.
        </p>
      </section>
    </div>
  )
}
