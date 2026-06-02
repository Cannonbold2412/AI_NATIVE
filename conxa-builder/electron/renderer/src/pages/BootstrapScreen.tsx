import { useEffect, useMemo, useState } from "react";
import { BackendEvent } from "@/lib/ipc";

type DepName = "chromium" | "nsis" | "runtime";
type DepState = "pending" | "downloading" | "installing" | "extracting" | "verifying" | "ready" | "error";

interface DepStatus {
  dep: DepName;
  status: DepState;
  pct?: number;
  message?: string;
  url?: string;
  fileName?: string;
  downloadedBytes?: number;
  totalBytes?: number;
  remainingBytes?: number;
  bytesPerSec?: number;
  etaSeconds?: number;
}

function statusLabel(s: DepStatus): string {
  switch (s.status) {
    case "pending": return "Waiting...";
    case "downloading": return s.pct != null ? `${s.pct}%` : "Downloading...";
    case "installing": return s.pct != null ? `${s.pct}%` : "Installing...";
    case "extracting": return "Extracting...";
    case "verifying": return "Verifying...";
    case "ready": return "Ready";
    case "error": return "Failed";
  }
}

const REQUIRED_DEPS: DepName[] = ["chromium", "nsis", "runtime"];

const DEP_LABELS: Record<DepName, string> = {
  chromium: "Chromium browser",
  nsis: "Installer builder (NSIS)",
  runtime: "Conxa runtime",
};

function initialDeps(): Record<DepName, DepStatus> {
  return {
    chromium: { dep: "chromium", status: "pending" },
    nsis: { dep: "nsis", status: "pending" },
    runtime: { dep: "runtime", status: "pending" },
  };
}

