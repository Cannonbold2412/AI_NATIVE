/**
 * Claude-Desktop-inspired dark palette for Build Studio.
 * Injected as CSS custom properties on :root by applyDesignTokens().
 */
export const tokens = {
  "--bg-base": "#1a1a1a",
  "--bg-sidebar": "#1e1e1e",
  "--bg-surface": "#252525",
  "--bg-hover": "rgba(255,255,255,0.04)",
  "--bg-selected": "rgba(217,119,87,0.12)",
  "--border": "rgba(255,255,255,0.08)",
  "--text-primary": "#e8e6e3",
  "--text-secondary": "#8e8e8e",
  "--text-muted": "#5a5a5a",
  "--accent": "#d97757",
  "--accent-hover": "#e08565",
  "--green": "#4ade80",
  "--amber": "#fbbf24",
  "--red": "#f87171",
  "--radius": "6px",
  "--font": "Inter, system-ui, sans-serif",
} as const;

export function applyDesignTokens(root: HTMLElement = document.documentElement): void {
  for (const [key, value] of Object.entries(tokens)) {
    root.style.setProperty(key, value);
  }
}
