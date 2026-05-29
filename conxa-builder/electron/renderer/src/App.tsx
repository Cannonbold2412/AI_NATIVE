import { useCallback, useEffect, useState } from "react";
import { Routes, Route, Navigate, useLocation } from "react-router-dom";
import { Sidebar, type PluginSummary } from "@/components/Sidebar";
import { cmd } from "@/lib/ipc";
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
