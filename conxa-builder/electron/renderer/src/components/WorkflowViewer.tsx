import { useRef, useState } from "react";
import { ActionBadge } from "./ActionBadge";
import { useEditorStore } from "@/store/editorStore";

export type StepEditorDTO = {
  id: string;
  step_index: number;
  human_readable_description: string;
  action_type: string;
  intent: string;
  final_intent: string;
  url: string;
  target: Record<string, unknown>;
  selectors: Record<string, unknown>;
  anchors_signals: Record<string, unknown>[];
  anchors_recovery: Record<string, unknown>[];
  validation: Record<string, unknown>;
  recovery: Record<string, unknown>;
  value: unknown;
  scroll_mode: string | null;
  scroll_selector: string | null;
  scroll_amount: number | null;
  input_binding: string | null;
  action_payload: Record<string, unknown>;
  action_spec: Record<string, unknown>;
  frame: Record<string, unknown>;
  flags: { is_destructive: boolean; is_scroll: boolean; generic_intent: boolean };
  screenshot: { full_url: string | null; element_url: string | null; bbox: Record<string, number>; viewport: string; scroll_position: string };
  editable_fields: Record<string, boolean>;
  parameter_bindings: Record<string, unknown>[];
  check_kind?: string;
  check_pattern?: string;
  check_threshold?: number;
  check_selector?: string;
  check_text?: string;
};

type Props = {
  steps: StepEditorDTO[];
  onDelete: (index: number) => void;
  onAddAction: (kind: string) => void;
};

const ACTION_KINDS = [
  "click", "type", "navigate", "scroll", "select", "hover",
  "check", "assert", "wait", "fill", "keyboard_shortcut",
];

export function WorkflowViewer({ steps, onDelete, onAddAction }: Props) {
  const selected = useEditorStore((s) => s.selectedStepIndex);
  const setSelected = useEditorStore((s) => s.setSelectedStepIndex);
  const dirtySteps = useEditorStore((s) => s.dirtySteps);
  const [showAdd, setShowAdd] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        borderRight: "1px solid var(--border)",
        background: "var(--bg-sidebar)",
        minWidth: 0,
      }}
    >
      <div
        style={{
          padding: "12px 16px",
          borderBottom: "1px solid var(--border)",
          fontSize: 12,
          color: "var(--text-muted)",
          textTransform: "uppercase",
          letterSpacing: "0.06em",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <span>Steps ({steps.length})</span>
        <button
          style={{
            fontSize: 16,
            color: "var(--accent)",
            lineHeight: 1,
            padding: "0 2px",
          }}
          title="Add action"
          onClick={() => setShowAdd((v) => !v)}
        >
          +
        </button>
      </div>

      {showAdd && (
        <div
          style={{
            padding: "8px 12px",
            borderBottom: "1px solid var(--border)",
            display: "flex",
            flexWrap: "wrap",
            gap: 4,
          }}
        >
          {ACTION_KINDS.map((k) => (
            <button
              key={k}
              style={{
                padding: "3px 8px",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius)",
                fontSize: 11,
                color: "var(--text-secondary)",
              }}
              onClick={() => {
                onAddAction(k);
                setShowAdd(false);
              }}
            >
              {k}
            </button>
          ))}
        </div>
      )}

      <div style={{ flex: 1, overflowY: "auto" }}>
        {steps.length === 0 && (
          <div style={{ padding: 16, color: "var(--text-muted)", fontSize: 13 }}>
            No steps yet.
          </div>
        )}
        {steps.map((step) => {
          const isActive = selected === step.step_index;
          const isDirty = dirtySteps.has(step.step_index);
          const label =
            step.human_readable_description ||
            step.intent ||
            step.final_intent ||
            step.action_type;
          const compact = label.replace(/^Step\s+\d+:\s*/i, "").trim();

          return (
            <div
              key={step.id}
              onClick={() => setSelected(step.step_index)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "9px 12px",
                borderBottom: "1px solid var(--border)",
                cursor: "pointer",
                background: isActive ? "var(--bg-selected)" : undefined,
              }}
            >
              <span style={{ color: "var(--text-muted)", fontSize: 11, minWidth: 20 }}>
                {step.step_index + 1}
              </span>
              <ActionBadge action={step.action_type} />
              <span
                style={{
                  flex: 1,
                  fontSize: 12,
                  color: "var(--text-primary)",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
                title={label}
              >
                {compact}
              </span>
              {isDirty && (
                <span style={{ color: "var(--accent)", fontSize: 10 }} title="Unsaved changes">
                  ●
                </span>
              )}
              {confirmDelete === step.step_index ? (
                <span style={{ display: "flex", gap: 4 }}>
                  <button
                    style={{ color: "var(--red)", fontSize: 11 }}
                    onClick={(e) => {
                      e.stopPropagation();
                      onDelete(step.step_index);
                      setConfirmDelete(null);
                    }}
                  >
                    ✕
                  </button>
                  <button
                    style={{ color: "var(--text-muted)", fontSize: 11 }}
                    onClick={(e) => {
                      e.stopPropagation();
                      setConfirmDelete(null);
                    }}
                  >
                    ↩
                  </button>
                </span>
              ) : (
                <button
                  style={{ color: "var(--text-muted)", fontSize: 13, opacity: 0.5 }}
                  title="Delete step"
                  onClick={(e) => {
                    e.stopPropagation();
                    setConfirmDelete(step.step_index);
                  }}
                >
                  ×
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
