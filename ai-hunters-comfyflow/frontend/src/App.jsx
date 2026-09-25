import { Route, Routes } from 'react-router-dom'
import AppShell from './components/AppShell.jsx'
import { MessageProvider } from './context/MessageContext.jsx'
import { EventsProvider } from './context/EventsContext.jsx'
import { SystemProvider } from './context/SystemContext.jsx'
import { PreviewProvider } from './components/PreviewModals.jsx'
import Dashboard from './pages/Dashboard.jsx'
import Generate from './pages/Generate.jsx'
import WorkflowEditor from './pages/editor/WorkflowEditor.jsx'
import Workflows from './pages/Workflows.jsx'
import Wizard from './pages/Wizard.jsx'
import Models from './pages/Models.jsx'
import Results from './pages/Results.jsx'
import Settings from './pages/Settings.jsx'
import { EmptyState } from './components/Common.jsx'

export default function App() {
  return (
    <MessageProvider>
      <EventsProvider>
        <SystemProvider>
          <PreviewProvider>
            <AppShell>
              <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/generate" element={<Generate />} />
                <Route path="/workflows" element={<Workflows />} />
                <Route path="/workflows/new" element={<Wizard />} />
                <Route path="/workflows/:id/wizard" element={<Wizard />} />
                <Route path="/workflows/:id/editor" element={<WorkflowEditor />} />
                <Route path="/models" element={<Models />} />
                <Route path="/results" element={<Results />} />
                <Route path="/settings" element={<Settings />} />
                <Route path="*" element={<EmptyState icon="alert" title="Page not found" text="Use the menu on the left." />} />
              </Routes>
            </AppShell>
          </PreviewProvider>
        </SystemProvider>
      </EventsProvider>
    </MessageProvider>
  )
}
