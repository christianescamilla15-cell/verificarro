import { createContext, useContext } from 'react'

/**
 * Auth context global (MOD-024).
 *
 * El provider real con la lógica fetch vive en
 * `src/providers/AuthProvider.jsx`. Aquí solo exportamos el contexto
 * y el hook consumer — `useAuth.js` se queda como `.js` (sin JSX) para
 * cumplir Vite 8 strict que requiere `.jsx` para cualquier archivo
 * con JSX.
 *
 * Antes cada `useAuth()` consumer (Header + Dashboard + AuthVerify)
 * hacía su propio fetch a `/api/auth/me` al montar — 3 fetches
 * paralelos por navegación. Ahora `<AuthProvider>` (montado en
 * main.jsx) hace UN solo fetch y los consumers leen del context.
 */

export const AuthContext = createContext({
  user: null,
  loading: true,
  refresh: async () => {},
  logout: async () => {},
})


export function useAuth() {
  return useContext(AuthContext)
}
