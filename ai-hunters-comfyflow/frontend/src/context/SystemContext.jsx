import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { api } from '../api.js'

const SystemContext = createContext(null)

export function SystemProvider({ children }) {
  const [system, setSystem] = useState(null)
  const [offline, setOffline] = useState(false)
  const refresh = useCallback(async () => {
    try {
      setSystem(await api.get('/api/system'))
      setOffline(false)
    } catch {
      setOffline(true)
    }
  }, [])
  useEffect(() => {
    refresh()
    const t = setInterval(refresh, 6000)
    return () => clearInterval(t)
  }, [refresh])
  return <SystemContext.Provider value={{ system, offline, refresh }}>{children}</SystemContext.Provider>
}

export const useSystem = () => useContext(SystemContext)
