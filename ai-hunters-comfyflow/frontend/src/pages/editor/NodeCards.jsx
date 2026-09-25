import { memo } from 'react'
import { Handle, Position } from '@xyflow/react'
import Icon from '../../components/Icon.jsx'
import { mediaInfo } from '../../components/FieldControl.jsx'
import { ROLE, OUTPUT_ICON } from './theme.js'

function ModelBadge({ models }) {
  if (!models?.length) return null
  const missing = models.filter((m) => m.status !== 'ready').length
  return missing
    ? <span className="nbadge nbadge-warn" title={`${missing} model(s) not downloaded`}><Icon name="alert" size={11} />{missing} model{missing > 1 ? 's' : ''}</span>
    : <span className="nbadge nbadge-ok" title="Models ready"><Icon name="check" size={11} />models</span>
}

function MediaStrip({ kind, src, name, onPreview }) {
  return (
    <button type="button" className="nmedia nodrag" onClick={(e) => { e.stopPropagation(); onPreview() }} title={name} disabled={!src}>
      {kind === 'image' && src ? <img src={src} alt="" draggable={false} /> : (
        <span className={`nmedia-icon nmedia-${kind}`}><Icon name={kind === 'video' ? 'film' : kind === 'audio' ? 'audio' : 'image'} size={26} /></span>
      )}
      {src && <span className="nmedia-play"><Icon name={kind === 'image' ? 'eye' : 'play'} size={13} /></span>}
      <span className="nmedia-name">{name}</span>
    </button>
  )
}

export const WorkflowNode = memo(({ data, selected }) => {
  const { node, values, onPreview } = data
  const role = ROLE[node.role] || ROLE.generate
  const uploadField = node.fields.find((f) => f.control.startsWith('upload_'))
  const media = uploadField ? mediaInfo(values[uploadField.name] ?? uploadField.value, node.preview) : null
  const result = node.role === 'output' ? node.results?.[0] : null
  const runtime = node.fields.filter((f) => data.runtime(node.id, f)).length
  const dirty = Object.keys(values || {}).length > 0
  return (
    <div className={`wnode ${selected ? 'selected' : ''} ${node.known ? '' : 'unknown'}`} style={{ '--role': role.color, '--role-soft': role.soft }}>
      <Handle type="target" position={Position.Left} className="whandle" />
      <div className="wnode-head">
        <span className="wnode-icon"><Icon name={node.icon || role.icon} size={16} /></span>
        <div className="wnode-titles">
          <div className="wnode-title" title={node.title}>{node.title}{dirty && <span className="wnode-dirty" title="Unsaved changes">●</span>}</div>
          <div className="wnode-sub">{role.label}{node.title !== node.class_type ? ` · ${node.class_type}` : ''}</div>
        </div>
      </div>
      {data.summary && <div className="wnode-summary" title={data.summary}>{data.summary}</div>}
      {media && (
        <MediaStrip kind={uploadField.control.replace('upload_', '')} src={media.src} name={media.name}
          onPreview={() => onPreview([{ kind: uploadField.control.replace('upload_', ''), filename: media.name, src: media.src }], 0)} />
      )}
      {result && (
        <MediaStrip kind={result.kind === 'animation' ? 'video' : result.kind} src={result.kind === 'image' || result.kind === 'animation' ? result.url : result.url}
          name={`Last result · ${result.filename}`}
          onPreview={() => onPreview(node.results.map((r) => ({ kind: r.kind, filename: r.filename, runId: r.run_id })), 0)} />
      )}
      <div className="wnode-badges">
        {runtime > 0 && <span className="nbadge nbadge-rt" title="Fields asked on the Run screen"><Icon name="zap" size={11} />{runtime} run-time</span>}
        {node.role === 'output' && node.output && <span className="nbadge nbadge-out"><Icon name={OUTPUT_ICON[node.output]} size={11} />{node.output}</span>}
        <ModelBadge models={node.models} />
        {!node.known && <span className="nbadge nbadge-warn" title="This node type is not installed in ComfyUI">unknown node</span>}
      </div>
      <Handle type="source" position={Position.Right} className="whandle" />
    </div>
  )
})

export const ModelsGroupNode = memo(({ data, selected }) => {
  const missing = data.models.filter((m) => m.status !== 'ready').length
  return (
    <div className={`wnode wgroup ${selected ? 'selected' : ''}`} style={{ '--role': ROLE.model.color, '--role-soft': ROLE.model.soft }}>
      <div className="wnode-head">
        <span className="wnode-icon"><Icon name="layers" size={16} /></span>
        <div className="wnode-titles">
          <div className="wnode-title">Models ({data.count} {data.count === 1 ? 'node' : 'nodes'})</div>
          <div className="wnode-sub">{missing ? `${missing} to download` : 'All ready'} · click to see</div>
        </div>
      </div>
      <ul className="wgroup-list">
        {data.models.slice(0, 6).map((m) => (
          <li key={m.name}><span className={`dot ${m.status === 'ready' ? 'ok' : 'wait'}`} /><span className="truncate">{m.name}</span></li>
        ))}
        {data.models.length > 6 && <li className="muted">+{data.models.length - 6} more</li>}
      </ul>
      <Handle type="source" position={Position.Right} className="whandle" />
    </div>
  )
})
