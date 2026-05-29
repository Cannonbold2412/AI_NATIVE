export type PluginStatus = "published" | "unpublished" | "error";

const MAP: Record<PluginStatus, { glyph: string; color: string; label: string }> = {
  published: { glyph: "●", color: "var(--green)", label: "Published & synced" },
  unpublished: { glyph: "▲", color: "var(--amber)", label: "Unpublished changes" },
  // Outline circle for error so it is not signalled by color alone.
  error: { glyph: "○", color: "var(--red)", label: "Compile error" },
};

export function StatusDot({ status }: { status: PluginStatus }) {
  const s = MAP[status];
  return (
    <span title={s.label} aria-label={s.label} style={{ color: s.color, fontSize: 12 }}>
      {s.glyph}
    </span>
  );
}
