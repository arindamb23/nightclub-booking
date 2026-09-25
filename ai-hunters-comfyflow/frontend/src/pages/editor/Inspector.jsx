import { Link } from 'react-router-dom'
import Icon from '../../components/Icon.jsx'
import FieldControl from '../../components/FieldControl.jsx'
import { ROLE, OUTPUT_ICON } from './theme.js'

function FieldRow({ node, field, value, cfg, onValue, onCfg }) {
  const id = `f-${node.id}-${field.name}`
  const runtime = cfg.runtime ?? field.runtime
  return (
    <div className={`frow ${runtime ? 'frow-rt' : ''}`}>
      <div className="frow-head">
        <label htmlFor={id} className="frow-label">{field.default_label}</label>
        <span className="frow-type">{field.control.replace('upload_', 'upload ')}</span>
      </div>
      <FieldControl id={id} field={field} value={value} onChange={onValue} preview={node.preview} />
      {field.tooltip && <div className="hint mt-8">{field.tooltip}</div>}
      <div className="frow-rtbar">
        <label className="checkbox small">
          <input type="checkbox" checked={!!runtime} onChange={(e) => onCfg({ runtime: e.target.checked })} />
          <Icon name="zap" size={12} />Run time
          {field.runtime_default && <span className="muted"> (default)</span>}
        </label>
        {runtime && (
          <input className="input input-sm" placeholder="Label on the Run screen" value={cfg.label ?? field.label}
            onChange={(e) => onCfg({ label: e.target.value })} aria-label="Label on the Run screen" />
        )}
      </div>
    </div>
  )
}

export default function Inspector({ node, group, graph, edits, cfgs, outputs, onValue, onCfg, onOutput, onSelect, onClose }) {
  if (group) {
    return (
      <aside className="inspector">
        <div className="insp-head" style={{ '--role': ROLE.model.color }}>
          <span className="wnode-icon"><Icon name="layers" size={16} /></span>
          <div style={{ flex: 1, minWidth: 0 }}><h3>Models</h3><div className="small muted">{group.count} loader nodes are folded in Simple view</div></div>
          <button className="btn btn-ghost icon-btn" onClick={onClose} aria-label="Close"><Icon name="x" /></button>
        </div>
        <div className="insp-body stack" style={{ gap: 10 }}>
          {group.nodes.map((n) => (
            <button key={n.id} className="insp-link" onClick={() => onSelect(n.id)}>
              <span className="truncate"><b>{n.title}</b><span className="muted small"> · {n.class_type}</span></span>
              {n.models.map((m) => <span key={m.name} className="small mono truncate"><span className={`dot ${m.status === 'ready' ? 'ok' : 'wait'}`} /> {m.name}</span>)}
            </button>
          ))}
          <Link className="btn btn-sm" to="/models"><Icon name="box" size={14} />Open Model manager</Link>
        </div>
      </aside>
    )
  }
  if (!node) {
    const rt = graph.nodes.flatMap((n) => n.fields.filter((f) => (cfgs[n.id]?.[f.name]?.runtime ?? f.runtime)).map((f) => ({ n, f })))
    const outs = graph.nodes.filter((n) => n.role === 'output')
    return (
      <aside className="inspector">
        <div className="insp-head"><span className="wnode-icon"><Icon name="sliders" size={16} /></span><div><h3>Workflow</h3><div className="small muted">Click a node to edit its settings</div></div></div>
        <div className="insp-body stack">
          <div>
            <div className="insp-section">Asked on the Run screen ({rt.length})</div>
            {rt.length ? rt.map(({ n, f }) => (
              <button key={`${n.id}-${f.name}`} className="insp-link" onClick={() => onSelect(n.id)}>
                <span className="truncate"><Icon name="zap" size={12} /> <b>{cfgs[n.id]?.[f.name]?.label || f.label}</b></span>
                {(cfgs[n.id]?.[f.name]?.label || f.label) !== n.title && <span className="small muted truncate">{n.title}</span>}
              </button>
            )) : <p className="small muted">Nothing yet — tick “Run time” on any field.</p>}
          </div>
          <div>
            <div className="insp-section">Expected output</div>
            {outs.map((n) => (
              <button key={n.id} className="insp-link" onClick={() => onSelect(n.id)}>
                <span><Icon name={OUTPUT_ICON[outputs[n.id] || n.output] || 'image'} size={13} /> <b>{outputs[n.id] || n.output}</b></span>
                <span className="small muted">{n.title}</span>
              </button>
            ))}
          </div>
          <p className="small muted">Uploads and prompts are run-time by default (config\controlmap.json). Save writes the values into workflow.py and keeps a backup.</p>
        </div>
      </aside>
    )
  }
  const role = ROLE[node.role] || ROLE.generate
  return (
    <aside className="inspector">
      <div className="insp-head" style={{ '--role': role.color }}>
        <span className="wnode-icon" style={{ background: role.soft, color: role.color }}><Icon name={node.icon || role.icon} size={16} /></span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <h3 className="truncate">{node.title}</h3>
          <div className="small muted truncate">{node.class_type} · node {node.id} · <span style={{ color: role.color }}>{role.label}</span></div>
        </div>
        <button className="btn btn-ghost icon-btn" onClick={onClose} aria-label="Close"><Icon name="x" /></button>
      </div>
      <div className="insp-body">
        {!node.known && <div className="callout callout-warning" style={{ marginBottom: 12 }}><Icon name="alert" /><div>ComfyUI does not know this node type. Install its custom node, then Settings → Sync nodes.</div></div>}
        {node.role === 'output' && (
          <div className="frow">
            <div className="frow-head"><span className="frow-label">Expected output</span></div>
            <div className="seg">
              {['image', 'video', 'audio'].map((t) => (
                <button key={t} type="button" className={`seg-btn ${(outputs[node.id] || node.output) === t ? 'active' : ''}`} onClick={() => onOutput(t)}>
                  <Icon name={OUTPUT_ICON[t]} size={14} />{t}
                </button>
              ))}
            </div>
          </div>
        )}
        {node.fields.length === 0 && <p className="small muted">This node has no settings of its own; it only passes data along.</p>}
        {node.fields.map((f) => (
          <FieldRow key={f.name} node={node} field={f}
            value={edits[f.name] !== undefined ? edits[f.name] : f.value}
            cfg={cfgs[f.name] || {}}
            onValue={(v) => onValue(f.name, v)}
            onCfg={(c) => onCfg(f.name, c)} />
        ))}
        {node.connections.length > 0 && (
          <div className="mt-16">
            <div className="insp-section">Connected inputs</div>
            {node.connections.map((c) => {
              const src = graph.nodes.find((n) => n.id === c.from)
              return (
                <button key={c.input} className="insp-link" onClick={() => onSelect(c.from)}>
                  <span className="small"><b>{c.input}</b> ←</span>
                  <span className="small muted truncate">{src ? src.title : `node ${c.from}`}</span>
                </button>
              )
            })}
          </div>
        )}
        {node.models.length > 0 && (
          <div className="mt-16">
            <div className="insp-section">Models</div>
            {node.models.map((m) => (
              <div key={m.name} className="row small" style={{ gap: 6, padding: '3px 0' }}><span className={`dot ${m.status === 'ready' ? 'ok' : 'wait'}`} /><span className="mono truncate">{m.name}</span><span className="muted">{m.status}</span></div>
            ))}
          </div>
        )}
      </div>
    </aside>
  )
}
