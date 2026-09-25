import { useState } from 'react'
import Icon from './Icon.jsx'
import UploadModal from './UploadModal.jsx'
import { usePreview } from './PreviewModals.jsx'

const MAX_SEED = 2 ** 50
export const UPLOAD_KIND = { upload_image: 'image', upload_video: 'video', upload_audio: 'audio', image: 'image', video: 'video', audio: 'audio' }

// Media value: a string (current file) or {upload, original} (just uploaded, not saved yet)
export function mediaInfo(value, preview) {
  if (value && typeof value === 'object' && value.upload) {
    return { name: value.original || value.upload, src: `/api/uploads/${encodeURIComponent(value.upload)}` }
  }
  if (preview?.url) return { name: preview.name || String(value || ''), src: preview.url }
  return value ? { name: String(value).split(/[\\/]/).pop(), src: null } : null
}

export function MediaInput({ kind, value, preview, onChange, label }) {
  const [open, setOpen] = useState(false)
  const openPreview = usePreview()
  const info = mediaInfo(value, preview)
  const show = () => info?.src && openPreview([{ kind, filename: info.name, src: info.src }], 0)
  return (
    <div className="media-input">
      <button type="button" className="media-thumb" onClick={show} disabled={!info?.src} aria-label={`Preview ${label || kind}`}>
        {info?.src && kind === 'image' ? <img src={info.src} alt="" /> : <Icon name={kind === 'image' ? 'image' : kind === 'video' ? 'film' : 'audio'} size={22} />}
        {info?.src && kind !== 'image' && <span className="media-thumb-play"><Icon name="play" size={12} /></span>}
      </button>
      <div className="media-input-body">
        <div className="small truncate" title={info?.name}>{info?.name || <span className="muted">No file selected</span>}</div>
        <div className="row mt-8">
          <button type="button" className="btn btn-sm" onClick={() => setOpen(true)}><Icon name="upload" size={14} />Upload…</button>
          {info?.src && <button type="button" className="btn btn-sm btn-ghost" onClick={show}><Icon name={kind === 'image' ? 'eye' : 'play'} size={13} />{kind === 'image' ? 'Preview' : 'Play'}</button>}
        </div>
      </div>
      {open && (
        <UploadModal kind={kind} title={`Upload ${label || kind}`} onClose={() => setOpen(false)}
          onUploaded={(res) => { setOpen(false); onChange({ upload: res.filename, original: res.original }) }} />
      )}
    </div>
  )
}

// One editable value, rendered from its control type (control map / node definition)
export default function FieldControl({ field, value, onChange, id, preview, disabled }) {
  const control = field.control || field.kind
  const kind = UPLOAD_KIND[control]
  if (kind) return <MediaInput kind={kind} value={value} preview={preview ?? field.preview} onChange={onChange} label={field.label} />
  if (control === 'prompt' || control === 'text') {
    return <textarea id={id} className="textarea" rows={control === 'prompt' ? 4 : 3} value={value ?? ''} disabled={disabled} onChange={(e) => onChange(e.target.value)} />
  }
  if (control === 'select') {
    return (
      <select id={id} className="select" value={value ?? ''} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
        {(field.options || []).map((o) => <option key={String(o)} value={o}>{String(o)}</option>)}
      </select>
    )
  }
  if (control === 'toggle' || control === 'bool') {
    return (
      <label className="switch">
        <input id={id} type="checkbox" checked={!!value} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
        <span className="switch-track"><span className="switch-thumb" /></span>
        <span className="small muted">{value ? 'On' : 'Off'}</span>
      </label>
    )
  }
  if (control === 'number' || control === 'seed') {
    return (
      <div className="row">
        <input id={id} className="input" type="number" value={value ?? ''} disabled={disabled}
          min={field.min ?? undefined} max={field.max ?? undefined} step={field.is_float ? (field.step || 'any') : (field.step || 1)}
          onChange={(e) => onChange(e.target.value === '' ? '' : Number(e.target.value))} />
        {control === 'seed' && (
          <button type="button" className="btn icon-btn" aria-label="New random seed" disabled={disabled}
            onClick={() => onChange(Math.floor(Math.random() * MAX_SEED))}><Icon name="dice" /></button>
        )}
      </div>
    )
  }
  return <input id={id} className="input" value={value ?? ''} disabled={disabled} onChange={(e) => onChange(e.target.value)} />
}
