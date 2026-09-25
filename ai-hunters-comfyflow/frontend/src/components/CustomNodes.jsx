import { useCallback, useEffect, useRef, useState } from 'react'
import Modal from './Modal.jsx'
import Icon from './Icon.jsx'
import { Progress, Spinner } from './Common.jsx'
import { api } from '../api.js'
import { useEvent } from '../context/EventsContext.jsx'

const STATUS = {
  missing: ['badge-warning', 'Not installed'],
  no_url: ['badge-danger', 'Package unknown'],
  queued: ['badge-info', 'Waiting'],
  installing: ['badge-info', 'Installing'],
  installed: ['badge-accent', 'Installed · restart needed'],
  restart: ['badge-accent', 'Installed · restart needed'],
  restarting: ['badge-info', 'Restarting ComfyUI'],
  done: ['badge-success', 'Ready'],
  error: ['badge-danger', 'Install failed'],
}
const BUSY = ['queued', 'installing', 'restarting']

// Rows of missing custom-node packages with Install buttons; installs one package at a time, then restarts ComfyUI.
export function useCustomNodes(initialPacks, onReady) {
  const [packs, setPacks] = useState(() => (initialPacks || []).map((p) => ({ ...p, value: p.url || '' })))
  const [restart, setRestart] = useState({ status: 'idle', message: '' })
  const [error, setError] = useState('')
  const wantRestart = useRef(false)
  const readyRef = useRef(onReady)
  readyRef.current = onReady

  useEffect(() => { setPacks((cur) => mergePacks(cur, initialPacks || [])) }, [initialPacks])

  const applyJob = (job) => setPacks((cur) => cur.map((p) => (p.url && p.url === job.url
    ? { ...p, status: job.status === 'installed' ? 'installed' : job.status, error: job.error, job } : p)))
  useEvent('nodepack', applyJob)
  useEvent('comfy_restart', (ev) => {
    setRestart(ev)
    if (ev.status === 'done') {
      setPacks((cur) => cur.map((p) => (['installed', 'restart'].includes(p.status) ? { ...p, status: 'done' } : p)))
      wantRestart.current = false
      readyRef.current?.()
    }
  })

  // once every package is installed, restart ComfyUI (only after an "Install all")
  useEffect(() => {
    if (!wantRestart.current || restart.status === 'restarting') return
    if (packs.some((p) => BUSY.includes(p.status))) return
    if (packs.some((p) => p.status === 'error' || p.status === 'no_url' || p.status === 'missing')) { wantRestart.current = false; return }
    api.post('/api/comfyui/restart').then(setRestart).catch((e) => setError(e.message))
  }, [packs, restart.status])

  const install = useCallback(async (pack) => {
    const url = (pack.value || '').trim()
    if (!url) { setError(`Enter the GitHub URL of the package that provides ${pack.class_types.join(', ')}.`); return false }
    setError('')
    try {
      const job = await api.post('/api/nodepacks/install', { url, class_types: pack.class_types, name: pack.name })
      setPacks((cur) => cur.map((p) => (p === pack || p.class_types.join() === pack.class_types.join()
        ? { ...p, url: job.url, value: job.url, status: job.status, job } : p)))
      return true
    } catch (e) {
      setError(e.message)
      return false
    }
  }, [])

  const installAll = async () => {
    const todo = packs.filter((p) => ['missing', 'no_url', 'error'].includes(p.status))
    const blank = todo.filter((p) => !(p.value || '').trim())
    if (blank.length) { setError(`Enter the GitHub URL for: ${blank.flatMap((p) => p.class_types).join(', ')}`); return }
    wantRestart.current = true
    for (const p of todo) {
      if (!(await install(p))) { wantRestart.current = false; return }
    }
    if (!todo.length) api.post('/api/comfyui/restart').then(setRestart).catch((e) => setError(e.message))
  }
  const restartNow = () => api.post('/api/comfyui/restart').then(setRestart).catch((e) => setError(e.message))
  const setValue = (i, value) => setPacks((cur) => cur.map((p, j) => (j === i ? { ...p, value } : p)))
  const busy = packs.some((p) => BUSY.includes(p.status)) || restart.status === 'restarting'
  const needsRestart = packs.some((p) => ['installed', 'restart'].includes(p.status))
  return { packs, restart, error, busy, needsRestart, install, installAll, restartNow, setValue }
}

function mergePacks(cur, next) {
  return next.map((p) => {
    const old = cur.find((c) => c.class_types.join() === p.class_types.join())
    return { ...p, value: old?.value || p.url || '' }
  })
}

