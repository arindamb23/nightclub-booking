import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import Modal from '../components/Modal.jsx'
import Icon from '../components/Icon.jsx'

// Every user-facing message in the app goes through this modal service:
// showInfo / showSuccess / showWarning / showError / showConfirm (returns a Promise<boolean>).
const MessageContext = createContext(null)

const KIND = {
  info: { icon: 'info', cls: 'msg-info', title: 'Information' },
  success: { icon: 'checkCircle', cls: 'msg-success', title: 'Done' },
  warning: { icon: 'alert', cls: 'msg-warning', title: 'Please check' },
  error: { icon: 'errorCircle', cls: 'msg-error', title: 'Something went wrong' },
  confirm: { icon: 'help', cls: 'msg-confirm', title: 'Please confirm' },
}

export function MessageProvider({ children }) {
  const [queue, setQueue] = useState([])
  const idRef = useRef(0)

  const push = useCallback((kind, message, opts = {}) => new Promise((resolve) => {
    idRef.current += 1
    setQueue((q) => [...q, { id: idRef.current, kind, message, resolve, ...opts }])
  }), [])

  const close = (item, value) => {
    item.resolve(value)
    setQueue((q) => q.filter((m) => m.id !== item.id))
  }

  const api = useRef(null)
  api.current = {
    showInfo: (m, o) => push('info', m, o),
    showSuccess: (m, o) => push('success', m, o),
    showWarning: (m, o) => push('warning', m, o),
    showError: (m, o = {}) => {
      if (m && typeof m === 'object' && 'message' in m) return push('error', m.message, { details: m.details, ...o })
      return push('error', String(m), o)
    },
    showConfirm: (m, o) => push('confirm', m, o),
  }

  // Route stray browser messages into modals too.
  useEffect(() => {
    const nativeAlert = window.alert
    window.alert = (m) => { api.current.showInfo(String(m)) }
    const onError = (e) => api.current.showError(e.message || 'Unexpected error in the page.')
    const onRejection = (e) => api.current.showError(e.reason?.message || String(e.reason || 'Unexpected error.'))
    window.addEventListener('error', onError)
    window.addEventListener('unhandledrejection', onRejection)
    return () => {
      window.alert = nativeAlert
      window.removeEventListener('error', onError)
      window.removeEventListener('unhandledrejection', onRejection)
    }
  }, [])

  const current = queue[0]
  const stable = useRef({
    showInfo: (...a) => api.current.showInfo(...a),
    showSuccess: (...a) => api.current.showSuccess(...a),
    showWarning: (...a) => api.current.showWarning(...a),
    showError: (...a) => api.current.showError(...a),
    showConfirm: (...a) => api.current.showConfirm(...a),
  }).current

  return (
    <MessageContext.Provider value={stable}>
      {children}
      {current && <MessageModal item={current} onClose={close} />}
    </MessageContext.Provider>
  )
}

function MessageModal({ item, onClose }) {
  const k = KIND[item.kind]
  const isConfirm = item.kind === 'confirm'
  const footer = isConfirm ? (
    <>
      <button className="btn" onClick={() => onClose(item, false)}>{item.cancelText || 'Cancel'}</button>
      <button className={`btn ${item.danger ? 'btn-primary' : 'btn-primary'}`} data-autofocus onClick={() => onClose(item, true)}>
        {item.confirmText || 'Confirm'}
      </button>
    </>
  ) : (
    <button className="btn btn-primary" data-autofocus onClick={() => onClose(item, true)}>{item.okText || 'OK'}</button>
  )
  return (
    <Modal
      title={item.title || k.title}
      icon={<span className={`msg-icon ${k.cls}`}><Icon name={k.icon} size={20} /></span>}
      onClose={() => onClose(item, false)}
      footer={footer}
    >
      <div className="msg-text">{item.message}</div>
      {item.details?.length > 0 && (
        <ul className="msg-details">
          {item.details.map((d, i) => <li key={i}>{d}</li>)}
        </ul>
      )}
    </Modal>
  )
}

export const useMessages = () => useContext(MessageContext)
