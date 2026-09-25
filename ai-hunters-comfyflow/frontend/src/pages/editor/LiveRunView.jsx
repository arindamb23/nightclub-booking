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
  if (!state || state === 'waiting') return <span className="nstate nstate-waiting"><Icon name="clock" size={11} />Waiting</span>
  const t = fmtSecs(secs(entry, now))
  return (
    <span className={`nstate nstate-${state}`}>
      {state === 'running' ? <span className="nstate-spin" /> : <Icon name={state === 'error' ? 'x' : state === 'cached' ? 'layers' : state === 'stopped' ? 'stop' : 'check'} size={11} />}
      {STATE_LABEL[state]}{state === 'running' && step?.max ? ` · ${step.value}/${step.max}` : ''}{t && state !== 'cached' ? ` · ${t}` : ''}
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
    const all = graph.nodes.every((n) => n.position)
    if (all) return Object.fromEntries(graph.nodes.map((n) => [n.id, n.position]))
    return autoLayout(graph.nodes.map((n) => ({ id: n.id, data: { node: n } })), graph.edges)
  }, [graph])

  useEffect(() => {
    setNodes((cur) => {
      const old = Object.fromEntries(cur.map((n) => [n.id, n.position]))
      return graph.nodes.map((n) => {
        const state = nodeState(run, n.id)
        return {
          id: n.id,
          type: 'live',
          position: old[n.id] || positions[n.id] || { x: 0, y: 0 },
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
  useEffect(() => {
    if (!initialized) return
    if (!graph.nodes.every((n) => n.position)) {
      const pos = autoLayout(flow.getNodes(), graph.edges)
      setNodes((cur) => cur.map((n) => ({ ...n, position: pos[n.id] || n.position })))
    }
    setTimeout(() => flow.fitView({ padding: 0.15, minZoom: 0.35, maxZoom: 1, duration: 300 }), 60)
  }, [initialized]) // eslint-disable-line react-hooks/exhaustive-deps

  // keep the running node in view
  useEffect(() => {
    if (!follow || !active || !prog.node) return
    const n = flow.getNode(prog.node)
    if (n) flow.setCenter(n.position.x + NODE_W / 2, n.position.y + 80, { zoom: Math.max(flow.getZoom(), 0.85), duration: 450 })
  }, [prog.node, follow, active, flow])

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

function Timeline({ run, graph, onFocus }) {
  const active = !DONE.includes(run.status)
  const now = useNow(active)
  const prog = run.progress || {}
  const byId = Object.fromEntries(graph.nodes.map((n) => [n.id, n]))
  const entries = Object.entries(prog.nodes || {})
    .sort((a, b) => (a[1].order || 0) - (b[1].order || 0))
  const waiting = graph.nodes.length - entries.length
  return (
    <aside className="live-side">
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

function Inner({ run: initial, onClose, onCancel }) {
  const [run, setRun] = useState(initial)
  const [graph, setGraph] = useState(null)
  const [error, setError] = useState(null)
  const [follow, setFollow] = useState(true)
  const flow = useReactFlow()
  const ref = useRef(null)

  useEffect(() => { setRun((r) => (initial.id === r.id ? { ...r, ...initial } : initial)) }, [initial])
  useEvent('run', (ev) => { if (ev.run.id === run.id) setRun(ev.run) })
  useEffect(() => {
    api.get(`/api/runs/${initial.id}/graph`).then(setGraph).catch((e) => setError(e.message || String(e)))
  }, [initial.id])
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    ref.current?.focus()
    return () => { document.removeEventListener('keydown', onKey); document.body.style.overflow = '' }
  }, [onClose])

  const focus = useCallback((nid) => {
    setFollow(false)
    const n = flow.getNode(nid)
    if (n) flow.setCenter(n.position.x + NODE_W / 2, n.position.y + 80, { zoom: 1, duration: 400 })
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
        <button className="btn" onClick={() => flow.fitView({ padding: 0.15, duration: 300 })}><Icon name="maximize" />Fit</button>
        {run.workflow_id && <Link className="btn" to={`/workflows/${run.workflow_id}/editor`} onClick={onClose}><Icon name="sliders" />Open editor</Link>}
        {active && onCancel && <button className="btn btn-danger" onClick={onCancel}><Icon name="stop" size={13} />Cancel run</button>}
        <button className="btn btn-ghost icon-btn" onClick={onClose} aria-label="Close live view"><Icon name="x" /></button>
      </div>
      <div className="live-main">
        <div className="live-canvas">
          {error ? <div className="callout callout-warning" style={{ margin: 24 }}><Icon name="alert" /><div>{error}</div></div>
            : !graph ? <div className="row muted" style={{ padding: 24 }}><Spinner />Loading nodes…</div>
              : <Canvas run={run} graph={graph} follow={follow} />}
          <div className="legend">
            {['waiting', 'running', 'done', 'cached', 'error'].map((s) => <span key={s}><i className={`lg-${s}`} />{STATE_LABEL[s]}</span>)}
          </div>
        </div>
        {graph && <Timeline run={run} graph={graph} onFocus={focus} />}
      </div>
    </div>
  )
}

// Full-screen, editor-style view of a run: every node lights up as ComfyUI executes it.
export default function LiveRunView(props) {
  return createPortal(<ReactFlowProvider><Inner {...props} /></ReactFlowProvider>, document.body)
}
