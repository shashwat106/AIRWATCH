export function Problem({ message, retry }: { message: string; retry?: () => void }) {
  return (
    <div className="problem" role="alert">
      <p>{message}</p>
      {retry && <button type="button" onClick={retry}>Try again</button>}
    </div>
  );
}

export function Loading({ what }: { what: string }) {
  return <p className="loading" role="status">Loading {what}</p>;
}
