import { Route, Routes } from 'react-router-dom'
import Header from './components/Header.jsx'
import WhatsAppButton from './components/WhatsAppButton.jsx'
import AuthVerify from './pages/AuthVerify.jsx'
import CheckoutFailure from './pages/CheckoutFailure.jsx'
import CheckoutPending from './pages/CheckoutPending.jsx'
import CheckoutSuccess from './pages/CheckoutSuccess.jsx'
import CheckoutTier from './pages/CheckoutTier.jsx'
import Landing from './pages/Landing.jsx'
import Login from './pages/Login.jsx'
import Pricing from './pages/Pricing.jsx'
import PreviewReport from './pages/PreviewReport.jsx'

export default function App() {
  return (
    <div className="app">
      <Header />
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/precios" element={<Pricing />} />
        <Route path="/preview/:reportId" element={<PreviewReport />} />
        <Route path="/checkout-tier" element={<CheckoutTier />} />
        <Route path="/login" element={<Login />} />
        <Route path="/auth/verify" element={<AuthVerify />} />
        <Route path="/checkout/success" element={<CheckoutSuccess />} />
        <Route path="/checkout/failure" element={<CheckoutFailure />} />
        <Route path="/checkout/pending" element={<CheckoutPending />} />
      </Routes>
      <WhatsAppButton variant="floating" />
    </div>
  )
}
