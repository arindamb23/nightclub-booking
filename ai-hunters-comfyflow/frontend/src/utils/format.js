export function formatBytes(n) {
  if (!n && n !== 0) return '—'
  if (n < 1024) return `${n} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let v = n / 1024
  let i = 0
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++ }
  return `${v.toFixed(v >= 100 ? 0 : 1)} ${units[i]}`
}

export function formatDate(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString(undefined, { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
}

export function formatDuration(s) {
  if (s == null) return '—'
  if (s < 60) return `${s.toFixed(1)} s`
  const m = Math.floor(s / 60)
  return `${m} min ${Math.round(s % 60)} s`
}

export const fileUrl = (runId, filename, download = false) =>
  `/api/runs/${encodeURIComponent(runId)}/files/${encodeURIComponent(filename)}${download ? '?download=1' : ''}`

export const zipUrl = (runId) => `/api/runs/${encodeURIComponent(runId)}/zip`

export function greeting() {
  const h = new Date().getHours()
  if (h < 12) return 'Good morning'
  if (h < 18) return 'Good afternoon'
  return 'Good evening'
}

// "…\models\checkpoints" style short path; full path goes in the title attribute.
export function shortPath(p, keep = 3) {
  if (!p) return ''
  const sep = p.includes('\\') ? '\\' : '/'
  const parts = p.split(/[\\/]+/).filter(Boolean)
  if (parts.length <= keep + 1) return p
  return `…${sep}${parts.slice(-keep).join(sep)}`
}
