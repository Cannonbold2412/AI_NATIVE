import { useState } from "react";

type Props = {
  data: Record<string, unknown> | null;
  title?: string;
  defaultOpen?: boolean;
};

export function ValidationReportPanel({ data, title = "Validation report", defaultOpen = true }: Props) {
  const [open, setOpen] = useState(defaultOpen);
  if (!data) return null;

  const issues = Array.isArray(data.issues) ? (data.issues as { severity: string; message: string; code: string }[]) : null;
  const isError = data.error;

  return (
    <div
      style={{
        border: "1px solid var(--border)",
        borderRadius: "var(--radius)",
        overflow: "hidden",
        background: "var(--bg-surface)",
      }}
    >
      <button
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          width: "100%",
          padding: "8px 12px",
          fontSize: 11,
          color: "var(--text-muted)",
          textTransform: "uppercase",
          letterSpacing: "0.06em",
          textAlign: "left",
        }}
        onClick={() => setOpen((v) => !v)}
      >
        <span>{title}</span>
        <span>{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div style={{ borderTop: "1px solid var(--border)", padding: "12px" }}>
          {isError && (
            <div style={{ color: "var(--red)", fontSize: 13 }}>{String(data.error)}</div>
          )}
          {issues && issues.length === 0 && (
            <div className="banner-ok" style={{ fontSize: 13 }}>
              All checks passed
            </div>
          )}
          {issues && issues.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {issues.map((issue, i) => (
                <div
                  key={i}
                  style={{
                    padding: "8px 10px",
                    borderRadius: "var(--radius)",
                    background:
                      issue.severity === "error"
                        ? "rgba(248,113,113,0.08)"
                        : "rgba(251,191,36,0.08)",
                    border: `1px solid ${issue.severity === "error" ? "var(--red)" : "var(--amber)"}`,
                    fontSize: 12,
                  }}
                >
                  <div
                    style={{
                      fontWeight: 600,
                      color: issue.severity === "error" ? "var(--red)" : "var(--amber)",
                      marginBottom: 2,
                    }}
                  >
                    [{issue.severity.toUpperCase()}] {issue.code}
                  </div>
                  <div style={{ color: "var(--text-secondary)" }}>{issue.message}</div>
                </div>
              ))}
            </div>
          )}
          {!issues && !isError && (
            <pre
              style={{
                fontFamily: "monospace",
                fontSize: 11,
                color: "var(--text-secondary)",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
              }}
            >
              {JSON.stringify(data, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
