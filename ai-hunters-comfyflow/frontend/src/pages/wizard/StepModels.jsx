import { useCallback, useEffect, useRef, useState } from 'react'
import DataGrid from '../../components/DataGrid.jsx'
import Icon from '../../components/Icon.jsx'
import { ModelStatus, Progress, Spinner } from '../../components/Common.jsx'
import { api } from '../../api.js'
import { useMessages } from '../../context/MessageContext.jsx'
import { useEvent } from '../../context/EventsContext.jsx'
import { applyDownloadEvent } from '../Models.jsx'
import { formatBytes, shortPath } from '../../utils/format.js'
import { CustomNodeRows, RestartBanner, useCustomNodes } from '../../components/CustomNodes.jsx'

function CustomNodesCard({ workflow, onChanged }) {
  const [check, setCheck] = useState(null)
  const load = useCallback(() => api.get(`/api/workflows/${workflow.id}/nodes-check`).then(setCheck).catch(() => setCheck(null)), [workflow.id])
  useEffect(() => { load() }, [load])
  const state = useCustomNodes(check?.packs, () => { load(); onChanged?.() })
  if (!check) return null
  if (!check.available) {
    return <div className="callout callout-info"><Icon name="info" /><div>{check.message} Custom nodes this workflow needs are listed here once ComfyUI runs.</div></div>
  }
  if (!check.packs.length && state.restart.status !== 'done') return null
  return (
    <div className="card">
      <div className="card-head">
        <div><h3>Custom nodes</h3><span className="muted small">Node types this workflow uses that ComfyUI does not have yet</span></div>
        {check.packs.length > 0 && (
          <button className="btn btn-primary btn-sm" onClick={state.installAll} disabled={state.busy}>
            {state.busy ? <Spinner size={14} /> : <Icon name="download" size={14} />}Install all &amp; restart ComfyUI
          </button>
        )}
      </div>
      <div className="card-body stack" style={{ gap: 12 }}>
        {state.error && <div className="callout callout-warning"><Icon name="alert" /><div>{state.error}</div></div>}
        <RestartBanner state={state} />
        <CustomNodeRows state={state} compact />
      </div>
    </div>
  )
}

