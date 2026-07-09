import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import { AssignmentStateBadge, Spinner } from '../components/shared.jsx'
import { logger } from '../logger.js'

const STATE_OPTIONS = ['Open', 'In Progress', 'Done']

export default function MyQueue({ user, onOpen }) {
  const [items, setItems] = useState(null)
  const [err, setErr] = useState(null)

  const load = () =>
    api.assignments({ assignee_username: user.username }).then((d) => setItems(d.items)).catch((e) => setErr(e.message))

  useEffect(() => { load() }, [])

  const setState = async (a, state) => {
    try {
      await api.updateAssignment(a.id, { state })
      logger.track('my-queue', `Set assignment #${a.id} (PID ${a.pid}) to ${state}.`, { state }, a.pid)
      load()
    } catch (e) {
      setErr(e.message)
    }
  }

  if (err) return <div className="py-16 text-center text-flag text-sm">{err}</div>
  if (!items) return <Spinner label="Loading your queue…" />

  const open = items.filter((a) => a.state !== 'Done')
  const done = items.filter((a) => a.state === 'Done')

  return (
    <div className="space-y-4">
      <div className="card p-6">
        <div className="label">Work Management</div>
        <h1 className="text-2xl font-semibold mt-1">My Queue</h1>
        <p className="text-sm text-inkmute mt-3 max-w-3xl leading-relaxed">
          Properties assigned to you, with a due date. Update state as you work through each one.
        </p>
      </div>

      <div className="card p-5">
        <div className="label mb-2">Open &amp; In Progress ({open.length})</div>
        {open.length === 0 ? (
          <div className="text-sm text-inkmute py-6 text-center">Nothing assigned to you right now.</div>
        ) : (
          <div className="overflow-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-inkmute border-b border-line">
                  <th className="py-1.5 pr-3">PID</th><th className="py-1.5 pr-3">Neighborhood</th>
                  <th className="py-1.5 pr-3">Due</th><th className="py-1.5 pr-3">Notes</th>
                  <th className="py-1.5 pr-3">State</th><th className="py-1.5">Assigned by</th>
                </tr>
              </thead>
              <tbody>
                {open.map((a) => (
                  <tr key={a.id} className="border-b border-line last:border-0">
                    <td className="py-1.5 pr-3 figure cursor-pointer text-teal hover:underline"
                      onClick={() => onOpen && onOpen(a.pid)}>{a.pid}</td>
                    <td className="py-1.5 pr-3">{a.neighborhood || '—'}</td>
                    <td className={`py-1.5 pr-3 figure ${a.overdue ? 'text-flag font-semibold' : ''}`}>
                      {a.due_date?.slice(0, 10)}{a.overdue ? ' (overdue)' : ''}
                    </td>
                    <td className="py-1.5 pr-3 text-xs max-w-xs truncate" title={a.notes}>{a.notes || '—'}</td>
                    <td className="py-1.5 pr-3">
                      <select value={a.state} onChange={(e) => setState(a, e.target.value)}
                        aria-label={`State for assignment ${a.id}`}
                        className="border border-line rounded-sm px-1.5 py-1 text-xs bg-white">
                        {STATE_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
                      </select>
                    </td>
                    <td className="py-1.5">{a.created_by || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="card p-5">
        <div className="label mb-2">Done ({done.length})</div>
        {done.length === 0 ? (
          <div className="text-sm text-inkmute py-6 text-center">No completed assignments yet.</div>
        ) : (
          <div className="overflow-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-inkmute border-b border-line">
                  <th className="py-1.5 pr-3">PID</th><th className="py-1.5 pr-3">Neighborhood</th>
                  <th className="py-1.5 pr-3">Completed</th><th className="py-1.5">State</th>
                </tr>
              </thead>
              <tbody>
                {done.map((a) => (
                  <tr key={a.id} className="border-b border-line last:border-0">
                    <td className="py-1.5 pr-3 figure cursor-pointer text-teal hover:underline"
                      onClick={() => onOpen && onOpen(a.pid)}>{a.pid}</td>
                    <td className="py-1.5 pr-3">{a.neighborhood || '—'}</td>
                    <td className="py-1.5 pr-3 figure">{a.completed_at?.slice(0, 10) || '—'}</td>
                    <td className="py-1.5"><AssignmentStateBadge state={a.state} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
