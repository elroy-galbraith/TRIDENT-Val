import React, { useState } from 'react'
import { api } from '../api.js'
import { logger } from '../logger.js'

export default function Login({ onLoggedIn }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    setErr(null)
    setBusy(true)
    try {
      const user = await api.login(username, password)
      logger.track('auth', `Logged in as '${user.username}' (${user.role}).`)
      onLoggedIn(user)
    } catch {
      setErr('Invalid username or password.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="max-w-sm mx-auto mt-16">
      <form onSubmit={submit} className="card p-6 space-y-4">
        <div>
          <div className="text-lg font-semibold">Sign in</div>
          <div className="text-xs text-inkmute mt-1">TRIDENT-Val demo — see README for demo credentials.</div>
        </div>
        {err && <div className="text-sm text-flag">{err}</div>}
        <div>
          <label className="text-sm mb-1 block">Username</label>
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus
            className="w-full border border-line rounded-sm px-3 py-2 text-sm focus:outline-none focus:border-teal" />
        </div>
        <div>
          <label className="text-sm mb-1 block">Password</label>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
            className="w-full border border-line rounded-sm px-3 py-2 text-sm focus:outline-none focus:border-teal" />
        </div>
        <button type="submit" disabled={busy || !username || !password}
          className="w-full bg-ink hover:bg-black text-white text-sm font-medium py-2 rounded-sm disabled:opacity-50">
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  )
}
