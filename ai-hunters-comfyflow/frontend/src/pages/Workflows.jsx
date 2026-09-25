import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import DataGrid from '../components/DataGrid.jsx'
import Icon from '../components/Icon.jsx'
import CodeModal from '../components/CodeModal.jsx'
import { EmptyState, PageHeader, RunStatus } from '../components/Common.jsx'
import { api } from '../api.js'
import { useMessages } from '../context/MessageContext.jsx'
import { formatDate } from '../utils/format.js'

export default function Workflows() {
  const msg = useMessages()
  const navigate = useNavigate()
  const [rows, setRows] = useState(null)
  const [query, setQuery] = useState('')
  const [code, setCode] = useState(null)

  const load = useCallback(async () => {
    try { setRows((await api.get('/api/workflows')).workflows) } catch (e) { msg.showError(e); setRows([]) }
  }, [msg])
  useEffect(() => { load() }, [load])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return (rows || []).filter((r) => !q || r.name.toLowerCase().includes(q) || r.source_filename.toLowerCase().includes(q))
  }, [rows, query])

  const remove = async (row) => {
    const ok = await msg.showConfirm(`Delete the workflow “${row.name}”?\n\nIts generated script is removed. Downloaded models and previous results are kept.`, { confirmText: 'Delete', title: 'Delete workflow' })
    if (!ok) return
    try { await api.del(`/api/workflows/${row.id}`); load() } catch (e) { msg.showError(e) }
  }

  const columns = [
    {
      key: 'name', header: 'Workflow', width: '30%',
      render: (r) => (
        <>
          <div className="cell-main"><Link to={`/workflows/${r.id}/wizard?step=2`}>{r.name}</Link></div>
          <div className="cell-sub">{r.source_filename}</div>
        </>
      ),
    },
    { key: 'format', header: 'Format', render: (r) => <span className="badge">{r.format === 'ui' ? 'UI graph' : 'API'}</span> },
    { key: 'nodes', header: 'Nodes', render: (r) => r.node_count },
    {
      key: 'models', header: 'Models',
      render: (r) => (
        <span className={`badge ${r.models_ready === r.models_total ? 'badge-success' : 'badge-warning'}`}>
          <span className="badge-dot" />{r.models_ready} / {r.models_total} ready
        </span>
      ),
    },
    { key: 'last', header: 'Last run', render: (r) => <RunStatus status={r.last_run_status} /> },
    { key: 'created', header: 'Added', render: (r) => <span className="small muted">{formatDate(r.created_at)}</span> },
    {
      key: 'actions', header: '', className: 'col-actions',
      render: (r) => (
        <div className="actions">
          <button className="btn btn-sm" onClick={() => navigate(`/workflows/${r.id}/wizard?step=2`)}><Icon name="box" size={15} />Models</button>
          <button className="btn btn-sm btn-primary" onClick={() => navigate(`/workflows/${r.id}/wizard?step=3`)} disabled={r.models_ready !== r.models_total}><Icon name="play" size={12} />Run</button>
          <button className="btn btn-ghost icon-btn" onClick={() => setCode(r)} aria-label={`View script of ${r.name}`}><Icon name="code" size={16} /></button>
          <button className="btn btn-ghost icon-btn btn-danger" onClick={() => remove(r)} aria-label={`Delete ${r.name}`}><Icon name="trash" size={16} /></button>
        </div>
      ),
    },
  ]

  return (
    <>
      <PageHeader
        title="Workflows"
        subtitle="Imported ComfyUI workflows. Each one is converted to a Python script; runs unlock when all of its models are downloaded."
        actions={<button className="btn btn-primary" onClick={() => navigate('/workflows/new')}><Icon name="plus" />New workflow</button>}
      />
      {rows && rows.length === 0 ? (
        <div className="card">
          <EmptyState icon="workflow" title="No workflows yet" text="Import a ComfyUI workflow .json to get started. A sample SD 1.5 workflow is included."
            action={<button className="btn btn-primary mt-8" onClick={() => navigate('/workflows/new')}><Icon name="plus" />New workflow</button>} />
        </div>
      ) : (
        <DataGrid
          columns={columns}
          rows={filtered}
          rowKey={(r) => r.id}
          empty={rows ? 'No workflows match your search.' : 'Loading…'}
          toolbar={(
            <>
              <div className="search"><Icon name="search" size={16} /><input className="input" placeholder="Search workflows…" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search workflows" /></div>
              <span className="topbar-spacer" />
              <button className="btn btn-ghost" onClick={load}><Icon name="refresh" />Refresh</button>
            </>
          )}
        />
      )}
      {code && <CodeModal workflow={code} onClose={() => setCode(null)} />}
    </>
  )
}
