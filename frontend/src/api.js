const BASE = '/api/v1'

async function get(path) {
  const r = await fetch(`${BASE}${path}`)
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json()
}

export const api = {
  summary: () => get('/portfolio/summary'),
  map: () => get('/portfolio/map'),
  filters: () => get('/properties/filters'),
  properties: (params) => get(`/properties?${new URLSearchParams(params)}`),
  property: (pid) => get(`/properties/${pid}`),
  spec: () => get('/model/spec'),
  valuate: (features) =>
    fetch(`${BASE}/valuate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ features }),
    }).then((r) => { if (!r.ok) throw new Error('valuation failed'); return r.json() }),
  updateAudit: (pid, body) =>
    fetch(`${BASE}/properties/${pid}/audit`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then((r) => { if (!r.ok) throw new Error('audit update failed'); return r.json() }),
  exportUrl: `${BASE}/properties/export`,
}

export const usd = (n, digits = 0) =>
  n == null ? '—' : n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: digits })

export const pct = (n, digits = 1) => n == null ? '—' : `${(n * 100).toFixed(digits)}%`

export const ltvTier = (ltv) => (ltv >= 0.8 ? 'high' : ltv >= 0.6 ? 'mid' : 'low')
export const tierColor = { high: '#B3352C', mid: '#C77D0A', low: '#2E7D4F' }
