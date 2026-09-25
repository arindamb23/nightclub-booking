export function LogoMark({ size = 36, className = '' }) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 64 64" role="img" aria-label="AI Hunters ComfyFlow logo">
      <rect width="64" height="64" rx="16" fill="#C96442" />
      <path d="M45 19.5A17 17 0 1 0 45 44.5" fill="none" stroke="#fff" strokeWidth="4.5" strokeLinecap="round" />
      <path d="M15.5 32H30c4 0 6-3.5 9-3.5s4.5 2 6.5 3.5" fill="none" stroke="#fff" strokeOpacity=".75" strokeWidth="3" strokeLinecap="round" />
      <circle cx="45" cy="19.5" r="5" fill="#fff" /><circle cx="45" cy="19.5" r="2" fill="#C96442" />
      <circle cx="15" cy="32" r="5" fill="#fff" /><circle cx="15" cy="32" r="2" fill="#C96442" />
      <circle cx="45" cy="44.5" r="5" fill="#fff" /><circle cx="45" cy="44.5" r="2" fill="#C96442" />
      <circle cx="49" cy="32" r="2.6" fill="#fff" />
    </svg>
  )
}

export default function Logo() {
  return (
    <div className="brand">
      <LogoMark className="brand-mark" />
      <div>
        <div className="brand-kicker">AI Hunters</div>
        <div className="brand-name">Comfy<span>Flow</span></div>
      </div>
    </div>
  )
}
