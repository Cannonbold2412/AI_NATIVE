import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { cmd, CmdError } from "@/lib/ipc";
import { WorkflowViewer, type StepEditorDTO } from "@/components/WorkflowViewer";
import { StepEditorPanel, type StepEditorPanelHandle } from "@/components/StepEditorPanel";
import { ValidationReportPanel } from "@/components/ValidationReportPanel";
import { SuggestionsPanel } from "@/components/SuggestionsPanel";
import { useEditorStore } from "@/store/editorStore";

interface WorkflowResponse {
  skill_id: string;
  package_meta: Record<string, unknown>;
  inputs: Record<string, unknown>[];
  steps: StepEditorDTO[];
  suggestions: { step_index: number; severity: "info" | "warn" | "error"; code: string; message: string }[];
  asset_base_url: string;
}

type ToolPane = "suggestions" | "validation" | null;

export function StepEditor() {
  const { pluginId, skillId } = useParams<{ pluginId: string; skillId: string }>();
  const navigate = useNavigate();

  const [workflow, setWorkflow] = useState<WorkflowResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [toolPane, setToolPane] = useState<ToolPane>("suggestions");
  const [leftWidth, setLeftWidth] = useState(260);
  const [rightWidth, setRightWidth] = useState(320);
  const [isResizingLeft, setIsResizingLeft] = useState(false);
  const [isResizingRight, setIsResizingRight] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const stepEditorRef = useRef<StepEditorPanelHandle>(null);

  const selected = useEditorStore((s) => s.selectedStepIndex);
  const setSelected = useEditorStore((s) => s.setSelectedStepIndex);
  const setValidationReport = useEditorStore((s) => s.setValidationReport);
  const validationReport = useEditorStore((s) => s.validationReport);
  const dirtySteps = useEditorStore((s) => s.dirtySteps);

  useEffect(() => {
    if (!skillId) return;
    setLoading(true);
    setLoadError(null);
    cmd<{ workflow: WorkflowResponse }>("get_workflow", { skill_id: skillId })
      .then((r) => {
        setWorkflow(r.workflow);
        if (r.workflow.steps.length > 0) setSelected(0);
      })
      .catch((e) => setLoadError(e instanceof CmdError ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [skillId]);

  const onWorkflowUpdated = useCallback((wf: unknown) => {
    setWorkflow(wf as WorkflowResponse);
  }, []);

  const currentStep = useMemo(() => {
    if (!workflow || selected === null) return null;
    return workflow.steps.find((s) => s.step_index === selected) ?? null;
  }, [workflow, selected]);

  async function onDelete(index: number) {
    if (!skillId) return;
    setActionError(null);
    try {
      const r = await cmd<{ workflow: WorkflowResponse }>("delete_step", {
        skill_id: skillId,
        step_index: index,
      });
      setWorkflow(r.workflow);
      const n = r.workflow.steps.length;
      if (n === 0) setSelected(null);
      else if (selected !== null) {
        if (index < selected) setSelected(selected - 1);
        else if (index === selected) setSelected(Math.min(selected, n - 1));
      }
    } catch (e) {
      setActionError(e instanceof CmdError ? e.message : String(e));
    }
  }

  async function onAddAction(kind: string) {
    if (!skillId) return;
    setActionError(null);
    try {
      const savedOk = await (stepEditorRef.current?.submitIfDirty() ?? Promise.resolve(true));
      if (!savedOk) {
        setActionError("Save the open step before adding a new action.");
        return;
      }
      const steps = workflow?.steps ?? [];
      const insertAfter = selected ?? (steps.length > 0 ? steps.length - 1 : null);
      const r = await cmd<{ workflow: WorkflowResponse }>("insert_step", {
        skill_id: skillId,
        action_kind: kind,
        insert_after: insertAfter,
      });
      onWorkflowUpdated(r.workflow);
      const nextIndex = insertAfter === null ? r.workflow.steps.length - 1 : insertAfter + 1;
      setSelected(nextIndex);
    } catch (e) {
      setActionError(e instanceof CmdError ? e.message : String(e));
    }
  }

  async function runValidate() {
    if (!skillId) return;
    try {
      const r = await cmd<{ report: Record<string, unknown> }>("validate_workflow", { skill_id: skillId });
      setValidationReport(r.report);
      setToolPane("validation");
    } catch (e) {
      setValidationReport({ error: e instanceof CmdError ? e.message : String(e) });
      setToolPane("validation");
    }
  }

  async function finishEditing() {
    if (!skillId) return;
    setActionError(null);
    const savedOk = await (stepEditorRef.current?.submitIfDirty() ?? Promise.resolve(true));
    if (!savedOk) {
      setActionError("Save the open step before finishing.");
      return;
    }
    if (dirtySteps.size > 0) {
      setActionError(`Unsaved changes on ${dirtySteps.size} step(s) — save each before finishing.`);
      return;
    }
    try {
      await cmd("sign_off", { skill_id: skillId });
    } catch {
      // non-fatal
    }
    if (pluginId) {
      navigate(`/plugins/${encodeURIComponent(pluginId)}`);
    }
  }

  // Left pane resize
  useEffect(() => {
    if (!isResizingLeft) return;
    const onMove = (e: MouseEvent) => {
      const rect = containerRef.current?.getBoundingClientRect();
      if (!rect) return;
      setLeftWidth(Math.max(200, Math.min(480, e.clientX - rect.left)));
    };
    const onUp = () => {
      setIsResizingLeft(false);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
  }, [isResizingLeft]);

  // Right pane resize
  useEffect(() => {
    if (!isResizingRight) return;
    const onMove = (e: MouseEvent) => {
      const rect = containerRef.current?.getBoundingClientRect();
      if (!rect) return;
      setRightWidth(Math.max(240, Math.min(520, rect.right - e.clientX)));
    };
    const onUp = () => {
      setIsResizingRight(false);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
  }, [isResizingRight]);

  if (loading) {
    return <div style={{ padding: 32, color: "var(--text-secondary)" }}>Loading workflow…</div>;
  }
  if (loadError) {
    return <div className="banner-error" style={{ margin: 32 }}>{loadError}</div>;
  }
  if (!workflow) return null;

  const title =
    typeof workflow.package_meta.title === "string" && workflow.package_meta.title.trim()
      ? workflow.package_meta.title.trim()
      : skillId ?? "Skill";

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        margin: "-24px -32px",
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "10px 20px",
          borderBottom: "1px solid var(--border)",
          background: "var(--bg-sidebar)",
          flexShrink: 0,
        }}
      >
        <div>
          <span style={{ fontWeight: 600 }}>{title}</span>
          <span style={{ marginLeft: 8, fontSize: 12, color: "var(--text-muted)", fontFamily: "monospace" }}>
            {skillId}
          </span>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {actionError && (
            <span style={{ fontSize: 12, color: "var(--red)", maxWidth: 260 }}>{actionError}</span>
          )}
          <button
            style={{
              padding: "6px 12px",
              border: "1px solid var(--border)",
              borderRadius: "var(--radius)",
              color: "var(--text-secondary)",
              fontSize: 13,
            }}
            onClick={() => void runValidate()}
          >
            Check issues
          </button>
          <button className="btn-accent" onClick={() => void finishEditing()}>
            Finish
          </button>
        </div>
      </div>

      {/* Three-panel body */}
      <div
        ref={containerRef}
        style={{
          display: "flex",
          flex: 1,
          minHeight: 0,
          overflow: "hidden",
        }}
      >
        {/* Left: workflow list */}
        <div style={{ width: leftWidth, flexShrink: 0, minHeight: 0, overflow: "hidden" }}>
          <WorkflowViewer
            steps={workflow.steps}
            onDelete={onDelete}
            onAddAction={onAddAction}
          />
        </div>

        {/* Left resize handle */}
        <div
          style={{
            width: 6,
            cursor: "col-resize",
            background: "var(--border)",
            flexShrink: 0,
            transition: "background 0.1s",
          }}
          onMouseDown={(e) => {
            e.preventDefault();
            setIsResizingLeft(true);
          }}
        />

        {/* Middle: step editor */}
        <div style={{ flex: 1, minWidth: 0, minHeight: 0, overflow: "hidden" }}>
          <StepEditorPanel
            ref={stepEditorRef}
            step={currentStep}
            skillId={skillId!}
            onWorkflowUpdated={onWorkflowUpdated}
          />
        </div>

        {/* Right resize handle */}
        {toolPane && (
          <div
            style={{
              width: 6,
              cursor: "col-resize",
              background: "var(--border)",
              flexShrink: 0,
            }}
            onMouseDown={(e) => {
              e.preventDefault();
              setIsResizingRight(true);
            }}
          />
        )}

        {/* Right: tools panel */}
        <div
          style={{
            width: rightWidth,
            flexShrink: 0,
            borderLeft: "1px solid var(--border)",
            display: "flex",
            flexDirection: "column",
            minHeight: 0,
          }}
        >
          {/* Tools tab strip */}
          <div
            style={{
              display: "flex",
              borderBottom: "1px solid var(--border)",
              background: "var(--bg-sidebar)",
              flexShrink: 0,
            }}
          >
            {(["suggestions", "validation"] as ToolPane[]).map((pane) => (
              <button
                key={pane}
                style={{
                  flex: 1,
                  padding: "8px",
                  fontSize: 12,
                  color: toolPane === pane ? "var(--text-primary)" : "var(--text-secondary)",
                  borderBottom: toolPane === pane ? "2px solid var(--accent)" : "2px solid transparent",
                }}
                onClick={() => setToolPane(toolPane === pane ? null : pane)}
              >
                {pane === "suggestions"
                  ? `Suggestions${workflow.suggestions.length > 0 ? ` (${workflow.suggestions.length})` : ""}`
                  : "Validation"}
              </button>
            ))}
          </div>

          {/* Tool content */}
          <div style={{ flex: 1, overflowY: "auto", padding: 12 }}>
            {toolPane === "suggestions" && (
              <SuggestionsPanel
                suggestions={workflow.suggestions}
                onSelectStep={(idx) => setSelected(idx)}
              />
            )}
            {toolPane === "validation" && (
              validationReport ? (
                <ValidationReportPanel data={validationReport} />
              ) : (
                <div style={{ color: "var(--text-muted)", fontSize: 13 }}>
                  Click "Check issues" to run validation.
                </div>
              )
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
