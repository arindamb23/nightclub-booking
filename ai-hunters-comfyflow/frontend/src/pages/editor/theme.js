export const ROLE = {
  input: { label: 'Input', color: '#3f6b98', soft: '#e5edf6', icon: 'upload' },
  prompt: { label: 'Prompt', color: '#c96442', soft: '#f7e9e2', icon: 'edit' },
  model: { label: 'Model', color: '#7a6a9e', soft: '#ece8f4', icon: 'box' },
  generate: { label: 'Generate', color: '#5e5d59', soft: '#efede7', icon: 'sparkle' },
  output: { label: 'Output', color: '#4e7d4a', soft: '#e8f0e4', icon: 'image' },
}

const TYPE_COLORS = {
  IMAGE: '#4e7d4a', MASK: '#6d8f69', LATENT: '#b0578a', MODEL: '#7a6a9e', CLIP: '#b9892a', CLIP_VISION: '#a8872f',
  CLIP_VISION_OUTPUT: '#a8872f', CONDITIONING: '#c96442', VAE: '#b3372e', NOISE: '#6b7a8f', SAMPLER: '#6b7a8f',
  SIGMAS: '#6b7a8f', GUIDER: '#6b7a8f', INT: '#3f6b98', FLOAT: '#3f6b98', STRING: '#83827d', AUDIO: '#2f7f86',
}
export const typeColor = (t) => TYPE_COLORS[String(t || '').toUpperCase()] || '#a8a69f'
export const LEGEND = ['IMAGE', 'LATENT', 'MODEL', 'CONDITIONING', 'CLIP', 'VAE']

export const OUTPUT_ICON = { image: 'image', video: 'film', audio: 'audio' }
export const GROUP_ID = '__models__'
