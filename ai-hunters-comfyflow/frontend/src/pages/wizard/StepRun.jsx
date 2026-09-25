import { useCallback, useEffect, useRef, useState } from 'react'
import Icon from '../../components/Icon.jsx'
import { Progress, RunStatus, Spinner } from '../../components/Common.jsx'
import { Thumb, outputsToItems, usePreview } from '../../components/PreviewModals.jsx'
import { api } from '../../api.js'
import { useMessages } from '../../context/MessageContext.jsx'
import { useEvent } from '../../context/EventsContext.jsx'
import { useSystem } from '../../context/SystemContext.jsx'
import { formatDate, formatDuration } from '../../utils/format.js'
import MissingModelsModal from '../../components/MissingModelsModal.jsx'
import RunProgress from '../../components/RunProgress.jsx'

const keyOf = (p) => `${p.node_id}::${p.input}`
const MAX_SEED = 2 ** 50

function MediaField({ param, value, onChange }) {
  const msg = useMessages()
  const ref = useRef(null)
  const [busy, setBusy] = useState(false)
  const upload = async (file) => {
    if (!file) return
    setBusy(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await api.upload('/api/uploads', fd)
      onChange({ upload: res.filename, original: res.original })
    } catch (e) {
      msg.showError(e)
    } finally {
      setBusy(false)
    }
  }
  const uploaded = value && typeof value === 'object' && value.upload
  return (
    <div className="media-pick">
      {uploaded && param.kind === 'image' && <img src={`/api/uploads/${encodeURIComponent(value.upload)}`} alt="Selected input" />}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="small truncate">{uploaded ? value.original : <span className="muted">Current: <span className="mono">{String(param.value)}</span></span>}</div>
        <div className="row mt-8">
          <button className="btn btn-sm" type="button" onClick={() => ref.current?.click()} disabled={busy}>
            {busy ? <Spinner size={14} /> : <Icon name="upload" size={15} />}{uploaded ? 'Replace' : `Upload ${param.kind}`}
          </button>
          {uploaded && <button className="btn btn-sm btn-ghost" type="button" onClick={() => onChange(param.value)}>Use original</button>}
        </div>
      </div>
      <input ref={ref} type="file" hidden accept={param.kind === 'image' ? 'image/*' : 'video/*'} onChange={(e) => upload(e.target.files?.[0])} />
    </div>
  )
}

function ParamField({ param, value, onChange, randomSeed, setRandomSeed }) {
  const id = `p-${keyOf(param)}`
  const label = (
    <label htmlFor={id} className="param-title">{param.title}<span className="muted">· {param.input}</span></label>
  )
  if (param.kind === 'image' || param.kind === 'video') {
    return <div className="field full">{label}<MediaField param={param} value={value} onChange={onChange} /></div>
  }
  if (param.kind === 'text') {
    return <div className="field full">{label}<textarea id={id} className="textarea" value={value} onChange={(e) => onChange(e.target.value)} rows={3} /></div>
  }
  if (param.kind === 'seed') {
    return (
      <div className="field">
        {label}
        <div className="row">
          <input id={id} className="input" type="number" min={0} value={value} disabled={randomSeed} onChange={(e) => onChange(e.target.value === '' ? '' : Number(e.target.value))} />
          <button className="btn icon-btn" type="button" aria-label="New random seed" onClick={() => onChange(Math.floor(Math.random() * MAX_SEED))} disabled={randomSeed}><Icon name="dice" /></button>
        </div>
        <label className="checkbox small"><input type="checkbox" checked={randomSeed} onChange={(e) => setRandomSeed(e.target.checked)} />Random seed for every run</label>
      </div>
    )
  }
  if (param.kind === 'number') {
    return (
      <div className="field">
        {label}
        <input id={id} className="input" type="number" step={param.is_float ? 'any' : 1} value={value} onChange={(e) => onChange(e.target.value === '' ? '' : Number(e.target.value))} />
      </div>
    )
  }
  return <div className="field">{label}<input id={id} className="input" value={value} onChange={(e) => onChange(e.target.value)} /></div>
}

