import { logger } from './logger.js'

const BASE = '/api/v1'

// Set by App.jsx so a session that expires mid-use (401 on any call) can bounce
// the user back to the login screen instead of surfacing a raw fetch error.
let onUnauthorized = () => {}
export function setUnauthorizedHandler(fn) { onUnauthorized = fn }

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
    if (r.status === 401) onUnauthorized()
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
    if (r.status === 401) onUnauthorized()
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
  propertyValuations: (pid) => get(`/properties/${pid}/valuations`),
  comps: (pid, limit = 6) => get(`/properties/${pid}/comps?limit=${limit}`),
  valuate: (features, model_id) =>
    send('POST', '/valuate', model_id ? { features, model_id } : { features }, 'valuation failed'),
  updateAudit: (pid, body) => send('PATCH', `/properties/${pid}/audit`, body, 'audit update failed'),
  triageDecision: (pid, body) =>
    send('POST', `/properties/${pid}/triage-decision`, body, 'triage decision failed'),
  exportUrl: `${BASE}/properties/export`,
  login: (username, password) => send('POST', '/auth/login', { username, password }, 'login failed'),
  logout: () => send('POST', '/auth/logout', {}, 'logout failed'),
  me: () => get('/auth/me'),
  models: () => get('/models'),
  model: (id) => get(`/models/${id}`),
  modelSpec: (id) => get(`/models/${id}/spec`),
  modelImportance: (id) => get(`/models/${id}/importance`),
  promoteModel: (id, rationale) =>
    send('POST', `/models/${id}/promote`, { rationale }, 'promotion failed'),
  compareModels: (params) => get(`/models/compare?${new URLSearchParams(params)}`),
  disagreements: (params) => get(`/models/disagreements?${new URLSearchParams(params)}`),
  assetReportUrl: (pid) => `${BASE}/properties/${pid}/report`,
  portfolioReportUrl: (params) => {
    const qs = params && Object.keys(params).length ? `?${new URLSearchParams(params)}` : ''
    return `${BASE}/portfolio/report${qs}`
  },
  revaluations: () => get('/revaluations'),
  revaluation: (runId) => get(`/revaluations/${runId}`),
  revaluationFlagged: (runId, params) => get(`/revaluations/${runId}/flagged?${new URLSearchParams(params)}`),
  runRevaluation: (body) => send('POST', '/revaluations', body, 'revaluation cycle failed'),
  revaluationReportUrl: (runId) => `${BASE}/revaluations/${runId}/report`,
  ingestionSync: (sourceSystem) =>
    send('POST', '/ingestion/sync', { source_system: sourceSystem }, 'ingestion sync failed'),
  ingestionRuns: () => get('/ingestion/runs'),
  ingestionRun: (runId) => get(`/ingestion/runs/${runId}`),
  ingestionRecords: (params) => get(`/ingestion/records?${new URLSearchParams(params)}`),
  ingestionQuarantine: (params) => get(`/ingestion/quarantine?${new URLSearchParams(params)}`),
  resolveQuarantine: (id, resolution_notes) =>
    send('POST', `/ingestion/quarantine/${id}/resolve`, { resolution_notes }, 'quarantine resolution failed'),
  generateDocuments: (pids, style, degrade) =>
    send('POST', '/documents/generate', { pids, style, degrade }, 'document generation failed'),
  documents: (params) => get(`/documents?${new URLSearchParams(params)}`),
  runExtraction: (documentId) =>
    send('POST', `/documents/${documentId}/extract`, {}, 'extraction failed'),
  extractionRuns: () => get('/extraction/runs'),
  extractionRun: (runId) => get(`/extraction/runs/${runId}`),
  extractionAccuracy: () => get('/extraction/accuracy'),
  extractionTriage: (params) => get(`/extraction/triage?${new URLSearchParams(params)}`),
  resolveExtractionTriage: (id, resolution) =>
    send('POST', `/extraction/triage/${id}/resolve`, { resolution }, 'triage resolution failed'),
}

export const usd = (n, digits = 0) =>
  n == null ? '—' : n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: digits })

export const pct = (n, digits = 1) => n == null ? '—' : `${(n * 100).toFixed(digits)}%`

export const ltvTier = (ltv) => (ltv >= 0.8 ? 'high' : ltv >= 0.6 ? 'mid' : 'low')
export const tierColor = { high: '#B3352C', mid: '#C77D0A', low: '#2E7D4F' }
