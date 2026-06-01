import { useEffect, useState } from "react";
import { BackendEvent } from "@/lib/ipc";

interface DepStatus {
  dep: string;
  status: "pending" | "downloading" | "ready" | "error";
  pct?: number;
  message?: string;
  url?: string;
}

function statusLabel(s: DepStatus): string {
  switch (s.status) {
    case "pending": return "Waiting…";
    case "downloading": return s.pct != null ? `${s.pct}%` : "Downloading…";
    case "ready": return "Ready";
    case "error": return s.message ?? "Failed";
  }
}

const DEP_LABELS: Record<string, string> = {
  chromium: "Chromium browser",
  nsis: "Installer builder (NSIS)",
  runtime: "Conxa runtime",
};

export function BootstrapScreen({ onComplete }: { onComplete: () => void }) {
  const [deps, setDeps] = useState<Record<string, DepStatus>>({
    chromium: { dep: "chromium", status: "pending" },
    nsis:     { dep: "nsis",     status: "pending" },
    runtime:  { dep: "runtime",  status: "pending" },
  });
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    const unsub = window.conxa.onEvent((ev: BackendEvent) => {
      if (ev.phase !== "bootstrap") return;

      const dep = ev.dep as string | undefined;
      if (!dep) {
        if (ev.status === "complete") {
          setDone(true);
        }
        return;
      }

      setDeps((prev) => ({
        ...prev,
        [dep]: {
          dep,
          status: (ev.status as DepStatus["status"]) ?? "pending",
          pct: ev.pct as number | undefined,
          message: ev.message as string | undefined,
          url: ev.url as string | undefined,
        },
      }));
    });

    // Fire bootstrap and handle errors.
    window.conxa
      .cmd("bootstrap", {})
      .then((res) => {
        if (!res.ok) setError(res.message ?? "Bootstrap failed");
        else setDone(true);
      })
      .catch((e) => setError(String(e)));

    return unsub;
  }, []);

  // Proceed once all deps are ready.
  useEffect(() => {
    if (done) onComplete();
  }, [done, onComplete]);

  const hasError = error || Object.values(deps).some((d) => d.status === "error");

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
          Downloading required components. This happens once.
        </p>
      </div>

      <div style={{ width: "100%", maxWidth: 440, display: "flex", flexDirection: "column", gap: 12 }}>
        {Object.values(deps).map((d) => (
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
            maxWidth: 440,
            width: "100%",
            fontSize: 13,
            color: "#fca5a5",
            display: "flex",
            flexDirection: "column",
            gap: 10,
          }}
        >
          <span>{error ?? "One or more components failed to download."}</span>
          <span style={{ color: "#94a3b8" }}>
            Check your internet connection and restart the app to retry.
            Recording and installer build will not work until setup completes.
          </span>
          <button
            onClick={onComplete}
            style={{
              marginTop: 4,
              padding: "6px 14px",
              background: "transparent",
              border: "1px solid #475569",
              borderRadius: 6,
              color: "#94a3b8",
              cursor: "pointer",
              fontSize: 13,
              alignSelf: "flex-start",
            }}
          >
            Continue without full setup →
          </button>
        </div>
      )}
    </div>
  );
}

function DepRow({ dep }: { dep: DepStatus }) {
  const label = DEP_LABELS[dep.dep] ?? dep.dep;
  const isReady = dep.status === "ready";
  const isError = dep.status === "error";
  const isDownloading = dep.status === "downloading";

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
      }}
    >
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 14, fontWeight: 500, marginBottom: isDownloading ? 6 : 0 }}>
          {label}
        </div>
        {isDownloading && dep.pct != null && (
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
                width: `${dep.pct}%`,
                background: "#3b82f6",
                borderRadius: 2,
                transition: "width 0.2s",
              }}
            />
          </div>
        )}
      </div>
      <span
        style={{
          fontSize: 13,
          color: isReady ? "#4ade80" : isError ? "#f87171" : "#64748b",
          minWidth: 70,
          textAlign: "right",
        }}
      >
        {statusLabel(dep)}
      </span>
    </div>
  );
}
