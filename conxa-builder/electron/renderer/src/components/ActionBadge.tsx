const COLORS: Record<string, string> = {
  click: "var(--accent)",
  type: "#5b9bd5",
  navigate: "#9d7cd8",
  scroll: "var(--text-muted)",
  select: "var(--accent)",
  hover: "var(--text-secondary)",
};

export function ActionBadge({ action }: { action: string }) {
  const key = (action || "").toLowerCase();
  const color = COLORS[key] ?? "var(--text-secondary)";
  return (
    <span
      style={{
        color,
        border: `1px solid ${color}`,
        borderRadius: 4,
        padding: "2px 8px",
        fontSize: 11,
        textTransform: "capitalize",
        textAlign: "center",
      }}
    >
      {action || "action"}
    </span>
  );
}
