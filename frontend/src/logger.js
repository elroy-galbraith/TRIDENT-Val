// Human-readable, leveled logging for the workbench, built on `loglevel`.
//
// Every call site passes a `scope` (e.g. 'inspector', 'api') so console lines
// read like `14:02:11 INFO  [inspector] Recalculated valuation`. WARN/ERROR
// lines and explicit `logger.track(...)` usage events are shipped to the
// backend's unified `system_logs` ledger (see /api/v1/logs/client) so they
// land in the same audit trail as backend telemetry — logging must never be
// able to break the UI, so shipping failures are swallowed.
import log from 'loglevel'

const BASE = '/api/v1'
const REMOTE_LEVELS = new Set(['WARN', 'ERROR'])
const LEVEL_STYLE = {
  TRACE: 'color:#5B6B77', DEBUG: 'color:#5B6B77', INFO: 'color:#0E7C7B',
  WARN: 'color:#C77D0A;font-weight:600', ERROR: 'color:#B3352C;font-weight:600',
}

let queue = []
let flushTimer = null

// `keepalive` is only safe for the beforeunload flush: browsers cap total
// concurrent keepalive payload size (~64KB), so using it on every periodic
// flush risks a TypeError if a batch is large.
function flush(isUnloading = false) {
  if (flushTimer) { clearTimeout(flushTimer); flushTimer = null }
  if (!queue.length) return
  const batch = queue
  queue = []
  fetch(`${BASE}/logs/client`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(batch),
    ...(isUnloading ? { keepalive: true } : {}),
  }).catch(() => {})
}

function ship(entry) {
  queue.push(entry)
  if (!flushTimer) flushTimer = setTimeout(() => flush(false), 1500)
}

if (typeof window !== 'undefined') {
  window.addEventListener('beforeunload', () => flush(true))
}

function serialize(arg) {
  if (arg instanceof Error) return arg.stack || arg.message
  if (typeof arg === 'object' && arg !== null) {
    try { return JSON.stringify(arg) } catch { return String(arg) }
  }
  return String(arg)
}

const originalFactory = log.methodFactory
log.methodFactory = (methodName, logLevel, loggerName) => {
  const raw = originalFactory(methodName, logLevel, loggerName)
  const levelName = methodName.toUpperCase()
  return (scope, ...args) => {
    const ts = new Date().toTimeString().slice(0, 8)
    raw(`%c${ts} ${levelName.padEnd(5)} [${scope}]`, LEVEL_STYLE[levelName] || '', ...args)
    if (REMOTE_LEVELS.has(levelName)) {
      ship({ level: levelName, logger: scope, message: args.map(serialize).join(' ') })
    }
  }
}
log.setLevel(import.meta.env.DEV ? 'debug' : 'warn')
log.rebuild()

export const logger = {
  debug: (scope, ...args) => log.debug(scope, ...args),
  info: (scope, ...args) => log.info(scope, ...args),
  warn: (scope, ...args) => log.warn(scope, ...args),
  error: (scope, ...args) => log.error(scope, ...args),

  // Explicit usage/audit event: logged to console AND always persisted to
  // the backend ledger, regardless of the active console log level.
  track(scope, message, context, pid) {
    log.info(scope, message)
    ship({ level: 'INFO', logger: scope, message, context, pid })
  },
}
