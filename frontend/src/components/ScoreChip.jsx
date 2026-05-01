export default function ScoreChip({ score, risk }) {
  return (
    <div className={`score-chip score-${risk}`}>
      <span className="score-num">{score}</span>
      <span className="score-label">/ 100</span>
      <div className="risk-label">
        {risk === 'green' ? 'RIESGO BAJO'
          : risk === 'yellow' ? 'PRECAUCIÓN'
          : 'ALTO RIESGO'}
      </div>
    </div>
  )
}
