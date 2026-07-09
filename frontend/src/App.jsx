import React, { useState } from 'react'
import Dashboard from './views/Dashboard.jsx'
import PortfolioGrid from './views/PortfolioGrid.jsx'
import Inspector from './views/Inspector.jsx'

const TABS = [
  { id: 'dashboard', label: 'Risk Overview' },
  { id: 'portfolio', label: 'Portfolio' },
]

export default function App() {
  const [view, setView] = useState('dashboard')
  const [pid, setPid] = useState(null)
  const [gridStatus, setGridStatus] = useState('')

  const openProperty = (id) => { setPid(id); setView('inspector') }
  const openTriage = () => { setGridStatus('Flagged: High Variance'); setView('portfolio') }
  const openTab = (id) => { if (id === 'portfolio') setGridStatus(''); setView(id) }

  return (
    <div className="min-h-screen">
      <header className="bg-ink text-white">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center gap-8">
          <div>
            <div className="font-semibold tracking-wide">TRIDENT-Val</div>
            <div className="text-[11px] text-white/60 tracking-wide">Residential Portfolio AVM &amp; Risk Triage Engine · PoC Sandbox</div>
          </div>
          <nav className="flex gap-1 ml-auto">
            {TABS.map((t) => (
              <button key={t.id} onClick={() => openTab(t.id)}
                className={`px-4 py-1.5 text-sm rounded-sm transition-colors ${
                  view === t.id || (t.id === 'portfolio' && view === 'inspector')
                    ? 'bg-white/15 text-white' : 'text-white/70 hover:text-white'}`}>
                {t.label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-6">
        {view === 'dashboard' && <Dashboard onTriage={openTriage} />}
        {view === 'portfolio' && (
          <PortfolioGrid key={gridStatus} onOpen={openProperty} initialStatus={gridStatus} />
        )}
        {view === 'inspector' && <Inspector pid={pid} onBack={() => setView('portfolio')} />}
      </main>

      <footer className="max-w-7xl mx-auto px-6 py-4 text-[11px] text-inkmute border-t border-line">
        Sandbox data: Ames Housing Dataset (De Cock, 2011). Loan balances and audit states are programmatically simulated. Not for production credit decisions.
      </footer>
    </div>
  )
}
