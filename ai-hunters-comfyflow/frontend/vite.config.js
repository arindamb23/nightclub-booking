import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'
import { readFileSync } from 'node:fs'
import path from 'node:path'

const here = path.dirname(fileURLToPath(import.meta.url))
const pkg = JSON.parse(readFileSync(path.join(here, 'package.json'), 'utf-8'))

// Ports come from the project-root .env only.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, path.resolve(here, '..'), '')
  const frontendPort = Number.parseInt(env.FRONTEND_PORT, 10)
  const backendPort = Number.parseInt(env.BACKEND_PORT, 10)
  if (!frontendPort || !backendPort) {
    throw new Error('FRONTEND_PORT / BACKEND_PORT missing in ../.env - run Setup.bat first.')
  }
  const backendHost = env.BACKEND_HOST || '127.0.0.1'
  const server = {
    host: '127.0.0.1',
    port: frontendPort,
    strictPort: true,
    proxy: { '/api': { target: `http://${backendHost}:${backendPort}`, changeOrigin: true } },
  }
  return {
    plugins: [react()],
    define: { __APP_VERSION__: JSON.stringify(pkg.version) },
    server,
    preview: server,
  }
})
