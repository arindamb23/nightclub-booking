import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import Icon from './Icon.jsx'

// Base modal: portal, backdrop, Esc to close, focus management, 3D pop-in animation.
export default function Modal({ title, icon, size = '', onClose, children, footer, dismissible = true, labelId }) {
  const ref = useRef(null)
  useEffect(() => {
    const prev = document.activeElement
    const node = ref.current
    const focusable = node?.querySelector('[data-autofocus]') || node?.querySelector('button, [href], input, select, textarea')
    focusable?.focus()
    const onKey = (e) => {
      if (e.key === 'Escape' && dismissible) {
        e.stopPropagation()
        onClose?.()
      }
    }
    document.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
      prev?.focus?.()
    }
  }, [dismissible, onClose])

  const autoId = useRef(`modal-${Math.random().toString(36).slice(2, 8)}`)
  const id = labelId || autoId.current
  return createPortal(
    <div className="modal-root">
      <div className="modal-backdrop" onClick={dismissible ? onClose : undefined} />
      <div className={`modal ${size ? `modal-${size}` : ''}`} role="dialog" aria-modal="true" aria-labelledby={id} ref={ref}>
        <div className="modal-head">
          {icon}
          <h2 id={id} className="truncate">{title}</h2>
          {dismissible && (
            <button className="btn btn-ghost icon-btn" onClick={onClose} aria-label="Close">
              <Icon name="x" />
            </button>
          )}
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>,
    document.body,
  )
}
