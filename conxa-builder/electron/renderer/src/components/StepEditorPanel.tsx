import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { cmd, CmdError } from "@/lib/ipc";
import { useEditorStore } from "@/store/editorStore";
import type { StepEditorDTO } from "./WorkflowViewer";

export interface StepEditorPanelHandle {
  submitIfDirty: () => Promise<boolean>;
}

type Props = {
  step: StepEditorDTO | null;
  skillId: string;
  onWorkflowUpdated: (wf: unknown) => void;
};

type FormState = {
  intent: string;
  url: string;
  primarySelector: string;
  fallbackSelectors: string[];
  value: string;
  css: string;
  aria: string;
  text_based: string;
  xpath: string;
};

function buildForm(step: StepEditorDTO): FormState {
  const tgt = step.target as { primary_selector?: string; fallback_selectors?: string[] };
  const sel = step.selectors as { css?: string; aria?: string; text_based?: string; xpath?: string };
  const ap = step.action_payload || {};
  return {
    intent: step.intent || step.final_intent || "",
    url: step.url || "",
    primarySelector: String(tgt.primary_selector || ""),
    fallbackSelectors: (tgt.fallback_selectors || []).map(String),
    value:
      typeof step.value === "string"
        ? step.value
        : typeof ap.value === "string"
        ? ap.value
        : ap.ms != null
        ? String(ap.ms)
        : "",
    css: String(sel.css || ""),
    aria: String(sel.aria || ""),
    text_based: String(sel.text_based || ""),
    xpath: String(sel.xpath || ""),
  };
}

