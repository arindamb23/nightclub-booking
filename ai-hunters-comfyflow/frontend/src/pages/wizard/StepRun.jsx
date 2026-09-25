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
import CustomNodesModal from '../../components/CustomNodes.jsx'
import RunProgress from '../../components/RunProgress.jsx'
import FieldControl from '../../components/FieldControl.jsx'
import { Link } from 'react-router-dom'

const keyOf = (p) => `${p.node_id}::${p.input}`
const MAX_SEED = 2 ** 50

function ParamField({ param, value, onChange, randomSeed, setRandomSeed }) {
  const id = `p-${keyOf(param)}`
  const wide = ['text', 'image', 'video', 'audio'].includes(param.kind)
  return (
    <div className={`field ${wide ? 'full' : ''}`}>
      <label htmlFor={id} className="param-title">{param.label}{param.title !== param.label && <span className="muted">· {param.title}</span>}</label>
      <FieldControl id={id} field={param} value={value} onChange={onChange} preview={param.preview} disabled={param.kind === 'seed' && randomSeed} />
      {param.kind === 'seed' && (
        <label className="checkbox small"><input type="checkbox" checked={randomSeed} onChange={(e) => setRandomSeed(e.target.checked)} />Random seed for every run</label>
      )}
      {param.tooltip && <span className="hint">{param.tooltip}</span>}
    </div>
  )
}

const OUT_ICON = { image: 'image', video: 'film', audio: 'audio' }

export default function StepRun({ workflow, onBack, onChanged }) {
  const msg = useMessages()
  const openPreview = usePreview()
  const { system, refresh } = useSystem()
  const [params, setParams] = useState(null)
  const [outputs, setOutputs] = useState([])
  const [values, setValues] = useState({})
  const [randomSeeds, setRandomSeeds] = useState({})
  const [run, setRun] = useState(null)
  const [history, setHistory] = useState([])
  const [starting, setStarting] = useState(false)
  const [missing, setMissing] = useState(null) // { models, reason }
  const [nodesNeeded, setNodesNeeded] = useState(null)
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
      setOutputs(d.outputs || [])
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
    } else if (r.status === 'failed' && r.error_code === 'nodes_missing' && r.missing_nodes?.length) {
      setNodesNeeded(r.missing_nodes)
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
        msg.showWarning(`Please enter a value for “${p.label}”.`)
        return
      }
      if (JSON.stringify(v) !== JSON.stringify(p.value)) {
        overrides[p.node_id] = { ...(overrides[p.node_id] || {}), [p.input]: v }
      }
    }
    setStarting(true)
    try {
      // Custom nodes first (ComfyUI refuses the whole workflow without them), then models.
      const nodes = await api.get(`/api/workflows/${workflow.id}/nodes-check`).catch(() => null)
      if (nodes?.packs?.length) {
        setNodesNeeded(nodes.packs)
        return
      }
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
      else if (e.code === 'nodes_missing') setNodesNeeded(e.data.packs)
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
        <div className="card-head">
          <div><h3>Run-time inputs</h3><span className="muted small">{params ? `${params.length} field(s) · choose which fields appear here in the Workflow editor` : ''}</span></div>
          <Link className="btn btn-sm" to={`/workflows/${workflow.id}/editor`}><Icon name="sliders" size={14} />Open editor</Link>
        </div>
        <div className="card-body">
          {!params ? <div className="row muted"><Spinner />Loading…</div> : params.length === 0 ? (
            <p className="muted">No run-time fields. Press Run, or tick “Run time” on any node setting in the Workflow editor.</p>
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
        {outputs.length > 0 && (
          <div className="card-body" style={{ borderTop: '1px solid var(--border)', paddingTop: 14, paddingBottom: 14 }}>
            <div className="row row-wrap" style={{ gap: 8 }}>
              <span className="small muted" style={{ fontWeight: 600 }}>Expected output</span>
              {outputs.map((o) => (
                <span key={o.node_id} className={`badge ${o.type === 'audio' ? 'badge-success' : o.type === 'video' ? 'badge-accent' : 'badge-info'}`}>
                  <Icon name={OUT_ICON[o.type] || 'image'} size={12} />{o.type} · {o.title}
                </span>
              ))}
            </div>
          </div>
        )}
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
          <RunProgress run={run} onCancel={cancel} />
        </div>
      )}

      {nodesNeeded && (
        <CustomNodesModal packs={nodesNeeded} onClose={() => setNodesNeeded(null)}
          onReady={() => { setNodesNeeded(null); onChanged?.(); setTimeout(() => startRef.current?.(), 300) }} />
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
