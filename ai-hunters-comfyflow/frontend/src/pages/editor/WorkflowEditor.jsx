import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  ReactFlow, ReactFlowProvider, Background, Controls, MiniMap, useNodesState, useNodesInitialized, useReactFlow,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import Icon from '../../components/Icon.jsx'
import { Spinner } from '../../components/Common.jsx'
import { usePreview } from '../../components/PreviewModals.jsx'
import { api } from '../../api.js'
import { useMessages } from '../../context/MessageContext.jsx'
import { useEvent } from '../../context/EventsContext.jsx'
import { WorkflowNode, ModelsGroupNode } from './NodeCards.jsx'
import Inspector from './Inspector.jsx'
import LiveRunView, { nodeState } from './LiveRunView.jsx'
import { RunStatus } from '../../components/Common.jsx'
import { autoLayout } from './layout.js'
import { GROUP_ID, LEGEND, ROLE, typeColor } from './theme.js'

const nodeTypes = { workflow: WorkflowNode, models: ModelsGroupNode }

// One-line card summary from the current (possibly edited) values
function summaryFor(node, edits) {
  const values = { ...Object.fromEntries(node.fields.map((f) => [f.name, f.value])), ...edits }
  const prompt = node.fields.find((f) => f.control === 'prompt')
  if (node.role === 'prompt' && prompt) return String(values[prompt.name] ?? '').slice(0, 90)
  const parts = (node.summary_keys || []).map((k) => values[k]).filter((v) => v !== undefined && v !== null && v !== '')
  return parts.length ? parts.join(' · ') : node.summary
}

