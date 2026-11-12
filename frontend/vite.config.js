import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Frontend dev server proxies API calls to the FastAPI process, so the
// browser only ever talks to one origin and no CORS config is needed in dev.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
