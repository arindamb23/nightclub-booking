import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link } from 'react-router-dom'
import {
  ReactFlow, ReactFlowProvider, Background, Controls, MiniMap, Handle, Position, useNodesState, useNodesInitialized, useReactFlow,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import Icon from '../../components/Icon.jsx'
import { Progress, RunStatus, Spinner } from '../../components/Common.jsx'
import { outputsToItems, usePreview } from '../../components/PreviewModals.jsx'
import { api } from '../../api.js'
import { formatBytes } from '../../utils/format.js'
import { useEvent } from '../../context/EventsContext.jsx'
import { autoLayout, NODE_W } from './layout.js'
import { ROLE, typeColor } from './theme.js'

const DONE = ['succeeded', 'failed', 'cancelled']
export const STATE_LABEL = {
  waiting: 'Waiting', running: 'Running', done: 'Done', cached: 'Cached', error: 'Failed', stopped: 'Stopped',
}

// Node state for a run: running / done / cached / error from the backend, everything else waiting
export function nodeState(run, nid) {
  return run?.progress?.nodes?.[nid]?.state || 'waiting'
}

function secs(entry, now) {
  if (!entry?.started) return null
  const end = entry.ended || now
  return Math.max(0, end - entry.started)
}
const fmtSecs = (s) => (s == null ? '' : s < 60 ? `${s.toFixed(1)}s` : `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`)

export function NodeRunBadge({ state, entry, step, now }) {
  const st = state || 'waiting'
  const t = st === 'waiting' || st === 'cached' ? '' : fmtSecs(secs(entry, now))
  const text = [STATE_LABEL[st], st === 'running' && step?.max ? `${step.value}/${step.max}` : '', t].filter(Boolean).join(' · ')
  const icon = { waiting: 'clock', error: 'x', cached: 'layers', stopped: 'stop' }[st] || 'check'
  return (
    <span key={st} className={`nstate nstate-${st}`}>
      {st === 'running' ? <span className="nstate-spin" /> : <Icon name={icon} size={11} />}
      <span>{text}</span>
    </span>
  )
}

const LiveNode = memo(({ data }) => {
  const { node, state, entry, step, now, outputs, preview, onPreview } = data
  const role = ROLE[node.role] || ROLE.generate
  const pct = state === 'running' && step?.max ? (step.value / step.max) * 100 : null
  return (
    <div className={`wnode live live-${state}`} style={{ '--role': role.color, '--role-soft': role.soft }}>
      <Handle type="target" position={Position.Left} className="whandle" isConnectable={false} />
      <div className="wnode-head">
        <span className="wnode-icon"><Icon name={node.icon || role.icon} size={16} /></span>
        <div className="wnode-titles">
          <div className="wnode-title" title={node.title}>{node.title}</div>
          <div className="wnode-sub">#{node.id} · {node.class_type}</div>
        </div>
      </div>
      {node.summary && <div className="wnode-summary" title={node.summary}>{node.summary}</div>}
      {state === 'running' && preview && (
        <div className="live-preview"><img src={preview} alt="Live preview" draggable={false} /><span>Live preview</span></div>
      )}
      {outputs?.length > 0 && (
        <button type="button" className="nmedia nodrag" onClick={(e) => { e.stopPropagation(); onPreview(outputs, 0) }} title="Open result">
          {outputs[0].kind === 'image' ? <img src={outputs[0].src} alt="" draggable={false} /> : (
            <span className={`nmedia-icon nmedia-${outputs[0].kind === 'audio' ? 'audio' : 'video'}`}><Icon name={outputs[0].kind === 'audio' ? 'audio' : 'film'} size={26} /></span>
          )}
          <span className="nmedia-play"><Icon name={outputs[0].kind === 'image' ? 'eye' : 'play'} size={13} /></span>
          <span className="nmedia-name">{outputs.length > 1 ? `${outputs.length} results` : outputs[0].filename}</span>
        </button>
      )}
      <div className="wnode-badges"><NodeRunBadge state={state} entry={entry} step={step} now={now} /></div>
      {pct != null && <div className="live-bar"><i style={{ width: `${pct}%` }} /></div>}
      <Handle type="source" position={Position.Right} className="whandle" isConnectable={false} />
    </div>
  )
})

const nodeTypes = { live: LiveNode }

const validPos = (p) => (p && Number.isFinite(p.x) && Number.isFinite(p.y) ? p : null)

// Fit / center only with finite numbers: one NaN position blanks the whole canvas and the minimap
export function safeFit(flow) {
  const ok = flow.getNodes().filter((n) => validPos(n.position))
  if (ok.length) flow.fitView({ nodes: ok.map((n) => ({ id: n.id })), padding: 0.15, minZoom: 0.3, maxZoom: 1, duration: 300 })
}
function centerOn(flow, nid, zoom) {
  const n = flow.getNode(nid)
  const p = validPos(n?.position)
  if (!p) return
  const w = n.measured?.width || NODE_W
  const h = n.measured?.height || 160
  const z = zoom || Math.max(Math.min(flow.getZoom() || 1, 1.2), 0.85)
  if (Number.isFinite(z)) flow.setCenter(p.x + w / 2, p.y + h / 2, { zoom: z, duration: 450 })
}

function useNow(active) {
  const [now, setNow] = useState(Date.now() / 1000)
  useEffect(() => {
    if (!active) return undefined
    const t = setInterval(() => setNow(Date.now() / 1000), 500)
    return () => clearInterval(t)
  }, [active])
  return now
}

function Canvas({ run, graph, follow }) {
  const flow = useReactFlow()
  const openPreview = usePreview()
  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [preview, setPreview] = useState(null)
  const active = !DONE.includes(run.status)
  const now = useNow(active)
  const prog = run.progress || {}

  // live sampling preview frames (ComfyUI --preview-method auto)
  useEvent('run_preview', (ev) => {
    if (ev.run_id === run.id) setPreview(`/api/runs/${run.id}/preview?n=${ev.n}`)
  })

  const outputsByNode = useMemo(() => {
    const map = {}
    outputsToItems(run).forEach((item) => {
      const nid = String(item.node_id ?? '')
      ;(map[nid] = map[nid] || []).push({ ...item, src: `/api/runs/${run.id}/files/${encodeURIComponent(item.filename)}` })
    })
    return map
  }, [run])

  const positions = useMemo(() => {
    const all = graph.nodes.every((n) => validPos(n.position))
    if (all) return Object.fromEntries(graph.nodes.map((n) => [n.id, n.position]))
    return autoLayout(graph.nodes.map((n) => ({ id: n.id, data: { node: n } })), graph.edges)
  }, [graph])

  useEffect(() => {
    setNodes((cur) => {
      // keep React Flow's own fields (measured size, internals): a node without them is hidden until re-measured
      const byId = Object.fromEntries(cur.map((n) => [n.id, n]))
      return graph.nodes.map((n) => {
        const state = nodeState(run, n.id)
        const prev = byId[n.id]
        return {
          ...(prev || {}),
          id: n.id,
          type: 'live',
          position: validPos(prev?.position) || validPos(positions[n.id]) || { x: 0, y: 0 },
          data: {
            node: n, state, entry: prog.nodes?.[n.id], now,
            step: prog.node === n.id ? { value: prog.value, max: prog.max } : null,
            outputs: outputsByNode[n.id], preview: prog.node === n.id ? preview : null, onPreview: openPreview,
          },
        }
      })
    })
  }, [graph, run, positions, now, preview, outputsByNode, openPreview, setNodes]) // eslint-disable-line react-hooks/exhaustive-deps

  const edges = useMemo(() => graph.edges.map((e) => {
    const s = nodeState(run, e.source)
    const t = nodeState(run, e.target)
    const flowing = t === 'running'
    const passed = ['done', 'cached'].includes(s) && t !== 'waiting'
    return {
      id: e.id, source: e.source, target: e.target, animated: flowing,
      style: { stroke: typeColor(e.type), strokeWidth: flowing ? 3 : 2, opacity: flowing || passed || !active ? 1 : 0.45 },
    }
  }), [graph, run, active])

  const initialized = useNodesInitialized()
  const laidOut = useRef(false)
  useEffect(() => {
    if (!initialized || laidOut.current) return
    laidOut.current = true  // once: later updates keep positions (and the user's panning)
    if (!graph.nodes.every((n) => validPos(n.position))) {
      const pos = autoLayout(flow.getNodes(), graph.edges)
      setNodes((cur) => cur.map((n) => ({ ...n, position: validPos(pos[n.id]) || n.position })))
    }
    setTimeout(() => safeFit(flow), 80)
  }, [initialized]) // eslint-disable-line react-hooks/exhaustive-deps

  // keep the running node in view (also once the cards are measured and laid out)
  useEffect(() => {
    if (!follow || !active || !prog.node || !initialized) return
    const t = setTimeout(() => centerOn(flow, prog.node), 120)
    return () => clearTimeout(t)
  }, [prog.node, follow, active, flow, initialized])

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodesChange={onNodesChange}
      nodesConnectable={false}
      edgesFocusable={false}
      deleteKeyCode={null}
      minZoom={0.2}
      maxZoom={1.8}
      proOptions={{ hideAttribution: true }}
    >
      <Background gap={22} size={1.2} color="#dcd8cc" />
      <Controls showInteractive={false} position="bottom-left" />
      <MiniMap pannable zoomable position="bottom-right" maskColor="rgba(250,249,245,0.7)"
        nodeColor={(n) => ({ running: '#c96442', done: '#4e7d4a', cached: '#a8a69f', error: '#b3372e' }[n.data?.state] || '#dcd8cc')} />
    </ReactFlow>
  )
}

