import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import Modal from './Modal.jsx'
import Icon from './Icon.jsx'
import { fileUrl, formatBytes, zipUrl } from '../utils/format.js'

// items: [{ runId, filename, kind: 'image'|'video'|'animation', size }]
const isMotion = (item) => item.kind === 'video' || item.kind === 'animation'
function useKeyNav(count, index, setIndex) {
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

function DownloadButtons({ item, allRunId, count }) {
  return (
    <>
      {count > 1 && allRunId && (
        <a className="btn" href={zipUrl(allRunId)} download><Icon name="archive" />Download all</a>
      )}
      <a className="btn btn-primary" href={fileUrl(item.runId, item.filename, true)} download={item.filename} data-autofocus>
        <Icon name="download" />Download
      </a>
    </>
  )
}

export function ImagePreviewModal({ items, startIndex = 0, onClose }) {
  const [index, setIndex] = useState(startIndex)
  const [zoom, setZoom] = useState(0) // 0 = fit
  const [dims, setDims] = useState(null)
  const item = items[index]
  useKeyNav(items.length, index, setIndex)
  useEffect(() => { setDims(null) }, [index])
  const sameRun = items.every((i) => i.runId === items[0].runId) ? items[0].runId : null
  const zoomLabel = zoom === 0 ? 'Auto' : `${Math.round(zoom * 100)}%`
  const step = (dir) => setZoom((z) => {
    const cur = z || 1
    return Math.min(4, Math.max(0.1, +(cur * (dir > 0 ? 1.25 : 0.8)).toFixed(2)))
  })
  return (
    <Modal
      size="xl"
      title={item.filename}
      icon={<span className="msg-icon msg-info"><Icon name="image" size={20} /></span>}
      onClose={onClose}
      footer={(
        <>
          <div className="left">
            <div className="zoom-controls">
              <button className="btn icon-btn" onClick={() => step(-1)} aria-label="Zoom out"><Icon name="zoomOut" /></button>
              <span>{zoomLabel}</span>
              <button className="btn icon-btn" onClick={() => step(1)} aria-label="Zoom in"><Icon name="zoomIn" /></button>
              <button className="btn btn-sm" onClick={() => setZoom(0)}><Icon name="maximize" size={15} />Fit</button>
              <button className="btn btn-sm" onClick={() => setZoom(1)}>100%</button>
            </div>
          </div>
          <DownloadButtons item={item} allRunId={sameRun} count={items.length} />
        </>
      )}
    >
      <div className="preview-stage">
        <NavButtons count={items.length} setIndex={setIndex} />
        <img
          key={item.filename}
          src={fileUrl(item.runId, item.filename)}
          alt={item.filename}
          className={zoom === 0 ? 'fit' : ''}
          style={zoom && dims ? { width: dims.w * zoom, height: dims.h * zoom, maxWidth: 'none' } : undefined}
          onLoad={(e) => setDims({ w: e.target.naturalWidth, h: e.target.naturalHeight })}
        />
      </div>
      <div className="preview-meta mt-16">
        {items.length > 1 && <span><b>{index + 1}</b> / {items.length}</span>}
        {dims && <span><b>{dims.w} × {dims.h}</b> px</span>}
        <span><b>{formatBytes(item.size)}</b></span>
        {item.workflowName && <span>Workflow <b>{item.workflowName}</b></span>}
      </div>
    </Modal>
  )
}

export function VideoPreviewModal({ items, startIndex = 0, onClose }) {
  const [index, setIndex] = useState(startIndex)
  const [meta, setMeta] = useState(null)
  const item = items[index]
  useKeyNav(items.length, index, setIndex)
  useEffect(() => { setMeta(null) }, [index])
  const sameRun = items.every((i) => i.runId === items[0].runId) ? items[0].runId : null
  return (
    <Modal
      size="lg"
      title={item.filename}
      icon={<span className="msg-icon msg-confirm"><Icon name="film" size={20} /></span>}
      onClose={onClose}
      footer={(
        <>
          <button className="btn" onClick={onClose}>Close</button>
          <DownloadButtons item={item} allRunId={sameRun} count={items.length} />
        </>
      )}
    >
      <div className="preview-stage" style={{ background: '#1f1e1d' }}>
        <NavButtons count={items.length} setIndex={setIndex} />
        {item.kind === 'animation' ? (
          <img
            key={item.filename}
            src={fileUrl(item.runId, item.filename)}
            alt={item.filename}
            className="fit"
            onLoad={(e) => setMeta({ w: e.target.naturalWidth, h: e.target.naturalHeight })}
          />
        ) : (
          <video
            key={item.filename}
            src={fileUrl(item.runId, item.filename)}
            controls
            autoPlay
            loop
            playsInline
            onLoadedMetadata={(e) => setMeta({ w: e.target.videoWidth, h: e.target.videoHeight, d: e.target.duration })}
          />
        )}
      </div>
      <div className="preview-meta mt-16">
        {items.length > 1 && <span><b>{index + 1}</b> / {items.length}</span>}
        {meta && <span><b>{meta.w} × {meta.h}</b> px</span>}
        {meta && Number.isFinite(meta.d) && <span><b>{meta.d.toFixed(1)} s</b></span>}
        {item.kind === 'animation' && <span>Animated image</span>}
        <span><b>{formatBytes(item.size)}</b></span>
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
    const kind = isMotion(item) ? 'video' : 'image'
    const group = all.filter((i) => (isMotion(i) ? 'video' : 'image') === kind)
    setState({ kind, items: group, index: Math.max(0, group.indexOf(item)) })
  }, [])
  const value = useMemo(() => openPreview, [openPreview])
  return (
    <PreviewContext.Provider value={value}>
      {children}
      {state?.kind === 'image' && <ImagePreviewModal items={state.items} startIndex={state.index} onClose={() => setState(null)} />}
      {state?.kind === 'video' && <VideoPreviewModal items={state.items} startIndex={state.index} onClose={() => setState(null)} />}
    </PreviewContext.Provider>
  )
}

export const usePreview = () => useContext(PreviewContext)

export function outputsToItems(run) {
  return (run?.outputs || [])
    .filter((o) => o.kind === 'image' || isMotion(o))
    .map((o) => ({ ...o, runId: run.id, workflowName: run.workflow_name }))
}

export function Thumb({ item, onClick, mini = false }) {
  const src = fileUrl(item.runId, item.filename)
  return (
    <button className={mini ? 'thumb-mini' : 'thumb'} onClick={onClick} title={item.filename} type="button">
      {item.kind === 'video' ? <video src={`${src}#t=0.1`} muted preload="metadata" /> : <img src={src} alt={item.filename} loading="lazy" />}
      {!mini && (
        <span className="thumb-kind"><Icon name={isMotion(item) ? 'film' : 'image'} size={12} />{item.kind}</span>
      )}
    </button>
  )
}
