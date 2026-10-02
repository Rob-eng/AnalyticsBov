import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Servido pelo FastAPI em /app (api_main.py). Em dev, /api vai para o backend local.
export default defineConfig({
  base: '/app/',
  plugins: [react()],
  server: {
    proxy: { '/api': 'http://localhost:8000' },
  },
})
