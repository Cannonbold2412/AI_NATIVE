import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { cmd, CmdError } from "@/lib/ipc";
import { useBackendEvents } from "@/hooks/usePythonCmd";

type StepState = "pending" | "running" | "done" | "error";

interface CompileStep {
  id: string;
  label: string;
  state: StepState;
  detail?: string;
}

const PIPELINE_STEPS: Omit<CompileStep, "state" | "detail">[] = [
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

  useEffect(() => {
    if (!pluginId || !sessionId) return;
    cmd("compile", { plugin_id: pluginId, session_id: sessionId }).catch((e) => {
      setError(e instanceof CmdError ? e.message : String(e));
      setOverallStatus("error");
    });
    // Mark first step as running immediately
    setSteps((prev) =>
      prev.map((s, i) => (i === 0 ? { ...s, state: "running" } : s))
    );
  }, [pluginId, sessionId]);

  useBackendEvents((ev) => {
    if (ev.phase === "compile_step") {
      const { step, status, detail } = ev as unknown as {
        phase: string;
        step: string;
        status: string;
        detail?: string;
      };
      setSteps((prev) => {
        const idx = prev.findIndex((s) => s.id === step);
        if (idx === -1) return prev;
        const next = prev.map((s, i) => {
          if (i === idx) return { ...s, state: status as StepState, detail };
          if (i === idx + 1 && status === "done") return { ...s, state: "running" as StepState };
          return s;
        });
        return next;
      });
    }
    if (ev.phase === "compile_done") {
      setOverallStatus("done");
      setSkillId(ev.skill_id as string | null);
    }
    if (ev.phase === "compile_error") {
      setOverallStatus("error");
      setError(String(ev.message ?? "Compile failed"));
      setSteps((prev) =>
        prev.map((s) => (s.state === "running" ? { ...s, state: "error" } : s))
      );
    }
  }, sessionId ?? undefined);

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
    <div style={{ maxWidth: 560 }}>
      <h2 style={{ marginBottom: 4 }}>Compiling workflow</h2>
      <p style={{ color: "var(--text-secondary)", marginBottom: 20, fontSize: 13 }}>
        {overallStatus === "running"
          ? `Step ${doneCount + 1} of ${steps.length}`
          : overallStatus === "done"
          ? "Compilation complete"
          : "Compilation failed"}
      </p>

      <ProgressBar pct={pct} status={overallStatus} />

      <div style={{ marginTop: 20, marginBottom: 20 }}>
        {steps.map((step) => (
          <div key={step.id} className="compile-step">
            <StateIcon state={step.state} />
            <div>
              <div style={{ fontWeight: step.state === "running" ? 600 : undefined }}>
                {step.label}
              </div>
              {step.detail && (
                <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 2 }}>
                  {step.detail}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>

      {error && <div className="banner-error" style={{ marginBottom: 16 }}>{error}</div>}

      {overallStatus === "done" && (
        <div className="banner-ok" style={{ marginBottom: 16 }}>
          Workflow compiled successfully.
        </div>
      )}

      <div style={{ display: "flex", gap: 8 }}>
        {overallStatus === "done" && skillId && (
          <button className="btn-accent" onClick={goToEditor}>
            Review steps →
          </button>
        )}
        <button
          style={{
            padding: "8px 14px",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius)",
            color: "var(--text-secondary)",
          }}
          onClick={goToPlugin}
        >
          Back to plugin
        </button>
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
        height: 6,
        background: "var(--bg-surface)",
        borderRadius: 3,
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

function StateIcon({ state }: { state: StepState }) {
  if (state === "done") return <span style={{ color: "var(--green)", width: 20, textAlign: "center" }}>✓</span>;
  if (state === "error") return <span style={{ color: "var(--red)", width: 20, textAlign: "center" }}>✗</span>;
  if (state === "running") return <Spinner />;
  return <span style={{ color: "var(--text-muted)", width: 20, textAlign: "center" }}>○</span>;
}

function Spinner() {
  return (
    <span
      style={{
        display: "inline-block",
        width: 14,
        height: 14,
        margin: "0 3px",
        border: "2px solid var(--border)",
        borderTopColor: "var(--accent)",
        borderRadius: "50%",
        animation: "spin 0.8s linear infinite",
        flexShrink: 0,
      }}
    />
  );
}
