import { useCallback, useEffect, useMemo, useState } from 'react'
import DataGrid from '../components/DataGrid.jsx'
import Icon from '../components/Icon.jsx'
import { PageHeader, Progress, RunStatus } from '../components/Common.jsx'
import { Thumb, outputsToItems, usePreview } from '../components/PreviewModals.jsx'
import { api } from '../api.js'
import { useMessages } from '../context/MessageContext.jsx'
import { useEvent } from '../context/EventsContext.jsx'
import { formatDate, formatDuration, zipUrl } from '../utils/format.js'

export default function Results() {
  const msg = useMessages()
  const openPreview = usePreview()
  const [runs, setRuns] = useState(null)
  const [wf, setWf] = useState('')
  const [status, setStatus] = useState('')

  const load = useCallback(async () => {
    try { setRuns((await api.get('/api/runs')).runs) } catch (e) { msg.showError(e); setRuns([]) }
  }, [msg])
  useEffect(() => { load() }, [load])
  useEvent('run', (ev) => {
    setRuns((list) => {
      if (!list) return list
      const i = list.findIndex((r) => r.id === ev.run.id)
      if (i === -1) return [ev.run, ...list]
      const next = [...list]
      next[i] = { ...next[i], ...ev.run }
      return next
    })
  })

  const workflows = useMemo(() => [...new Set((runs || []).map((r) => r.workflow_name))], [runs])
  const filtered = (runs || []).filter((r) => (!wf || r.workflow_name === wf) && (!status || r.status === status))

  const remove = async (r) => {
    const ok = await msg.showConfirm('Delete this run and its output files from ComfyFlow?', { confirmText: 'Delete', title: 'Delete run' })
    if (!ok) return
    try { await api.del(`/api/runs/${r.id}`); load() } catch (e) { msg.showError(e) }
  }

  const columns = [
    {
      key: 'outputs', header: 'Outputs', width: '28%',
      render: (r) => {
        const items = outputsToItems(r)
        if (!items.length) return <span className="muted small">{r.status === 'running' || r.status === 'queued' ? 'Rendering…' : 'No preview'}</span>
        return (
          <div className="thumb-strip">
            {items.slice(0, 4).map((item, i) => <Thumb mini key={item.filename} item={item} onClick={() => openPreview(items, i)} />)}
            {items.length > 4 && (
              <button className="thumb-mini" onClick={() => openPreview(items, 4)}><span className="more">+{items.length - 4}</span></button>
            )}
          </div>
        )
      },
    },
    { key: 'wf', header: 'Workflow', render: (r) => <><div className="cell-main">{r.workflow_name}</div><div className="cell-sub mono">{r.id}</div></> },
    {
      key: 'status', header: 'Status',
      render: (r) => (
        <div className="status-cell">
          <RunStatus status={r.status} />
          {(r.status === 'running' || r.status === 'queued') && <Progress percent={r.progress?.total ? (r.progress.done / r.progress.total) * 100 : 0} indeterminate={!r.progress?.done} />}
          {r.status === 'failed' && <span className="small truncate" style={{ color: 'var(--danger)', maxWidth: 260 }} title={r.error}>{r.error}</span>}
        </div>
      ),
    },
    { key: 'when', header: 'Started', render: (r) => <span className="small muted">{formatDate(r.created_at)}</span> },
    { key: 'dur', header: 'Duration', render: (r) => <span className="small">{formatDuration(r.duration)}</span> },
    {
      key: 'actions', header: '', className: 'col-actions',
      render: (r) => {
        const items = outputsToItems(r)
        return (
          <div className="actions">
            {r.status === 'failed' && <button className="btn btn-sm" onClick={() => msg.showError(r.error, { title: 'Why the run failed', details: r.error_details })}><Icon name="info" size={15} />Details</button>}
            <button className="btn btn-sm" disabled={!items.length} onClick={() => openPreview(items, 0)}><Icon name="eye" size={15} />Preview</button>
            <a className={`btn btn-ghost icon-btn ${r.outputs?.length ? '' : 'disabled'}`} href={r.outputs?.length ? zipUrl(r.id) : undefined} aria-label="Download all outputs" download><Icon name="archive" size={16} /></a>
            <button className="btn btn-ghost icon-btn btn-danger" onClick={() => remove(r)} aria-label="Delete run"><Icon name="trash" size={16} /></button>
          </div>
        )
      },
    },
  ]

  return (
    <>
      <PageHeader title="Results" subtitle="Every run with its images and videos. Click a thumbnail to preview it; download single files or everything as a ZIP." />
      <DataGrid
        columns={columns}
        rows={filtered}
        rowKey={(r) => r.id}
        empty={runs ? 'No runs yet. Run a workflow from the wizard.' : 'Loading…'}
        toolbar={(
          <>
            <select className="select" style={{ width: 240 }} value={wf} onChange={(e) => setWf(e.target.value)} aria-label="Filter by workflow">
              <option value="">All workflows</option>
              {workflows.map((w) => <option key={w}>{w}</option>)}
            </select>
            <select className="select" style={{ width: 170 }} value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filter by status">
              <option value="">Any status</option>
              {['succeeded', 'failed', 'running', 'cancelled'].map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
            <span className="topbar-spacer" />
            <button className="btn btn-ghost" onClick={load}><Icon name="refresh" />Refresh</button>
          </>
        )}
      />
    </>
  )
}
