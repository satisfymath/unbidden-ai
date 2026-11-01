// The Unbidden mark as the references show it: an open ring with a separate dot beside the opening. No vector asset
// exists in the repositories (only demo videos), so this is drawn to match the reference, not a generic symbol.
export function Logo({ size = 22, title = "Unbidden" }: { size?: number; title?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" role="img" aria-label={title} style={{ flex: "none" }}>
      <defs>
        <linearGradient id="ub-ring" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#ffffff" />
          <stop offset="1" stopColor="#bfe3ff" />
        </linearGradient>
      </defs>
      <path
        d="M 17.6 6.6 A 8 8 0 1 0 19.6 15"
        fill="none"
        stroke="url(#ub-ring)"
        strokeWidth="2.6"
        strokeLinecap="round"
      />
      <circle cx="19.9" cy="8.6" r="1.9" fill="#ffffff" />
    </svg>
  );
}

export function Wordmark({ project }: { project?: string }) {
  return (
    <span className="row" style={{ gap: 10 }}>
      <Logo size={24} />
      <span style={{ fontWeight: 700, letterSpacing: "0.22em", fontSize: 13.5, color: "var(--ink)" }}>UNBIDDEN</span>
      {project ? (
        <span className="row" style={{ gap: 8, fontSize: 14, color: "var(--ink-2)" }}>
          <span style={{ color: "var(--muted-2)" }}>/</span>
          <span style={{ fontWeight: 500 }}>{project}</span>
        </span>
      ) : null}
    </span>
  );
}
