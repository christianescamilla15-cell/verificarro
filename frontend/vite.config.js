import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:3009',
      '/health': 'http://localhost:3009',
    },
  },
  build: {
    rollupOptions: {
      output: {
        // MOD-023: separar vendor libs en chunks dedicados.
        // Razón: cuando Christian deploya un cambio de código (que pasa
        // todos los días), `index-{hash}.js` se invalida pero los
        // vendor chunks NO. Browser sirve react/react-dom/router desde
        // cache → segunda visita carga ~70% más rápido.
        manualChunks: {
          'react-vendor': ['react', 'react-dom'],
          'router': ['react-router-dom'],
          // lucide-react se queda con el resto del app code porque
          // tree-shaking ya splittea iconos por chunk de page; sacarlo
          // a su propio chunk duplicaría algunos iconos.
        },
      },
    },
  },
})
