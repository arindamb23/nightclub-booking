import { useEffect, useRef, useState } from 'react'
import { Progress, RunStatus } from './Common.jsx'
import Icon from './Icon.jsx'
import LiveRunView, { RunHealth } from '../pages/editor/LiveRunView.jsx'
import { Thumb, outputsToItems, usePreview } from './PreviewModals.jsx'
import { api } from '../api.js'
import { useEvent } from '../context/EventsContext.jsx'

const DONE = ['succeeded', 'failed', 'cancelled']
const AUTO_KEY = 'comfyflow.liveView.auto'

function readAuto() {
  try { return localStorage.getItem(AUTO_KEY) === '1' } catch { return false }
}

// Live progress of one run: model downloads (preparing), node execution, then result thumbnails.
export default function RunProgress({ run, title = 'Current run', onCancel }) {
  const openPreview = usePreview()
  const [live, setLive] = useState(false)
  const [auto, setAuto] = useState(readAuto)
  const opened = useRef(null)
  // open the node view by itself when a new run starts (if the user asked for it)
  useEffect(() => {
    if (auto && run && !DONE.includes(run.status) && opened.current !== run.id) {
      opened.current = run.id
      setLive(true)
    }
  }, [auto, run])
  const toggleAuto = (v) => {
    setAuto(v)
    if (run) opened.current = run.id
    try { localStorage.setItem(AUTO_KEY, v ? '1' : '0') } catch { /* private window */ }
  }
  const prog = run?.progress
  const active = run && !DONE.includes(run.status)
  const nodePct = prog?.max ? (prog.value / prog.max) * 100 : null
  const overall = prog?.total ? (prog.done / prog.total) * 100 : 0
  const items = run?.status === 'succeeded' ? outputsToItems(run) : []
  return (
    <>
      <div className="row between row-wrap" style={{ gap: 8 }}>
        <h3>{title}</h3>
        <div className="row" style={{ gap: 8 }}>
          <RunStatus status={run.status} />
          <button className="btn btn-sm" onClick={() => setLive(true)} title="See every node light up as ComfyUI runs it">
            <Icon name="workflow" size={14} />Live node view
          </button>
        </div>
      </div>
      <label className="checkbox small mt-8"><input type="checkbox" checked={auto} onChange={(e) => toggleAuto(e.target.checked)} />Open the live node view automatically when a run starts</label>
      {run.status === 'preparing' && prog?.models && (
        <div className="run-progress mt-16">
          <div className="row between small">
            <span><b>Downloading models</b> before the run starts</span>
            <span className="muted">{prog.models.ready} / {prog.models.total} ready</span>
          </div>
          <div className="mt-8"><Progress percent={(prog.models.ready / Math.max(1, prog.models.total)) * 100} large /></div>
          <div className="stack mt-16" style={{ gap: 8 }}>
            {prog.models.items.filter((m) => m.status !== 'ready').map((m) => (
              <div key={m.name}>
                <div className="row between small"><span className="mono truncate">{m.name}</span><span className="muted">{m.percent != null ? `${Math.round(m.percent)}%` : m.status}</span></div>
                <div className="mt-8"><Progress percent={m.percent} indeterminate={m.percent == null} /></div>
              </div>
            ))}
          </div>
        </div>
      )}
      <div className="run-progress mt-16">
        <div className="row between small">
          <span>{active && prog?.class_type ? <>Executing <b>{prog.class_type}</b> (node {prog.node})</> : run.status === 'preparing' ? 'Starts when the models are ready' : active ? (prog?.phase || 'Waiting for ComfyUI to start the workflow…') : 'Finished'}</span>
          <span className="muted">{prog?.done || 0} / {prog?.total || 0} nodes</span>
        </div>
        <div className="mt-8"><Progress percent={overall} large indeterminate={run.status !== 'preparing' && active && !overall} /></div>
        {nodePct != null && active && (
          <div className="mt-8 small muted row between"><span>Steps</span><span>{prog.value} / {prog.max}</span></div>
        )}
        {nodePct != null && active && <div className="mt-8"><Progress percent={nodePct} /></div>}
      </div>
      {run.model_moves?.length > 0 && (
        <div className="callout callout-info small mt-16"><Icon name="info" /><div>
          <b>{run.model_moves.length} model(s) moved to the folder ComfyUI reads:</b>
          <ul>{run.model_moves.map((m) => <li key={m.name}><span className="mono">{m.name}</span>: models\{m.from} → models\{m.to}</li>)}</ul>
        </div></div>
      )}
      <div className="mt-16"><RunHealth run={run} compact onOpenConsole={() => setLive('console')} /></div>
      {items.length > 0 && (
        <div className="thumbs mt-16">
          {items.map((item, i, all) => <Thumb key={item.filename} item={item} onClick={() => openPreview(all, i)} />)}
        </div>
      )}
      {live && <LiveRunView run={run} showConsole={live === 'console'} onClose={() => setLive(false)} onCancel={onCancel} />}
    </>
  )
}

// Follows a run through SSE (with a polling fallback) and calls onFinish once.
export function useRunTracker(onFinish) {
  const [run, setRun] = useState(null)
  const idRef = useRef(null)
  const finishRef = useRef(onFinish)
  finishRef.current = onFinish

  const settle = (r) => {
    if (idRef.current !== r.id) return
    setRun(r)
    if (DONE.includes(r.status)) {
      idRef.current = null
      finishRef.current?.(r)
    }
  }
  useEvent('run', (ev) => settle(ev.run))
  useEvent('download', () => {
    if (idRef.current) api.get(`/api/runs/${idRef.current}`).then(settle).catch(() => {})
  })
  useEffect(() => {
    const t = setInterval(() => {
      if (idRef.current) api.get(`/api/runs/${idRef.current}`).then(settle).catch(() => {})
    }, 4000)
    return () => clearInterval(t)
  }, [])

  const track = (r) => {
    idRef.current = r.id
    setRun(r)
  }
  const active = !!run && !DONE.includes(run.status)
  return { run, track, active }
}
