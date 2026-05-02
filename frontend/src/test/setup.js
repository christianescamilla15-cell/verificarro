import '@testing-library/jest-dom/vitest'

// localStorage stub: jsdom incluye uno pero a veces falla con JSON.
// Reseteamos entre tests para evitar leak de estado entre cases.
beforeEach(() => {
  localStorage.clear()
})
