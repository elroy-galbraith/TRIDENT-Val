import React, { useEffect, useRef, useState } from 'react'
import Dashboard from './views/Dashboard.jsx'
import PortfolioGrid from './views/PortfolioGrid.jsx'
import Inspector from './views/Inspector.jsx'
import MapView from './views/MapView.jsx'
import { logger } from './logger.js'
import { createCopilot } from './copilot.js'

const TABS = [
  { id: 'dashboard', label: 'Risk Overview' },
  { id: 'portfolio', label: 'Portfolio' },
  { id: 'map', label: 'Map' },
]

export default function App() {
  const [view, setView] = useState('dashboard')
  const [pid, setPid] = useState(null)
  const [gridStatus, setGridStatus] = useState('')
  const [copilotOpen, setCopilotOpen] = useState(true)
  const copilotRef = useRef(null)

  // Closing the widget's "X" button calls agent.dispose(), which is terminal — the only way
  // back in is to spin up a fresh PageAgent, since a disposed one can't be reused.
  const openCopilot = () => {
    if (copilotRef.current && !copilotRef.current.disposed) {
      copilotRef.current.panel.show()
    } else {
      const agent = createCopilot()
      agent.addEventListener('dispose', () => setCopilotOpen(false))
      copilotRef.current = agent
    }
    setCopilotOpen(true)
  }

  useEffect(() => {
    openCopilot()
    return () => copilotRef.current?.dispose()
  }, [])

  const openProperty = (id) => {
    logger.track('app', `Opened property inspector for PID ${id}.`, null, id)
    setPid(id); setView('inspector')
  }
  const openTriage = () => {
    logger.track('app', 'Opened the high-variance triage queue.')
    setGridStatus('Flagged: High Variance'); setView('portfolio')
  }
  const openTab = (id) => {
    logger.track('app', `Switched to "${id}" view.`)
    if (id === 'portfolio') setGridStatus(''); setView(id)
  }

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
          {!copilotOpen && (
            <button onClick={openCopilot} aria-label="Reopen AI copilot"
              className="px-3 py-1.5 text-sm rounded-sm border border-white/20 text-white/80 hover:text-white hover:border-white/40 transition-colors">
              ✦ Copilot
            </button>
          )}
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-6">
        {view === 'dashboard' && <Dashboard onTriage={openTriage} onOpen={openProperty} />}
        {view === 'portfolio' && (
          <PortfolioGrid key={gridStatus} onOpen={openProperty} initialStatus={gridStatus} />
        )}
        {view === 'map' && <MapView onOpen={openProperty} />}
        {view === 'inspector' && <Inspector pid={pid} onBack={() => setView('portfolio')} onOpen={openProperty} />}
      </main>

      <footer className="max-w-7xl mx-auto px-6 py-4 text-[11px] text-inkmute border-t border-line">
        Sandbox data: Ames Housing Dataset (De Cock, 2011). Loan balances and audit states are programmatically simulated. Not for production credit decisions.
      </footer>
    </div>
  )
}
