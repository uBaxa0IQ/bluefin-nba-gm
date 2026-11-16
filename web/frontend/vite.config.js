import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { bluefinAssets } from './bluefin-assets'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
    plugins: [react(), bluefinAssets()],
    server: {
      host: '127.0.0.1',
      proxy: {
        '/api': {
          target: env.API_PROXY_TARGET || 'http://127.0.0.1:8000',
          changeOrigin: true,
        }
      }
    }
  }
})