const STALL_SECS = 45

// What ComfyUI is doing when the nodes do not move: queue, GPU / RAM, silence
// Memory in use changing = ComfyUI is loading / moving a model (it sends no messages while it does that)
function useMemoryTrend(res) {
  const hist = useRef([])
  const used = res && res.ram_free != null ? (res.ram_total - res.ram_free) + (res.vram_total && res.vram_free != null ? res.vram_total - res.vram_free : 0) : null
  useEffect(() => {
    if (used == null) return
    const t = Date.now() / 1000
    hist.current = [...hist.current.filter((h) => t - h.t < 20), { t, used }]
  }, [used])
  const h = hist.current
  if (h.length < 2) return 0
  return h[h.length - 1].used - h[0].used
}

export function RunHealth({ run, onOpenConsole, compact = false, nodeTitle }) {
  const active = !DONE.includes(run.status)
  const now = useNow(active)
  const prog = run.progress || {}
  const res = prog.resources
  const [busy, setBusy] = useState(false)
  const memDelta = useMemoryTrend(res)
  if (!active || run.status === 'preparing') return null
  const title = nodeTitle || prog.class_type
  const loading = /load|clip|encode|unet|vae|checkpoint|model/i.test(`${title} ${prog.class_type}`)
  const moving = Math.abs(memDelta) > 64 * 1024 * 1024
  const quiet = prog.last_event ? now - prog.last_event : null
  const stalled = quiet != null && quiet > STALL_SECS
  const vramUsed = res?.vram_total && res.vram_free != null ? res.vram_total - res.vram_free : null
  const vramPct = vramUsed != null ? (vramUsed / res.vram_total) * 100 : null
  const ramPct = res?.ram_total && res.ram_free != null ? ((res.ram_total - res.ram_free) / res.ram_total) * 100 : null
  const clear = async () => {
    setBusy(true)
    try { await api.post('/api/comfyui/clear-queue', { keep_run_id: run.id }) } catch { /* shown by the next update */ }
    setBusy(false)
  }
  return (
    <div className={`live-health ${compact ? 'compact' : ''}`}>
      {(vramPct != null || ramPct != null) && (
        <div className="live-meters">
          {vramPct != null && (
            <div title={res.gpu || 'GPU'}><span className="small muted">GPU memory</span><b className="small">{formatBytes(vramUsed)} / {formatBytes(res.vram_total)}</b>
              <div className={`meter ${vramPct > 92 ? 'meter-hot' : ''}`}><i style={{ width: `${vramPct}%` }} /></div></div>
          )}
          {ramPct != null && (
            <div><span className="small muted">System RAM</span><b className="small">{formatBytes(res.ram_total - (res.ram_free || 0))} / {formatBytes(res.ram_total)}</b>
              <div className={`meter ${ramPct > 92 ? 'meter-hot' : ''}`}><i style={{ width: `${ramPct}%` }} /></div></div>
          )}
        </div>
      )}
      {prog.queue_ahead > 0 && (
        <div className="callout callout-warning small"><Icon name="clock" /><div style={{ flex: 1 }}>
          <b>ComfyUI is busy with another job</b> ({prog.queue_ahead} ahead). This run starts when it finishes — often an older run that is still loading or running.
          <div className="mt-8"><button className="btn btn-sm" onClick={clear} disabled={busy}>{busy ? <Spinner size={13} /> : <Icon name="x" size={13} />}Stop the other jobs</button></div>
        </div></div>
      )}
      {stalled && !prog.queue_ahead && (
        <div className="callout callout-info small"><Icon name="info" /><div style={{ flex: 1 }}>
          {prog.node ? <><b>{title}</b> has been working for {Math.floor(quiet / 60) ? `${Math.floor(quiet / 60)}m ` : ''}{Math.round(quiet % 60)}s without a progress message. </>
            : <>No update from ComfyUI for {Math.floor(quiet / 60) ? `${Math.floor(quiet / 60)}m ` : ''}{Math.round(quiet % 60)}s. </>}
          {!prog.node ? 'ComfyUI has not started this workflow yet.'
            : moving ? `ComfyUI is busy: memory in use changed by ${formatBytes(Math.abs(memDelta))} in the last seconds (a model is being loaded or moved).`
              : loading ? 'ComfyUI reports nothing while it loads a model: text encoders (T5-XXL ≈ 9.8 GB, umt5-xxl ≈ 6.7 GB) and diffusion models can take minutes on the first run, longer when RAM is nearly full and Windows uses the page file.'
                : 'Some nodes send no progress while they work. The ComfyUI console shows what it is doing.'}
          {onOpenConsole && <div className="mt-8"><button className="btn btn-sm" onClick={onOpenConsole}><Icon name="code" size={13} />Show ComfyUI console</button></div>}
        </div></div>
      )}
    </div>
  )
}

