import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

/**
 * Vitest config — vive separado de vite.config.js porque Vitest tiene
 * sus propios resolvers y queremos un setup file dedicado para tests
 * (jsdom env, @testing-library/jest-dom matchers).
 *
 * Comandos:
 *   npm run test       — watch mode
 *   npm run test:run   — single run (CI)
 */
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.js'],
    css: false, // no necesitamos CSS en tests
    restoreMocks: true,
    clearMocks: true,
  },
})
