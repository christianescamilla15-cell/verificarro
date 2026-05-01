export default function FindingList({ title, findings, getText, emptyText }) {
  if (!findings || findings.length === 0) {
    return (
      <div className="finding-section">
        <h3>{title}</h3>
        <p className="muted">{emptyText || 'Sin banderas detectadas.'}</p>
      </div>
    )
  }
  return (
    <div className="finding-section">
      <h3>{title} <span className="muted">({findings.length})</span></h3>
      <ul className="finding-list">
        {findings.map((f, i) => (
          <li key={i} className={`finding finding-${f.severity}`}>
            <span className="severity-tag">{f.severity.toUpperCase()}</span>
            <span className="finding-text">{getText(f)}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
