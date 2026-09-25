import { useEffect, useState } from 'react'
import Modal from './Modal.jsx'
import Icon from './Icon.jsx'
import { api } from '../api.js'
import { useMessages } from '../context/MessageContext.jsx'
import { Spinner } from './Common.jsx'

export default function CodeModal({ workflow, onClose }) {
  const msg = useMessages()
  const [code, setCode] = useState(null)
  const [copied, setCopied] = useState(false)
  useEffect(() => {
    api.get(`/api/workflows/${workflow.id}/script`).then(setCode).catch((e) => { msg.showError(e); onClose() })
  }, [workflow.id, msg, onClose])
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      msg.showWarning('Copy is blocked by the browser. Select the code and press Ctrl+C instead.')
    }
  }
  const download = () => {
    const url = URL.createObjectURL(new Blob([code], { type: 'text/x-python' }))
    const a = document.createElement('a')
    a.href = url
    a.download = `${workflow.id}.py`
    a.click()
    URL.revokeObjectURL(url)
  }
  return (
    <Modal
      size="lg"
      title={`${workflow.name} · workflow.py`}
      icon={<span className="msg-icon msg-confirm"><Icon name="code" size={20} /></span>}
      onClose={onClose}
      footer={(
        <>
          <div className="left muted small">Auto-generated from {workflow.source_filename}</div>
          <button className="btn" onClick={copy} disabled={!code}><Icon name={copied ? 'check' : 'file'} />{copied ? 'Copied' : 'Copy'}</button>
          <button className="btn btn-primary" onClick={download} disabled={!code}><Icon name="download" />Download .py</button>
        </>
      )}
    >
      {code == null ? <div className="row muted"><Spinner />Loading…</div> : <pre className="code-view">{code}</pre>}
    </Modal>
  )
}