export const StepEditorPanel = forwardRef<StepEditorPanelHandle, Props>(
  function StepEditorPanel({ step, skillId, onWorkflowUpdated }, ref) {
    const markDirty = useEditorStore((s) => s.markStepDirty);
    const clearDirty = useEditorStore((s) => s.clearStepDirty);
    const [form, setForm] = useState<FormState | null>(null);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [saved, setSaved] = useState(false);
    const isDirtyRef = useRef(false);

    useEffect(() => {
      if (!step) {
        setForm(null);
        isDirtyRef.current = false;
        return;
      }
      setForm(buildForm(step));
      isDirtyRef.current = false;
      setError(null);
      setSaved(false);
    }, [step?.id]);

    function patch<K extends keyof FormState>(key: K, value: FormState[K]) {
      setForm((prev) => (prev ? { ...prev, [key]: value } : prev));
      if (step) markDirty(step.step_index);
      isDirtyRef.current = true;
      setSaved(false);
    }

    async function save(): Promise<boolean> {
      if (!step || !form) return true;
      setSaving(true);
      setError(null);
      try {
        const payload = {
          skill_id: skillId,
          step_index: step.step_index,
          intent: form.intent,
          url: form.url,
          primary_selector: form.primarySelector,
          fallback_selectors: form.fallbackSelectors.filter(Boolean),
          value: form.value,
          selectors: {
            css: form.css,
            aria: form.aria,
            text_based: form.text_based,
            xpath: form.xpath,
          },
        };
        const r = await cmd<{ workflow: unknown }>("patch_step", payload);
        onWorkflowUpdated(r.workflow);
        clearDirty(step.step_index);
        isDirtyRef.current = false;
        setSaved(true);
        return true;
      } catch (e) {
        setError(e instanceof CmdError ? e.message : String(e));
        return false;
      } finally {
        setSaving(false);
      }
    }

    useImperativeHandle(ref, () => ({
      submitIfDirty: () => (isDirtyRef.current ? save() : Promise.resolve(true)),
    }));

    if (!step || !form) {
      return (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            height: "100%",
            color: "var(--text-muted)",
            fontSize: 14,
          }}
        >
          Select a step to edit
        </div>
      );
    }

    const isScroll = step.flags.is_scroll;
    const isNavigate = step.action_type === "navigate";

    return (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          height: "100%",
          overflowY: "auto",
          padding: "16px 20px",
          gap: 16,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div>
            <div style={{ fontSize: 13, fontWeight: 600 }}>
              Step {step.step_index + 1} — {step.action_type}
            </div>
            <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
              {step.url}
            </div>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            {saved && (
              <span style={{ color: "var(--green)", fontSize: 12 }}>Saved ✓</span>
            )}
            <button
              className="btn-accent"
              disabled={saving}
              onClick={() => void save()}
              style={{ padding: "6px 14px", fontSize: 13 }}
            >
              {saving ? "Saving…" : "Save step"}
            </button>
          </div>
        </div>

        {error && <div className="banner-error">{error}</div>}

        <Field label="Intent">
          <input
            style={inputStyle}
            value={form.intent}
            onChange={(e) => patch("intent", e.target.value)}
            placeholder="Describe what this step does"
          />
        </Field>

        {isNavigate && (
          <Field label="URL">
            <input
              style={inputStyle}
              value={form.url}
              onChange={(e) => patch("url", e.target.value)}
              placeholder="https://…"
            />
          </Field>
        )}

        {!isScroll && !isNavigate && (
          <>
            <Field label="Primary selector">
              <input
                style={{ ...inputStyle, fontFamily: "monospace", fontSize: 12 }}
                value={form.primarySelector}
                onChange={(e) => patch("primarySelector", e.target.value)}
                placeholder="[data-testid=submit]"
              />
            </Field>

            <Field label="Fallback selectors">
              {form.fallbackSelectors.map((sel, i) => (
                <div key={i} style={{ display: "flex", gap: 6, marginTop: i > 0 ? 4 : 0 }}>
                  <input
                    style={{ ...inputStyle, flex: 1, fontFamily: "monospace", fontSize: 12 }}
                    value={sel}
                    onChange={(e) => {
                      const next = [...form.fallbackSelectors];
                      next[i] = e.target.value;
                      patch("fallbackSelectors", next);
                    }}
                    placeholder={`Fallback ${i + 1}`}
                  />
                  <button
                    style={{ color: "var(--text-muted)", fontSize: 16 }}
                    onClick={() => {
                      const next = form.fallbackSelectors.filter((_, j) => j !== i);
                      patch("fallbackSelectors", next);
                    }}
                  >
                    ×
                  </button>
                </div>
              ))}
              <button
                style={{
                  marginTop: 6,
                  fontSize: 12,
                  color: "var(--accent)",
                  padding: "2px 0",
                }}
                onClick={() => patch("fallbackSelectors", [...form.fallbackSelectors, ""])}
              >
                + Add fallback
              </button>
            </Field>

            <Field label="Typed value / text">
              <input
                style={inputStyle}
                value={form.value}
                onChange={(e) => patch("value", e.target.value)}
                placeholder="Value to type or select"
              />
            </Field>
          </>
        )}

        {isScroll && (
          <Field label="Scroll amount (px)">
            <input
              style={inputStyle}
              value={form.value}
              onChange={(e) => patch("value", e.target.value)}
              placeholder="300"
              type="number"
            />
          </Field>
        )}

        <details>
          <summary
            style={{
              cursor: "pointer",
              fontSize: 12,
              color: "var(--text-secondary)",
              userSelect: "none",
              padding: "4px 0",
            }}
          >
            Selector signals (CSS · ARIA · text · XPath)
          </summary>
          <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 8 }}>
            {(["css", "aria", "text_based", "xpath"] as const).map((key) => (
              <Field key={key} label={key}>
                <input
                  style={{ ...inputStyle, fontFamily: "monospace", fontSize: 12 }}
                  value={form[key]}
                  onChange={(e) => patch(key, e.target.value)}
                />
              </Field>
            ))}
          </div>
        </details>

        {step.screenshot?.full_url && (
          <details>
            <summary
              style={{
                cursor: "pointer",
                fontSize: 12,
                color: "var(--text-secondary)",
                userSelect: "none",
                padding: "4px 0",
              }}
            >
              Screenshot
            </summary>
            <img
              src={step.screenshot.full_url}
              alt="step screenshot"
              style={{ maxWidth: "100%", marginTop: 8, borderRadius: "var(--radius)" }}
            />
          </details>
        )}
      </div>
    );
  }
);

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label
        style={{
          display: "block",
          fontSize: 11,
          color: "var(--text-muted)",
          textTransform: "uppercase",
          letterSpacing: "0.06em",
          marginBottom: 4,
        }}
      >
        {label}
      </label>
      {children}
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  display: "block",
  width: "100%",
  padding: "7px 10px",
  background: "var(--bg-surface)",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius)",
  color: "var(--text-primary)",
  fontSize: 13,
};
