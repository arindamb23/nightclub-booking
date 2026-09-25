import { useEffect, useRef, useState } from 'react'
import Modal from './Modal.jsx'
import Icon from './Icon.jsx'
import { Spinner } from './Common.jsx'
import { api } from '../api.js'
import { formatBytes } from '../utils/format.js'

const ACCEPT = {
  image: { accept: 'image/*', ext: /\.(png|jpe?g|webp|bmp|gif)$/i, label: 'image', hint: 'PNG, JPG, WEBP, GIF' },
  video: { accept: 'video/*', ext: /\.(mp4|webm|mov|mkv|avi)$/i, label: 'video', hint: 'MP4, WEBM, MOV, MKV' },
  audio: { accept: 'audio/*', ext: /\.(wav|mp3|flac|ogg|m4a)$/i, label: 'audio file', hint: 'WAV, MP3, FLAC, OGG, M4A' },
}

// The only place where media is uploaded: choose/drop → preview → Upload.
export default function UploadModal({ kind = 'image', title, onClose, onUploaded }) {
  const cfg = ACCEPT[kind] || ACCEPT.image
  const inputRef = useRef(null)
  const [file, setFile] = useState(null)
  const [preview, setPreview] = useState(null)
  const [over, setOver] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview) }, [preview])

  const pick = (f) => {
    if (!f) return
    if (!cfg.ext.test(f.name)) {
      setError(`“${f.name}” is not a supported ${cfg.label}. Use ${cfg.hint}.`)
      return
    }
    setError('')
    setFile(f)
    setPreview(URL.createObjectURL(f))
  }

  const upload = async () => {
    if (!file) return setError(`Choose a ${cfg.label} first.`)
    setBusy(true)
    setError('')
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await api.upload('/api/uploads', fd)
      onUploaded({ ...res, kind })
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      title={title || `Upload ${cfg.label}`}
      icon={<span className="msg-icon msg-confirm"><Icon name="upload" size={20} /></span>}
      onClose={onClose}
      footer={(
        <>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={upload} disabled={!file || busy} data-autofocus>
            {busy ? <Spinner /> : <Icon name="upload" />}Upload
          </button>
        </>
      )}
    >
      <div
        className={`dropzone ${over ? 'over' : ''}`}
        role="button"
        tabIndex={0}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setOver(true) }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); pick(e.dataTransfer.files?.[0]) }}
        style={{ padding: preview ? 16 : 32 }}
      >
        {preview ? (
          <div className="upload-preview">
            {kind === 'image' && <img src={preview} alt="Selected file" />}
            {kind === 'video' && <video src={preview} controls muted />}
            {kind === 'audio' && <audio src={preview} controls />}
          </div>
        ) : (
          <>
            <div className="dropzone-icon"><Icon name={kind === 'image' ? 'image' : kind === 'video' ? 'film' : 'audio'} size={26} /></div>
            <h3>Drop the {cfg.label} here</h3>
            <p className="muted">or click to choose a file · {cfg.hint}</p>
          </>
        )}
        <input ref={inputRef} type="file" hidden accept={cfg.accept} onChange={(e) => pick(e.target.files?.[0])} />
      </div>
      {file && (
        <div className="row between mt-8 small">
          <span className="truncate"><b>{file.name}</b> · {formatBytes(file.size)}</span>
          <button className="btn btn-ghost btn-sm" onClick={() => inputRef.current?.click()}>Choose another</button>
        </div>
      )}
      {error && <div className="callout callout-warning mt-16" role="alert"><Icon name="alert" /><div>{error}</div></div>}
    </Modal>
  )
}