function numberField(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function formatBytes(value?: number): string | null {
  if (value == null || !Number.isFinite(value)) return null;
  const units = ["B", "KB", "MB", "GB"];
  let n = value;
  let unit = 0;
  while (n >= 1024 && unit < units.length - 1) {
    n /= 1024;
    unit += 1;
  }
  const digits = unit === 0 || n >= 100 ? 0 : 1;
  return `${n.toFixed(digits)} ${units[unit]}`;
}

function formatEta(seconds?: number): string | null {
  if (seconds == null || !Number.isFinite(seconds)) return null;
  if (seconds <= 1) return "about 1s left";
  if (seconds < 60) return `about ${Math.ceil(seconds)}s left`;
  const minutes = Math.ceil(seconds / 60);
  return `about ${minutes}m left`;
}

function progressDetail(dep: DepStatus): string | null {
  const parts: string[] = [];
  const downloaded = formatBytes(dep.downloadedBytes);
  const total = formatBytes(dep.totalBytes);
  const remaining = formatBytes(dep.remainingBytes);
  const speed = dep.bytesPerSec ? `${formatBytes(dep.bytesPerSec)}/s` : null;
  const eta = formatEta(dep.etaSeconds);

  if (dep.fileName && dep.status !== "ready") parts.push(dep.fileName);
  if (downloaded && total) parts.push(`${downloaded} of ${total}`);
  else if (downloaded) parts.push(`${downloaded} received`);
  if (remaining) parts.push(`${remaining} remaining`);
  if (speed) parts.push(speed);
  if (eta) parts.push(eta);

  if (!parts.length && dep.status === "installing") return "Installing required browser files...";
  if (!parts.length && dep.status === "extracting") return "Unpacking downloaded files...";
  if (!parts.length && dep.status === "verifying") return "Checking downloaded files...";
  if (!parts.length && dep.status === "error" && dep.message) return dep.message;
  return parts.length ? parts.join(" - ") : null;
}

export function BootstrapScreen({ onComplete }: { onComplete: () => void }) {
  const [deps, setDeps] = useState<Record<DepName, DepStatus>>(initialDeps);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [backendComplete, setBackendComplete] = useState(false);
  const [eventComplete, setEventComplete] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setDeps(initialDeps());
    setError(null);
    setBackendComplete(false);
    setEventComplete(false);

    const unsub = window.conxa.onEvent((ev: BackendEvent) => {
      if (ev.phase !== "bootstrap") return;

      const dep = ev.dep as DepName | undefined;
      if (!dep) {
        if (ev.status === "complete") {
          setEventComplete(true);
        }
        return;
      }
      if (!REQUIRED_DEPS.includes(dep)) return;

      setDeps((prev) => ({
        ...prev,
        [dep]: {
          dep,
          status: (ev.status as DepState) ?? "pending",
          pct: numberField(ev.pct),
          message: typeof ev.message === "string" ? ev.message : undefined,
          url: typeof ev.url === "string" ? ev.url : undefined,
          fileName: typeof ev.file_name === "string" ? ev.file_name : undefined,
          downloadedBytes: numberField(ev.downloaded_bytes),
          totalBytes: numberField(ev.total_bytes),
          remainingBytes: numberField(ev.remaining_bytes),
          bytesPerSec: numberField(ev.bytes_per_sec),
          etaSeconds: numberField(ev.eta_seconds),
        },
      }));
    });

    window.conxa
      .cmd("bootstrap", {})
      .then((res) => {
        if (cancelled) return;
        if (!res.ok) setError(res.message ?? "Bootstrap failed");
        else setBackendComplete(true);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      });

    return () => {
      cancelled = true;
      unsub();
    };
  }, [attempt]);

  useEffect(() => {
    const allReady = REQUIRED_DEPS.every((dep) => deps[dep].status === "ready");
    if (backendComplete && eventComplete && allReady) onComplete();
  }, [backendComplete, deps, eventComplete, onComplete]);

  const hasError = error || Object.values(deps).some((d) => d.status === "error");
  const firstDepError = Object.values(deps).find((d) => d.status === "error");
  const errorText = error ?? firstDepError?.message ?? "One or more components failed to download.";
  const allowUrl = firstDepError?.url;
  const rows = useMemo(() => REQUIRED_DEPS.map((dep) => deps[dep]), [deps]);

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        background: "#090b0d",
        color: "#e2e8f0",
        fontFamily: "system-ui, sans-serif",
        gap: 32,
        padding: 40,
      }}
    >
      <div style={{ textAlign: "center" }}>
        <h1 style={{ fontSize: 22, fontWeight: 600, marginBottom: 6 }}>
          Setting up Conxa Build Studio
        </h1>
        <p style={{ color: "#94a3b8", fontSize: 14 }}>
          Downloading required components. This happens once and is required.
        </p>
      </div>

      <div style={{ width: "100%", maxWidth: 560, display: "flex", flexDirection: "column", gap: 12 }}>
        {rows.map((d) => (
          <DepRow key={d.dep} dep={d} />
        ))}
      </div>

      {hasError && (
        <div
          style={{
            background: "#1e1215",
            border: "1px solid #7f1d1d",
            borderRadius: 8,
            padding: "12px 16px",
            maxWidth: 560,
            width: "100%",
            fontSize: 13,
            color: "#fca5a5",
            display: "flex",
            flexDirection: "column",
            gap: 10,
          }}
        >
          <span>{errorText}</span>
          <span style={{ color: "#94a3b8" }}>
            Setup is required before Conxa Build Studio can open. Check your internet connection and retry.
            {allowUrl ? ` If your network blocks downloads, allow: ${allowUrl}` : ""}
          </span>
          <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
            <button
              onClick={() => setAttempt((n) => n + 1)}
              style={{
                padding: "7px 14px",
                background: "#1d4ed8",
                border: "1px solid #2563eb",
                borderRadius: 6,
                color: "#eff6ff",
                cursor: "pointer",
                fontSize: 13,
              }}
            >
              Retry setup
            </button>
            <button
              onClick={() => window.conxa.windowControls.close()}
              style={{
                padding: "7px 14px",
                background: "transparent",
                border: "1px solid #475569",
                borderRadius: 6,
                color: "#94a3b8",
                cursor: "pointer",
                fontSize: 13,
              }}
            >
              Quit
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function DepRow({ dep }: { dep: DepStatus }) {
  const label = DEP_LABELS[dep.dep] ?? dep.dep;
  const isReady = dep.status === "ready";
  const isError = dep.status === "error";
  const isActive = ["downloading", "installing", "extracting", "verifying"].includes(dep.status);
  const detail = progressDetail(dep);
  const progressPct = dep.pct != null ? Math.max(0, Math.min(100, dep.pct)) : undefined;

  return (
    <div
      style={{
        background: "#0f1117",
        border: `1px solid ${isError ? "#7f1d1d" : isReady ? "#14532d" : "#1e293b"}`,
        borderRadius: 8,
        padding: "12px 16px",
        display: "flex",
        alignItems: "center",
        gap: 12,
        minHeight: 70,
      }}
    >
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 14, fontWeight: 600, marginBottom: isActive ? 6 : 0 }}>
          {label}
        </div>
        {isActive && (
          <div
            style={{
              height: 4,
              background: "#1e293b",
              borderRadius: 2,
              overflow: "hidden",
            }}
          >
            <div
              style={{
                height: "100%",
                width: `${progressPct ?? 36}%`,
                background: "#3b82f6",
                borderRadius: 2,
                transition: "width 0.2s",
                opacity: progressPct == null ? 0.55 : 1,
              }}
            />
          </div>
        )}
        {detail && (
          <div
            style={{
              marginTop: 7,
              color: isError ? "#fca5a5" : "#94a3b8",
              fontSize: 12,
              lineHeight: 1.35,
              overflowWrap: "anywhere",
            }}
          >
            {detail}
          </div>
        )}
      </div>
      <span
        style={{
          fontSize: 13,
          color: isReady ? "#4ade80" : isError ? "#f87171" : "#64748b",
          minWidth: 96,
          textAlign: "right",
        }}
      >
        {statusLabel(dep)}
      </span>
    </div>
  );
}
