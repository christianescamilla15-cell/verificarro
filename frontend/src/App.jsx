import { Route, Routes } from 'react-router-dom'
import Header from './components/Header.jsx'
import AuthVerify from './pages/AuthVerify.jsx'
import CheckoutFailure from './pages/CheckoutFailure.jsx'
import CheckoutPending from './pages/CheckoutPending.jsx'
import CheckoutSuccess from './pages/CheckoutSuccess.jsx'
import Landing from './pages/Landing.jsx'
import Login from './pages/Login.jsx'

export default function App() {
  return (
    <div className="app">
      <Header />
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/login" element={<Login />} />
        <Route path="/auth/verify" element={<AuthVerify />} />
        <Route path="/checkout/success" element={<CheckoutSuccess />} />
        <Route path="/checkout/failure" element={<CheckoutFailure />} />
        <Route path="/checkout/pending" element={<CheckoutPending />} />
      </Routes>
    </div>
  )
}
