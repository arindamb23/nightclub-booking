import { useState } from 'react'
import Modal from './Modal.jsx'
import Icon from './Icon.jsx'
import { Progress, Spinner } from './Common.jsx'
import { api } from '../api.js'
import { useEvent } from '../context/EventsContext.jsx'

// A run failed with a known library/version problem (config/known-fixes.json): explain it and fix it with one click.
export default function KnownFixModal({ run, onClose, onFixed }) {
  const [job, setJob] = useState(null)
  const [error, setError] = useState('')
  const busy = job && ['running', 'restarting'].includes(job.status)

  useEvent('fix', (ev) => {
    if (ev.id !== run.fix?.id) return
    setJob(ev)
    if (ev.status === 'done') setTimeout(() => onFixed?.(), 600)
    if (ev.status === 'error') setError(ev.error)
  })

  const apply = async () => {
    setError('')
    try { setJob(await api.post(`/api/runs/${run.id}/fix`)) } catch (e) { setError(e.message) }
  }

  return (
    <Modal
      size="lg"
      title={run.fix?.title || 'Known problem'}
      icon={<span className="msg-icon msg-warning"><Icon name="zap" size={20} /></span>}
      onClose={onClose}
      dismissible={!busy}
      footer={(
        <>
          <div className="left muted small">Changes only ComfyUI&apos;s Python packages; models and workflows are not touched.</div>
          <button className="btn" onClick={onClose} disabled={busy}>Close</button>
          <button className="btn btn-primary" onClick={apply} disabled={busy || job?.status === 'done'} data-autofocus>
            {busy ? <Spinner /> : <Icon name="play" size={13} />}{job?.status === 'error' ? 'Try again' : 'Apply fix & run again'}
          </button>
        </>
      )}
    >
      <p className="msg-text" style={{ marginTop: 0 }}>{run.fix?.explain}</p>
      <div className="callout callout-warning small mt-8"><Icon name="alert" /><div className="mono break">{run.error}</div></div>
      {job && (
        <div className="mt-16">
          <div className="row between small">
            <b>{job.status === 'restarting' ? 'Restarting ComfyUI…' : job.status === 'done' ? 'Fixed — running the workflow again' : job.status === 'error' ? 'The fix did not work' : 'Installing…'}</b>
          </div>
          {busy && <div className="mt-8"><Progress indeterminate /></div>}
          {job.log?.length > 0 && <pre className="nodepack-log">{job.log.join('\n')}</pre>}
        </div>
      )}
      {error && <div className="callout callout-danger small mt-8"><Icon name="alert" /><div>{error}</div></div>}
    </Modal>
  )
}
