import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import Logo from './Logo.jsx'
import Icon from './Icon.jsx'
import { useSystem } from '../context/SystemContext.jsx'

const TITLES = [
  ['/workflows/new', 'New workflow'],
  ['/workflows/', 'Workflow wizard'],
  ['/workflows', 'Workflows'],
  ['/models', 'Model manager'],
  ['/results', 'Results'],
  ['/settings', 'Settings'],
  ['/', 'Dashboard'],
]

export function ComfyStatusPill() {
  const { system, offline } = useSystem()
  const navigate = useNavigate()
  let dot = 'wait'
  let text = 'Checking…'
  if (offline) { dot = 'off'; text = 'Backend offline' } else if (system) {
    const c = system.comfyui
    if (c.reachable) { dot = 'ok'; text = 'ComfyUI connected' } else if (c.starting) { dot = 'wait'; text = 'ComfyUI starting…' } else { dot = 'off'; text = c.installed ? 'ComfyUI stopped' : 'ComfyUI not installed' }
  }
  return (
    <button className="status-pill" onClick={() => navigate('/settings')} aria-label={`${text}. Open settings`}>
      <span className={`dot ${dot}`} />{text}
    </button>
  )
}

export default function AppShell({ children }) {
  const { pathname } = useLocation()
  const { system } = useSystem()
  const title = TITLES.find(([p]) => (p === '/' ? pathname === '/' : pathname.startsWith(p)))?.[1] || ''
  return (
    <div className="shell">
      <aside className="sidebar">
        <Logo />
        <nav className="nav" aria-label="Main">
          <NavLink to="/workflows/new" className="nav-cta"><Icon name="plus" />New workflow</NavLink>
          <div className="nav-label">Workspace</div>
          <NavLink to="/" end><Icon name="home" />Dashboard</NavLink>
          <NavLink to="/workflows" end><Icon name="workflow" />Workflows</NavLink>
          <NavLink to="/models"><Icon name="box" />Models</NavLink>
          <NavLink to="/results"><Icon name="image" />Results</NavLink>
          <div className="nav-label">System</div>
          <NavLink to="/settings"><Icon name="settings" />Settings</NavLink>
        </nav>
        <div className="sidebar-foot">
          <div>AI Hunters ComfyFlow</div>
          <div>v{__APP_VERSION__}{system ? ` · API :${system.backend_port}` : ''}</div>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <span className="topbar-title">{title}</span>
          <span className="topbar-spacer" />
          <ComfyStatusPill />
          <span className="version-pill">v{__APP_VERSION__}</span>
        </header>
        <main className="content">{children}</main>
      </div>
    </div>
  )
}
