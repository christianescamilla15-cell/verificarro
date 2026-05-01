export default function KVTable({ rows }) {
  return (
    <table className="kv-table">
      <tbody>
        {rows.map(([label, value], i) => (
          <tr key={i}>
            <td className="kv-label">{label}</td>
            <td className="kv-value">{value || '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
