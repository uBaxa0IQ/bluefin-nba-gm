import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { bluefinAssets } from './bluefin-assets'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), bluefinAssets()],
  server: {
    host: '127.0.0.1',
    proxy: {
      '/api': {
        target: process.env.VITE_API_URL || 'http://localhost:8000',
        changeOrigin: true,
      }
    }
  }
})
