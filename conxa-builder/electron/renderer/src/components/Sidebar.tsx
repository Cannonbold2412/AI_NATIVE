import { NavLink, useNavigate } from "react-router-dom";
import conxaIcon from "../assets/conxa-icon.png";
import { StatusDot, type PluginStatus } from "./StatusDot";

export interface PluginSummary {
  id: string;
  name: string;
  status: PluginStatus;
}

export function Sidebar({ plugins }: { plugins: PluginSummary[] }) {
  const navigate = useNavigate();
  return (
    <nav className="sidebar">
      <div className="sidebar__brand" aria-label="Conxa Build Studio">
        <img className="sidebar__brand-icon" src={conxaIcon} alt="" width={32} height={32} />
        <div className="sidebar__brand-text">
          <span>Conxa</span>
          <small>Build Studio</small>
        </div>
      </div>
      <div className="sidebar__heading">Plugins</div>
      <div style={{ flex: 1, overflowY: "auto" }}>
        {plugins.map((p) => (
          <NavLink
            key={p.id}
            to={`/plugins/${encodeURIComponent(p.id)}`}
            className={({ isActive }) =>
              "plugin-row" + (isActive ? " plugin-row--active" : "")
            }
          >
            <StatusDot status={p.status} />
            <span className="plugin-row__name">{p.name}</span>
          </NavLink>
        ))}
        {plugins.length === 0 && (
          <div style={{ color: "var(--text-muted)", padding: 8 }}>No plugins yet.</div>
        )}
      </div>
      <button className="btn-accent" onClick={() => navigate("/setup")}>
        + New plugin
      </button>
    </nav>
  );
}
