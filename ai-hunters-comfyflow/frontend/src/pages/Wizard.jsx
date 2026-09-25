import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import Icon from '../components/Icon.jsx'
import { PageHeader } from '../components/Common.jsx'
import { api } from '../api.js'
import { useMessages } from '../context/MessageContext.jsx'
import StepSelect from './wizard/StepSelect.jsx'
import StepModels from './wizard/StepModels.jsx'
import StepRun from './wizard/StepRun.jsx'

const STEPS = ['Select workflow', 'Models', 'Run & results']

function Stepper({ step, reached, onGo }) {
  return (
    <div className="stepper" role="list">
      {STEPS.map((label, i) => {
        const n = i + 1
        const state = n === step ? 'active' : n < step ? 'done' : ''
        const clickable = n !== step && n <= reached
        return (
          <div key={label} style={{ display: 'contents' }}>
            {i > 0 && <div className={`step-line ${n <= reached ? 'done' : ''}`} />}
            <button role="listitem" className={`step ${state} ${clickable ? 'clickable' : ''}`} onClick={() => clickable && onGo(n)} aria-current={n === step ? 'step' : undefined} type="button">
              <span className="step-num">{state === 'done' && n !== step ? <Icon name="check" size={15} /> : n}</span>
              {label}
            </button>
          </div>
        )
      })}
    </div>
  )
}

export default function Wizard() {
  const { id } = useParams()
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const msg = useMessages()
  const [workflow, setWorkflow] = useState(null)
  const step = id ? Math.min(3, Math.max(1, Number(params.get('step')) || 2)) : 1

  const reload = useCallback(async () => {
    if (!id) { setWorkflow(null); return null }
    try {
      const wf = await api.get(`/api/workflows/${id}`)
      setWorkflow(wf)
      return wf
    } catch (e) {
      msg.showError(e)
      navigate('/workflows')
      return null
    }
  }, [id, msg, navigate])

  useEffect(() => { reload() }, [reload])

  const modelsReady = workflow && workflow.models_ready === workflow.models_total
  const reached = !workflow ? 1 : modelsReady ? 3 : 2
  const go = (n) => {
    if (n === 1) setParams({ step: '1' })
    else setParams({ step: String(n) })
  }

  return (
    <>
      <PageHeader
        title={workflow ? workflow.name : 'New workflow'}
        subtitle={step === 1
          ? 'Choose a ComfyUI workflow file. It is converted to a Python script automatically.'
          : step === 2
            ? 'These models are needed by the workflow. Missing ones are downloaded into the right ComfyUI folders.'
            : 'Adjust the inputs, run the workflow and preview the results.'}
      />
      <Stepper step={step} reached={reached} onGo={go} />
      {step === 1 && (
        <StepSelect
          workflow={id ? workflow : null}
          onImported={(wf) => navigate(`/workflows/${wf.id}/wizard?step=2`)}
          onNext={() => go(2)}
        />
      )}
      {step === 2 && workflow && (
        <StepModels workflow={workflow} onBack={() => go(1)} onNext={() => go(3)} onChanged={reload} />
      )}
      {step === 3 && workflow && (
        <StepRun workflow={workflow} onBack={() => go(2)} onChanged={reload} />
      )}
    </>
  )
}