function EditorCanvas() {
  const { id } = useParams()
  const navigate = useNavigate()
  const msg = useMessages()
  const openPreview = usePreview()
  const flow = useReactFlow()
  const [graph, setGraph] = useState(null)
  const [view, setView] = useState('simple')
  const [edits, setEdits] = useState({}) // {nid: {field: value}}
  const [cfgs, setCfgs] = useState({}) // {nid: {field: {runtime,label}}}
  const [outputs, setOutputs] = useState({}) // {nid: type}
  const [positions, setPositions] = useState({}) // saved + dragged
  const [posDirty, setPosDirty] = useState(false)
  const [selected, setSelected] = useState(null)
  const [saving, setSaving] = useState(false)
  const [query, setQuery] = useState('')
  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const lastLayout = useRef({ key: '', positions: null })

  const load = useCallback(async () => {
    try {
      const g = await api.get(`/api/workflows/${id}/graph`)
      setGraph(g)
      setView(g.view || 'simple')
      const pos = {}
      g.nodes.forEach((n) => { if (n.position) pos[n.id] = n.position })
      setPositions(pos)
      return g
    } catch (e) {
      msg.showError(e)
      navigate('/workflows')
      return null
    }
  }, [id, msg, navigate])
  useEffect(() => { load() }, [load])
  // a run of this workflow (started here, in the wizard or elsewhere) lights up the cards node by node
  const [liveRun, setLiveRun] = useState(null)
  const [liveOpen, setLiveOpen] = useState(false)
  useEffect(() => {
    api.get(`/api/runs?workflow_id=${encodeURIComponent(id)}`).then((d) => {
      const r = d.runs[0]
      if (r && ['preparing', 'queued', 'running'].includes(r.status)) setLiveRun(r)
    }).catch(() => {})
  }, [id])
  useEvent('run', (ev) => {
    if (ev.run.workflow_id !== id) return
    setLiveRun(ev.run)
    if (ev.run.status === 'succeeded') load()
  })
  const liveActive = liveRun && ['preparing', 'queued', 'running'].includes(liveRun.status)

  const dirty = Object.keys(edits).length > 0 || Object.keys(cfgs).length > 0 || Object.keys(outputs).length > 0 || posDirty
  const runtimeOf = useCallback((nid, f) => cfgs[nid]?.[f.name]?.runtime ?? f.runtime, [cfgs])

  // visible graph for the chosen view (Simple folds model loaders into one group card)
  const visible = useMemo(() => {
    if (!graph) return { nodes: [], edges: [] }
    const hidden = new Set(view === 'simple' ? graph.nodes.filter((n) => n.role === 'model').map((n) => n.id) : [])
    const rfNodes = graph.nodes.filter((n) => !hidden.has(n.id)).map((n) => ({
      id: n.id,
      type: 'workflow',
      data: {
        node: n, values: edits[n.id] || {}, onPreview: openPreview, runtime: runtimeOf,
        summary: summaryFor(n, edits[n.id] || {}),
        live: liveRun ? {
          state: nodeState(liveRun, n.id), entry: liveRun.progress?.nodes?.[n.id],
          step: liveRun.progress?.node === n.id ? { value: liveRun.progress.value, max: liveRun.progress.max } : null,
        } : null,
      },
    }))
    if (hidden.size) {
      const hiddenNodes = graph.nodes.filter((n) => hidden.has(n.id))
      const models = hiddenNodes.flatMap((n) => n.models)
      const uniq = [...new Map(models.map((m) => [m.name, m])).values()]
      rfNodes.unshift({ id: GROUP_ID, type: 'models', data: { count: hiddenNodes.length, models: uniq, nodes: hiddenNodes } })
    }
    const map = (x) => (hidden.has(x) ? GROUP_ID : x)
    const seen = new Set()
    const rfEdges = []
    graph.edges.forEach((e) => {
      const s = map(e.source)
      const t = map(e.target)
      if (s === t) return
      const key = `${s}->${t}:${e.type}`
      if (seen.has(key)) return
      seen.add(key)
      const color = typeColor(e.type)
      rfEdges.push({ id: key, source: s, target: t, style: { stroke: color, strokeWidth: 2 }, data: { type: e.type }, animated: false })
    })
    return { nodes: rfNodes, edges: rfEdges }
  }, [graph, view, edits, openPreview, runtimeOf, liveRun])

  // positions: saved ones when every visible node has one, otherwise auto layout
  useEffect(() => {
    if (!graph) return
    const allSaved = visible.nodes.every((n) => positions[n.id])
    const pos = allSaved ? positions : autoLayout(visible.nodes, visible.edges)
    const layoutKey = `${view}|${visible.nodes.map((n) => n.id).join(',')}`
    const relaid = layoutKey !== lastLayout.current.key || positions !== lastLayout.current.positions
    lastLayout.current = { key: layoutKey, positions }
    setNodes((current) => {
      const byId = Object.fromEntries(current.map((n) => [n.id, n]))
      // keep React Flow's measured size (else the card is hidden until re-measured) and, when only the data
      // changed (edits, live run states), the position it has now
      return visible.nodes.map((n) => {
        const prev = byId[n.id]
        const position = (!relaid && prev?.position) || pos[n.id] || prev?.position || { x: 0, y: 0 }
        return { ...(prev || {}), ...n, position, selected: !!prev?.selected }
      })
    })
  }, [visible, positions, graph, setNodes]) // eslint-disable-line react-hooks/exhaustive-deps

  // Fit the whole graph; when it is too wide to stay readable (zoom < 0.6), start at the inputs (left edge)
  const canvasRef = useRef(null)
  const fitSoon = useCallback(() => setTimeout(() => {
    const el = canvasRef.current
    const all = flow.getNodes()
    if (!el || !all.length) return
    const b = flow.getNodesBounds(all)
    const w = el.clientWidth
    const h = el.clientHeight
    const pad = 40
    const zoom = Math.max(0.6, Math.min(1, (w - pad * 2) / b.width, (h - pad * 2 - 40) / b.height))
    const fitsX = b.width * zoom <= w - pad * 2
    const x = fitsX ? (w - b.width * zoom) / 2 - b.x * zoom : pad - b.x * zoom
    const y = Math.max(pad + 30 - b.y * zoom, (h - b.height * zoom) / 2 - b.y * zoom)
    flow.setViewport({ x, y, zoom }, { duration: 300 })
  }, 80), [flow])
  // fit once the cards have been measured (on open and when the view changes)
  const initialized = useNodesInitialized()
  useEffect(() => {
    if (!initialized) return
    // auto-laid-out views are re-laid out once with the real (measured) card heights
    if (!visible.nodes.every((n) => positions[n.id])) {
      const measured = flow.getNodes()
      const pos = autoLayout(measured, visible.edges)
      setNodes((cur) => cur.map((n) => ({ ...n, position: pos[n.id] || n.position })))
    }
    fitSoon()
  }, [initialized, view, graph?.workflow?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  const relayout = () => {
    const pos = autoLayout(flow.getNodes(), visible.edges)
    setPositions((p) => ({ ...p, ...pos }))
    setPosDirty(true)
    fitSoon()
  }
  const onNodeDragStop = (_, node) => {
    setPositions((p) => {
      const next = { ...p }
      nodes.forEach((n) => { next[n.id] = n.id === node.id ? node.position : (p[n.id] || n.position) })
      return next
    })
    setPosDirty(true)
  }

  const save = async () => {
    setSaving(true)
    try {
      const values = {}
      Object.entries(edits).forEach(([nid, v]) => { values[nid] = v })
      const g = await api.put(`/api/workflows/${id}/graph`, {
        values, fields: cfgs, outputs, view, positions: posDirty ? positions : {},
      })
      setGraph(g)
      setEdits({}); setCfgs({}); setOutputs({}); setPosDirty(false)
      const pos = {}
      g.nodes.forEach((n) => { if (n.position) pos[n.id] = n.position })
      setPositions((p) => ({ ...p, ...pos }))
      msg.showSuccess(Object.keys(values).length
        ? 'Saved. The new values were written into workflow.py (the previous version is kept in history).'
        : 'Saved.', { title: 'Workflow saved' })
      return true
    } catch (e) {
      msg.showError(e, { title: 'Not saved' })
      return false
    } finally {
      setSaving(false)
    }
  }
  const run = async () => {
    if (dirty) {
      const ok = await msg.showConfirm('Save your changes before running?', { confirmText: 'Save & run' })
      if (!ok || !(await save())) return
    }
    navigate(`/workflows/${id}/wizard?step=3`)
  }
  const discard = async () => {
    const ok = await msg.showConfirm('Discard all unsaved changes?', { confirmText: 'Discard' })
    if (!ok) return
    setEdits({}); setCfgs({}); setOutputs({}); setPosDirty(false)
    load()
  }
  const find = (q) => {
    const n = graph?.nodes.find((x) => x.title.toLowerCase().includes(q.toLowerCase()) || x.class_type.toLowerCase().includes(q.toLowerCase()))
    if (!n) return msg.showInfo(`No node matches “${q}”.`)
    if (view === 'simple' && n.role === 'model') setView('detailed')
    setSelected(n.id)
    setTimeout(() => {
      const rf = flow.getNode(n.id)
      if (rf) flow.setCenter(rf.position.x + 122, rf.position.y + 60, { zoom: 1.1, duration: 400 })
    }, 120)
  }

  if (!graph) return <div className="row muted"><Spinner />Loading workflow…</div>

  const selNode = graph.nodes.find((n) => n.id === selected)
  const group = selected === GROUP_ID ? visible.nodes.find((n) => n.id === GROUP_ID)?.data : null
  const setValue = (nid) => (name, v) => {
    const original = graph.nodes.find((n) => n.id === nid)?.fields.find((f) => f.name === name)?.value
    setEdits((all) => {
      const node = { ...(all[nid] || {}) }
      if (JSON.stringify(v) === JSON.stringify(original)) delete node[name]
      else node[name] = v
      const next = { ...all, [nid]: node }
      if (!Object.keys(node).length) delete next[nid]
      return next
    })
  }
  const setCfg = (nid) => (name, c) => setCfgs((all) => ({ ...all, [nid]: { ...(all[nid] || {}), [name]: { ...(all[nid]?.[name] || {}), ...c } } }))

  return (
    <div className="editor">
      <div className="editor-bar">
        <div className="editor-title">
          <button className="btn btn-ghost icon-btn" onClick={() => navigate('/workflows')} aria-label="Back to workflows"><Icon name="chevronLeft" /></button>
          <div style={{ minWidth: 0 }}>
            <h2 className="truncate">{graph.workflow.name}</h2>
            <div className="small muted">{graph.nodes.length} nodes · {graph.edges.length} connections{dirty && <span className="unsaved"> · unsaved changes</span>}</div>
          </div>
        </div>
        <form className="search" onSubmit={(e) => { e.preventDefault(); if (query.trim()) find(query.trim()) }}>
          <Icon name="search" size={16} />
          <input className="input" list="node-titles" placeholder="Find node…" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Find node" />
          <datalist id="node-titles">{graph.nodes.map((n) => <option key={n.id} value={n.title} />)}</datalist>
        </form>
        <div className="seg" role="tablist" aria-label="View">
          <button className={`seg-btn ${view === 'simple' ? 'active' : ''}`} onClick={() => { setView('simple'); setPosDirty(true) }}><Icon name="layers" size={14} />Simple</button>
          <button className={`seg-btn ${view === 'detailed' ? 'active' : ''}`} onClick={() => { setView('detailed'); setPosDirty(true) }}><Icon name="workflow" size={14} />Detailed</button>
        </div>
        <button className="btn" onClick={relayout}><Icon name="layout" />Auto layout</button>
        <button className="btn" onClick={fitSoon}><Icon name="maximize" />Fit</button>
        {dirty && <button className="btn btn-ghost" onClick={discard}>Discard</button>}
        <button className="btn" onClick={save} disabled={saving || !dirty}>{saving ? <Spinner /> : <Icon name="save" />}Save</button>
        <button className="btn btn-primary" onClick={run}><Icon name="play" size={13} />Run</button>
      </div>
      {liveRun && (liveActive || liveOpen || liveRun.progress?.nodes) && (
        <div className="editor-live">
          <RunStatus status={liveRun.status} />
          <span className="grow truncate">
            {liveActive
              ? liveRun.status === 'preparing' ? 'Downloading models before the run starts…'
                : liveRun.progress?.class_type ? <>Executing <b>{graph.nodes.find((n) => n.id === liveRun.progress.node)?.title || liveRun.progress.class_type}</b> · {liveRun.progress.done} / {liveRun.progress.total} nodes</>
                  : liveRun.progress?.phase || 'Waiting for ComfyUI…'
              : `Last run ${liveRun.status} — the cards show which nodes ran.`}
          </span>
          <button className="btn btn-sm" onClick={() => setLiveOpen(true)}><Icon name="workflow" size={14} />Live node view</button>
          {!liveActive && <button className="btn btn-sm btn-ghost" onClick={() => setLiveRun(null)}>Hide</button>}
        </div>
      )}
      {liveOpen && liveRun && (
        <LiveRunView run={liveRun} autoPreview onClose={() => setLiveOpen(false)}
          onCancel={() => api.post(`/api/runs/${liveRun.id}/cancel`).catch((e) => msg.showError(e))} />
      )}
      <div className="editor-main">
        <div className="editor-canvas" ref={canvasRef}>
          <ReactFlow
            nodes={nodes}
            edges={visible.edges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onNodeDragStop={onNodeDragStop}
            onNodeClick={(_, n) => setSelected(n.id)}
            onPaneClick={() => setSelected(null)}
            nodesConnectable={false}
            edgesFocusable={false}
            deleteKeyCode={null}
            minZoom={0.2}
            maxZoom={1.8}
            proOptions={{ hideAttribution: true }}
          >
            <Background gap={22} size={1.2} color="#dcd8cc" />
            <Controls showInteractive={false} position="bottom-left" />
            <MiniMap pannable zoomable position="bottom-right" nodeColor={(n) => (n.type === 'models' ? ROLE.model.color : (ROLE[n.data?.node?.role] || ROLE.generate).color)} maskColor="rgba(250,249,245,0.7)" />
          </ReactFlow>
          <div className="legend">
            {Object.entries(ROLE).map(([k, r]) => <span key={k}><i style={{ background: r.color }} />{r.label}</span>)}
            <span className="legend-sep" />
            {LEGEND.map((t) => <span key={t}><b style={{ background: typeColor(t) }} />{t.toLowerCase()}</span>)}
          </div>
        </div>
        <Inspector
          node={selNode}
          group={group}
          graph={graph}
          edits={selNode ? edits[selNode.id] || {} : {}}
          cfgs={selNode ? cfgs[selNode.id] || {} : cfgs}
          outputs={outputs}
          onValue={selNode ? setValue(selNode.id) : () => {}}
          onCfg={selNode ? setCfg(selNode.id) : () => {}}
          onOutput={(t) => setOutputs((o) => ({ ...o, [selNode.id]: t }))}
          onSelect={(nid) => { if (view === 'simple' && graph.nodes.find((n) => n.id === nid)?.role === 'model') setView('detailed'); setSelected(nid) }}
          onClose={() => setSelected(null)}
        />
      </div>
    </div>
  )
}

export default function WorkflowEditor() {
  return (
    <ReactFlowProvider>
      <EditorCanvas />
    </ReactFlowProvider>
  )
}
