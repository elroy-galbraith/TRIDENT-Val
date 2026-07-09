import React, { useEffect, useRef, useState } from 'react'
import Dashboard from './views/Dashboard.jsx'
import PortfolioGrid from './views/PortfolioGrid.jsx'
import Inspector from './views/Inspector.jsx'
import MapView from './views/MapView.jsx'
import ModelCard from './views/ModelCard.jsx'
import ModelCompare from './views/ModelCompare.jsx'
import Login from './views/Login.jsx'
import { Spinner } from './components/shared.jsx'
import { logger } from './logger.js'
import { createCopilot } from './copilot.js'
import { api, setUnauthorizedHandler } from './api.js'

const TABS = [
  { id: 'dashboard', label: 'Risk Overview' },
  { id: 'portfolio', label: 'Portfolio' },
  { id: 'map', label: 'Map' },
  { id: 'model-card', label: 'Model Card' },
  { id: 'compare', label: 'Compare' },
]

const VIEW_IDS = new Set(['dashboard', 'portfolio', 'map', 'model-card', 'compare'])

function stateToPath({ view, pid, gridStatus }) {
  if (view === 'inspector' && pid != null) return `/inspector/${encodeURIComponent(pid)}`
  if (view === 'portfolio' && gridStatus) return `/portfolio?status=${encodeURIComponent(gridStatus)}`
  return `/${view}`
}

function stateFromLocation() {
  const segments = window.location.pathname.split('/').filter(Boolean)
  const [head, arg] = segments
  if (head === 'inspector' && arg) return { view: 'inspector', pid: decodeURIComponent(arg), gridStatus: '' }
  if (VIEW_IDS.has(head)) {
    const status = head === 'portfolio' ? new URLSearchParams(window.location.search).get('status') || '' : ''
    return { view: head, pid: null, gridStatus: status }
  }
  return { view: 'dashboard', pid: null, gridStatus: '' }
}

export default function App() {
  const [{ view, pid, gridStatus }, setNavState] = useState(stateFromLocation)
  const [copilotOpen, setCopilotOpen] = useState(true)
  const copilotRef = useRef(null)
  // undefined = checking for an existing session, null = logged out, object = logged in
  const [user, setUser] = useState(undefined)

  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null))
    api.me().then(setUser).catch(() => setUser(null))
  }, [])

  const handleLogout = async () => {
    logger.track('auth', `Logged out '${user.username}'.`)
    try { await api.logout() } catch { /* session is being cleared client-side regardless */ }
    // Flipping `user` to null re-runs the copilot-mount effect below, whose own
    // cleanup disposes the widget — no need to touch copilotRef/copilotOpen here.
    setUser(null)
  }

  // Pushes a new browser history entry so the back/forward buttons move between
  // views instead of leaving every page stuck on the initial "/" entry.
  // The history mutation happens here, outside the setState updater — React's
  // StrictMode double-invokes updater functions in dev, which would otherwise
  // push two history entries per navigation.
  const navigate = (next, { replace = false } = {}) => {
    const merged = { view, pid, gridStatus, ...next }
    const path = stateToPath(merged)
    if (replace) window.history.replaceState(merged, '', path)
    else window.history.pushState(merged, '', path)
    setNavState(merged)
  }

  useEffect(() => {
    // Normalize the initial URL (e.g. bare "/") without adding an extra history entry.
    const initial = stateFromLocation()
    window.history.replaceState(initial, '', stateToPath(initial))

    const onPopState = () => setNavState(stateFromLocation())
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

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
    if (!user) return
    openCopilot()
    return () => copilotRef.current?.dispose()
  }, [user])

  const openProperty = (id) => {
    logger.track('app', `Opened property inspector for PID ${id}.`, null, id)
    navigate({ view: 'inspector', pid: id })
  }
  const openTriage = () => {
    logger.track('app', 'Opened the high-variance triage queue.')
    navigate({ view: 'portfolio', gridStatus: 'Flagged: High Variance' })
  }
  const openTab = (id) => {
    logger.track('app', `Switched to "${id}" view.`)
    navigate({ view: id, gridStatus: id === 'portfolio' ? '' : gridStatus, pid: null })
  }

  return (
    <div className="min-h-screen">
      <header className="bg-ink text-white">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center gap-8">
          <div>
            <div className="font-semibold tracking-wide">TRIDENT-Val</div>
            <div className="text-[11px] text-white/60 tracking-wide">Residential Portfolio AVM &amp; Risk Triage Engine · PoC Sandbox</div>
          </div>
          {user && (
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
          )}
          {user && !copilotOpen && (
            <button onClick={openCopilot} aria-label="Reopen AI copilot"
              className="px-3 py-1.5 text-sm rounded-sm border border-white/20 text-white/80 hover:text-white hover:border-white/40 transition-colors">
              ✦ Copilot
            </button>
          )}
          {user && (
            <div className="flex items-center gap-3 text-sm text-white/70">
              <span>{user.username} · {user.role}</span>
              <button onClick={handleLogout}
                className="text-white/70 hover:text-white underline underline-offset-2">
                Log out
              </button>
            </div>
          )}
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-6">
        {user === undefined && <Spinner label="Checking session…" />}
        {user === null && <Login onLoggedIn={setUser} />}
        {user && (
          <>
            {view === 'dashboard' && <Dashboard onTriage={openTriage} onOpen={openProperty} />}
            {view === 'portfolio' && (
              <PortfolioGrid key={gridStatus} onOpen={openProperty} initialStatus={gridStatus} />
            )}
            {view === 'map' && <MapView onOpen={openProperty} />}
            {view === 'model-card' && (
              <ModelCard user={user} onBrowse={() => openTab('portfolio')} onCompare={() => openTab('compare')} />
            )}
            {view === 'compare' && <ModelCompare user={user} onOpen={openProperty} />}
            {view === 'inspector' && (
              <Inspector pid={pid} user={user} onBack={() => navigate({ view: 'portfolio', pid: null })} onOpen={openProperty} />
            )}
          </>
        )}
      </main>

      <footer className="max-w-7xl mx-auto px-6 py-4 text-[11px] text-inkmute border-t border-line">
        Sandbox data: Ames Housing Dataset (De Cock, 2011). Loan balances and audit states are programmatically simulated. Not for production credit decisions.
      </footer>
    </div>
  )
}
