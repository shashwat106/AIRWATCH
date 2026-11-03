import { Component, ReactNode } from "react";

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

/** A failure in one view shows a way forward rather than a blank page. */
export class Boundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <main className="column">
        <Problem message="This page could not be displayed. Reload to try again." retry={() => window.location.reload()} />
      </main>
    );
  }
}
