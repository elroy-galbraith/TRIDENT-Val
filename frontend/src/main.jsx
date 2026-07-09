import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import { logger } from './logger.js'
import './index.css'

logger.track('app', 'Session started.')
window.addEventListener('error', (e) =>
  logger.error('app', `Unhandled error: ${e.message} (${e.filename}:${e.lineno})`))
window.addEventListener('unhandledrejection', (e) =>
  logger.error('app', `Unhandled promise rejection: ${e.reason}`))

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode><App /></React.StrictMode>
)