export default function StepModels({ workflow, onBack, onNext, onChanged }) {
  const msg = useMessages()
  const [rows, setRows] = useState(null)
  const [categories, setCategories] = useState([])
  const [auto, setAuto] = useState(true)
  const [editing, setEditing] = useState(null)
  const [saving, setSaving] = useState(false)
  const autoStarted = useRef(false)

  const load = useCallback(async () => {
    try {
      const data = await api.get(`/api/workflows/${workflow.id}/models`)
      setRows(data.models)
      return data.models
    } catch (e) {
      msg.showError(e)
      return []
    }
  }, [workflow.id, msg])

  const downloadMissing = useCallback(async (quiet = false) => {
    try {
      const { started } = await api.post(`/api/workflows/${workflow.id}/models/download-missing`)
      if (!quiet && !started.length) msg.showInfo('Nothing to download: every model with a URL is already on disk.')
      await load()
    } catch (e) {
      msg.showError(e)
    }
  }, [workflow.id, msg, load])

  useEffect(() => {
    let alive = true
    ;(async () => {
      const [models, settings, cats] = await Promise.all([
        load(),
        api.get('/api/settings').catch(() => null),
        api.get('/api/models').catch(() => ({ categories: [] })),
      ])
      if (!alive) return
      setCategories(cats.categories || [])
      const autoOn = settings?.settings?.auto_download_models ?? true
      setAuto(autoOn)
      if (autoOn && !autoStarted.current && models.some((m) => m.status === 'missing')) {
        autoStarted.current = true
        downloadMissing(true)
      }
    })()
    return () => { alive = false }
  }, [load, downloadMissing])

  useEvent('download', (ev) => {
    setRows((r) => (r ? applyDownloadEvent(r, ev, 'registry_name') : r))
    if (ev.status === 'done' || ev.status === 'error') {
      load()
      onChanged?.()
    }
  })

  const toggleAuto = async (checked) => {
    setAuto(checked)
    try {
      await api.put('/api/settings', { values: { AUTO_DOWNLOAD_MODELS: checked ? 'true' : 'false' } })
      if (checked) downloadMissing(true)
    } catch (e) {
      msg.showError(e)
    }
  }

  const download = async (row) => {
    try {
      const job = await api.post('/api/models/download', { name: row.registry_name, requested_name: row.name })
      setRows((r) => applyDownloadEvent(r, job, 'registry_name'))
    } catch (e) {
      msg.showError(e)
    }
  }
  const cancel = async (row) => {
    try { await api.post('/api/models/cancel', { name: row.registry_name, requested_name: row.name }) } catch (e) { msg.showError(e) }
  }

  const startEdit = (row) => setEditing({ key: row.name, draft: { url: row.url || '', save_dir: row.save_dir || '', category: row.category } })
  const setDraft = (p) => setEditing((e) => ({ ...e, draft: { ...e.draft, ...p } }))
  const save = async (row) => {
    setSaving(true)
    try {
      await api.post('/api/models', { name: row.registry_name, ...editing.draft, original_name: row.registry_name })
      setEditing(null)
      const models = await load()
      const updated = models.find((m) => m.name === row.name)
      if (updated && updated.status === 'missing' && auto) download(updated)
    } catch (e) {
      msg.showError(e)
    } finally {
      setSaving(false)
    }
  }

  if (!rows) return <div className="card card-pad row muted"><Spinner />Detecting models…</div>

  const ready = rows.filter((r) => r.status === 'ready' || r.status === 'node').length
  const allReady = ready === rows.length
  const noUrl = rows.filter((r) => r.status === 'no_url').length
  const isEditing = (r) => editing?.key === r.name
  const d = editing?.draft

  const columns = [
    {
      key: 'name', header: 'Model', width: '26%',
      render: (r) => (
        <>
          <div className="cell-main break">{r.name}</div>
          {r.kind === 'repo' && <div className="cell-sub"><span className="badge badge-info" style={{ height: 18 }}>Hugging Face repository</span>{r.status === 'node' ? ' the node downloads it on its first run' : ' downloaded as a folder'}</div>}
          <div className="cell-sub">Used by {r.used_by.join(', ')}{r.size ? ` · ${formatBytes(r.size)}` : ''}</div>
        </>
      ),
    },
    {
      key: 'category', header: 'Category',
      render: (r) => isEditing(r) ? (
        <select className="select input-sm" value={d.category} onChange={(e) => setDraft({ category: e.target.value })} aria-label="Category">
          {categories.map((c) => <option key={c}>{c}</option>)}
        </select>
      ) : <span className="badge">{r.category}</span>,
    },
    {
      key: 'url', header: 'Download URL', width: '26%',
      render: (r) => isEditing(r) ? (
        <input className="input input-sm input-mono" value={d.url} autoFocus placeholder="https://…" onChange={(e) => setDraft({ url: e.target.value })} aria-label="Download URL" />
      ) : r.url ? (
        <a className="small mono break" href={r.url} target="_blank" rel="noreferrer" title={r.url}>{r.url.length > 60 ? `${r.url.slice(0, 57)}…` : r.url}</a>
      ) : (
        <button className="btn btn-sm" onClick={() => startEdit(r)} disabled={!!editing}><Icon name="link" size={14} />Add URL</button>
      ),
    },
    {
      key: 'save', header: 'Save to', width: '20%',
      render: (r) => isEditing(r) ? (
        <input className="input input-sm input-mono" value={d.save_dir} placeholder="(default folder)" onChange={(e) => setDraft({ save_dir: e.target.value })} aria-label="Save location" />
      ) : <span className="small mono" title={r.resolved_dir}>{shortPath(r.resolved_dir)}</span>,
    },
    { key: 'status', header: 'Status', render: (r) => <ModelStatus status={r.status} job={r.job} partial={r.partial} /> },
    {
      key: 'actions', header: '', className: 'col-actions',
      render: (r) => isEditing(r) ? (
        <div className="actions">
          <button className="btn btn-primary btn-sm" onClick={() => save(r)} disabled={saving}><Icon name="save" size={15} />Save</button>
          <button className="btn btn-sm" onClick={() => setEditing(null)}>Cancel</button>
        </div>
      ) : (
        <div className="actions">
          {(r.status === 'downloading' || r.status === 'queued') && <button className="btn btn-sm" onClick={() => cancel(r)}><Icon name="stop" size={13} />Cancel</button>}
          {(r.status === 'missing' || r.status === 'error') && <button className="btn btn-sm btn-primary" onClick={() => download(r)}><Icon name="download" size={15} />{r.status === 'error' ? 'Retry' : 'Download'}</button>}
          {r.kind !== 'repo' && <button className="btn btn-ghost icon-btn" onClick={() => startEdit(r)} disabled={!!editing} aria-label={`Edit ${r.name}`}><Icon name="edit" size={16} /></button>}
        </div>
      ),
    },
  ]

  return (
    <div className="stack">
      <CustomNodesCard workflow={workflow} onChanged={onChanged} />
      <div className="card card-pad">
        <div className="row between row-wrap">
          <div className="row row-wrap" style={{ gap: 14 }}>
            <label className="checkbox"><input type="checkbox" checked={auto} onChange={(e) => toggleAuto(e.target.checked)} />Auto-download missing models</label>
            <button className="btn" onClick={() => downloadMissing(false)}><Icon name="download" />Download all missing</button>
            <button className="btn btn-ghost" onClick={load}><Icon name="refresh" />Refresh</button>
          </div>
          <div style={{ minWidth: 240 }}>
            <div className="row between small"><span className="muted">Models ready</span><b>{ready} / {rows.length}</b></div>
            <div className="mt-8"><Progress percent={rows.length ? (ready / rows.length) * 100 : 100} /></div>
          </div>
        </div>
        {noUrl > 0 && (
          <div className="callout callout-warning mt-16"><Icon name="alert" /><div>{noUrl} model(s) have no download URL. Click <b>Add URL</b> and paste a direct link (for Hugging Face use the <span className="mono">…/resolve/main/…</span> link).</div></div>
        )}
        {!rows.length && <div className="callout callout-info mt-16"><Icon name="info" /><div>No model files were detected in this workflow. You can continue to the run step.</div></div>}
      </div>

      <DataGrid columns={columns} rows={rows} rowKey={(r) => r.name} rowClassName={(r) => (isEditing(r) ? 'editing' : '')} empty="This workflow does not reference any model files." />

      <div className="card">
        <div className="wizard-foot" style={{ borderTop: 'none' }}>
          <button className="btn" onClick={onBack}><Icon name="chevronLeft" />Back</button>
          <div className="row">
            <span className="muted small">{allReady ? 'All required models are ready.' : 'Missing models are downloaded automatically when you run.'}</span>
            <button className="btn btn-primary" onClick={onNext}>Next: run<Icon name="chevronRight" /></button>
          </div>
        </div>
      </div>
    </div>
  )
}
