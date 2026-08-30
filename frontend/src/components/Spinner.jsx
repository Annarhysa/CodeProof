export default function Spinner({ label }) {
  return (
    <span className="loading-row">
      <span className="spinner" />
      {label && <span>{label}</span>}
    </span>
  );
}
