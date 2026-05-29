import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { cmd, CmdError } from "@/lib/ipc";

/** First-run wizard: name a plugin, optionally record auth, optionally record a workflow. */
export function SetupWizard({ onCreated }: { onCreated?: () => void }) {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [name, setName] = useState("");
  const [targetUrl, setTargetUrl] = useState("");
  const [pluginId, setPluginId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function createPlugin() {
    setError(null);
    try {
      const res = await cmd<{ plugin: { id: string } }>("create_plugin", {
        name: name.trim(),
        target_url: targetUrl.trim() || "about:blank",
      });
      setPluginId(res.plugin.id);
      onCreated?.();
      setStep(2);
    } catch (e) {
      setError(e instanceof CmdError ? e.message : String(e));
    }
  }

  function finish() {
    if (pluginId) navigate(`/plugins/${encodeURIComponent(pluginId)}`);
  }

  return (
    <div style={{ maxWidth: 520 }}>
      <h2 style={{ marginBottom: 16 }}>Step {step} of 3</h2>
      {error && <div className="banner-error" style={{ marginBottom: 16 }}>{error}</div>}

      {step === 1 && (
        <section>
          <h3>Name your first plugin</h3>
          <label style={{ display: "block", margin: "12px 0" }}>
            Plugin name
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Render Deployment"
              style={inputStyle}
            />
          </label>
          <label style={{ display: "block", margin: "12px 0" }}>
            Target URL
            <input
              value={targetUrl}
              onChange={(e) => setTargetUrl(e.target.value)}
              placeholder="https://dashboard.render.com"
              style={inputStyle}
            />
          </label>
          <button className="btn-accent" disabled={!name.trim()} onClick={createPlugin}>
            Continue →
          </button>
        </section>
      )}

      {step === 2 && (
        <section>
          <h3>Record authentication</h3>
          <p style={muted}>Log into the website once so Conxa can replay your session.</p>
          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <button
              className="btn-accent"
              onClick={() =>
                pluginId &&
                navigate(`/plugins/${encodeURIComponent(pluginId)}/record/__auth__`)
              }
            >
              Open browser &amp; record login
            </button>
            <button onClick={() => setStep(3)} style={ghost}>Skip</button>
          </div>
        </section>
      )}

      {step === 3 && (
        <section>
          <h3>Record your first workflow</h3>
          <p style={muted}>Browse normally. Conxa captures every action.</p>
          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <button className="btn-accent" onClick={finish}>Go to plugin</button>
            <button onClick={finish} style={ghost}>Skip</button>
          </div>
        </section>
      )}
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  display: "block",
  width: "100%",
  marginTop: 6,
  padding: "8px 10px",
  background: "var(--bg-surface)",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius)",
  color: "var(--text-primary)",
};
const muted: React.CSSProperties = { color: "var(--text-secondary)" };
const ghost: React.CSSProperties = {
  padding: "8px 14px",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius)",
  color: "var(--text-secondary)",
};
