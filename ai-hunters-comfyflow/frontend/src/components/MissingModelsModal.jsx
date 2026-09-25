import { useEffect, useState } from 'react'
import Modal from './Modal.jsx'
import Icon from './Icon.jsx'
import { Spinner } from './Common.jsx'
import { api } from '../api.js'

// Shown when a run needs models that cannot be downloaded (no URL, wrong URL or wrong path).
// The user types a download URL or the path of the file on this PC; the model table is updated
// and the run is started again, which downloads (or links) the models automatically.
export default function MissingModelsModal({ resolvePath, extraBody = {}, models, reason, onClose, onSaved }) {
  const [rows, setRows] = useState(() => models.map((m) => ({ ...m, value: m.url || '' })))
  const [categories, setCategories] = useState([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => { api.get('/api/models').then((d) => setCategories(d.categories)).catch(() => {}) }, [])
  const set = (i, patch) => setRows((r) => r.map((row, j) => (j === i ? { ...row, ...patch } : row)))

  const save = async () => {
    const empty = rows.filter((r) => !r.value.trim())
    if (empty.length) {
      setError(`Please enter a URL or file path for: ${empty.map((r) => r.name).join(', ')}`)
      return
    }
    setBusy(true)
    setError('')
    try {
      await api.post(resolvePath, {
        ...extraBody,
        items: rows.map((r) => ({ name: r.name, value: r.value.trim(), category: r.category })),
      })
      onSaved()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      size="lg"
      title="Models needed for this run"
      icon={<span className="msg-icon msg-warning"><Icon name="box" size={20} /></span>}
      onClose={onClose}
      footer={(
        <>
          <div className="left muted small">Saved to the model table, so the next runs download them automatically.</div>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={save} disabled={busy} data-autofocus>
            {busy ? <Spinner /> : <Icon name="play" size={13} />}Save &amp; run
          </button>
        </>
      )}
    >
      <p className="msg-text" style={{ marginTop: 0 }}>
        {reason || 'These models are not on this computer and have no working download link.'} Enter a direct
        <b> download URL</b> or the <b>full path of the file</b> (or its folder) on this PC. Local files are linked or
        copied into the right ComfyUI models folder.
      </p>
      {error && <div className="callout callout-warning mt-8" role="alert"><Icon name="alert" /><div className="msg-text">{error}</div></div>}
      <div className="stack mt-16" style={{ gap: 14 }}>
        {rows.map((r, i) => (
          <div key={r.name} className="card card-pad" style={{ padding: 14 }}>
            <div className="row between row-wrap">
              <div style={{ minWidth: 0 }}>
                <div className="cell-main break" style={{ fontWeight: 600 }}>{r.name}</div>
                <div className="cell-sub">Used by {(r.used_by || []).join(', ') || 'this workflow'}</div>
              </div>
              <span className={`badge ${r.status === 'error' ? 'badge-danger' : 'badge-warning'}`}>
                <span className="badge-dot" />{r.status === 'error' ? 'Download failed' : 'No URL / path'}
              </span>
            </div>
            {r.error && <div className="small mt-8" style={{ color: 'var(--danger)' }}>{r.error}</div>}
            <div className="row mt-8" style={{ alignItems: 'flex-start' }}>
              <div className="field" style={{ flex: 1 }}>
                <label htmlFor={`mm-${i}`}>Download URL or file path</label>
                <input id={`mm-${i}`} className="input input-mono" value={r.value}
                  placeholder="https://huggingface.co/…/resolve/main/file.safetensors   or   D:\models\file.safetensors"
                  onChange={(e) => set(i, { value: e.target.value })} />
              </div>
              <div className="field" style={{ width: 180 }}>
                <label htmlFor={`mc-${i}`}>Category</label>
                <select id={`mc-${i}`} className="select" value={r.category} onChange={(e) => set(i, { category: e.target.value })}>
                  {(categories.length ? categories : [r.category]).map((c) => <option key={c}>{c}</option>)}
                </select>
              </div>
            </div>
          </div>
        ))}
      </div>
    </Modal>
  )
}
