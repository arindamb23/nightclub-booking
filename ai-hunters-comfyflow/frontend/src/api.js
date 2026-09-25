// Thin fetch wrapper. Every failure becomes an ApiError that the UI shows in a modal.
export class ApiError extends Error {
  constructor(message, { status = 0, details = [] } = {}) {
    super(message)
    this.status = status
    this.details = details
  }
}

async function request(method, url, body, { form = false } = {}) {
  const opts = { method, headers: {} }
  if (body !== undefined) {
    if (form) opts.body = body
    else {
      opts.headers['Content-Type'] = 'application/json'
      opts.body = JSON.stringify(body)
    }
  }
  let res
  try {
    res = await fetch(url, opts)
  } catch {
    throw new ApiError('Cannot reach the ComfyFlow backend. Is Start-all.bat running?')
  }
  const type = res.headers.get('content-type') || ''
  const data = type.includes('application/json') ? await res.json().catch(() => null) : await res.text()
  if (!res.ok) {
    let msg = (data && data.detail) || (typeof data === 'string' && data) || `Request failed (${res.status})`
    if (Array.isArray(msg)) msg = msg.map((d) => d.msg || JSON.stringify(d)).join('\n')
    throw new ApiError(msg, { status: res.status })
  }
  return data
}

export const api = {
  get: (url) => request('GET', url),
  post: (url, body) => request('POST', url, body ?? {}),
  put: (url, body) => request('PUT', url, body),
  patch: (url, body) => request('PATCH', url, body),
  del: (url) => request('DELETE', url),
  upload: (url, formData) => request('POST', url, formData, { form: true }),
}
