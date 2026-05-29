type SuggestionItem = {
  step_index: number;
  severity: "info" | "warn" | "error";
  code: string;
  message: string;
};

type Props = {
  suggestions: SuggestionItem[];
  onSelectStep: (index: number) => void;
};

const SEVERITY_COLOR: Record<string, string> = {
  error: "var(--red)",
  warn: "var(--amber)",
  info: "var(--text-secondary)",
};

export function SuggestionsPanel({ suggestions, onSelectStep }: Props) {
  if (suggestions.length === 0) {
    return (
      <div className="banner-ok" style={{ fontSize: 13 }}>
        No suggestions — looks good
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {suggestions.map((s, i) => (
        <div
          key={i}
          style={{
            padding: "8px 10px",
            borderRadius: "var(--radius)",
            background: "var(--bg-surface)",
            border: "1px solid var(--border)",
            cursor: "pointer",
          }}
          onClick={() => onSelectStep(s.step_index)}
          title={`Jump to step ${s.step_index + 1}`}
        >
          <div
            style={{
              fontSize: 11,
              fontWeight: 600,
              color: SEVERITY_COLOR[s.severity] ?? "var(--text-secondary)",
              marginBottom: 2,
              textTransform: "uppercase",
            }}
          >
            Step {s.step_index + 1} · {s.code}
          </div>
          <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>{s.message}</div>
        </div>
      ))}
    </div>
  );
}
