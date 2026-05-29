import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { cmd, CmdError } from "@/lib/ipc";
import { useBackendEvents } from "@/hooks/usePythonCmd";
import { ActionBadge } from "@/components/ActionBadge";

interface FeedEvent {
  seq: number;
  ts: number;
  action: string;
  selector?: string;
  value?: string;
  url?: string;
  screenshot?: string;
  expanded: boolean;
}

export function RecordingFeed() {
  const { pluginId, workflowName } = useParams<{ pluginId: string; workflowName: string }>();
  const navigate = useNavigate();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [events, setEvents] = useState<FeedEvent[]>([]);
  const [status, setStatus] = useState<"idle" | "recording" | "stopping" | "done">("idle");
  const [error, setError] = useState<string | null>(null);
  const seqRef = useRef(0);
  const bottomRef = useRef<HTMLDivElement>(null);

  const isAuth = workflowName === "__auth__";

  useEffect(() => {
    if (!pluginId || !workflowName) return;
    start();
  }, [pluginId, workflowName]);

  useBackendEvents((ev) => {
    if (ev.phase === "recording") {
      setEvents((prev) => [
        ...prev,
        {
          seq: seqRef.current++,
          ts: Date.now(),
          action: ev.action ?? "action",
          selector: ev.selector,
          value: ev.value,
          url: ev.url,
          screenshot: ev.screenshot,
          expanded: false,
        },
      ]);
    }
    if (ev.phase === "recording_stopped") {
      setStatus("done");
      if (ev.session_id) setSessionId(ev.session_id);
    }
  }, sessionId ?? undefined);

  async function start() {
    setError(null);
    setStatus("recording");
    try {
      const r = await cmd<{ session_id: string }>("start_recording", {
        plugin_id: pluginId,
        workflow_name: workflowName,
      });
      setSessionId(r.session_id);
    } catch (e) {
      setError(e instanceof CmdError ? e.message : String(e));
      setStatus("idle");
    }
  }

  async function stop() {
    if (!sessionId) return;
    setStatus("stopping");
    try {
      await cmd("stop_recording", { session_id: sessionId });
    } catch (e) {
      setError(e instanceof CmdError ? e.message : String(e));
      setStatus("recording");
    }
  }

  async function compile() {
    if (!sessionId || !pluginId) return;
    try {
      const r = await cmd<{ job_id: string }>("compile", {
        plugin_id: pluginId,
        session_id: sessionId,
      });
      navigate(`/plugins/${encodeURIComponent(pluginId)}/compile/${encodeURIComponent(r.job_id)}`);
    } catch (e) {
      setError(e instanceof CmdError ? e.message : String(e));
    }
  }

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events.length]);

  function toggle(seq: number) {
    setEvents((prev) =>
      prev.map((ev) => (ev.seq === seq ? { ...ev, expanded: !ev.expanded } : ev))
    );
  }

  const title = isAuth ? "Recording login" : `Recording: ${workflowName}`;

  return (
    <div style={{ maxWidth: 700 }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 20,
        }}
      >
        <div>
          <h2 style={{ marginBottom: 4 }}>{title}</h2>
          <StatusChip status={status} count={events.length} />
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          {status === "recording" && (
            <button
              style={{
                padding: "8px 16px",
                background: "var(--red)",
                color: "#fff",
                borderRadius: "var(--radius)",
                fontWeight: 600,
              }}
              onClick={stop}
            >
              Stop recording
            </button>
          )}
          {status === "done" && !isAuth && (
            <button className="btn-accent" onClick={compile}>
              Compile →
            </button>
          )}
          {status === "done" && isAuth && (
            <button
              className="btn-accent"
              onClick={() =>
                navigate(`/plugins/${encodeURIComponent(pluginId!)}`)
              }
            >
              Done
            </button>
          )}
        </div>
      </div>

      {error && <div className="banner-error" style={{ marginBottom: 16 }}>{error}</div>}

      <div
        style={{
          border: "1px solid var(--border)",
          borderRadius: "var(--radius)",
          overflow: "hidden",
        }}
      >
        {events.length === 0 && status === "recording" && (
          <div style={{ padding: 24, color: "var(--text-secondary)", textAlign: "center" }}>
            Waiting for browser actions…
          </div>
        )}
        {events.map((ev) => (
          <div key={ev.seq}>
            <div className="feed-row" onClick={() => toggle(ev.seq)} style={{ cursor: "pointer" }}>
              <ActionBadge action={ev.action} />
              <span style={{ color: "var(--text-muted)", fontSize: 12 }}>
                {formatTime(ev.ts)}
              </span>
              <span
                style={{
                  color: "var(--text-secondary)",
                  fontSize: 12,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {ev.selector ?? ev.url ?? ""}
              </span>
              <span style={{ color: "var(--text-muted)", fontSize: 12, textAlign: "right" }}>
                {ev.expanded ? "▲" : "▼"}
              </span>
            </div>
            {ev.expanded && (
              <div
                style={{
                  padding: "12px 16px",
                  background: "var(--bg-surface)",
                  borderBottom: "1px solid var(--border)",
                  fontSize: 12,
                  color: "var(--text-secondary)",
                }}
              >
                {ev.selector && (
                  <div style={{ marginBottom: 4 }}>
                    <strong>Selector:</strong>{" "}
                    <code style={{ fontFamily: "monospace" }}>{ev.selector}</code>
                  </div>
                )}
                {ev.value && (
                  <div style={{ marginBottom: 4 }}>
                    <strong>Value:</strong> {ev.value}
                  </div>
                )}
                {ev.url && (
                  <div style={{ marginBottom: 4 }}>
                    <strong>URL:</strong> {ev.url}
                  </div>
                )}
                {ev.screenshot && (
                  <img
                    src={ev.screenshot}
                    alt="screenshot"
                    style={{ marginTop: 8, maxWidth: "100%", borderRadius: 4 }}
                  />
                )}
              </div>
            )}
          </div>
        ))}
      </div>
      <div ref={bottomRef} />
    </div>
  );
}

function StatusChip({ status, count }: { status: string; count: number }) {
  const label =
    status === "recording"
      ? `● Recording — ${count} action${count !== 1 ? "s" : ""}`
      : status === "stopping"
      ? "Stopping…"
      : status === "done"
      ? `✓ Done — ${count} action${count !== 1 ? "s" : ""}`
      : "Idle";

  const color =
    status === "recording"
      ? "var(--red)"
      : status === "done"
      ? "var(--green)"
      : "var(--text-secondary)";

  return <span style={{ fontSize: 13, color }}>{label}</span>;
}

function formatTime(ts: number) {
  const d = new Date(ts);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`;
}