export default function StepRun({ workflow, onBack, onChanged }) {
  const msg = useMessages()
  const openPreview = usePreview()
  const { system, refresh } = useSystem()
  const [params, setParams] = useState(null)
  const [values, setValues] = useState({})
  const [randomSeeds, setRandomSeeds] = useState({})
  const [run, setRun] = useState(null)
  const [history, setHistory] = useState([])
  const [starting, setStarting] = useState(false)
  const [missing, setMissing] = useState(null) // { models, reason }
  const runRef = useRef(null)
  const startRef = useRef(null)
  const runCardRef = useRef(null)

  const loadHistory = useCallback(async () => {
    try {
      const data = await api.get(`/api/runs?workflow_id=${encodeURIComponent(workflow.id)}`)
      setHistory(data.runs.slice(0, 6))
    } catch { /* shown elsewhere */ }
  }, [workflow.id])

  useEffect(() => {
    api.get(`/api/workflows/${workflow.id}/parameters`).then((d) => {
      setParams(d.parameters)
      const v = {}
      d.parameters.forEach((p) => { v[keyOf(p)] = p.value })
      setValues(v)
    }).catch((e) => msg.showError(e))
    loadHistory()
  }, [workflow.id, msg, loadHistory])

  const finish = useCallback(async (r) => {
    loadHistory()
    onChanged?.()
    if (r.status === 'succeeded') {
      const items = outputsToItems(r)
      if (items.length) openPreview(items, 0)
      else msg.showWarning(r.error || 'The run finished without image or video outputs.', { title: 'No previewable output' })
    } else if (r.status === 'failed' && r.error_code === 'models_missing') {
      setMissing({ models: r.failed_models, reason: 'These models could not be downloaded.' })
    } else if (r.status === 'failed') {
      msg.showError(r.error || 'The workflow failed.', { title: 'Workflow failed', details: r.error_details })
    } else if (r.status === 'cancelled') {
      msg.showInfo('The run was cancelled.', { title: 'Run cancelled' })
    }
  }, [loadHistory, onChanged, openPreview, msg])

  useEvent('run', (ev) => {
    const r = ev.run
    if (!runRef.current || r.id !== runRef.current) return
    setRun(r)
    if (['succeeded', 'failed', 'cancelled'].includes(r.status)) {
      runRef.current = null
      finish(r)
    }
  })
  // keep the models progress of a preparing run live
  useEvent('download', () => {
    if (runRef.current) api.get(`/api/runs/${runRef.current}`).then((cur) => { if (runRef.current === cur.id) setRun(cur) }).catch(() => {})
  })

  const comfy = system?.comfyui
  const active = run && ['queued', 'running', 'preparing'].includes(run.status)

  const startComfy = async () => {
    try {
      const res = await api.post('/api/comfyui/start')
      msg.showInfo(res.message, { title: 'ComfyUI' })
      setTimeout(refresh, 3000)
    } catch (e) {
      msg.showError(e)
    }
  }

  const start = async () => {
    const overrides = {}
    for (const p of params || []) {
      const k = keyOf(p)
      let v = values[k]
      if (p.kind === 'seed' && randomSeeds[k]) v = { random_seed: true }
      if ((p.kind === 'number' || p.kind === 'seed') && v === '') {
        msg.showWarning(`Please enter a value for “${p.title} · ${p.input}”.`)
        return
      }
      if (JSON.stringify(v) !== JSON.stringify(p.value)) {
        overrides[p.node_id] = { ...(overrides[p.node_id] || {}), [p.input]: v }
      }
    }
    setStarting(true)
    try {
      // Ask for models that cannot be fetched automatically before starting the run.
      const check = await api.get(`/api/workflows/${workflow.id}/models`)
      const need = check.models
        .filter((m) => m.status === 'no_url' || m.status === 'error')
        .map((m) => ({ name: m.name, category: m.category, url: m.url, status: m.status, error: m.job?.error || '', used_by: m.used_by }))
      if (need.length) {
        setMissing({ models: need })
        return
      }
      const r = await api.post('/api/runs', { workflow_id: workflow.id, overrides })
      runRef.current = r.id
      setRun(r)
      setTimeout(() => runCardRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 80)
      // Fallback poll in case an SSE event was missed.
      const poll = setInterval(async () => {
        if (runRef.current !== r.id) return clearInterval(poll)
        try {
          const cur = await api.get(`/api/runs/${r.id}`)
          if (['succeeded', 'failed', 'cancelled'].includes(cur.status) && runRef.current === r.id) {
            runRef.current = null
            clearInterval(poll)
            setRun(cur)
            finish(cur)
          }
        } catch { /* ignore */ }
      }, 4000)
    } catch (e) {
      if (e.code === 'models_missing') setMissing({ models: e.data.models })
      else msg.showError(e, { title: 'Cannot start the run' })
    } finally {
      setStarting(false)
    }
  }
  startRef.current = start

  const cancel = async () => {
    try { await api.post(`/api/runs/${run.id}/cancel`) } catch (e) { msg.showError(e) }
  }


  return (
    <div className="stack">
      {comfy && !comfy.reachable && (
        <div className="callout callout-warning">
          <Icon name="alert" />
          <div style={{ flex: 1 }}>
            <b>ComfyUI is not running.</b> {comfy.installed ? 'Start it here or with Start-all.bat, then run the workflow.' : 'Run Setup.bat to install ComfyUI, or point Settings to your own ComfyUI server.'}
          </div>
          {comfy.installed && <button className="btn btn-sm" onClick={startComfy}><Icon name="play" size={13} />Start ComfyUI</button>}
        </div>
      )}

      <div className="card">
        <div className="card-head"><h3>Inputs</h3><span className="muted small">{params ? `${params.length} editable value(s)` : ''}</span></div>
        <div className="card-body">
          {!params ? <div className="row muted"><Spinner />Loading…</div> : params.length === 0 ? (
            <p className="muted">This workflow has no prompts, seeds or input images to edit. Just press Run.</p>
          ) : (
            <div className="params">
              {params.map((p) => (
                <ParamField
                  key={keyOf(p)}
                  param={p}
                  value={values[keyOf(p)]}
                  onChange={(v) => setValues((s) => ({ ...s, [keyOf(p)]: v }))}
                  randomSeed={!!randomSeeds[keyOf(p)]}
                  setRandomSeed={(b) => setRandomSeeds((s) => ({ ...s, [keyOf(p)]: b }))}
                />
              ))}
            </div>
          )}
        </div>
        <div className="wizard-foot">
          <button className="btn" onClick={onBack}><Icon name="chevronLeft" />Back</button>
          <div className="row">
            {active && <button className="btn btn-danger" onClick={cancel}><Icon name="stop" size={13} />Cancel run</button>}
            <button className="btn btn-primary btn-lg" onClick={start} disabled={starting || active || !comfy?.reachable || !params}>
              {starting || active ? <Spinner /> : <Icon name="play" size={15} />}{run?.status === 'preparing' ? 'Downloading models…' : active ? 'Running…' : 'Run workflow'}
            </button>
          </div>
        </div>
      </div>

      {run && (
        <div className="card card-pad" ref={runCardRef} style={{ scrollMarginTop: 76 }}>
          <RunProgress run={run} />
        </div>
      )}

      {missing && (
        <MissingModelsModal
          resolvePath={`/api/workflows/${workflow.id}/models/resolve`}
          models={missing.models}
          reason={missing.reason}
          onClose={() => setMissing(null)}
          onSaved={() => { setMissing(null); onChanged?.(); startRef.current?.() }}
        />
      )}

      {history.length > 0 && (
        <div className="card">
          <div className="card-head"><h3>Previous runs</h3></div>
          <div className="card-body stack" style={{ gap: 12 }}>
            {history.map((h) => {
              const items = outputsToItems(h)
              return (
                <div key={h.id} className="row between row-wrap">
                  <div className="row"><RunStatus status={h.status} /><span className="small muted">{formatDate(h.created_at)} · {formatDuration(h.duration)}</span></div>
                  <div className="thumb-strip">
                    {items.slice(0, 5).map((item, i) => <Thumb mini key={item.filename} item={item} onClick={() => openPreview(items, i)} />)}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
