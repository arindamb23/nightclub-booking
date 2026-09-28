import { useCallback, useEffect, useState } from 'react'
import Icon from './Icon.jsx'
import { Spinner } from './Common.jsx'
import { api } from '../api.js'
import { useEvent } from '../context/EventsContext.jsx'
import { useMessages } from '../context/MessageContext.jsx'

// Settings: custom node packs ComfyUI could not load at its last start (from its console log), with Repair.
export default function NodeHealth() {
  const msg = useMessages()
  const [data, setData] = useState(null)
  const [restart, setRestart] = useState(null)
  const load = useCallback(() => api.get('/api/nodepacks/health').then(setData).catch(() => setData({ packs: [], log_available: false })), [])
  useEffect(() => { load() }, [load])
  useEvent('nodepack', (ev) => setData((d) => d && { ...d, packs: d.packs.map((p) => (p.url === ev.url ? { ...p, status: ev.status, job: ev } : p)) }))
  useEvent('comfy_restart', (ev) => { setRestart(ev); if (ev.status === 'done') setTimeout(load, 1500) })

  const repair = async (p) => {
    try { await api.post('/api/nodepacks/repair', { folder: p.folder }) } catch (e) { msg.showError(e) }
  }
  const restartNow = () => api.post('/api/comfyui/restart').then(setRestart).catch((e) => msg.showError(e))
  const needsRestart = data?.packs.some((p) => p.status === 'installed')

  return (
    <div className="card">
      <div className="card-head">
        <div><h3>Custom nodes health</h3><span className="muted small">Node packs ComfyUI could not load at its last start</span></div>
        <button className="btn btn-sm btn-ghost" onClick={load}><Icon name="refresh" size={14} />Check again</button>
      </div>
      <div className="card-body stack" style={{ gap: 12 }}>
        {!data ? <div className="row muted"><Spinner />Reading the ComfyUI console…</div>
          : !data.log_available ? <div className="callout callout-info small"><Icon name="info" /><div>Start ComfyUI with Start-all.bat (or Settings → Start ComfyUI) so its console is recorded, then check again.</div></div>
            : !data.packs.length ? <div className="callout callout-success small"><Icon name="checkCircle" /><div>Every custom node pack loaded.</div></div>
              : data.packs.map((p) => {
                const busy = ['queued', 'installing'].includes(p.status)
                return (
                  <div key={p.folder} className="card card-pad nodepack">
                    <div className="row between row-wrap" style={{ gap: 8 }}>
                      <div style={{ minWidth: 0 }}>
                        <div className="cell-main" style={{ fontWeight: 600 }}>{p.folder}</div>
                        <div className="cell-sub">{p.modules.length ? `Missing: ${p.modules.join(', ')}` : 'Failed to load'}{p.engine ? ` · needs ${p.engine}` : ''}</div>
                      </div>
                      {p.status === 'installed'
                        ? <span className="badge badge-accent"><span className="badge-dot" />Repaired · restart needed</span>
                        : p.status === 'error' ? <span className="badge badge-danger"><span className="badge-dot" />Repair failed</span>
                          : <button className="btn btn-sm btn-primary" onClick={() => repair(p)} disabled={busy || !p.url}>{busy ? <Spinner size={13} /> : <Icon name="refresh" size={13} />}Repair</button>}
                    </div>
                    <pre className="nodepack-log">{(p.job?.log?.length ? p.job.log : p.errors).join('\n')}</pre>
                    {p.job?.error && <div className="small mt-8" style={{ color: 'var(--danger)' }}>{p.job.error}</div>}
                  </div>
                )
              })}
        {restart?.status === 'restarting' && <div className="callout callout-info small"><Spinner size={14} /><div>{restart.message}</div></div>}
        {restart?.status === 'error' && <div className="callout callout-warning small"><Icon name="alert" /><div>{restart.message}</div></div>}
        {needsRestart && restart?.status !== 'restarting' && (
          <div className="callout callout-info small"><Icon name="info" /><div style={{ flex: 1 }}>Restart ComfyUI to load the repaired nodes.</div>
            <button className="btn btn-sm btn-primary" onClick={restartNow}><Icon name="refresh" size={13} />Restart ComfyUI</button></div>
        )}
      </div>
    </div>
  )
}
