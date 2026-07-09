import { logger } from './logger.js'

const BASE = '/api/v1'

async function get(path) {
  const start = performance.now()
  let r
  try {
    r = await fetch(`${BASE}${path}`)
  } catch (e) {
    logger.error('api', `Network error fetching ${path}: ${e.message}`)
    throw e
  }
  const duration_ms = Math.round(performance.now() - start)
  if (!r.ok) {
    const body = await r.text()
    logger.error('api', `${path} -> ${r.status} (${duration_ms}ms)`)
    throw new Error(`${r.status} ${body}`)
  }
  logger.debug('api', `${path} -> ${r.status} (${duration_ms}ms)`)
  return r.json()
}

async function send(method, path, body, failMessage) {
  let r
  try {
    r = await fetch(`${BASE}${path}`, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  } catch (e) {
    logger.error('api', `Network error on ${method} ${path}: ${e.message}`)
    throw e
  }
  if (!r.ok) {
    logger.error('api', `${method} ${path} -> ${r.status}`)
    throw new Error(failMessage)
  }
  return r.json()
}

export const api = {
  summary: () => get('/portfolio/summary'),
  map: () => get('/portfolio/map'),
  filters: () => get('/properties/filters'),
  properties: (params) => get(`/properties?${new URLSearchParams(params)}`),
  property: (pid) => get(`/properties/${pid}`),
  comps: (pid, limit = 6) => get(`/properties/${pid}/comps?limit=${limit}`),
  spec: () => get('/model/spec'),
  valuate: (features) => send('POST', '/valuate', { features }, 'valuation failed'),
  updateAudit: (pid, body) => send('PATCH', `/properties/${pid}/audit`, body, 'audit update failed'),
  exportUrl: `${BASE}/properties/export`,
}

export const usd = (n, digits = 0) =>
  n == null ? '—' : n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: digits })

export const pct = (n, digits = 1) => n == null ? '—' : `${(n * 100).toFixed(digits)}%`

export const ltvTier = (ltv) => (ltv >= 0.8 ? 'high' : ltv >= 0.6 ? 'mid' : 'low')
export const tierColor = { high: '#B3352C', mid: '#C77D0A', low: '#2E7D4F' }
