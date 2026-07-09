import React, { useEffect, useState } from 'react'
import {
  Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { api } from '../api.js'
import { Spinner } from '../components/shared.jsx'
import { logger } from '../logger.js'

const AGE_BUCKET_COLOR = { '0-3d': '#2E7D4F', '3-7d': '#C77D0A', '7-14d': '#B3352C', '>14d': '#7A1F1F' }
const STATE_OPTIONS = ['Open', 'In Progress', 'Done']

function Metric({ label, value, accent }) {
  return (
    <div className="border border-line rounded-sm p-4">
      <div className="label">{label}</div>
      <div className={`figure text-2xl font-semibold mt-1 ${accent || 'text-tealdeep'}`}>{value}</div>
    </div>
  )
}

// Local date, not new Date().toISOString().slice(0, 10) — that's UTC, which for a user behind
// UTC can render as tomorrow and default the due-date picker a day ahead of "today".
function todayLocal() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function AssignForm({ users, onCreated, onCancel }) {
  const [pid, setPid] = useState('')
  const [assignee, setAssignee] = useState(users[0]?.username || '')
  const [dueDate, setDueDate] = useState(todayLocal)
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (users.length > 0 && !assignee) setAssignee(users[0].username)
  }, [users, assignee])

  const submit = async () => {
    if (!pid || !assignee || !dueDate) { setError('PID, assignee, and due date are required'); return }
    setSubmitting(true)
    setError(null)
    try {
      const a = await api.createAssignment({ pid: +pid, assignee_username: assignee, due_date: dueDate, notes })
      logger.track('manager', `Assigned PID ${a.pid} to ${a.assignee_username}, due ${a.due_date?.slice(0, 10)}.`, a, a.pid)
      setPid(''); setNotes('')
      onCreated()
    } catch (e) {
      setError(e.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="card p-5 space-y-4">
      <div className="label">New Assignment</div>
      <div className="grid sm:grid-cols-4 gap-4">
        <label className="text-sm space-y-1 block">
          <span className="text-inkmute">Property PID</span>
          <input type="number" value={pid} onChange={(e) => setPid(e.target.value)}
            placeholder="e.g. 526301100" className="w-full border border-line rounded-sm px-2 py-1.5" />
        </label>
        <label className="text-sm space-y-1 block">
          <span className="text-inkmute">Assignee</span>
          <select value={assignee} onChange={(e) => setAssignee(e.target.value)}
            className="w-full border border-line rounded-sm px-2 py-1.5 bg-white">
            {users.map((u) => <option key={u.username} value={u.username}>{u.username} ({u.role})</option>)}
          </select>
        </label>
        <label className="text-sm space-y-1 block">
          <span className="text-inkmute">Due date</span>
          <input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)}
            className="w-full border border-line rounded-sm px-2 py-1.5 bg-white" />
        </label>
        <label className="text-sm space-y-1 block">
          <span className="text-inkmute">Notes (optional)</span>
          <input value={notes} onChange={(e) => setNotes(e.target.value)}
            className="w-full border border-line rounded-sm px-2 py-1.5" />
        </label>
      </div>
      {error && <div className="text-sm text-flag">{error}</div>}
      <div className="flex gap-2">
        <button onClick={submit} disabled={submitting}
          className="bg-ink hover:bg-black text-white text-sm font-medium px-4 py-2 rounded-sm disabled:opacity-50">
          {submitting ? 'Assigning…' : 'Assign'}
        </button>
        <button onClick={onCancel} disabled={submitting} className="px-4 py-2 text-sm border border-line rounded-sm">
          Cancel
        </button>
      </div>
    </div>
  )
}

