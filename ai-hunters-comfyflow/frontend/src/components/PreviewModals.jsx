import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import Modal from './Modal.jsx'
import Icon from './Icon.jsx'
import { fileUrl, formatBytes, zipUrl } from '../utils/format.js'

// items: [{ kind: 'image'|'video'|'animation'|'audio', filename, size?, runId?, src?, downloadSrc? }]
// src/downloadSrc let any file be previewed (e.g. a node's uploaded input); otherwise the run file URLs are used.
const isMotion = (item) => item.kind === 'video' || item.kind === 'animation'
const srcOf = (item) => item.src || fileUrl(item.runId, item.filename)
const downloadOf = (item) => item.downloadSrc || (item.runId ? fileUrl(item.runId, item.filename, true) : item.src)
const groupOf = (item) => (item.kind === 'audio' ? 'audio' : isMotion(item) ? 'video' : 'image')

function useKeyNav(count, setIndex) {
  useEffect(() => {
    const onKey = (e) => {
      if (count < 2) return
      if (e.key === 'ArrowRight') setIndex((i) => (i + 1) % count)
      if (e.key === 'ArrowLeft') setIndex((i) => (i - 1 + count) % count)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [count, setIndex])
}

function NavButtons({ count, setIndex }) {
  if (count < 2) return null
  return (
    <>
      <button className="btn icon-btn preview-nav prev" aria-label="Previous" onClick={() => setIndex((i) => (i - 1 + count) % count)}><Icon name="chevronLeft" /></button>
      <button className="btn icon-btn preview-nav next" aria-label="Next" onClick={() => setIndex((i) => (i + 1) % count)}><Icon name="chevronRight" /></button>
    </>
  )
}

function DownloadButtons({ item, items }) {
  const sameRun = items.length > 1 && items.every((i) => i.runId && i.runId === items[0].runId) ? items[0].runId : null
  return (
    <>
      {sameRun && <a className="btn" href={zipUrl(sameRun)} download><Icon name="archive" />Download all</a>}
      <a className="btn btn-primary" href={downloadOf(item)} download={item.filename} data-autofocus>
        <Icon name="download" />Download
      </a>
    </>
  )
}

const fmtTime = (t) => (Number.isFinite(t) ? `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}` : '0:00')

// Play / Pause / Stop + seek bar for a <video> or <audio> element
export function MediaControls({ mediaRef, autoPlay = true }) {
  const [playing, setPlaying] = useState(false)
  const [time, setTime] = useState(0)
  const [duration, setDuration] = useState(0)
  useEffect(() => {
    const el = mediaRef.current
    if (!el) return undefined
    const sync = () => { setPlaying(!el.paused); setTime(el.currentTime); setDuration(el.duration || 0) }
    const events = ['play', 'pause', 'timeupdate', 'loadedmetadata', 'ended']
    events.forEach((ev) => el.addEventListener(ev, sync))
    if (autoPlay) el.play().catch(() => {})
    return () => events.forEach((ev) => el.removeEventListener(ev, sync))
  }, [mediaRef, autoPlay])
  const el = () => mediaRef.current
  return (
    <div className="media-controls">
      <button className="btn icon-btn" aria-label="Play" onClick={() => el()?.play()} disabled={playing}><Icon name="play" size={15} /></button>
      <button className="btn icon-btn" aria-label="Pause" onClick={() => el()?.pause()} disabled={!playing}><Icon name="pause" size={15} /></button>
      <button className="btn icon-btn" aria-label="Stop" onClick={() => { const m = el(); if (m) { m.pause(); m.currentTime = 0 } }}><Icon name="stop" size={13} /></button>
      <input className="media-seek" type="range" min={0} max={duration || 0} step="0.05" value={time} aria-label="Seek"
        onChange={(e) => { const m = el(); if (m) m.currentTime = Number(e.target.value) }} />
      <span className="media-time">{fmtTime(time)} / {fmtTime(duration)}</span>
    </div>
  )
}

export function ImagePreviewModal({ items, startIndex = 0, onClose }) {
  const [index, setIndex] = useState(startIndex)
  const [zoom, setZoom] = useState(0)
  const [dims, setDims] = useState(null)
  const item = items[index]
  useKeyNav(items.length, setIndex)
  useEffect(() => { setDims(null) }, [index])
  const step = (dir) => setZoom((z) => Math.min(4, Math.max(0.1, +((z || 1) * (dir > 0 ? 1.25 : 0.8)).toFixed(2))))
  return (
    <Modal size="xl" title={item.filename} icon={<span className="msg-icon msg-info"><Icon name="image" size={20} /></span>} onClose={onClose}
      footer={(
        <>
          <div className="left">
            <div className="zoom-controls">
              <button className="btn icon-btn" onClick={() => step(-1)} aria-label="Zoom out"><Icon name="zoomOut" /></button>
              <span>{zoom === 0 ? 'Auto' : `${Math.round(zoom * 100)}%`}</span>
              <button className="btn icon-btn" onClick={() => step(1)} aria-label="Zoom in"><Icon name="zoomIn" /></button>
              <button className="btn btn-sm" onClick={() => setZoom(0)}><Icon name="maximize" size={15} />Fit</button>
              <button className="btn btn-sm" onClick={() => setZoom(1)}>100%</button>
            </div>
          </div>
          <DownloadButtons item={item} items={items} />
        </>
      )}>
      <div className="preview-stage">
        <NavButtons count={items.length} setIndex={setIndex} />
        <img key={srcOf(item)} src={srcOf(item)} alt={item.filename} className={zoom === 0 ? 'fit' : ''}
          style={zoom && dims ? { width: dims.w * zoom, height: dims.h * zoom, maxWidth: 'none' } : undefined}
          onLoad={(e) => setDims({ w: e.target.naturalWidth, h: e.target.naturalHeight })} />
      </div>
      <div className="preview-meta mt-16">
        {items.length > 1 && <span><b>{index + 1}</b> / {items.length}</span>}
        {dims && <span><b>{dims.w} × {dims.h}</b> px</span>}
        {item.size ? <span><b>{formatBytes(item.size)}</b></span> : null}
        {item.workflowName && <span>Workflow <b>{item.workflowName}</b></span>}
      </div>
    </Modal>
  )
}

export function VideoPreviewModal({ items, startIndex = 0, onClose }) {
  const [index, setIndex] = useState(startIndex)
  const [meta, setMeta] = useState(null)
  const mediaRef = useRef(null)
  const item = items[index]
  useKeyNav(items.length, setIndex)
  useEffect(() => { setMeta(null) }, [index])
  return (
    <Modal size="lg" title={item.filename} icon={<span className="msg-icon msg-confirm"><Icon name="film" size={20} /></span>} onClose={onClose}
      footer={(
        <>
          {item.kind !== 'animation' && <div className="left" style={{ flex: 1 }}><MediaControls key={srcOf(item)} mediaRef={mediaRef} /></div>}
          <DownloadButtons item={item} items={items} />
        </>
      )}>
      <div className="preview-stage" style={{ background: '#1f1e1d' }}>
        <NavButtons count={items.length} setIndex={setIndex} />
        {item.kind === 'animation' ? (
          <img key={srcOf(item)} src={srcOf(item)} alt={item.filename} className="fit" onLoad={(e) => setMeta({ w: e.target.naturalWidth, h: e.target.naturalHeight })} />
        ) : (
          <video key={srcOf(item)} ref={mediaRef} src={srcOf(item)} loop playsInline
            onClick={(e) => (e.target.paused ? e.target.play() : e.target.pause())}
            onLoadedMetadata={(e) => setMeta({ w: e.target.videoWidth, h: e.target.videoHeight, d: e.target.duration })} />
        )}
      </div>
      <div className="preview-meta mt-16">
        {items.length > 1 && <span><b>{index + 1}</b> / {items.length}</span>}
        {meta && <span><b>{meta.w} × {meta.h}</b> px</span>}
        {meta && Number.isFinite(meta.d) && <span><b>{meta.d.toFixed(1)} s</b></span>}
        {item.size ? <span><b>{formatBytes(item.size)}</b></span> : null}
        {item.kind === 'animation' && <span>Animated image</span>}
      </div>
    </Modal>
  )
}

export function AudioPreviewModal({ items, startIndex = 0, onClose }) {
  const [index, setIndex] = useState(startIndex)
  const mediaRef = useRef(null)
  const item = items[index]
  useKeyNav(items.length, setIndex)
  return (
    <Modal title={item.filename} icon={<span className="msg-icon msg-success"><Icon name="audio" size={20} /></span>} onClose={onClose}
      footer={<DownloadButtons item={item} items={items} />}>
      <div className="audio-stage">
        <div className="audio-disc"><Icon name="audio" size={34} /></div>
        <audio key={srcOf(item)} ref={mediaRef} src={srcOf(item)} />
        <MediaControls key={`c-${srcOf(item)}`} mediaRef={mediaRef} />
        {items.length > 1 && (
          <div className="row between small mt-8">
            <button className="btn btn-sm" onClick={() => setIndex((i) => (i - 1 + items.length) % items.length)}><Icon name="chevronLeft" size={14} />Previous</button>
            <span className="muted">{index + 1} / {items.length}</span>
            <button className="btn btn-sm" onClick={() => setIndex((i) => (i + 1) % items.length)}>Next<Icon name="chevronRight" size={14} /></button>
          </div>
        )}
        {item.size ? <div className="preview-meta mt-8"><span><b>{formatBytes(item.size)}</b></span></div> : null}
      </div>
    </Modal>
  )
}

// ---- controller: any page calls openPreview(items, index) and the right modal opens
const PreviewContext = createContext(null)

export function PreviewProvider({ children }) {
  const [state, setState] = useState(null)
  const openPreview = useCallback((all, clicked) => {
    const item = all[clicked]
    if (!item) return
    const kind = groupOf(item)
    const group = all.filter((i) => groupOf(i) === kind)
    setState({ kind, items: group, index: Math.max(0, group.indexOf(item)) })
  }, [])
  const value = useMemo(() => openPreview, [openPreview])
  const close = () => setState(null)
  return (
    <PreviewContext.Provider value={value}>
      {children}
      {state?.kind === 'image' && <ImagePreviewModal items={state.items} startIndex={state.index} onClose={close} />}
      {state?.kind === 'video' && <VideoPreviewModal items={state.items} startIndex={state.index} onClose={close} />}
      {state?.kind === 'audio' && <AudioPreviewModal items={state.items} startIndex={state.index} onClose={close} />}
    </PreviewContext.Provider>
  )
}

export const usePreview = () => useContext(PreviewContext)

export function outputsToItems(run) {
  return (run?.outputs || [])
    .filter((o) => ['image', 'video', 'animation', 'audio'].includes(o.kind))
    .map((o) => ({ ...o, runId: run.id, workflowName: run.workflow_name }))
}

export function Thumb({ item, onClick, mini = false }) {
  const src = srcOf(item)
  return (
    <button className={mini ? 'thumb-mini' : 'thumb'} onClick={onClick} title={item.filename} type="button">
      {item.kind === 'audio' ? (
        <span className="thumb-audio"><Icon name="audio" size={mini ? 18 : 30} /></span>
      ) : item.kind === 'video' ? <video src={`${src}#t=0.1`} muted preload="metadata" /> : <img src={src} alt={item.filename} loading="lazy" />}
      {!mini && <span className="thumb-kind"><Icon name={item.kind === 'audio' ? 'audio' : isMotion(item) ? 'film' : 'image'} size={12} />{item.kind}</span>}
    </button>
  )
}
