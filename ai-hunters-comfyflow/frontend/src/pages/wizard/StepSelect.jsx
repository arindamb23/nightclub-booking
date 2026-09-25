import { useRef, useState } from 'react'
import Icon from '../../components/Icon.jsx'
import CodeModal from '../../components/CodeModal.jsx'
import { Spinner } from '../../components/Common.jsx'
import { api } from '../../api.js'
import { useMessages } from '../../context/MessageContext.jsx'

const SAMPLE_PATH = 'samples/workflows/sd15_text2image.json'

export default function StepSelect({ workflow, onImported, onNext }) {
  const msg = useMessages()
  const fileRef = useRef(null)
  const [over, setOver] = useState(false)
  const [file, setFile] = useState(null)
  const [path, setPath] = useState('')
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [showCode, setShowCode] = useState(false)
  const [replace, setReplace] = useState(!workflow)

  const pick = (f) => {
    if (!f) return
    if (!/\.(json|py)$/i.test(f.name)) {
      msg.showWarning(`“${f.name}” is not a workflow file. Choose a ComfyUI .json export or a Python workflow .py script.`)
      return
    }
    setFile(f)
    setPath('')
    if (!name) setName(f.name.replace(/\.(json|py)$/i, ''))
  }

  const finish = async (wf) => {
    const lines = [wf.format === 'python'
      ? `Opened the Python workflow script (${wf.node_count} nodes).`
      : `Converted ${wf.node_count} nodes (${wf.format === 'ui' ? 'UI' : 'API'} format) to workflow.py.`]
    lines.push(`${wf.models_total} model file(s) detected, ${wf.models_ready} already on disk.`)
    if (wf.warnings?.length) {
      await msg.showWarning(lines.join('\n') + '\n\nThe converter reported some notes:', { title: 'Workflow imported with notes', details: wf.warnings })
    } else {
      await msg.showSuccess(lines.join('\n'), { title: 'Workflow imported', okText: 'Continue to models' })
    }
    onImported(wf)
  }

  const importNow = async () => {
    if (!file && !path.trim()) {
      msg.showWarning('Choose a workflow file, drop one on the box, or type the path of a .json file on this computer.')
      return
    }
    setBusy(true)
    try {
      let wf
      if (file) {
        const fd = new FormData()
        fd.append('file', file)
        if (name.trim()) fd.append('name', name.trim())
        wf = await api.upload('/api/workflows/upload', fd)
      } else {
        wf = await api.post('/api/workflows/import-path', { path: path.trim(), name: name.trim() || null })
      }
      await finish(wf)
    } catch (e) {
      msg.showError(e)
    } finally {
      setBusy(false)
    }
  }

  const useSample = () => {
    setFile(null)
    setPath(SAMPLE_PATH)
    setName('SD 1.5 Text to Image')
  }

  if (workflow && !replace) {
    return (
      <div className="card">
        <div className="card-body stack">
          <div className="summary">
            <div><div className="k">Source file</div><div className="v truncate">{workflow.source_filename}</div></div>
            <div><div className="k">Format</div><div className="v">{{ ui: 'ComfyUI graph (UI)', api: 'ComfyUI API', python: 'Python script' }[workflow.format] || workflow.format}</div></div>
            <div><div className="k">Nodes</div><div className="v">{workflow.node_count}</div></div>
            <div><div className="k">Models ready</div><div className="v">{workflow.models_ready} / {workflow.models_total}</div></div>
          </div>
          {workflow.warnings?.length > 0 && (
            <div className="callout callout-warning"><Icon name="alert" /><div>Conversion notes<ul>{workflow.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul></div></div>
          )}
        </div>
        <div className="wizard-foot">
          <div className="row">
            <button className="btn" onClick={() => setShowCode(true)}><Icon name="code" />View .py</button>
            <button className="btn btn-ghost" onClick={() => setReplace(true)}><Icon name="upload" />Import another file</button>
          </div>
          <button className="btn btn-primary" onClick={onNext}>Next: models<Icon name="chevronRight" /></button>
        </div>
        {showCode && <CodeModal workflow={workflow} onClose={() => setShowCode(false)} />}
      </div>
    )
  }

  return (
    <div className="card">
      <div className="card-body">
        <div
          className={`dropzone ${over ? 'over' : ''}`}
          role="button"
          tabIndex={0}
          onClick={() => fileRef.current?.click()}
          onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && fileRef.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setOver(true) }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); pick(e.dataTransfer.files?.[0]) }}
        >
          <div className="dropzone-icon"><Icon name="upload" size={26} /></div>
          {file ? (
            <>
              <h3>{file.name}</h3>
              <p className="muted">{(file.size / 1024).toFixed(1)} KB · click to choose a different file</p>
            </>
          ) : (
            <>
              <h3>Drop a workflow file here</h3>
              <p className="muted">or click to browse. ComfyUI <b>.json</b> exports (“Save” or “Export (API)”) are converted to Python; existing Python workflow <b>.py</b> scripts open as they are.</p>
            </>
          )}
          <input ref={fileRef} type="file" accept=".json,.py,application/json,text/x-python" hidden onChange={(e) => pick(e.target.files?.[0])} />
        </div>

        <div className="divider-text">or use a path on this computer</div>

        <div className="form-grid">
          <div className="field">
            <label htmlFor="wf-path">Workflow file path</label>
            <div className="row">
              <span className="muted"><Icon name="folder" /></span>
              <input id="wf-path" className="input input-mono" placeholder="C:\Users\you\Documents\ComfyUI\my_workflow.json  or  …\my_workflow.py" value={path}
                onChange={(e) => { setPath(e.target.value); setFile(null) }} />
            </div>
            <span className="hint">Paths relative to the ComfyFlow folder work too. More ready-made workflows: Workflows → Sample library. <button className="btn btn-ghost btn-sm" type="button" onClick={useSample}>Use the SD 1.5 sample</button></span>
          </div>
          <div className="field">
            <label htmlFor="wf-name">Workflow name</label>
            <input id="wf-name" className="input" placeholder="Defaults to the file name" value={name} onChange={(e) => setName(e.target.value)} />
            <span className="hint">Shown in the Workflows list. The generated script is saved as workflow.py.</span>
          </div>
        </div>
      </div>
      <div className="wizard-foot">
        <span className="muted small">Step 1 of 3</span>
        <div className="row">
          {workflow && <button className="btn" onClick={() => setReplace(false)}>Cancel</button>}
          <button className="btn btn-primary" onClick={importNow} disabled={busy}>
            {busy ? <Spinner /> : <Icon name="zap" />}Open workflow
          </button>
        </div>
      </div>
    </div>
  )
}