export function ComfyConsole({ active, onClose }) {
  const [log, setLog] = useState(null)
  const box = useRef(null)
  useEffect(() => {
    let alive = true
    const load = () => api.get('/api/comfyui/log?lines=120').then((d) => { if (alive) setLog(d) }).catch(() => {})
    load()
    const t = active ? setInterval(load, 2000) : null
    return () => { alive = false; if (t) clearInterval(t) }
  }, [active])
  useEffect(() => { if (box.current) box.current.scrollTop = box.current.scrollHeight }, [log])
  return (
    <div className="live-console">
      <div className="live-console-head">
        <b className="small">ComfyUI console</b>
        <span className="small muted truncate">{log?.available ? log.path : ''}</span>
        {onClose && <button className="btn btn-ghost icon-btn" onClick={onClose} aria-label="Hide console"><Icon name="x" size={14} /></button>}
      </div>
      <pre ref={box}>{!log ? 'Loading…' : log.available ? log.lines.join('\n') || '(empty)'
        : 'The console is recorded when ComfyUI is started by Start-all.bat or Settings → Start ComfyUI (v1.0.7 or newer). Restart ComfyUI with Stop-all.bat and Start-all.bat to see it here.'}</pre>
    </div>
  )
}

function Timeline({ run, graph, onFocus, health }) {
  const active = !DONE.includes(run.status)
  const now = useNow(active)
  const prog = run.progress || {}
  const byId = Object.fromEntries(graph.nodes.map((n) => [n.id, n]))
  const entries = Object.entries(prog.nodes || {})
    .sort((a, b) => (a[1].order || 0) - (b[1].order || 0))
  const waiting = graph.nodes.length - entries.length
  return (
    <aside className="live-side">
      {health}
      <div className="live-side-head"><b>Execution order</b><span className="muted small">{entries.length} / {graph.nodes.length}</span></div>
      <ol className="live-list">
        {entries.map(([nid, e], i) => (
          <li key={nid} className={`live-item live-item-${e.state}`}>
            <button type="button" onClick={() => onFocus(nid)}>
              <span className="live-num">{i + 1}</span>
              <span className="live-item-main">
                <span className="truncate">{byId[nid]?.title || byId[nid]?.class_type || `Node ${nid}`}</span>
                <span className="small muted">{STATE_LABEL[e.state]}{e.state !== 'cached' && secs(e, now) != null ? ` · ${fmtSecs(secs(e, now))}` : ''}</span>
              </span>
              {e.state === 'running' ? <Spinner size={14} /> : <Icon name={e.state === 'error' ? 'errorCircle' : e.state === 'cached' ? 'layers' : 'checkCircle'} size={15} />}
            </button>
          </li>
        ))}
        {waiting > 0 && <li className="live-item live-item-waiting"><span className="small muted">{waiting} node(s) {active ? 'waiting' : 'not executed'}</span></li>}
      </ol>
      {run.error && <div className="callout callout-danger small"><Icon name="alert" /><div>{run.error}</div></div>}
    </aside>
  )
}

