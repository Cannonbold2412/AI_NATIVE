import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { cmd, CmdError } from "@/lib/ipc";
import { useBackendEvents } from "@/hooks/usePythonCmd";

type StepState = "pending" | "running" | "done" | "error";

interface CompileStep {
  id: string;
  label: string;
  state: StepState;
  startedAt?: number;
  endedAt?: number;
}

interface LogEntry {
  ts: number;
  message: string;
  level: string;
}

interface ApiCallEntry {
  task: string;
  kind: string;
  duration_ms: number;
  status: string;
}

interface CompileResult {
  skill_id: string;
  version: number;
  step_count: number;
}

const PIPELINE_STEPS: Omit<CompileStep, "state">[] = [
  { id: "normalize", label: "Normalize events" },
  { id: "dedupe", label: "Deduplicate actions" },
  { id: "enrich", label: "Enrich with DOM snapshots" },
  { id: "selectors", label: "Generate selectors" },
  { id: "assertions", label: "Build assertions" },
  { id: "recovery", label: "Build recovery blocks" },
  { id: "package", label: "Package skill" },
];

export function CompileProgress() {
  const { pluginId, sessionId } = useParams<{ pluginId: string; sessionId: string }>();
  const navigate = useNavigate();
  const [steps, setSteps] = useState<CompileStep[]>(
    PIPELINE_STEPS.map((s) => ({ ...s, state: "pending" as StepState }))
  );
  const [overallStatus, setOverallStatus] = useState<"running" | "done" | "error">("running");
  const [skillId, setSkillId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [apiCalls, setApiCalls] = useState<ApiCallEntry[]>([]);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!pluginId || !sessionId) return;
    setOverallStatus("running");
    setSkillId(null);
    setError(null);
    setLogs([]);
    setApiCalls([]);
    setSteps(
      PIPELINE_STEPS.map((s, i) => ({
        ...s,
        state: i === 0 ? "running" : "pending",
        startedAt: i === 0 ? Date.now() : undefined,
        endedAt: undefined,
      }))
    );
    cmd<CompileResult>("compile", { plugin_id: pluginId, session_id: sessionId })
      .then((result) => {
        setSkillId(result.skill_id);
        setOverallStatus("done");
        setSteps((prev) =>
          prev.map((s) => ({ ...s, state: "done", endedAt: s.endedAt ?? Date.now() }))
        );
      })
      .catch((e) => {
        setError(e instanceof CmdError ? e.message : String(e));
        setOverallStatus("error");
        setSteps((prev) =>
          prev.map((s) =>
            s.state === "running" ? { ...s, state: "error", endedAt: Date.now() } : s
          )
        );
      });
  }, [pluginId, sessionId]);

  // auto-scroll log panel
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [logs]);

  useBackendEvents((ev) => {
    const now = Date.now();

    if (ev.phase === "compile_log") {
      setLogs((prev) => [
        ...prev,
        {
          ts: (ev.ts as number) ?? now / 1000,
          message: String(ev.message ?? ""),
          level: String(ev.level ?? "info"),
        },
      ]);
    }

    if (ev.phase === "api_call") {
      setApiCalls((prev) => [
        ...prev,
        {
          task: String(ev.task ?? ""),
          kind: String(ev.kind ?? "text"),
          duration_ms: Number(ev.duration_ms ?? 0),
          status: String(ev.status ?? "ok"),
        },
      ]);
    }

    if (ev.phase === "pipeline_done") {
      setSteps((prev) =>
        prev.map((s, i) => {
          if (i <= 2) return { ...s, state: "done", endedAt: now };
          if (s.id === "selectors") return { ...s, state: "running", startedAt: now };
          return s;
        })
      );
    }

    if (ev.phase === "compiler_start") {
      setSteps((prev) =>
        prev.map((s) =>
          s.id === "selectors" && s.state !== "done"
            ? { ...s, state: "running", startedAt: s.startedAt ?? now }
            : s
        )
      );
    }

    if (ev.phase === "compile_step") {
      const { step, status } = ev as unknown as { phase: string; step: string; status: string };
      setSteps((prev) => {
        const idx = prev.findIndex((s) => s.id === step);
        if (idx === -1) return prev;
        return prev.map((s, i) => {
          if (i === idx) {
            return {
              ...s,
              state: status as StepState,
              startedAt: status === "running" ? (s.startedAt ?? now) : s.startedAt,
              endedAt: status === "done" || status === "error" ? now : s.endedAt,
            };
          }
          if (i === idx + 1 && status === "done") {
            return { ...s, state: "running", startedAt: now };
          }
          return s;
        });
      });
    }

    if (ev.phase === "compile_done") {
      setOverallStatus("done");
      setSkillId(ev.skill_id as string | null);
    }

    if (ev.phase === "compile_error") {
      const failedStep = String(ev.failed_step ?? "");
      setOverallStatus("error");
      setError(String(ev.message ?? "Compile failed"));
      setSteps((prev) =>
        prev.map((s) =>
          s.state === "running" || s.id === failedStep
            ? { ...s, state: "error", endedAt: now }
            : s
        )
      );
    }
  });

  function goToEditor() {
    if (!skillId) return;
    const fromParam = pluginId ? `?from=${encodeURIComponent(`/plugins/${pluginId}`)}` : "";
    navigate(`/edit/${encodeURIComponent(skillId)}${fromParam}`);
  }

  function goToPlugin() {
    if (!pluginId) return;
    navigate(`/plugins/${encodeURIComponent(pluginId)}`);
  }

  const doneCount = steps.filter((s) => s.state === "done").length;
  const pct = Math.round((doneCount / steps.length) * 100);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", gap: 0 }}>
      {/* Header */}
      <div style={{ padding: "16px 20px 12px", borderBottom: "1px solid var(--border)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 10 }}>
          <button
            onClick={goToPlugin}
            style={{
              background: "none",
              border: "1px solid var(--border)",
              borderRadius: "var(--radius)",
              padding: "4px 10px",
              color: "var(--text-secondary)",
              cursor: "pointer",
              fontSize: 13,
            }}
          >
            ← Back
          </button>
          <h2 style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>Compiling workflow</h2>
          <span
            style={{
              fontSize: 11,
              padding: "2px 8px",
              borderRadius: 4,
              background:
                overallStatus === "done"
                  ? "color-mix(in oklch, var(--green) 15%, transparent)"
                  : overallStatus === "error"
                  ? "color-mix(in oklch, var(--red) 15%, transparent)"
                  : "color-mix(in oklch, var(--accent) 15%, transparent)",
              color:
                overallStatus === "done"
                  ? "var(--green)"
                  : overallStatus === "error"
                  ? "var(--red)"
                  : "var(--accent)",
              border: `1px solid ${
                overallStatus === "done"
                  ? "color-mix(in oklch, var(--green) 30%, transparent)"
                  : overallStatus === "error"
                  ? "color-mix(in oklch, var(--red) 30%, transparent)"
                  : "color-mix(in oklch, var(--accent) 30%, transparent)"
              }`,
            }}
          >
            {overallStatus === "running"
              ? `Step ${doneCount + 1} of ${steps.length}`
              : overallStatus === "done"
              ? "Complete"
              : "Failed"}
          </span>
          <div style={{ flex: 1 }} />
          {overallStatus === "done" && skillId && (
            <button className="btn-accent" onClick={goToEditor}>
              Review steps →
            </button>
          )}
        </div>
        <ProgressBar pct={pct} status={overallStatus} />
      </div>

      {/* Three-panel body */}
      <div style={{ display: "flex", flex: 1, minHeight: 0, overflow: "hidden" }}>
        {/* Compile Log */}
        <div
          style={{
            flex: 1,
            display: "flex",
            flexDirection: "column",
            borderRight: "1px solid var(--border)",
            minWidth: 0,
          }}
        >
          <div
            style={{
              padding: "8px 14px",
              fontSize: 11,
              fontWeight: 600,
              color: "var(--text-secondary)",
              textTransform: "uppercase",
              letterSpacing: "0.06em",
              borderBottom: "1px solid var(--border)",
            }}
          >
            Compile Log
          </div>
          <div
            ref={logRef}
            style={{
              flex: 1,
              overflowY: "auto",
              padding: "8px 4px",
              fontFamily: "var(--font-mono, monospace)",
              fontSize: 12,
            }}
          >
            {logs.length === 0 ? (
              <div
                style={{
                  padding: "20px 14px",
                  color: "var(--text-muted)",
                  fontSize: 12,
                  fontStyle: "italic",
                }}
              >
                Waiting for compile to start…
              </div>
            ) : (
              logs.map((entry, i) => (
                <LogRow key={i} entry={entry} />
              ))
            )}
            {error && overallStatus === "error" && (
              <LogRow
                entry={{ ts: Date.now() / 1000, message: error, level: "error" }}
              />
            )}
          </div>
        </div>

        {/* Right column: Phase Timeline + API Calls */}
        <div
          style={{
            width: 280,
            flexShrink: 0,
            display: "flex",
            flexDirection: "column",
            overflow: "hidden",
          }}
        >
          {/* Phase Timeline */}
          <div
            style={{
              flex: "0 0 auto",
              maxHeight: 260,
              display: "flex",
              flexDirection: "column",
              minHeight: 0,
            }}
          >
            <div
              style={{
                padding: "8px 14px",
                fontSize: 11,
                fontWeight: 600,
                color: "var(--text-secondary)",
                textTransform: "uppercase",
                letterSpacing: "0.06em",
                borderBottom: "1px solid var(--border)",
                flexShrink: 0,
              }}
            >
              Phase Timeline
            </div>
            <div style={{ overflowY: "auto", padding: "6px 0" }}>
              {steps.map((step) => (
                <PhaseRow key={step.id} step={step} />
              ))}
            </div>
          </div>

          {/* API Calls */}
          <div
            style={{
              borderTop: "1px solid var(--border)",
              flex: 1,
              minHeight: 0,
              display: "flex",
              flexDirection: "column",
            }}
          >
            <div
              style={{
                padding: "8px 14px",
                fontSize: 11,
                fontWeight: 600,
                color: "var(--text-secondary)",
                textTransform: "uppercase",
                letterSpacing: "0.06em",
                borderBottom: "1px solid var(--border)",
                flexShrink: 0,
              }}
            >
              API Calls{" "}
              {apiCalls.length > 0 && (
                <span
                  style={{
                    fontWeight: 400,
                    color: "var(--accent)",
                    fontSize: 11,
                    textTransform: "none",
                  }}
                >
                  ({apiCalls.length})
                </span>
              )}
            </div>
            <div style={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
              {apiCalls.length === 0 ? (
                <div
                  style={{
                    padding: "10px 14px",
                    color: "var(--text-muted)",
                    fontSize: 11,
                    fontStyle: "italic",
                  }}
                >
                  No LLM calls yet
                </div>
              ) : (
                apiCalls.map((call, i) => <ApiCallRow key={i} call={call} />)
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function ProgressBar({ pct, status }: { pct: number; status: string }) {
  const color =
    status === "error" ? "var(--red)" : status === "done" ? "var(--green)" : "var(--accent)";
  return (
    <div
      style={{
        height: 4,
        background: "var(--bg-surface)",
        borderRadius: 2,
        overflow: "hidden",
      }}
    >
      <div
        style={{
          height: "100%",
          width: `${pct}%`,
          background: color,
          transition: "width 0.3s ease",
        }}
      />
    </div>
  );
}

function PhaseRow({ step }: { step: CompileStep }) {
  const elapsed =
    step.startedAt && step.endedAt
      ? ((step.endedAt - step.startedAt) / 1000).toFixed(1) + "s"
      : step.startedAt && step.state === "running"
      ? "…"
      : null;

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "5px 14px",
        opacity: step.state === "pending" ? 0.4 : 1,
      }}
    >
      <PhaseIcon state={step.state} />
      <span
        style={{
          fontSize: 12,
          flex: 1,
          fontWeight: step.state === "running" ? 600 : undefined,
          color:
            step.state === "error"
              ? "var(--red)"
              : step.state === "done"
              ? "var(--text-primary)"
              : "var(--text-secondary)",
        }}
      >
        {step.label}
      </span>
      {elapsed && (
        <span style={{ fontSize: 11, color: "var(--text-muted)" }}>{elapsed}</span>
      )}
    </div>
  );
}

function PhaseIcon({ state }: { state: StepState }) {
  if (state === "done")
    return (
      <span style={{ color: "var(--green)", width: 16, textAlign: "center", fontSize: 13 }}>
        ✓
      </span>
    );
  if (state === "error")
    return (
      <span style={{ color: "var(--red)", width: 16, textAlign: "center", fontSize: 13 }}>
        ✗
      </span>
    );
  if (state === "running") return <Spinner />;
  return (
    <span style={{ color: "var(--text-muted)", width: 16, textAlign: "center", fontSize: 11 }}>
      ○
    </span>
  );
}

function LogRow({ entry }: { entry: LogEntry }) {
  const isError = entry.level === "error";
  const isWarn = entry.level === "warn";
  const timeStr = new Date(entry.ts * 1000).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  return (
    <div
      style={{
        display: "flex",
        gap: 8,
        padding: "3px 14px",
        borderLeft: `2px solid ${isError ? "var(--red)" : isWarn ? "oklch(0.75 0.15 80)" : "transparent"}`,
        background: isError
          ? "color-mix(in oklch, var(--red) 6%, transparent)"
          : "transparent",
      }}
    >
      <span style={{ color: "var(--text-muted)", flexShrink: 0, fontSize: 11 }}>{timeStr}</span>
      <span
        style={{
          color: isError ? "var(--red)" : isWarn ? "oklch(0.75 0.15 80)" : "var(--text-secondary)",
          wordBreak: "break-word",
          fontSize: 12,
        }}
      >
        {entry.message}
      </span>
    </div>
  );
}

function ApiCallRow({ call }: { call: ApiCallEntry }) {
  const isOk = call.status === "ok";
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        padding: "4px 14px",
        fontSize: 11,
        borderBottom: "1px solid var(--border)",
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          background: isOk ? "var(--green)" : "var(--red)",
          flexShrink: 0,
        }}
      />
      <span style={{ flex: 1, color: "var(--text-secondary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {call.task}
      </span>
      <span style={{ color: "var(--text-muted)", flexShrink: 0 }}>
        {call.duration_ms > 0 ? `${(call.duration_ms / 1000).toFixed(1)}s` : ""}
      </span>
    </div>
  );
}

function Spinner() {
  return (
    <span
      style={{
        display: "inline-block",
        width: 12,
        height: 12,
        margin: "0 2px",
        border: "2px solid var(--border)",
        borderTopColor: "var(--accent)",
        borderRadius: "50%",
        animation: "spin 0.8s linear infinite",
        flexShrink: 0,
      }}
    />
  );
}
