import { useEffect, useState } from 'react'
import { Link, Navigate } from 'react-router-dom'
import {
  AlertTriangle, CheckCircle2, Clock, FileText, Search,
  ShieldAlert, ShieldCheck, TrendingUp,
} from 'lucide-react'
import { api } from '../lib/api.js'
import { useAuth } from '../hooks/useAuth.js'

/**
 * Tablero del usuario (dealer-friendly): stats, suscripción y últimos
 * reportes. Una sola request a `/api/auth/me/dashboard`.
 *
 * Si no hay sesión, redirigimos a /login. El header ya muestra el email,
 * así que no duplicamos identidad — el dashboard se enfoca en datos.
 */
export default function Dashboard() {
  const { user, loading: authLoading } = useAuth()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (authLoading || !user) return
    let cancelled = false
    ;(async () => {
      const res = await api.get('/api/auth/me/dashboard')
      if (cancelled) return
      if (!res.ok) {
        setError(res.error || 'No pudimos cargar el tablero.')
        setLoading(false)
        return
      }
      setData(res.data)
      setLoading(false)
    })()
    return () => { cancelled = true }
  }, [authLoading, user])

  if (authLoading) return null
  if (!user) return <Navigate to="/login" replace />

  if (loading) {
    return (
      <main className="dashboard">
        <h1>Tablero</h1>
        <p className="muted">Cargando reportes…</p>
      </main>
    )
  }

  if (error) {
    return (
      <main className="dashboard">
        <h1>Tablero</h1>
        <div className="error">
          <AlertTriangle size={16} /> {error}
        </div>
      </main>
    )
  }

  const { summary, subscription, reports } = data
  return (
    <main className="dashboard">
      <header className="dashboard-header">
        <div>
          <h1 style={{ margin: 0 }}>Tablero</h1>
          <p className="muted" style={{ margin: '4px 0 0' }}>
            Hola {user.email}. Aquí están tus reportes y tu plan.
          </p>
        </div>
        <Link to="/" className="primary big" style={{ alignSelf: 'flex-start' }}>
          <Search size={18} /> Nuevo reporte
        </Link>
      </header>

      {subscription && (
        <SubscriptionCard subscription={subscription} />
      )}

      <section className="stats-grid">
        <StatCard
          icon={<FileText size={20} />}
          label="Reportes totales"
          value={summary.total_reports}
        />
        <StatCard
          icon={<Clock size={20} />}
          label="Últimos 30 días"
          value={summary.reports_this_month}
        />
        <StatCard
          icon={<TrendingUp size={20} />}
          label="Score promedio"
          value={summary.avg_score == null ? '—' : Math.round(summary.avg_score)}
        />
        <StatCard
          icon={<ShieldAlert size={20} className="risk-high" />}
          label="Reportes en rojo"
          value={summary.high_risk_count}
          tone="danger"
        />
      </section>

      <section className="dashboard-meta">
        <span className="muted small">
          Has gastado <strong>${summary.spent_mxn.toLocaleString('es-MX')} MXN</strong> en
          {' '}{summary.total_reports} {summary.total_reports === 1 ? 'reporte' : 'reportes'}.
        </span>
      </section>

      <section className="reports-list">
        <h2>Últimos reportes</h2>
        {reports.length === 0 ? (
          <div className="empty-state">
            <p className="muted">Aún no has generado ningún reporte.</p>
            <Link to="/" className="primary">
              <Search size={16} /> Escanear mi primer auto
            </Link>
          </div>
        ) : (
          <ul className="report-rows">
            {reports.map((r) => (
              <ReportRow key={r.id} report={r} />
            ))}
          </ul>
        )}
      </section>
    </main>
  )
}


function SubscriptionCard({ subscription }) {
  const tierName = subscription.tier === 'search' ? 'Búsqueda activa' : 'Dealer / Lotero'
  const expires = subscription.expires_at
    ? new Date(subscription.expires_at).toLocaleDateString('es-MX', {
        day: '2-digit', month: 'short', year: 'numeric',
      })
    : null
  const usagePct = subscription.monthly_cap > 0
    ? Math.min(100, Math.round((subscription.monthly_used / subscription.monthly_cap) * 100))
    : 0

  return (
    <section className={`subscription-card ${subscription.active ? 'active' : 'expired'}`}>
      <div className="subscription-header">
        <div>
          <span className="muted small">Tu plan</span>
          <div className="subscription-tier">
            {subscription.active
              ? <ShieldCheck size={20} className="ok" />
              : <AlertTriangle size={20} className="warn" />}
            {tierName}
          </div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <span className="muted small">
            {subscription.active ? 'Renueva' : 'Venció'}
          </span>
          <div style={{ fontWeight: 'var(--fw-semibold)' }}>
            {expires || '—'}
          </div>
        </div>
      </div>
      <div className="subscription-usage">
        <div className="usage-bar">
          <div
            className={`usage-fill ${usagePct >= 80 ? 'high' : ''}`}
            style={{ width: `${usagePct}%` }}
          />
        </div>
        <div className="usage-label">
          {subscription.monthly_used} / {subscription.monthly_cap} reportes
          este periodo
        </div>
      </div>
      {!subscription.active && (
        <Link to={`/checkout-tier?tier=${subscription.tier}`} className="primary">
          Renovar plan
        </Link>
      )}
    </section>
  )
}


function StatCard({ icon, label, value, tone }) {
  return (
    <div className={`stat-card ${tone || ''}`}>
      <div className="stat-icon">{icon}</div>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
    </div>
  )
}


function ReportRow({ report }) {
  const date = new Date(report.created_at).toLocaleDateString('es-MX', {
    day: '2-digit', month: 'short', year: 'numeric',
  })
  const title = [report.year, report.make, report.model]
    .filter(Boolean).join(' ') || report.plate || report.vin || 'Sin identificar'
  const riskClass = `risk-${report.risk_level}`

  return (
    <li className="report-row">
      <Link to={`/preview/${report.id}`} className="report-row-link">
        <div className="report-row-main">
          <div className="report-row-title">{title}</div>
          <div className="report-row-meta muted small">
            {date}
            {report.plate && <> · placa <strong>{report.plate}</strong></>}
            {report.status === 'preview' && <> · solo preview</>}
          </div>
        </div>
        <div className={`report-row-score ${riskClass}`}>
          {report.score}
          {report.risk_level === 'low' && <CheckCircle2 size={16} />}
          {report.risk_level === 'medium' && <AlertTriangle size={16} />}
          {report.risk_level === 'high' && <ShieldAlert size={16} />}
        </div>
      </Link>
    </li>
  )
}