function Inner({ run: initial, onClose, onCancel, autoPreview = false, showConsole = false }) {
  const [run, setRun] = useState(initial)
  const [consoleOpen, setConsoleOpen] = useState(showConsole)
  const openPreview = usePreview()
  const previewed = useRef(DONE.includes(initial.status))
  const [graph, setGraph] = useState(null)
  const [error, setError] = useState(null)
  const [follow, setFollow] = useState(true)
  const flow = useReactFlow()
  const ref = useRef(null)

  useEffect(() => { setRun((r) => (initial.id === r.id ? { ...r, ...initial } : initial)) }, [initial])
  useEvent('run', (ev) => { if (ev.run.id === run.id) setRun(ev.run) })
  // results open in the preview when the run finishes (the Run / Generate screens do it themselves)
  useEffect(() => {
    if (!autoPreview || previewed.current || run.status !== 'succeeded') return
    previewed.current = true
    const items = outputsToItems(run)
    if (items.length) openPreview(items, 0)
  }, [run, autoPreview, openPreview])
  useEffect(() => {
    api.get(`/api/runs/${initial.id}/graph`).then(setGraph).catch((e) => setError(e.message || String(e)))
  }, [initial.id])
  // Back (button, Esc, the browser's Back / mouse back button) returns to the screen underneath; the run keeps going
  const closeRef = useRef(onClose)
  closeRef.current = onClose
  const closed = useRef(false)
  useEffect(() => {
    if (window.history.state?.comfyflowLive !== initial.id) {  // once, even when React runs the effect twice
      window.history.pushState({ ...(window.history.state || {}), comfyflowLive: initial.id }, '')
    }
    const onPop = () => {
      if (closed.current) return
      closed.current = true
      closeRef.current()
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  const goBack = useCallback(() => {
    if (window.history.state?.comfyflowLive === initial.id) window.history.back()  // popstate closes the view
    else if (!closed.current) { closed.current = true; closeRef.current() }
  }, [initial.id])

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape' && !document.querySelector('.modal-root')) goBack() }
    document.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    ref.current?.focus()
    return () => { document.removeEventListener('keydown', onKey); document.body.style.overflow = '' }
  }, [goBack])

  const focus = useCallback((nid) => {
    setFollow(false)
    centerOn(flow, nid, 1)
  }, [flow])

  const prog = run.progress || {}
  const active = !DONE.includes(run.status)
  const overall = prog.total ? (prog.done / prog.total) * 100 : 0
  const current = graph?.nodes.find((n) => n.id === prog.node)
  const line = run.status === 'preparing'
    ? `Downloading models (${prog.models?.ready ?? 0} / ${prog.models?.total ?? 0} ready) — nodes start after that`
    : !active ? (run.status === 'succeeded' ? 'Finished' : run.status === 'cancelled' ? 'Cancelled' : 'Failed')
      : current ? `Executing ${current.title}${prog.max ? ` — step ${prog.value} / ${prog.max}` : ''}`
        : prog.phase || 'Waiting for ComfyUI to start the workflow…'

  return (
    <div className="live-root" role="dialog" aria-modal="true" aria-label="Live node progress" tabIndex={-1} ref={ref}>
      <div className="live-bar-top">
        <button className="btn live-back" onClick={goBack} title={active ? 'Back to the previous screen — the run keeps going' : 'Back to the previous screen'}>
          <Icon name="chevronLeft" />Back
        </button>
        <div className="live-title">
          <span className="live-logo"><Icon name="workflow" size={18} /></span>
          <div style={{ minWidth: 0 }}>
            <h2 className="truncate">{run.workflow_name || 'Run'}</h2>
            <div className="small muted truncate">Live node progress · run {run.id}</div>
          </div>
        </div>
        <div className="live-progress">
          <div className="row between small"><span className="truncate">{line}</span><span className="muted">{prog.done || 0} / {prog.total || graph?.nodes.length || 0} nodes</span></div>
          <div className="mt-8"><Progress percent={overall} indeterminate={active && !overall} /></div>
        </div>
        <RunStatus status={run.status} />
        <label className="checkbox small" title="Keep the running node centred"><input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} />Follow</label>
        <button className="btn" onClick={() => safeFit(flow)}><Icon name="maximize" /><span className="live-lbl">Fit</span></button>
        {run.workflow_id && <Link className="btn" to={`/workflows/${run.workflow_id}/editor`} onClick={onClose}><Icon name="sliders" /><span className="live-lbl">Open editor</span></Link>}
        <button className={`btn ${consoleOpen ? 'btn-active' : ''}`} onClick={() => setConsoleOpen((v) => !v)}><Icon name="code" /><span className="live-lbl">Console</span></button>
        {active && onCancel && <button className="btn btn-danger" onClick={onCancel}><Icon name="stop" size={13} /><span className="live-lbl">Cancel run</span></button>}
      </div>
      <div className="live-main">
        <div className="live-canvas">
          {error ? <div className="callout callout-warning" style={{ margin: 24 }}><Icon name="alert" /><div>{error}</div></div>
            : !graph ? <div className="row muted" style={{ padding: 24 }}><Spinner />Loading nodes…</div>
              : <Canvas run={run} graph={graph} follow={follow} />}
          <div className="legend">
            {['waiting', 'running', 'done', 'cached', 'error'].map((s) => <span key={s}><i className={`lg-${s}`} />{STATE_LABEL[s]}</span>)}
          </div>
          {consoleOpen && <ComfyConsole active onClose={() => setConsoleOpen(false)} />}
        </div>
        {graph && <Timeline run={run} graph={graph} onFocus={focus} health={<RunHealth run={run} nodeTitle={current?.title} onOpenConsole={() => setConsoleOpen(true)} />} />}
      </div>
    </div>
  )
}

// Full-screen, editor-style view of a run: every node lights up as ComfyUI executes it.
export default function LiveRunView(props) {
  return createPortal(<ReactFlowProvider><Inner {...props} /></ReactFlowProvider>, document.body)
}
