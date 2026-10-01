import { useI18n } from "../i18n";
import { WORKSPACE_TABS } from "../workspaceTabs";
import type { WorkspaceMode } from "../types";

export function WorkspaceTabs({ mode, arenaAvailable, problemAvailable, onChange }: {
  mode: WorkspaceMode;
  arenaAvailable: boolean;
  problemAvailable: boolean;
  onChange: (next: WorkspaceMode) => void;
}) {
  const { t } = useI18n();
  return <nav className="workspace-tabs" aria-label={t("workspace")}>
    {WORKSPACE_TABS.map((tab) => {
      const noArena = tab.mode === "arena" && !arenaAvailable;
      const noProblem = (tab.mode === "run" || tab.mode === "search") && !problemAvailable;
      return <button key={tab.mode} type="button"
        className={`workspace-tabs__tab workspace-tabs__tab--${tab.mode}${mode === tab.mode ? " is-active" : ""}`}
        aria-pressed={mode === tab.mode}
        aria-label={noArena ? `${t(tab.label)} — ${t("this objective measures its own region: there is no arena to build")}`
          : noProblem ? `${t(tab.label)} — ${t("Choose a problem first")}` : t(tab.label)}
        disabled={noArena || noProblem}
        onClick={() => onChange(tab.mode)}>{t(tab.label)}</button>;
    })}
  </nav>;
}
