import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'

const src = fileURLToPath(new URL('./src', import.meta.url))

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': src,
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/skills': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/skill': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/record': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/compile': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/metrics': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
