export default function Spinner({ message }) {
  return (
    <div className="spinner-wrap">
      <div className="spinner" />
      {message && <p className="spinner-message">{message}</p>}
    </div>
  )
}
