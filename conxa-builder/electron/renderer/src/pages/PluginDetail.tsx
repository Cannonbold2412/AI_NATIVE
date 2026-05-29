import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { cmd, CmdError } from "@/lib/ipc";
import { StatusDot } from "@/components/StatusDot";

type Tab = "workflows" | "auth" | "test" | "build" | "install";

interface Workflow {
  name: string;
  step_count: number;
  status: string;
}

interface PluginInfo {
  id: string;
  name: string;
  status: string;
  target_url: string;
  version?: string;
  published_version?: string;
  workflows: Workflow[];
}

export function PluginDetail() {
  const { pluginId } = useParams<{ pluginId: string }>();
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>("workflows");
  const [plugin, setPlugin] = useState<PluginInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionPending, setActionPending] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!pluginId) return;
    setLoading(true);
    cmd<{ plugin: PluginInfo }>("get_plugin", { plugin_id: pluginId })
      .then((r) => setPlugin(r.plugin))
      .catch((e) => setError(e instanceof CmdError ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [pluginId]);

  async function doAction(type: string, extra?: Record<string, unknown>) {
    setActionError(null);
    setActionPending(true);
    try {
      await cmd(type, { plugin_id: pluginId, ...extra });
      const r = await cmd<{ plugin: PluginInfo }>("get_plugin", { plugin_id: pluginId });
      setPlugin(r.plugin);
    } catch (e) {
      setActionError(e instanceof CmdError ? e.message : String(e));
    } finally {
      setActionPending(false);
    }
  }

  function copyShareLink() {
    if (!plugin?.id) return;
    navigator.clipboard.writeText(`conxa://install/${encodeURIComponent(plugin.id)}`);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  if (loading) return <div style={{ color: "var(--text-secondary)" }}>Loading…</div>;
  if (error) return <div className="banner-error">{error}</div>;
  if (!plugin) return null;

  const tabs: { id: Tab; label: string }[] = [
    { id: "workflows", label: "Workflows" },
    { id: "auth", label: "Auth" },
    { id: "test", label: "Test" },
    { id: "build", label: "Build" },
    { id: "install", label: "Install" },
  ];

  return (
    <div style={{ maxWidth: 680 }}>
      <h2 style={{ marginBottom: 4 }}>{plugin.name}</h2>
      <div style={{ color: "var(--text-secondary)", marginBottom: 20, fontSize: 13 }}>
        {plugin.target_url}
      </div>

      <div className="tabbar">
        {tabs.map((t) => (
          <button
            key={t.id}
            className={"tab" + (tab === t.id ? " tab--active" : "")}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {actionError && (
        <div className="banner-error" style={{ marginBottom: 16 }}>
          {actionError}
        </div>
      )}

      {tab === "workflows" && (
        <WorkflowsTab plugin={plugin} pluginId={pluginId!} navigate={navigate} />
      )}
      {tab === "auth" && (
        <AuthTab pluginId={pluginId!} navigate={navigate} />
      )}
      {tab === "test" && (
        <TestTab pluginId={pluginId!} doAction={doAction} pending={actionPending} />
      )}
      {tab === "build" && (
        <BuildTab doAction={doAction} pending={actionPending} />
      )}
      {tab === "install" && (
        <InstallTab plugin={plugin} copied={copied} onCopy={copyShareLink} />
      )}
    </div>
  );
}

function WorkflowsTab({
  plugin,
  pluginId,
  navigate,
}: {
  plugin: PluginInfo;
  pluginId: string;
  navigate: ReturnType<typeof useNavigate>;
}) {
  return (
    <section>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <h3>Workflows</h3>
        <button
          className="btn-accent"
          onClick={() => navigate(`/plugins/${encodeURIComponent(pluginId)}/record/new`)}
        >
          + Record new workflow
        </button>
      </div>

      {plugin.workflows.length === 0 ? (
        <p style={{ color: "var(--text-secondary)" }}>No workflows yet. Record one to get started.</p>
      ) : (
        <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius)", overflow: "hidden" }}>
          {plugin.workflows.map((w) => (
            <div
              key={w.name}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                padding: "12px 16px",
                borderBottom: "1px solid var(--border)",
                cursor: "pointer",
              }}
              onClick={() => navigate(`/plugins/${encodeURIComponent(pluginId)}/edit/${encodeURIComponent(w.name)}`)}
            >
              <StatusDot status={w.status === "error" ? "error" : w.status === "ready" ? "published" : "unpublished"} />
              <span style={{ flex: 1 }}>{w.name}</span>
              <span style={{ color: "var(--text-secondary)", fontSize: 12 }}>
                {w.step_count} step{w.step_count !== 1 ? "s" : ""}
              </span>
              <span style={{ color: "var(--text-muted)", fontSize: 12 }}>›</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function AuthTab({
  pluginId,
  navigate,
}: {
  pluginId: string;
  navigate: ReturnType<typeof useNavigate>;
}) {
  return (
    <section>
      <h3 style={{ marginBottom: 8 }}>Authentication</h3>
      <p style={{ color: "var(--text-secondary)", marginBottom: 16 }}>
        Record a login session so Conxa can replay authenticated workflows. Auth is stored locally
        and never included in published installers.
      </p>
      <button
        className="btn-accent"
        onClick={() =>
          navigate(`/plugins/${encodeURIComponent(pluginId)}/record/__auth__`)
        }
      >
        Re-record login
      </button>
    </section>
  );
}

function TestTab({
  pluginId,
  doAction,
  pending,
}: {
  pluginId: string;
  doAction: (type: string, extra?: Record<string, unknown>) => Promise<void>;
  pending: boolean;
}) {
  return (
    <section>
      <h3 style={{ marginBottom: 8 }}>Test</h3>
      <p style={{ color: "var(--text-secondary)", marginBottom: 16 }}>
        Run a dry-run compilation to verify selectors before building.
      </p>
      <button
        className="btn-accent"
        disabled={pending}
        onClick={() => doAction("run_pipeline", { plugin_id: pluginId })}
      >
        {pending ? "Running…" : "Run pipeline check"}
      </button>
    </section>
  );
}

function BuildTab({
  doAction,
  pending,
}: {
  doAction: (type: string) => Promise<void>;
  pending: boolean;
}) {
  return (
    <section>
      <h3 style={{ marginBottom: 16 }}>Build</h3>
      <div style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 320 }}>
        <BuildRow
          label="Build plugin"
          description="Compile all workflows into a skill package."
          action="build_plugin"
          doAction={doAction}
          pending={pending}
        />
        <BuildRow
          label="Build installer"
          description="Package the skill bundle into a distributable .exe."
          action="build_installer"
          doAction={doAction}
          pending={pending}
        />
        <BuildRow
          label="Publish to cloud"
          description="Upload skill package to the Conxa registry."
          action="publish"
          doAction={doAction}
          pending={pending}
        />
      </div>
    </section>
  );
}

function BuildRow({
  label,
  description,
  action,
  doAction,
  pending,
}: {
  label: string;
  description: string;
  action: string;
  doAction: (type: string) => Promise<void>;
  pending: boolean;
}) {
  return (
    <div
      style={{
        background: "var(--bg-surface)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius)",
        padding: "12px 16px",
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        gap: 16,
      }}
    >
      <div>
        <div style={{ fontWeight: 600, marginBottom: 2 }}>{label}</div>
        <div style={{ color: "var(--text-secondary)", fontSize: 12 }}>{description}</div>
      </div>
      <button className="btn-accent" disabled={pending} onClick={() => doAction(action)}>
        Run
      </button>
    </div>
  );
}

function InstallTab({
  plugin,
  copied,
  onCopy,
}: {
  plugin: PluginInfo;
  copied: boolean;
  onCopy: () => void;
}) {
  const statusLabel =
    plugin.status === "ready"
      ? "Published"
      : plugin.status === "error"
      ? "Error"
      : "Unpublished";

  const statusColor =
    plugin.status === "ready"
      ? "var(--green)"
      : plugin.status === "error"
      ? "var(--red)"
      : "var(--accent)";

  return (
    <section>
      <h3 style={{ marginBottom: 16 }}>Install</h3>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <InfoRow label="Version" value={plugin.version ?? "—"} />
        <InfoRow
          label="Status"
          value={<span style={{ color: statusColor }}>{statusLabel}</span>}
        />
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "10px 16px",
            background: "var(--bg-surface)",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius)",
          }}
        >
          <span style={{ color: "var(--text-secondary)", fontSize: 13 }}>Installer</span>
          <button
            className="btn-accent"
            onClick={() => window.conxa.openExternal(`conxa://download/${encodeURIComponent(plugin.id)}`)}
          >
            Download .exe
          </button>
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "10px 16px",
            background: "var(--bg-surface)",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius)",
          }}
        >
          <span style={{ color: "var(--text-secondary)", fontSize: 13 }}>Share link</span>
          <button
            style={{
              padding: "6px 14px",
              border: "1px solid var(--border)",
              borderRadius: "var(--radius)",
              color: copied ? "var(--green)" : "var(--text-secondary)",
            }}
            onClick={onCopy}
          >
            {copied ? "Copied!" : "Copy link"}
          </button>
        </div>
      </div>
    </section>
  );
}

function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "10px 16px",
        background: "var(--bg-surface)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius)",
      }}
    >
      <span style={{ color: "var(--text-secondary)", fontSize: 13 }}>{label}</span>
      <span>{value}</span>
    </div>
  );
}
