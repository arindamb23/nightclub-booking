import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Icon from '../components/Icon.jsx'
import { EmptyState, RunStatus } from '../components/Common.jsx'
import { Thumb, outputsToItems, usePreview } from '../components/PreviewModals.jsx'
import { api } from '../api.js'
import { useMessages } from '../context/MessageContext.jsx'
import { formatDate, greeting } from '../utils/format.js'

function Stat({ icon, label, value, sub, onClick }) {
  return (
    <button className="card stat" onClick={onClick} style={{ textAlign: 'left', cursor: onClick ? 'pointer' : 'default', font: 'inherit', color: 'inherit' }}>
      <div className="stat-label"><Icon name={icon} size={16} />{label}</div>
      <div className="stat-value">{value}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </button>
  )
}

export default function Dashboard() {
  const msg = useMessages()
  const navigate = useNavigate()
  const openPreview = usePreview()
  const [d, setD] = useState(null)
  const load = useCallback(async () => { try { setD(await api.get('/api/dashboard')) } catch (e) { msg.showError(e) } }, [msg])
  useEffect(() => { load() }, [load])

  const comfy = d?.comfyui
  const recentItems = (d?.recent_runs || []).flatMap(outputsToItems).slice(0, 8)

  return (
    <div className="stack" style={{ gap: 20 }}>
      <div className="card hero">
        <h1>{greeting()}.</h1>
        <p>Import a ComfyUI workflow, let ComfyFlow fetch its models into the right folders, then run it and preview every image and video right here.</p>
        <div className="row row-wrap">
          <button className="btn btn-primary btn-lg" onClick={() => navigate('/workflows/new')}><Icon name="plus" />New workflow</button>
          <button className="btn btn-lg" onClick={() => navigate('/models')}><Icon name="box" />Manage models</button>
        </div>
      </div>

      <div className="grid-4">
        <Stat icon="workflow" label="Workflows" value={d?.workflows ?? '—'} sub="Imported and converted" onClick={() => navigate('/workflows')} />
        <Stat icon="box" label="Models ready" value={d ? `${d.models_ready}/${d.models_total}` : '—'} sub={d?.downloads_active ? `${d.downloads_active} downloading now` : d?.models_no_url ? `${d.models_no_url} without URL` : 'In the model list'} onClick={() => navigate('/models')} />
        <Stat icon="image" label="Runs" value={d?.runs_total ?? '—'} sub={d ? `${d.runs_succeeded} succeeded` : ''} onClick={() => navigate('/results')} />
        <Stat icon="server" label="ComfyUI" value={comfy ? (comfy.reachable ? 'Online' : 'Offline') : '—'}
          sub={comfy ? (comfy.reachable ? (comfy.devices?.[0]?.name || comfy.url) : comfy.installed ? 'Start it in Settings' : 'Not installed yet') : ''} onClick={() => navigate('/settings')} />
      </div>

      <div className="grid-2">
        <div className="card">
          <div className="card-head"><h3>Latest results</h3><button className="btn btn-ghost btn-sm" onClick={() => navigate('/results')}>View all<Icon name="chevronRight" size={15} /></button></div>
          <div className="card-body">
            {recentItems.length ? (
              <div className="thumbs">{recentItems.map((item, i) => <Thumb key={`${item.runId}-${item.filename}`} item={item} onClick={() => openPreview(recentItems, i)} />)}</div>
            ) : <EmptyState icon="image" title="No results yet" text="Your generated images and videos will appear here." />}
          </div>
        </div>
        <div className="card">
          <div className="card-head"><h3>Recent workflows</h3><button className="btn btn-ghost btn-sm" onClick={() => navigate('/workflows')}>View all<Icon name="chevronRight" size={15} /></button></div>
          <div className="card-body stack" style={{ gap: 10 }}>
            {d?.recent_workflows?.length ? d.recent_workflows.map((w) => (
              <div key={w.id} className="row between">
                <div style={{ minWidth: 0 }}>
                  <div className="cell-main truncate" style={{ fontWeight: 600 }}>{w.name}</div>
                  <div className="small muted">{w.models_ready}/{w.models_total} models · added {formatDate(w.created_at)}</div>
                </div>
                <div className="row">
                  <RunStatus status={w.last_run_status} />
                  <button className="btn btn-sm" onClick={() => navigate(`/workflows/${w.id}/wizard?step=${w.models_ready === w.models_total ? 3 : 2}`)}>Open</button>
                </div>
              </div>
            )) : <EmptyState icon="workflow" title="No workflows yet" text="Start with the included sample workflow." />}
          </div>
        </div>
      </div>
    </div>
  )
}
