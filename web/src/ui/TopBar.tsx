import type { ReplayCatalog, Scene } from "../generated/schemas";
import { app, setWorkspace, useApp, WORKSPACES } from "../state/app";
import { IconPanelRight, IconSidebar } from "./icons";
import { ReplayMenu } from "./ReplayMenu";
import { Search } from "./Search";

export function TopBar({ scene, catalog }: { scene: Scene; catalog: ReplayCatalog | undefined }) {
  const workspace = useApp((s) => s.workspace);
  const leftOpen = useApp((s) => s.leftOpen);
  const rightOpen = useApp((s) => s.rightOpen);
  return (
    <header className="topbar">
      <button
        className={`icon-button ${leftOpen ? "on" : ""}`}
        title="Toggle left panel"
        aria-label="Toggle left panel"
        aria-pressed={leftOpen}
        onClick={() => app.set({ leftOpen: !leftOpen })}
      >
        <IconSidebar />
      </button>
      <div className="brand">
        <span className="brand-mark" />
        Metro AGH
      </div>
      <nav className="tabs" aria-label="Workspaces">
        {WORKSPACES.map((w) => (
          <button
            key={w.id}
            className={w.id === workspace ? "tab active" : "tab"}
            aria-current={w.id === workspace ? "page" : undefined}
            onClick={() => setWorkspace(w.id)}
          >
            {w.label}
          </button>
        ))}
      </nav>
      <div className="topbar-spacer" />
      <Search scene={scene} />
      <ReplayMenu catalog={catalog} />
      <button
        className={`icon-button ${rightOpen ? "on" : ""}`}
        title="Toggle right panel"
        aria-label="Toggle right panel"
        aria-pressed={rightOpen}
        onClick={() => app.set({ rightOpen: !rightOpen })}
      >
        <IconPanelRight />
      </button>
    </header>
  );
}