export default function ManagerDashboard({ onOpen }) {
  const [summary, setSummary] = useState(null)
  const [items, setItems] = useState(null)
  const [users, setUsers] = useState([])
  const [showForm, setShowForm] = useState(false)
  const [err, setErr] = useState(null)

  const load = () => {
    api.assignmentsSummary().then(setSummary).catch((e) => setErr(e.message))
    api.assignments({}).then((d) => setItems(d.items)).catch((e) => setErr(e.message))
  }

  useEffect(() => { load() }, [])
  useEffect(() => { api.users().then((d) => setUsers(d.items)) }, [])

  const setItemState = async (a, state) => {
    try {
      await api.updateAssignment(a.id, { state })
      logger.track('manager', `Set assignment #${a.id} (PID ${a.pid}) to ${state}.`, { state }, a.pid)
      load()
    } catch (e) {
      setErr(e.message)
    }
  }

  const handleCreated = () => { setShowForm(false); load() }

  if (err) return <div className="py-16 text-center text-flag text-sm">{err}</div>
  if (!summary || !items) return <Spinner label="Loading manager dashboard…" />

  return (
    <div className="space-y-4">
      <div className="card p-6">
        <div className="label">Work Management</div>
        <h1 className="text-2xl font-semibold mt-1">Manager Dashboard</h1>
        <p className="text-sm text-inkmute mt-3 max-w-3xl leading-relaxed">
          Queue depth, aging, and completion across every assignment on the book. Assign
          properties needing review to an underwriter with a due date, then track progress here.
        </p>
        {!showForm && (
          <button onClick={() => setShowForm(true)}
            className="mt-4 bg-ink hover:bg-black text-white text-sm font-medium px-4 py-2 rounded-sm">
            New Assignment
          </button>
        )}
      </div>

      {showForm && <AssignForm users={users} onCreated={handleCreated} onCancel={() => setShowForm(false)} />}

      <div className="grid sm:grid-cols-4 gap-4">
        <Metric label="Open" value={summary.total_open.toLocaleString()} />
        <Metric label="In Progress" value={summary.total_in_progress.toLocaleString()} accent="text-amber" />
        <Metric label="Done" value={summary.total_done.toLocaleString()} accent="text-ok" />
        <Metric label="Overdue" value={summary.overdue_count.toLocaleString()} accent="text-flag" />
      </div>

      <div className="grid lg:grid-cols-2 gap-4">
        <div className="card p-5">
          <div className="label mb-1">Queue Aging</div>
          <div className="text-xs text-inkmute mb-4">Days open for assignments not yet Done</div>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={summary.aging_buckets}>
              <CartesianGrid strokeDasharray="3 3" stroke="#DDE3E0" vertical={false} />
              <XAxis dataKey="bucket" tick={{ fontSize: 12, fill: '#5B6B77' }} />
              <YAxis tick={{ fontSize: 12, fill: '#5B6B77' }} allowDecimals={false} />
              <Tooltip formatter={(v) => [v.toLocaleString(), 'Assignments']} />
              <Bar dataKey="count" radius={[3, 3, 0, 0]}>
                {summary.aging_buckets.map((b) => <Cell key={b.bucket} fill={AGE_BUCKET_COLOR[b.bucket]} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="card p-5">
          <div className="label mb-2">Queue Depth by Assignee</div>
          {summary.by_assignee.length === 0 ? (
            <div className="text-sm text-inkmute py-6 text-center">No assignments yet.</div>
          ) : (
            <div className="overflow-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-inkmute border-b border-line">
                    <th className="py-1.5 pr-3">Assignee</th><th className="py-1.5 pr-3">Open</th>
                    <th className="py-1.5 pr-3">In Progress</th><th className="py-1.5 pr-3">Done</th>
                    <th className="py-1.5 pr-3">Overdue</th><th className="py-1.5">Avg. age</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.by_assignee.map((b) => (
                    <tr key={b.assignee} className="border-b border-line last:border-0">
                      <td className="py-1.5 pr-3">{b.assignee}</td>
                      <td className="py-1.5 pr-3 figure">{b.open}</td>
                      <td className="py-1.5 pr-3 figure">{b.in_progress}</td>
                      <td className="py-1.5 pr-3 figure">{b.done}</td>
                      <td className={`py-1.5 pr-3 figure ${b.overdue > 0 ? 'text-flag font-semibold' : ''}`}>{b.overdue}</td>
                      <td className="py-1.5 figure">{b.avg_age_days}d</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      <div className="card p-5">
        <div className="label mb-2">All Assignments ({items.length})</div>
        {items.length === 0 ? (
          <div className="text-sm text-inkmute py-6 text-center">No assignments yet.</div>
        ) : (
          <div className="overflow-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-inkmute border-b border-line">
                  <th className="py-1.5 pr-3">PID</th><th className="py-1.5 pr-3">Neighborhood</th>
                  <th className="py-1.5 pr-3">Assignee</th><th className="py-1.5 pr-3">Due</th>
                  <th className="py-1.5 pr-3">State</th><th className="py-1.5">Assigned by</th>
                </tr>
              </thead>
              <tbody>
                {items.map((a) => (
                  <tr key={a.id} className="border-b border-line last:border-0">
                    <td className="py-1.5 pr-3 figure cursor-pointer text-teal hover:underline"
                      onClick={() => onOpen && onOpen(a.pid)}>{a.pid}</td>
                    <td className="py-1.5 pr-3">{a.neighborhood || '—'}</td>
                    <td className="py-1.5 pr-3">{a.assignee_username}</td>
                    <td className={`py-1.5 pr-3 figure ${a.overdue ? 'text-flag font-semibold' : ''}`}>
                      {a.due_date?.slice(0, 10)}{a.overdue ? ' (overdue)' : ''}
                    </td>
                    <td className="py-1.5 pr-3">
                      <select value={a.state} onChange={(e) => setItemState(a, e.target.value)}
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
    </div>
  )
}
