import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import Icon from '../components/Icon.jsx'
import { ModelStatus, PageHeader, RunStatus, Spinner } from '../components/Common.jsx'
import RunProgress, { useRunTracker } from '../components/RunProgress.jsx'
import MissingModelsModal from '../components/MissingModelsModal.jsx'
import UploadModal from '../components/UploadModal.jsx'
import { Thumb, outputsToItems, usePreview } from '../components/PreviewModals.jsx'
import { api } from '../api.js'
import { useMessages } from '../context/MessageContext.jsx'
import { useEvent } from '../context/EventsContext.jsx'
import { useSystem } from '../context/SystemContext.jsx'
import { applyDownloadEvent } from './Models.jsx'
import { formatDate } from '../utils/format.js'

const TASKS = [
  { id: 'text_to_image', label: 'Text to Image', icon: 'image', hint: 'Describe a picture' },
  { id: 'text_to_video', label: 'Text to Video', icon: 'film', hint: 'Describe a video clip' },
  { id: 'image_to_video', label: 'Image to Video', icon: 'film', hint: 'Animate a picture with a prompt' },
  { id: 'image_edit', label: 'Image Edit', icon: 'edit', hint: 'Change a picture with an instruction' },
]
const MAX_SEED = 2 ** 50
const randomSeed = () => Math.floor(Math.random() * MAX_SEED)

function initialValues(t) {
  const v = {}
  for (const p of t.params) {
    if (p.kind === 'seed') v[p.name] = p.default ?? randomSeed()
    else if (p.kind === 'image' || p.kind === 'video') v[p.name] = p.required ? { sample: 'girl.png' } : null
    else v[p.name] = p.default ?? ''
  }
  return v
}

function mediaUrl(value) {
  if (!value) return null
  if (value.upload) return `/api/uploads/${encodeURIComponent(value.upload)}`
  if (value.sample) return `/api/templates/sample-images/${encodeURIComponent(value.sample)}`
  return null
}

function ImageField({ param, value, onChange, samples }) {
  const [open, setOpen] = useState(false)
  const url = mediaUrl(value)
  return (
    <div className="field">
      <span className="label">{param.label}{!param.required && !/optional/i.test(param.label) && <span className="muted"> · optional</span>}</span>
      <div className="image-drop">
        {url ? <img src={url} alt={param.label} /> : <div className="image-drop-empty"><Icon name="image" size={26} /></div>}
        <div className="stack" style={{ gap: 8, flex: 1, minWidth: 0 }}>
          <div className="small truncate">{value?.original || value?.sample || (value?.upload ?? 'No image selected')}</div>
          <div className="row row-wrap">
            <button type="button" className="btn btn-sm" onClick={() => setOpen(true)}><Icon name="upload" size={15} />Upload image…</button>
            {samples.map((s) => (
              <button type="button" key={s} className={`btn btn-sm btn-ghost ${value?.sample === s ? 'selected' : ''}`} onClick={() => onChange({ sample: s })}>
                Sample: {s.replace(/\.\w+$/, '')}
              </button>
            ))}
            {!param.required && value && <button type="button" className="btn btn-sm btn-ghost" onClick={() => onChange(null)}>Remove</button>}
          </div>
        </div>
      </div>
      {open && (
        <UploadModal kind="image" title={`Upload ${param.label.toLowerCase()}`} onClose={() => setOpen(false)}
          onUploaded={(res) => { setOpen(false); onChange({ upload: res.filename, original: res.original }) }} />
      )}
    </div>
  )
}

