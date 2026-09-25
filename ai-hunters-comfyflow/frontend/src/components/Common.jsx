import Icon from './Icon.jsx'
import { formatBytes } from '../utils/format.js'

export function PageHeader({ title, subtitle, actions }) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  )
}

export function Progress({ percent, indeterminate = false, large = false }) {
  return (
    <div className={`progress ${large ? 'progress-lg' : ''} ${indeterminate ? 'indeterminate' : ''}`}>
      <div style={{ width: `${Math.max(0, Math.min(100, percent || 0))}%` }} />
    </div>
  )
}

const MODEL_STATUS = {
  ready: ['badge-success', 'Ready'],
  missing: ['badge-warning', 'Missing'],
  no_url: ['badge-danger', 'No URL'],
  queued: ['badge-info', 'Queued'],
  downloading: ['badge-info', 'Downloading'],
  error: ['badge-danger', 'Failed'],
  cancelled: ['', 'Cancelled'],
}

export function ModelStatus({ status, job }) {
  const [cls, label] = MODEL_STATUS[status] || ['', status]
  const active = status === 'downloading' || status === 'queued'
  return (
    <div className="status-cell">
      <span className={`badge ${cls}`} style={{ alignSelf: 'flex-start' }}><span className="badge-dot" />{label}{active && job?.percent != null ? ` ${Math.round(job.percent)}%` : ''}</span>
      {active && (
        <>
          <Progress percent={job?.percent} indeterminate={job?.percent == null} />
          <span className="small muted">
            {formatBytes(job?.downloaded || 0)}{job?.total ? ` / ${formatBytes(job.total)}` : ''}{job?.speed ? ` · ${formatBytes(job.speed)}/s` : ''}
          </span>
        </>
      )}
      {status === 'error' && job?.error && <span className="small" style={{ color: 'var(--danger)' }}>{job.error}</span>}
    </div>
  )
}

const RUN_STATUS = {
  queued: ['badge-info', 'Queued'],
  running: ['badge-accent', 'Running'],
  succeeded: ['badge-success', 'Succeeded'],
  failed: ['badge-danger', 'Failed'],
  cancelled: ['', 'Cancelled'],
}

export function RunStatus({ status }) {
  const [cls, label] = RUN_STATUS[status] || ['', status || 'Never run']
  return <span className={`badge ${cls}`}><span className="badge-dot" />{label}</span>
}

export function EmptyState({ icon = 'box', title, text, action }) {
  return (
    <div className="empty">
      <div className="empty-icon"><Icon name={icon} size={26} /></div>
      <h3>{title}</h3>
      {text && <p>{text}</p>}
      {action}
    </div>
  )
}

export function Spinner({ size = 16 }) {
  return <Icon name="loader" size={size} className="spin" />
}
