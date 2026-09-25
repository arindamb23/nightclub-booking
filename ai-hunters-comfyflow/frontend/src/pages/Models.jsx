import { useCallback, useEffect, useMemo, useState } from 'react'
import DataGrid from '../components/DataGrid.jsx'
import Icon from '../components/Icon.jsx'
import { ModelStatus, PageHeader, Spinner } from '../components/Common.jsx'
import { api } from '../api.js'
import { useMessages } from '../context/MessageContext.jsx'
import { useEvent } from '../context/EventsContext.jsx'
import { formatBytes, shortPath } from '../utils/format.js'

const NEW_KEY = '__new__'

export function applyDownloadEvent(rows, ev, nameKey = 'name') {
  let changed = false
  const next = rows.map((r) => {
    if (r[nameKey] !== ev.name && r.name !== ev.name) return r
    changed = true
    const status = ev.status === 'done' ? 'ready' : ev.status === 'cancelled' ? (r.url ? 'missing' : 'no_url') : ev.status
    return { ...r, status, job: ev, size: ev.status === 'done' ? ev.total : r.size }
  })
  return changed ? next : rows
}

export default function Models() {
  const msg = useMessages()
  const [rows, setRows] = useState([])
  const [categories, setCategories] = useState([])
  const [loading, setLoading] = useState(true)
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState('')
  const [editing, setEditing] = useState(null) // { key, draft }
  const [saving, setSaving] = useState(false)
  const [page, setPage] = useState(1)

  const load = useCallback(async () => {
    try {
      const data = await api.get('/api/models')
      setRows(data.models)
      setCategories(data.categories)
    } catch (e) {
      msg.showError(e)
    } finally {
      setLoading(false)
    }
  }, [msg])

  useEffect(() => { load() }, [load])
  useEvent('download', (ev) => {
    setRows((r) => applyDownloadEvent(r, ev))
    if (ev.status === 'error') msg.showError(`Download of “${ev.name}” failed.\n\n${ev.error}`, { title: 'Download failed' })
  })

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    const list = rows.filter((r) => (!category || r.category === category) && (!q || r.name.toLowerCase().includes(q) || (r.url || '').toLowerCase().includes(q)))
    if (editing?.key === NEW_KEY) return [{ name: NEW_KEY, url: '', category: 'checkpoints', save_dir: '', status: 'no_url' }, ...list]
    return list
  }, [rows, query, category, editing])

  const startEdit = (row) => setEditing({ key: row.name, draft: { name: row.name, url: row.url || '', category: row.category, save_dir: row.save_dir || '' } })
  const startAdd = () => {
    setPage(1)
    setEditing({ key: NEW_KEY, draft: { name: '', url: '', category: category || 'checkpoints', save_dir: '' } })
  }
  const setDraft = (patch) => setEditing((e) => ({ ...e, draft: { ...e.draft, ...patch } }))

  const save = async () => {
    const { key, draft } = editing
    if (!draft.name.trim()) return msg.showWarning('Please enter the model file name, for example “my_model.safetensors”.')
    setSaving(true)
    try {
      await api.post('/api/models', { ...draft, original_name: key === NEW_KEY ? null : key })
      setEditing(null)
      await load()
      msg.showSuccess(key === NEW_KEY ? `“${draft.name}” was added to the model list.` : `“${draft.name}” was saved.`)
    } catch (e) {
      msg.showError(e)
    } finally {
      setSaving(false)
    }
  }

  const download = async (row) => {
    try {
      const job = await api.post('/api/models/download', { name: row.name })
      setRows((r) => applyDownloadEvent(r, job))
    } catch (e) {
      msg.showError(e)
    }
  }
  const cancel = async (row) => {
    try { await api.post('/api/models/cancel', { name: row.name }) } catch (e) { msg.showError(e) }
  }
  const remove = async (row) => {
    const ok = await msg.showConfirm(`Remove “${row.name}” from the model list?\n\nThe downloaded file (if any) stays on disk.`, { confirmText: 'Remove', title: 'Remove model' })
    if (!ok) return
    try {
      await api.del(`/api/models/${encodeURIComponent(row.name)}`)
      await load()
    } catch (e) {
      msg.showError(e)
    }
  }
  const downloadAll = async () => {
    const missing = rows.filter((r) => r.status === 'missing' || r.status === 'error')
    if (!missing.length) return msg.showInfo('Every model that has a download URL is already downloaded.')
    const ok = await msg.showConfirm(`Start downloading ${missing.length} missing model(s)? Large models can take a long time.`, { confirmText: 'Download all' })
    if (!ok) return
    try { await api.post('/api/models/download-all') ; await load() } catch (e) { msg.showError(e) }
  }

  const isEditing = (row) => editing && editing.key === row.name
  const d = editing?.draft

  const columns = [
    {
      key: 'name', header: 'Model name', width: '24%',
      render: (row) => isEditing(row) ? (
        <input className="input input-sm input-mono" value={d.name} placeholder="model_file.safetensors" onChange={(e) => setDraft({ name: e.target.value })} aria-label="Model name" autoFocus />
      ) : (
        <>
          <div className="cell-main break">{row.name}</div>
          <div className="cell-sub">{row.size ? formatBytes(row.size) : 'Not downloaded'}</div>
        </>
      ),
    },
    {
      key: 'url', header: 'Download URL', width: '28%',
      render: (row) => isEditing(row) ? (
        <input className="input input-sm input-mono" value={d.url} placeholder="https://huggingface.co/…/resolve/main/file.safetensors" onChange={(e) => setDraft({ url: e.target.value })} aria-label="Download URL" />
      ) : row.url ? (
        <a href={row.url} target="_blank" rel="noreferrer" className="small mono break" title={row.url} style={{ display: 'block', maxWidth: 340 }}>
          {row.url.length > 70 ? `${row.url.slice(0, 67)}…` : row.url}
        </a>
      ) : <span className="muted small">No URL yet</span>,
    },
    {
      key: 'category', header: 'Category',
      render: (row) => isEditing(row) ? (
        <select className="select input-sm" value={d.category} onChange={(e) => setDraft({ category: e.target.value })} aria-label="Category">
          {categories.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      ) : <span className="badge">{row.category}</span>,
    },
    {
      key: 'save', header: 'Save location', width: '22%',
      render: (row) => isEditing(row) ? (
        <>
          <input className="input input-sm input-mono" value={d.save_dir} placeholder="(default: models\<category>)" onChange={(e) => setDraft({ save_dir: e.target.value })} aria-label="Save location" />
          <div className="cell-sub">Leave empty to use the ComfyUI models folder.</div>
        </>
      ) : (
        <>
          <div className="small mono" title={row.resolved_dir}>{shortPath(row.resolved_dir)}</div>
          <div className="cell-sub">{row.save_dir ? 'Custom location' : 'Default location'}</div>
        </>
      ),
    },
    { key: 'status', header: 'Status', render: (row) => row.name === NEW_KEY ? <span className="badge badge-accent">New</span> : <ModelStatus status={row.status} job={row.job} /> },
    {
      key: 'actions', header: '', className: 'col-actions',
      render: (row) => isEditing(row) ? (
        <div className="actions">
          <button className="btn btn-primary btn-sm" onClick={save} disabled={saving}>{saving ? <Spinner size={14} /> : <Icon name="save" size={15} />}Save</button>
          <button className="btn btn-sm" onClick={() => setEditing(null)}>Cancel</button>
        </div>
      ) : (
        <div className="actions">
          {(row.status === 'downloading' || row.status === 'queued') ? (
            <button className="btn btn-sm" onClick={() => cancel(row)}><Icon name="stop" size={13} />Cancel</button>
          ) : (row.status === 'missing' || row.status === 'error') ? (
            <button className="btn btn-sm btn-primary" onClick={() => download(row)}><Icon name="download" size={15} />Download</button>
          ) : null}
          <button className="btn btn-ghost icon-btn" onClick={() => startEdit(row)} aria-label={`Edit ${row.name}`} disabled={!!editing}><Icon name="edit" size={16} /></button>
          <button className="btn btn-ghost icon-btn btn-danger" onClick={() => remove(row)} aria-label={`Remove ${row.name}`} disabled={!!editing}><Icon name="trash" size={16} /></button>
        </div>
      ),
    },
  ]

  const readyCount = rows.filter((r) => r.status === 'ready').length
  return (
    <>
      <PageHeader
        title="Model manager"
        subtitle="Every model a workflow can use: its file name, where to download it from and where it is saved. Missing models are downloaded automatically into the right ComfyUI folder."
        actions={(
          <>
            <button className="btn" onClick={downloadAll}><Icon name="download" />Download all missing</button>
            <button className="btn btn-primary" onClick={startAdd} disabled={!!editing}><Icon name="plus" />Add model</button>
          </>
        )}
      />
      <DataGrid
        page={page}
        onPageChange={setPage}
        columns={columns}
        rows={filtered}
        rowKey={(r) => r.name}
        rowClassName={(r) => (isEditing(r) ? 'editing' : '')}
        empty={loading ? 'Loading models…' : 'No models match your search.'}
        toolbar={(
          <>
            <div className="search">
              <Icon name="search" size={16} />
              <input className="input" placeholder="Search name or URL…" value={query} onChange={(e) => { setQuery(e.target.value); setPage(1) }} aria-label="Search models" />
            </div>
            <select className="select" style={{ width: 200 }} value={category} onChange={(e) => { setCategory(e.target.value); setPage(1) }} aria-label="Filter by category">
              <option value="">All categories</option>
              {categories.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
            <span className="topbar-spacer" />
            <span className="badge badge-success">{readyCount} ready</span>
            <span className="badge">{rows.length} total</span>
          </>
        )}
      />
    </>
  )
}
