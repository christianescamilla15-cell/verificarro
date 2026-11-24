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
    // Vite 8 empaqueta con Rolldown: `rollupOptions` pasó a `rolldownOptions` y la forma de objeto de
    // `manualChunks` ya no existe; su equivalente son los grupos de `codeSplitting`.
    rolldownOptions: {
      output: {
        // MOD-023: separar vendor libs en chunks dedicados.
        // Razón: cuando Christian deploya un cambio de código (que pasa
        // todos los días), `index-{hash}.js` se invalida pero los
        // vendor chunks NO. Browser sirve react/react-dom/router desde
        // cache → segunda visita carga ~70% más rápido.
        codeSplitting: {
          groups: [
            // react-vendor primero (mayor prioridad): react también es dependencia del router.
            { name: 'react-vendor', test: /[\\/]node_modules[\\/](react|react-dom|scheduler)[\\/]/, priority: 2 },
            { name: 'router', test: /[\\/]node_modules[\\/](react-router|react-router-dom)[\\/]/, priority: 1 },
          ],
          // lucide-react se queda con el resto del app code porque
          // tree-shaking ya splittea iconos por chunk de page; sacarlo
          // a su propio chunk duplicaría algunos iconos.
        },
      },
    },
  },
})
