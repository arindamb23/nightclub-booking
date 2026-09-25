import { createContext, useContext, useEffect, useRef } from 'react'

// One EventSource for the whole app; components subscribe by event type.
const EventsContext = createContext(null)

export function EventsProvider({ children }) {
  const listeners = useRef(new Map())
  useEffect(() => {
    let es
    let retry
    const connect = () => {
      es = new EventSource('/api/events')
      es.onmessage = (e) => {
        let data
        try { data = JSON.parse(e.data) } catch { return }
        const set = listeners.current.get(data.type)
        set?.forEach((fn) => fn(data))
      }
      es.onerror = () => {
        es.close()
        retry = setTimeout(connect, 3000)
      }
    }
    connect()
    return () => { es?.close(); clearTimeout(retry) }
  }, [])

  const subscribe = (type, fn) => {
    if (!listeners.current.has(type)) listeners.current.set(type, new Set())
    listeners.current.get(type).add(fn)
    return () => listeners.current.get(type)?.delete(fn)
  }
  return <EventsContext.Provider value={subscribe}>{children}</EventsContext.Provider>
}

export function useEvent(type, handler) {
  const subscribe = useContext(EventsContext)
  const ref = useRef(handler)
  ref.current = handler
  useEffect(() => subscribe(type, (d) => ref.current(d)), [subscribe, type])
}
