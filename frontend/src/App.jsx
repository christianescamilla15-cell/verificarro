import { lazy, Suspense } from 'react'
import { Route, Routes } from 'react-router-dom'
import { Analytics } from '@vercel/analytics/react'
import { SpeedInsights } from '@vercel/speed-insights/react'
import Header from './components/Header.jsx'
import Spinner from './components/Spinner.jsx'
import WhatsAppButton from './components/WhatsAppButton.jsx'

// MOD-021: code splitting por route. Cada page se carga on-demand,
// reduciendo el bundle inicial. La landing (`/`) sigue siendo eager
// porque es el primer paint y no queremos que un Suspense fallback
// retrase el TTI inicial — pero las demás 9 pages se split-ean.
import Landing from './pages/Landing.jsx'

const AuthVerify = lazy(() => import('./pages/AuthVerify.jsx'))
const CheckoutFailure = lazy(() => import('./pages/CheckoutFailure.jsx'))
const CheckoutPending = lazy(() => import('./pages/CheckoutPending.jsx'))
const CheckoutSuccess = lazy(() => import('./pages/CheckoutSuccess.jsx'))
const CheckoutTier = lazy(() => import('./pages/CheckoutTier.jsx'))
const Dashboard = lazy(() => import('./pages/Dashboard.jsx'))
const Login = lazy(() => import('./pages/Login.jsx'))
const Pricing = lazy(() => import('./pages/Pricing.jsx'))
const PreviewReport = lazy(() => import('./pages/PreviewReport.jsx'))
const Privacidad = lazy(() => import('./pages/Privacidad.jsx'))
const Terminos = lazy(() => import('./pages/Terminos.jsx'))


function RouteFallback() {
  return (
    <main style={{ padding: '4rem 1rem', textAlign: 'center' }}>
      <Spinner message="Cargando…" />
    </main>
  )
}


export default function App() {
  return (
    <div className="app">
      <Header />
      <Suspense fallback={<RouteFallback />}>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/precios" element={<Pricing />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/preview/:reportId" element={<PreviewReport />} />
          <Route path="/checkout-tier" element={<CheckoutTier />} />
          <Route path="/login" element={<Login />} />
          <Route path="/auth/verify" element={<AuthVerify />} />
          <Route path="/checkout/success" element={<CheckoutSuccess />} />
          <Route path="/checkout/failure" element={<CheckoutFailure />} />
          <Route path="/checkout/pending" element={<CheckoutPending />} />
          <Route path="/privacidad" element={<Privacidad />} />
          <Route path="/terminos" element={<Terminos />} />
        </Routes>
      </Suspense>
      <WhatsAppButton variant="floating" />
      {/* MOD-026: Vercel Analytics + Speed Insights.
          - Analytics: page views + custom events (free tier 25K/mes)
          - SpeedInsights: Core Web Vitals (LCP, CLS, FID, INP) en
            tu Vercel dashboard. Ambos respetan DNT y NO mandan PII.
          Por LFPDPPP MX, los dos son privacy-respecting por default. */}
      <Analytics />
      <SpeedInsights />
    </div>
  )
}