function ParamInput({ p, value, onChange, modelNames }) {
  const id = `g-${p.name}`
  if (p.kind === 'bool') {
    return <label className="checkbox" style={{ height: 36 }}><input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} />{p.label}</label>
  }
  let control
  if (p.choices?.length) {
    control = <select id={id} className="select" value={value ?? ''} onChange={(e) => onChange(e.target.value)}>{p.choices.map((c) => <option key={c}>{c}</option>)}</select>
  } else if (p.kind === 'int' || p.kind === 'float') {
    control = <input id={id} className="input" type="number" step={p.kind === 'float' ? 'any' : 1} value={value ?? ''} onChange={(e) => onChange(e.target.value === '' ? '' : Number(e.target.value))} />
  } else if (p.kind === 'model') {
    control = (
      <>
        <input id={id} className="input input-mono" list={`${id}-list`} value={value ?? ''} onChange={(e) => onChange(e.target.value)} />
        <datalist id={`${id}-list`}>{modelNames.map((m) => <option key={m} value={m} />)}</datalist>
      </>
    )
  } else {
    control = <input id={id} className="input" value={value ?? ''} onChange={(e) => onChange(e.target.value)} />
  }
  return <div className="field"><label htmlFor={id}>{p.label}</label>{control}</div>
}

export default function Generate() {
  const msg = useMessages()
  const openPreview = usePreview()
  const { system, refresh } = useSystem()
  const [params, setParams] = useSearchParams()
  const [templates, setTemplates] = useState(null)
  const [samples, setSamples] = useState([])
  const [modelNames, setModelNames] = useState([])
  const [values, setValues] = useState({})
  const [seedRandom, setSeedRandom] = useState(true)
  const [models, setModels] = useState(null)
  const [checking, setChecking] = useState(false)
  const [starting, setStarting] = useState(false)
  const [missing, setMissing] = useState(null)
  const [recent, setRecent] = useState([])
  const uploadRef = useRef(null)

  const task = params.get('task') || 'text_to_image'
  const list = useMemo(() => (templates || []).filter((t) => t.task === task), [templates, task])
  const templateId = params.get('template') && list.some((t) => t.id === params.get('template')) ? params.get('template') : list[0]?.id
  const template = list.find((t) => t.id === templateId)

  const loadTemplates = useCallback(async () => {
    try {
      const [t, s, m] = await Promise.all([
        api.get('/api/templates'),
        api.get('/api/templates/sample-images'),
        api.get('/api/models'),
      ])
      setTemplates(t.templates)
      setSamples(s.images)
      setModelNames(m.models.map((x) => x.name))
    } catch (e) {
      msg.showError(e)
      setTemplates([])
    }
  }, [msg])
  useEffect(() => { loadTemplates() }, [loadTemplates])

  const loadRecent = useCallback(async () => {
    if (!templateId) return setRecent([])
    try { setRecent((await api.get(`/api/runs?template_id=${encodeURIComponent(templateId)}`)).runs.slice(0, 8)) } catch { setRecent([]) }
  }, [templateId])

  // reset the form when the template changes
  useEffect(() => {
    if (template) setValues(initialValues(template))
    loadRecent()
  }, [templateId]) // eslint-disable-line react-hooks/exhaustive-deps

  // which models does this template need (depends on model inputs such as the checkpoint)
  const modelKey = template ? JSON.stringify(template.params.filter((p) => p.kind === 'model').map((p) => values[p.name])) : ''
  const checkModels = useCallback(async () => {
    if (!template) return null
    setChecking(true)
    try {
      const res = await api.post(`/api/templates/${template.id}/models`, { values })
      setModels(res.models)
      return res.models
    } catch (e) {
      setModels([])
      return null
    } finally {
      setChecking(false)
    }
  }, [template?.id, modelKey]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { const t = setTimeout(checkModels, 250); return () => clearTimeout(t) }, [checkModels])
  useEvent('download', (ev) => {
    setModels((r) => (r ? applyDownloadEvent(r, ev) : r))
    if (ev.status === 'done' || ev.status === 'error') checkModels()
  })

  const { run, track, active } = useRunTracker((r) => {
    loadRecent()
    checkModels()
    if (r.status === 'succeeded') {
      const items = outputsToItems(r)
      if (items.length) openPreview(items, 0)
      else msg.showWarning(r.error || 'The run finished without an image or video.', { title: 'No previewable output' })
    } else if (r.status === 'failed' && r.error_code === 'models_missing') {
      setMissing({ models: r.failed_models, reason: 'These models could not be downloaded.' })
    } else if (r.status === 'failed') {
      msg.showError(r.error || 'Generation failed.', { title: 'Generation failed', details: r.error_details })
    } else if (r.status === 'cancelled') {
      msg.showInfo('Generation was cancelled.')
    }
  })

  const setValue = (name, v) => setValues((s) => ({ ...s, [name]: v }))
  const selectTask = (id) => setParams({ task: id })
  const selectTemplate = (id) => setParams({ task, template: id })

  const generate = async () => {
    if (!template) return
    for (const p of template.params) {
      const v = values[p.name]
      if (p.required && (p.kind === 'prompt') && !String(v || '').trim()) return msg.showWarning(`Please write the ${p.label.toLowerCase()} first.`)
      if (p.required && (p.kind === 'image' || p.kind === 'video') && !v) return msg.showWarning(`Please choose the ${p.label.toLowerCase()}.`)
    }
    const send = { ...values }
    const seedParam = template.params.find((p) => p.kind === 'seed')
    if (seedParam && seedRandom) {
      send[seedParam.name] = randomSeed()
      setValue(seedParam.name, send[seedParam.name])
    }
    setStarting(true)
    try {
      const rows = await checkModels()
      const need = (rows || []).filter((m) => m.status === 'no_url' || m.status === 'error')
        .map((m) => ({ name: m.name, category: m.category, url: m.url, status: m.status, error: m.job?.error || '', used_by: m.used_by }))
      if (need.length) {
        setMissing({ models: need })
        return
      }
      const r = await api.post(`/api/templates/${template.id}/generate`, { values: send })
      track(r)
    } catch (e) {
      if (e.code === 'models_missing') setMissing({ models: e.data.models })
      else msg.showError(e, { title: 'Cannot start' })
    } finally {
      setStarting(false)
    }
  }

  const cancel = async () => {
    try { await api.post(`/api/runs/${run.id}/cancel`) } catch (e) { msg.showError(e) }
  }
  const startComfy = async () => {
    try { const r = await api.post('/api/comfyui/start'); msg.showInfo(r.message, { title: 'ComfyUI' }); setTimeout(refresh, 3000) } catch (e) { msg.showError(e) }
  }
  const uploadTemplate = async (file) => {
    if (!file) return
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await api.upload('/api/templates/upload', fd)
      await loadTemplates()
      const t = res.templates[0]
      setParams({ task: t.task, template: t.id })
      msg.showSuccess(`Added ${res.templates.length} template(s): ${res.templates.map((x) => x.name).join(', ')}.\n\nTask: ${t.task_label}. Its models are detected automatically.`, { title: 'Template added' })
    } catch (e) {
      msg.showError(e, { title: 'Template not added' })
    } finally {
      if (uploadRef.current) uploadRef.current.value = ''
    }
  }
  const deleteTemplate = async () => {
    const ok = await msg.showConfirm(`Delete the template “${template.name}”? The .py file is removed from data\\templates.`, { confirmText: 'Delete' })
    if (!ok) return
    try { await api.del(`/api/templates/${encodeURIComponent(template.id)}`); await loadTemplates(); setParams({ task }) } catch (e) { msg.showError(e) }
  }
  const downloadMissing = async () => {
    try {
      const { started } = await api.post(`/api/templates/${template.id}/models/download-missing`, { values })
      if (!started.length) msg.showInfo('Nothing to download: models without a URL are asked for when you press Generate.')
      checkModels()
    } catch (e) { msg.showError(e) }
  }

  const comfy = system?.comfyui
  const main = template?.params.filter((p) => p.group === 'main') || []
  const advanced = template?.params.filter((p) => p.group === 'advanced') || []
  const ready = models?.filter((m) => m.status === 'ready').length ?? 0

  return (
    <>
      <PageHeader
        title="Generate"
        subtitle="Create images and videos from a prompt or a picture. Each generator is a Python template; its models are detected and downloaded automatically."
        actions={(
          <>
            <button className="btn" onClick={() => uploadRef.current?.click()}><Icon name="upload" />Add template (.py)</button>
            <input ref={uploadRef} type="file" hidden accept=".py,text/x-python" onChange={(e) => uploadTemplate(e.target.files?.[0])} />
          </>
        )}
      />

      <div className="task-tabs" role="tablist">
        {TASKS.map((t) => {
          const n = (templates || []).filter((x) => x.task === t.id).length
          return (
            <button key={t.id} role="tab" aria-selected={task === t.id} className={`task-tab ${task === t.id ? 'active' : ''}`} onClick={() => selectTask(t.id)}>
              <span className="task-tab-icon"><Icon name={t.icon} size={18} /></span>
              <span className="task-tab-text"><b>{t.label}</b><span>{t.hint}</span></span>
              <span className="badge">{n}</span>
            </button>
          )
        })}
      </div>

      {comfy && !comfy.reachable && (
        <div className="callout callout-warning mt-16">
          <Icon name="alert" />
          <div style={{ flex: 1 }}><b>ComfyUI is not running.</b> {comfy.installed ? 'Start it here or with Start-all.bat.' : 'Run Setup.bat to install it.'}</div>
          {comfy.installed && <button className="btn btn-sm" onClick={startComfy}><Icon name="play" size={13} />Start ComfyUI</button>}
        </div>
      )}

      {!templates ? <div className="row muted mt-16"><Spinner />Loading templates…</div> : !template ? (
        <div className="card card-pad mt-16 muted">No template for this task yet. Use “Add template (.py)” to add one.</div>
      ) : (
        <div className="generate-grid mt-16">
          <div className="card">
            <div className="card-head">
              <div style={{ minWidth: 0 }}>
                <h3>{template.name}</h3>
                <div className="small muted">{template.description}</div>
              </div>
              {template.origin === 'user' && <button className="btn btn-ghost icon-btn btn-danger" onClick={deleteTemplate} aria-label="Delete template"><Icon name="trash" size={16} /></button>}
            </div>
            <div className="card-body stack">
              {list.length > 1 && (
                <div className="field">
                  <label htmlFor="g-template">Template</label>
                  <select id="g-template" className="select" value={template.id} onChange={(e) => selectTemplate(e.target.value)}>
                    {list.map((t) => <option key={t.id} value={t.id}>{t.name}{t.origin === 'user' ? ' (yours)' : ''}</option>)}
                  </select>
                </div>
              )}
              {main.filter((p) => p.kind === 'image' || p.kind === 'video').map((p) => (
                <ImageField key={p.name} param={p} value={values[p.name]} onChange={(v) => setValue(p.name, v)} samples={samples} />
              ))}
              {main.filter((p) => p.kind === 'prompt' || p.kind === 'negative').map((p) => (
                <div className="field" key={p.name}>
                  <label htmlFor={`g-${p.name}`}>{p.label}</label>
                  <textarea id={`g-${p.name}`} className="textarea" rows={p.kind === 'prompt' ? 4 : 2}
                    placeholder={p.kind === 'prompt' ? (task.includes('video') ? 'e.g. a red fox running through fresh snow, slow motion, cinematic' : 'e.g. a cozy cabin in a snowy forest at dusk, warm window light') : 'Things to avoid, e.g. blurry, distorted'}
                    value={values[p.name] ?? ''} onChange={(e) => setValue(p.name, e.target.value)} />
                </div>
              ))}
              {main.filter((p) => p.kind === 'seed').map((p) => (
                <div className="field" key={p.name}>
                  <label htmlFor={`g-${p.name}`}>{p.label}</label>
                  <div className="row">
                    <input id={`g-${p.name}`} className="input" type="number" min={0} value={values[p.name] ?? ''} disabled={seedRandom}
                      onChange={(e) => setValue(p.name, e.target.value === '' ? '' : Number(e.target.value))} style={{ maxWidth: 260 }} />
                    <label className="checkbox small"><input type="checkbox" checked={seedRandom} onChange={(e) => setSeedRandom(e.target.checked)} />New random seed each time</label>
                  </div>
                </div>
              ))}
              {advanced.length > 0 && (
                <details className="advanced">
                  <summary>Advanced settings <span className="muted small">({advanced.length})</span></summary>
                  <div className="form-grid mt-16">
                    {advanced.map((p) => <ParamInput key={p.name} p={p} value={values[p.name]} onChange={(v) => setValue(p.name, v)} modelNames={modelNames} />)}
                  </div>
                </details>
              )}
            </div>
            <div className="wizard-foot">
              <span className="small muted mono truncate" title={template.path}>{template.file} · {template.function}()</span>
              <div className="row">
                {active && <button className="btn btn-danger" onClick={cancel}><Icon name="stop" size={13} />Cancel</button>}
                <button className="btn btn-primary btn-lg" onClick={generate} disabled={starting || active || !comfy?.reachable}>
                  {starting || active ? <Spinner /> : <Icon name="sparkle" size={16} />}
                  {run?.status === 'preparing' ? 'Downloading models…' : active ? 'Generating…' : 'Generate'}
                </button>
              </div>
            </div>
          </div>

          <div className="stack">
            <div className="card">
              <div className="card-head">
                <h3>Models</h3>
                <span className={`badge ${models && ready === models.length ? 'badge-success' : 'badge-warning'}`}>
                  {checking && !models ? '…' : `${ready} / ${models?.length ?? 0} ready`}
                </span>
              </div>
              <div className="card-body stack" style={{ gap: 12 }}>
                {!models ? <div className="row muted"><Spinner />Detecting models…</div> : models.length === 0 ? <span className="muted small">No model files needed.</span> : models.map((m) => (
                  <div key={m.name} className="model-line">
                    <div style={{ minWidth: 0 }}>
                      <div className="small mono truncate" title={m.name}>{m.name}</div>
                      <div className="cell-sub">{m.category}</div>
                    </div>
                    <ModelStatus status={m.status} job={m.job} partial={m.partial} />
                  </div>
                ))}
                {models && ready < models.length && (
                  <>
                    <p className="small muted" style={{ margin: 0 }}>Missing models are downloaded automatically when you press Generate; you are asked for a URL or file path if one has no download link.</p>
                    <button className="btn btn-sm" onClick={downloadMissing}><Icon name="download" size={15} />Download now</button>
                  </>
                )}
              </div>
            </div>

            {run && run.template_id === template.id && <div className="card card-pad"><RunProgress run={run} title="Generation" onCancel={cancel} /></div>}

            <div className="card">
              <div className="card-head"><h3>Recent results</h3></div>
              <div className="card-body">
                {recent.flatMap(outputsToItems).length ? (
                  <div className="thumbs">
                    {recent.flatMap(outputsToItems).slice(0, 8).map((item, i, all) => <Thumb key={`${item.runId}-${item.filename}`} item={item} onClick={() => openPreview(all, i)} />)}
                  </div>
                ) : <span className="muted small">Your {task.includes('video') ? 'videos' : 'images'} from this template appear here.</span>}
                {recent.length > 0 && (
                  <div className="stack mt-16" style={{ gap: 6 }}>
                    {recent.slice(0, 4).map((r) => (
                      <div key={r.id} className="row between small"><RunStatus status={r.status} /><span className="muted">{formatDate(r.created_at)}</span></div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {missing && template && (
        <MissingModelsModal
          resolvePath={`/api/templates/${template.id}/models/resolve`}
          extraBody={{ values }}
          models={missing.models}
          reason={missing.reason}
          onClose={() => setMissing(null)}
          onSaved={() => { setMissing(null); checkModels().then(() => generate()) }}
        />
      )}
    </>
  )
}
