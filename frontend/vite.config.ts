import { fileURLToPath } from 'node:url'
import { defineConfig, type Plugin } from 'vite'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'

const src = fileURLToPath(new URL('./src', import.meta.url))

function packagePageFallback(): Plugin {
  return {
    name: 'package-page-fallback',
    configureServer(server) {
      server.middlewares.use((req, _res, next) => {
        if (req.url === '/package') {
          req.url = '/index.html'
        }
        next()
      })
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [packagePageFallback(), react(), tailwindcss()],
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
