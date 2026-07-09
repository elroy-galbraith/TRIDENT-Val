import { PageAgent } from 'page-agent'
import { logger } from './logger.js'

const chartSummaries = {}
const truncate = (s, n = 400) => (s && s.length > n ? `${s.slice(0, n)}…` : s)

// Mirrors agent.history (steps/observations/retries/errors) into the app's own
// system_logs ledger via logger.track, so copilot activity is queryable later at
// GET /api/v1/logs the same way underwriter actions are.
function logHistoryEvent(event) {
  switch (event.type) {
    case 'step': {
      const { action, reflection } = event
      logger.track('copilot', `${action.name}: ${truncate(action.output)}`, {
        input: action.input, next_goal: reflection?.next_goal, memory: reflection?.memory,
      })
      break
    }
    case 'observation':
      logger.track('copilot', truncate(event.content))
      break
    case 'user_takeover':
      logger.track('copilot', 'User took over the page mid-task.')
      break
    case 'retry':
      logger.track('copilot', `Retry ${event.attempt}/${event.maxAttempts}: ${truncate(event.message)}`)
      break
    case 'error':
      logger.track('copilot', `Agent error: ${truncate(event.message)}`)
      break
  }
}

export function setChartSummary(key, data) {
  chartSummaries[key] = data
}

const SYSTEM_INSTRUCTIONS = `You are the in-page copilot for TRIDENT-Val, a residential-portfolio AVM and
risk-triage sandbox for bank underwriters and risk officers. Help the user navigate and
read the app — do not attempt to change loan or audit data on their behalf.

Four views, reachable from the top navigation:
- "Risk Overview": portfolio-wide KPIs (exposure, average LTV, equity cushion), an
  LTV-distribution chart, a neighborhood-concentration chart, and a map of the book.
- "Portfolio": a searchable, filterable, sortable grid of every property. Filters cover
  neighborhood, property type, audit status, and free-text search. Clicking a card opens
  that property's Inspector.
- "Map": the same portfolio plotted geographically; pins are colored by LTV risk tier.
- "Model Card": a plain-language explainer of the AVM itself, written for non-technical
  auditors — what it does, its holdout accuracy (MAPE/R²), what data it trained on, an
  interactive chart of which factors move its valuations the most (with click-to-expand
  explanations), and its known limitations/appropriate use. Point auditors here first if
  they ask what the model is or how trustworthy it is.

Opening a property (from a Portfolio card or a Map pin) opens its Inspector: the asset
file, an interactive what-if scenario panel (quality/size/kitchen/functional sliders and
selects that recalculate the AVM live), SHAP-based value-driver explanations, nearby
comparable properties, and an audit lifecycle box.

The LTV-distribution and neighborhood-concentration charts on Risk Overview, and the
factor-importance chart on the Model Card, render as SVG and are not readable from the
page text. If asked to explain one, use the JSON chart data summary appended to this
context instead of trying to read the chart's DOM.

The audit status dropdown, underwriter notes field, and "Save audit decision" button on
the Inspector are off-limits — they write to the bank's audit ledger and carry a
data-page-agent-not-interactive attribute that keeps you from clicking or typing into
them. If asked to change a property's audit status or notes, explain that only a human
underwriter can do that, and offer to navigate there instead.`

export function createCopilot() {
  const agent = new PageAgent({
    baseURL: '/api/v1/copilot',
    // Placeholder only: the real provider key lives server-side in the proxy, never in the browser.
    model: 'trident-copilot',
    language: 'en-US',
    instructions: { system: SYSTEM_INSTRUCTIONS },
    transformPageContent: async (content) => {
      const keys = Object.keys(chartSummaries)
      if (!keys.length) return content
      const summary = keys.map((k) => `${k}: ${JSON.stringify(chartSummaries[k])}`).join('\n')
      return `${content}\n\n[Chart data summary — charts are SVG and unreadable from the DOM]\n${summary}`
    },
  })
  agent.panel.show() // the panel starts hidden until shown; page-agent's own CDN bootstrap does the same

  let loggedCount = 0
  agent.addEventListener('historychange', () => {
    for (const event of agent.history.slice(loggedCount)) logHistoryEvent(event)
    loggedCount = agent.history.length
  })

  return agent
}
