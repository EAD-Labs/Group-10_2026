import { CircleHelp, WifiOff } from "lucide-react";
import { useProject } from "../context/ProjectContext";
import { Badge } from "../components/ui/Badge";
import { languageLabel } from "../lib/format";

export function Topbar() {
  const { mode, backendOnline, parsedScript, tracksByLanguage, activeLanguage } = useProject();

  const track = activeLanguage ? tracksByLanguage[activeLanguage] : null;
  const overBudget = track?.qa?.over_budget_count ?? 0;

  let statusLabel = "No project";
  let statusTone: "neutral" | "accent" | "warning" | "ok" = "neutral";
  if (parsedScript) {
    if (!track) {
      statusLabel = "Parsed";
      statusTone = "accent";
    } else if (overBudget > 0) {
      statusLabel = "In review";
      statusTone = "warning";
    } else {
      statusLabel = "Ready";
      statusTone = "ok";
    }
  }

  return (
    <header className="flex h-12 shrink-0 items-center justify-between border-b border-zinc-200 bg-white px-4 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex items-center gap-3">
        <span className="text-sm font-medium text-zinc-800 dark:text-zinc-100">
          {parsedScript ? parsedScript.source : "No project loaded"}
        </span>
        <Badge tone={statusTone}>{statusLabel}</Badge>
        {parsedScript && (
          <span className="text-xs text-zinc-400">
            {languageLabel(parsedScript.language)}
            {activeLanguage ? ` → ${languageLabel(activeLanguage)}` : ""}
          </span>
        )}
      </div>

      <div className="flex items-center gap-3">
        {mode === "demo" ? (
          <Badge tone="stub">DEMO SNAPSHOT</Badge>
        ) : backendOnline === false ? (
          <span className="flex items-center gap-1 text-xs text-red-500">
            <WifiOff className="h-3.5 w-3.5" /> Backend offline
          </span>
        ) : (
          <Badge tone="ok">Live</Badge>
        )}
        <button className="text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300" title="Help">
          <CircleHelp className="h-4 w-4" />
        </button>
        <div className="flex h-7 w-7 items-center justify-center rounded-full bg-indigo-100 text-[11px] font-semibold text-indigo-700 dark:bg-indigo-500/20 dark:text-indigo-300">
          U
        </div>
      </div>
    </header>
  );
}