export function CustomNodeRows({ state, compact = false }) {
  const { packs, install, setValue } = state
  const [openLog, setOpenLog] = useState(null)
  return (
    <div className="stack" style={{ gap: 12 }}>
      {packs.map((p, i) => {
        const [cls, label] = STATUS[p.status] || ['', p.status]
        const log = p.job?.log || []
        return (
          <div key={p.class_types.join()} className="card card-pad nodepack">
            <div className="row between row-wrap" style={{ gap: 8 }}>
              <div style={{ minWidth: 0 }}>
                <div className="cell-main break" style={{ fontWeight: 600 }}>{p.status === 'no_url' ? 'Unknown package' : p.name}</div>
                <div className="chips mt-8">{p.class_types.map((c) => <span key={c} className="chip mono">{c}</span>)}</div>
              </div>
              <span className={`badge ${cls}`}>{BUSY.includes(p.status) ? <Spinner size={12} /> : <span className="badge-dot" />}{label}</span>
            </div>
            {p.status !== 'done' && (
              <div className="row mt-8" style={{ alignItems: 'flex-end', gap: 8 }}>
                <div className="field" style={{ flex: 1, marginBottom: 0 }}>
                  <label htmlFor={`np-${i}`}>Git repository {p.source ? <span className="muted">· found in the {p.source}</span> : null}</label>
                  <input id={`np-${i}`} className="input input-mono" value={p.value || ''} disabled={BUSY.includes(p.status)}
                    list={p.alternatives?.length ? `np-alt-${i}` : undefined}
                    placeholder="https://github.com/owner/ComfyUI-SomeNodes" onChange={(e) => setValue(i, e.target.value)} />
                  {p.alternatives?.length > 0 && (
                    <datalist id={`np-alt-${i}`}>{[p.url, ...p.alternatives].filter(Boolean).map((u) => <option key={u} value={u} />)}</datalist>
                  )}
                  {p.alternatives?.length > 0 && <span className="hint">{p.alternatives.length} other package(s) also provide this node — the most used one is chosen.</span>}
                </div>
                {['missing', 'no_url', 'error'].includes(p.status) && (
                  <button className="btn" onClick={() => install(p)}><Icon name="download" size={14} />{p.status === 'error' ? 'Retry' : 'Install'}</button>
                )}
              </div>
            )}
            {p.status === 'no_url' && !compact && (
              <div className="small muted mt-8">Not in the ComfyUI-Manager list. Search the node name on GitHub or in ComfyUI-Manager and paste the repository link. If it is a core node, update ComfyUI instead.</div>
            )}
            {p.error && <div className="small mt-8" style={{ color: 'var(--danger)' }}>{p.error}</div>}
            {p.status === 'installing' && <div className="mt-8"><Progress indeterminate /></div>}
            {log.length > 0 && (
              <div className="mt-8">
                <button className="btn btn-ghost btn-sm" onClick={() => setOpenLog(openLog === i ? null : i)}><Icon name="code" size={13} />{openLog === i ? 'Hide' : 'Show'} install log</button>
                {openLog === i && <pre className="nodepack-log">{log.join('\n')}</pre>}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

export function RestartBanner({ state }) {
  const { restart, needsRestart, busy, restartNow } = state
  if (restart.status === 'restarting') return <div className="callout callout-info"><Spinner size={16} /><div>{restart.message || 'Restarting ComfyUI…'} This can take a minute.</div></div>
  if (restart.status === 'error') return <div className="callout callout-warning"><Icon name="alert" /><div style={{ flex: 1 }}>{restart.message}</div><button className="btn btn-sm" onClick={restartNow}>Try again</button></div>
  if (restart.status === 'done' && !needsRestart) return <div className="callout callout-success"><Icon name="checkCircle" /><div>{restart.message}</div></div>
  if (needsRestart && !busy) return <div className="callout callout-info"><Icon name="info" /><div style={{ flex: 1 }}>ComfyUI must restart to load the new nodes.</div><button className="btn btn-sm btn-primary" onClick={restartNow}><Icon name="refresh" size={13} />Restart ComfyUI</button></div>
  return null
}

// Shown when a run is refused because custom nodes are not installed.
export default function CustomNodesModal({ packs, onClose, onReady }) {
  const state = useCustomNodes(packs, onReady)
  const { error, busy, installAll } = state
  const allKnown = state.packs.every((p) => p.status !== 'no_url' || (p.value || '').trim())
  return (
    <Modal
      size="lg"
      title="Custom nodes needed for this workflow"
      icon={<span className="msg-icon msg-warning"><Icon name="layers" size={20} /></span>}
      onClose={onClose}
      dismissible={!busy}
      footer={(
        <>
          <div className="left muted small">Installed into ComfyUI\custom_nodes and added to config\custom-nodes.txt (Setup.bat keeps them).</div>
          <button className="btn" onClick={onClose} disabled={busy}>Cancel</button>
          <button className="btn btn-primary" onClick={installAll} disabled={busy || !allKnown} data-autofocus>
            {busy ? <Spinner /> : <Icon name="download" size={14} />}Install all &amp; restart ComfyUI
          </button>
        </>
      )}
    >
      <p className="msg-text" style={{ marginTop: 0 }}>
        ComfyUI does not have the node types below. ComfyFlow found the package for each one (from the workflow itself,
        the ComfyUI-Manager list or the Comfy Registry). Press <b>Install all</b>: each package is downloaded with git, its
        Python requirements are installed into ComfyUI&apos;s environment, ComfyUI restarts, and <b>the run starts again by itself</b>.
      </p>
      {error && <div className="callout callout-warning mt-8" role="alert"><Icon name="alert" /><div className="msg-text">{error}</div></div>}
      <div className="mt-16"><RestartBanner state={state} /></div>
      <div className="mt-16"><CustomNodeRows state={state} /></div>
      <p className="small muted mt-16">Only install packages you trust: custom nodes run Python code on this PC.</p>
    </Modal>
  )
}
