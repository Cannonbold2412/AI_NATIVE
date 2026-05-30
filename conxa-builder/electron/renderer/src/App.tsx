import { useCallback, useEffect, useState } from "react";
import { Routes, Route, Navigate, useLocation, useNavigate } from "react-router-dom";
import { Sidebar, type PluginSummary } from "@/components/Sidebar";
import { cmd, CmdError } from "@/lib/ipc";
import { SetupWizard } from "@/pages/SetupWizard";
import { PluginDetail } from "@/pages/PluginDetail";
import { RecordingFeed } from "@/pages/RecordingFeed";
import { CompileProgress } from "@/pages/CompileProgress";
import { StepEditor } from "@/pages/StepEditor";

interface RawPlugin {
  id: string;
  name: string;
  status: string;
}

function toSummary(p: RawPlugin): PluginSummary {
  const status =
    p.status === "error" ? "error" : p.status === "ready" ? "published" : "unpublished";
  return { id: p.id, name: p.name, status };
}

export function App() {
  const [plugins, setPlugins] = useState<PluginSummary[]>([]);
  const location = useLocation();
  const navigate = useNavigate();

  const refresh = useCallback(async () => {
    try {
      const res = await cmd<{ plugins: RawPlugin[] }>("list_plugins");
      setPlugins((res.plugins || []).map(toSummary));
    } catch {
      // list_plugins is optional in early dev; leave the list empty.
    }
  }, []);

  // Refresh the sidebar whenever the route changes (cheap, keeps dots current).
  useEffect(() => {
    void refresh();
  }, [location.pathname, refresh]);

  // Handle deep links from the web dashboard (conxa-studio://open[?plugin=<id>]).
  useEffect(() => {
    const unsub = window.conxa.onDeepLink(async (url) => {
      const pluginMatch = url.match(/[?&]plugin=([^&]+)/);
      const pluginId = pluginMatch ? decodeURIComponent(pluginMatch[1]) : null;
      try {
        const info = await cmd<{ logged_in: boolean }>("whoami");
        if (!info.logged_in) await cmd("login");
      } catch (err) {
        if (err instanceof CmdError && err.code === "cancelled") return;
        navigate("/setup");
        return;
      }
      await refresh();
      navigate(pluginId ? `/plugins/${pluginId}` : "/setup");
    });
    return unsub;
  }, [navigate, refresh]);

  return (
    <div className="app-shell">
      <Sidebar plugins={plugins} />
      <main className="main">
        <Routes>
          <Route path="/" element={<Navigate to="/setup" replace />} />
          <Route path="/setup" element={<SetupWizard onCreated={refresh} />} />
          <Route path="/plugins/:pluginId" element={<PluginDetail />} />
          <Route
            path="/plugins/:pluginId/record/:workflowName"
            element={<RecordingFeed />}
          />
          <Route path="/plugins/:pluginId/compile/:sessionId" element={<CompileProgress />} />
          <Route path="/plugins/:pluginId/edit/:skillId" element={<StepEditor />} />
        </Routes>
      </main>
    </div>
  );
}
