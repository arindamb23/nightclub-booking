import { useCallback, useEffect, useState } from 'react'
import Icon from '../components/Icon.jsx'
import { PageHeader, Spinner } from '../components/Common.jsx'
import { api } from '../api.js'
import { useMessages } from '../context/MessageContext.jsx'
import { useSystem } from '../context/SystemContext.jsx'
import { formatBytes } from '../utils/format.js'

const FIELDS = [
  ['COMFYUI_HOST', 'comfyui_host'], ['COMFYUI_DIR', 'comfyui_dir'], ['COMFYUI_PYTHON', 'comfyui_python'],
  ['COMFYUI_EXTRA_ARGS', 'comfyui_extra_args'], ['MODELS_DIR', 'models_dir'], ['MAX_PARALLEL_DOWNLOADS', 'max_parallel_downloads'],
  ['AUTO_DOWNLOAD_MODELS', 'auto_download_models'], ['HF_TOKEN', 'hf_token'], ['CIVITAI_TOKEN', 'civitai_token'],
]

export default function Settings() {
  const msg = useMessages()
  const { system, refresh } = useSystem()
  const [s, setS] = useState(null)
  const [form, setForm] = useState({})
  const [busy, setBusy] = useState('')

  const load = useCallback(async () => {
    try {
      const data = await api.get('/api/settings')
      setS(data.settings)
      const f = {}
      FIELDS.forEach(([envKey, key]) => { f[envKey] = String(data.settings[key] ?? '') })
      f.MODELS_DIR = data.settings.models_dir_custom ? data.settings.models_dir : ''
      setForm(f)
    } catch (e) { msg.showError(e) }
  }, [msg])
  useEffect(() => { load() }, [load])

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.type === 'checkbox' ? String(e.target.checked) : e.target.value }))

  const save = async () => {
    setBusy('save')
    try {
      await api.put('/api/settings', { values: form })
      await load()
      refresh()
      msg.showSuccess('Settings were saved to .env.', { title: 'Settings saved' })
    } catch (e) { msg.showError(e) } finally { setBusy('') }
  }
  const startComfy = async () => {
    setBusy('start')
    try {
      const r = await api.post('/api/comfyui/start')
      msg.showInfo(r.message, { title: 'ComfyUI' })
      setTimeout(refresh, 3000)
    } catch (e) { msg.showError(e) } finally { setBusy('') }
  }
  const sync = async () => {
    const ok = await msg.showConfirm('Read every node (including custom nodes) from the running ComfyUI and regenerate the typed Python node classes?\n\nRe-import workflows afterwards to use the new node definitions.', { confirmText: 'Sync nodes' })
    if (!ok) return
    setBusy('sync')
    try {
      const r = await api.post('/api/comfyui/sync-nodes')
      msg.showSuccess(`Synced ${r.nodes} node types and generated ${r.generated} Python classes.`, { title: 'Nodes synced' })
      refresh()
    } catch (e) { msg.showError(e) } finally { setBusy('') }
  }

  const comfy = system?.comfyui
  if (!s) return <div className="row muted"><Spinner />Loading settings…</div>

  return (
    <>
      <PageHeader
        title="Settings"
        subtitle="Stored in the .env file next to Start-all.bat. Ports can only be changed in .env (restart with Stop-all.bat / Start-all.bat afterwards)."
        actions={<button className="btn btn-primary" onClick={save} disabled={busy === 'save'}>{busy === 'save' ? <Spinner /> : <Icon name="save" />}Save settings</button>}
      />
      <div className="grid-2">
        <div className="card">
          <div className="card-head"><h3>ComfyUI</h3>
            <span className={`badge ${comfy?.reachable ? 'badge-success' : 'badge-danger'}`}><span className="badge-dot" />{comfy?.reachable ? 'Connected' : comfy?.starting ? 'Starting' : 'Offline'}</span>
          </div>
          <div className="card-body stack">
            <dl className="kv">
              <dt>Server</dt><dd className="mono">{s.comfyui_url}</dd>
              <dt>Installed</dt><dd>{comfy?.installed ? 'Yes' : 'No — run Setup.bat'}</dd>
              <dt>Version</dt><dd>{comfy?.version || '—'}</dd>
              <dt>GPU</dt><dd>{comfy?.devices?.length ? comfy.devices.map((d) => `${d.name}${d.vram_total ? ` (${formatBytes(d.vram_total)})` : ''}`).join(', ') : '—'}</dd>
              <dt>Node catalog</dt><dd>{comfy?.catalog_nodes ? `${comfy.catalog_nodes} node types` : 'Not synced yet'}</dd>
            </dl>
            <div className="row row-wrap">
              <button className="btn" onClick={startComfy} disabled={!comfy?.installed || comfy?.reachable || busy === 'start'}><Icon name="play" size={13} />Start ComfyUI</button>
              <button className="btn" onClick={sync} disabled={!comfy?.reachable || busy === 'sync'}>{busy === 'sync' ? <Spinner /> : <Icon name="refresh" />}Sync nodes from ComfyUI</button>
              <button className="btn btn-ghost" onClick={refresh}><Icon name="refresh" />Re-check</button>
            </div>
            <div className="form-grid">
              <div className="field"><label htmlFor="s-host">ComfyUI host</label><input id="s-host" className="input input-mono" value={form.COMFYUI_HOST} onChange={set('COMFYUI_HOST')} /><span className="hint">Port {s.comfyui_port} comes from .env (COMFYUI_PORT).</span></div>
              <div className="field"><label htmlFor="s-args">Extra start arguments</label><input id="s-args" className="input input-mono" placeholder="--lowvram" value={form.COMFYUI_EXTRA_ARGS} onChange={set('COMFYUI_EXTRA_ARGS')} /></div>
            </div>
            <div className="field"><label htmlFor="s-dir">ComfyUI folder</label><input id="s-dir" className="input input-mono" value={form.COMFYUI_DIR} onChange={set('COMFYUI_DIR')} /></div>
            <div className="field"><label htmlFor="s-py">ComfyUI Python</label><input id="s-py" className="input input-mono" value={form.COMFYUI_PYTHON} onChange={set('COMFYUI_PYTHON')} /></div>
          </div>
        </div>

        <div className="stack">
          <div className="card">
            <div className="card-head"><h3>Models &amp; downloads</h3></div>
            <div className="card-body stack">
              <div className="field">
                <label htmlFor="s-models">Models folder</label>
                <input id="s-models" className="input input-mono" placeholder="Empty = the models folder inside ComfyUI" value={form.MODELS_DIR} onChange={set('MODELS_DIR')} />
                <span className="hint">Now: <span className="mono">{s.models_dir}</span>. A custom folder is registered with ComfyUI through extra_model_paths.yaml.</span>
              </div>
              <div className="form-grid">
                <div className="field"><label htmlFor="s-par">Downloads at the same time</label>
                  <select id="s-par" className="select" value={form.MAX_PARALLEL_DOWNLOADS} onChange={set('MAX_PARALLEL_DOWNLOADS')}>{[1, 2, 3, 4].map((n) => <option key={n} value={n}>{n === 1 ? '1 — one by one (recommended)' : n}</option>)}</select>
                  <span className="hint">Big models download most reliably one at a time; the others wait in the queue.</span>
                </div>
                <div className="field"><span className="label">Wizard</span>
                  <label className="checkbox" style={{ height: 36 }}><input type="checkbox" checked={form.AUTO_DOWNLOAD_MODELS === 'true'} onChange={set('AUTO_DOWNLOAD_MODELS')} />Auto-download missing models</label>
                </div>
              </div>
            </div>
          </div>
          <div className="card">
            <div className="card-head"><h3>Access tokens</h3><Icon name="key" /></div>
            <div className="card-body stack">
              <div className="field"><label htmlFor="s-hf">Hugging Face token</label><input id="s-hf" className="input input-mono" placeholder="hf_…" value={form.HF_TOKEN} onChange={set('HF_TOKEN')} /><span className="hint">Needed for gated models (e.g. FLUX dev). Sent only to huggingface.co.</span></div>
              <div className="field"><label htmlFor="s-cv">Civitai API key</label><input id="s-cv" className="input input-mono" value={form.CIVITAI_TOKEN} onChange={set('CIVITAI_TOKEN')} /><span className="hint">Sent only to civitai.com.</span></div>
            </div>
          </div>
          <div className="card">
            <div className="card-head"><h3>Application</h3></div>
            <div className="card-body">
              <dl className="kv">
                <dt>Version</dt><dd>v{__APP_VERSION__}</dd>
                <dt>Frontend port</dt><dd>{s.frontend_port}</dd>
                <dt>Backend port</dt><dd>{s.backend_port}</dd>
                <dt>Data folder</dt><dd className="mono">{s.data_dir}</dd>
              </dl>
            </div>
          </div>
        </div>
      </div>
    </>
  )
}
