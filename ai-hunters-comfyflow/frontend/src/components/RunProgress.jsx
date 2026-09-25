import { useEffect, useRef, useState } from 'react'
import { Progress, RunStatus } from './Common.jsx'
import { Thumb, outputsToItems, usePreview } from './PreviewModals.jsx'
import { api } from '../api.js'
import { useEvent } from '../context/EventsContext.jsx'

const DONE = ['succeeded', 'failed', 'cancelled']

// Live progress of one run: model downloads (preparing), node execution, then result thumbnails.
export default function RunProgress({ run, title = 'Current run' }) {
  const openPreview = usePreview()
  const prog = run?.progress
  const active = run && !DONE.includes(run.status)
  const nodePct = prog?.max ? (prog.value / prog.max) * 100 : null
  const overall = prog?.total ? (prog.done / prog.total) * 100 : 0
  const items = run?.status === 'succeeded' ? outputsToItems(run) : []
  return (
    <>
      <div className="row between">
        <h3>{title}</h3>
        <RunStatus status={run.status} />
      </div>
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
          <span>{prog?.class_type ? <>Executing <b>{prog.class_type}</b> (node {prog.node})</> : run.status === 'preparing' ? 'Starts when the models are ready' : active ? 'Waiting for ComfyUI…' : 'Finished'}</span>
          <span className="muted">{prog?.done || 0} / {prog?.total || 0} nodes</span>
        </div>
        <div className="mt-8"><Progress percent={overall} large indeterminate={run.status !== 'preparing' && active && !overall} /></div>
        {nodePct != null && active && (
          <div className="mt-8 small muted row between"><span>Steps</span><span>{prog.value} / {prog.max}</span></div>
        )}
        {nodePct != null && active && <div className="mt-8"><Progress percent={nodePct} /></div>}
      </div>
      {items.length > 0 && (
        <div className="thumbs mt-16">
          {items.map((item, i, all) => <Thumb key={item.filename} item={item} onClick={() => openPreview(all, i)} />)}
        </div>
      )}
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
