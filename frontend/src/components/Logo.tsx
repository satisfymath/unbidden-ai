// The Unbidden mark from the brand sheet: a fine open ring with a separate small dot beside the opening.
export function Logo({ size = 22, title = "Unbidden" }: { size?: number; title?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" role="img" aria-label={title} style={{ flex: "none" }}>
      <path d="M 14.99 5.5 A 8.5 8.5 0 1 0 17.7 7.77" fill="none" stroke="var(--ink)" strokeWidth="1.05" strokeLinecap="round" />
      <circle cx="19.5" cy="3.9" r="1.25" fill="var(--ink)" />
    </svg>
  );
}

export function Wordmark({ project }: { project?: string }) {
  return (
    <span className="row" style={{ gap: 10 }}>
      <Logo size={24} />
      <span style={{ fontWeight: 300, letterSpacing: "0.42em", fontSize: 14, color: "var(--ink)" }}>UNBiDDEN</span>
      {project ? (
        <span className="row" style={{ gap: 8, fontSize: 14, color: "var(--ink-2)" }}>
          <span style={{ color: "var(--muted-2)" }}>/</span>
          <span style={{ fontWeight: 500 }}>{project}</span>
        </span>
      ) : null}
    </span>
  );
}
