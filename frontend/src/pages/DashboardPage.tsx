import { FilePlus2, PlayCircle, Sparkles } from "lucide-react";
import { Link } from "react-router-dom";
import { useProject } from "../context/ProjectContext";
import { Card, Stat } from "../components/ui/Card";
import { Button } from "../components/ui/Button";
import { EmptyState } from "../components/ui/EmptyState";
import { PipelineStatus } from "../components/PipelineStatus";
import { buildIssues } from "../lib/qa";
import { languageLabel } from "../lib/format";

export function DashboardPage() {
  const { parsedScript, tracksByLanguage, activeLanguage, loadDemo, mode } = useProject();
  const track = activeLanguage ? tracksByLanguage[activeLanguage] : null;
  const issues = buildIssues(parsedScript, track);

  if (!parsedScript) {
    return (
      <div className="p-6">
        <EmptyState
          icon={Sparkles}
          title="No project loaded"
          description="Upload a timed script to start a new production, or load the sample Synfig project (English → Tamil) to explore the tool."
          action={
            <div className="flex gap-2">
              <Link to="/new">
                <Button variant="primary">
                  <FilePlus2 className="h-3.5 w-3.5" /> New project
                </Button>
              </Link>
              <Button onClick={loadDemo}>
                <PlayCircle className="h-3.5 w-3.5" /> Load demo project
              </Button>
            </div>
          }
        />
      </div>
    );
  }

  const avgBudget =
    parsedScript.segments.reduce((sum, s) => sum + s.narration_budget, 0) /
    Math.max(parsedScript.segments.length, 1);
  const translationProgress = track
    ? track.translations.filter((t) => t.fitted).length / Math.max(track.translations.length, 1)
    : 0;
  const errorCount = issues.filter((i) => i.severity === "error").length;

  return (
    <div className="space-y-5 p-6">
      <Card
        title={
          <span>
            {parsedScript.source.replace(/^[0-9a-f]{32}-/, "")} —{" "}
            {languageLabel(parsedScript.language)}
            {activeLanguage ? ` → ${languageLabel(activeLanguage)}` : ""}
          </span>
        }
        action={
          mode === "demo" ? (
            <span className="text-xs text-orange-600 dark:text-orange-400">
              Frozen snapshot of a real backend run
            </span>
          ) : undefined
        }
      >
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
          <Stat label="Video duration" value={`${parsedScript.duration.toFixed(1)}s`} />
          <Stat label="Segments" value={String(parsedScript.segments.length)} />
          <Stat
            label="Over budget"
            value={track?.qa ? `${track.qa.over_budget_count}` : "-"}
            tone={track?.qa && track.qa.over_budget_count > 0 ? "error" : "ok"}
          />
          <Stat label="Avg narration budget" value={`${avgBudget.toFixed(1)}s`} />
          <Stat
            label="QA issues"
            value={String(issues.length)}
            tone={errorCount > 0 ? "error" : issues.length > 0 ? "warning" : "ok"}
          />
          <Stat
            label="Translation fit"
            value={track ? `${(translationProgress * 100).toFixed(0)}%` : "-"}
          />
        </div>
      </Card>

      <div>
        <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-400">
          Pipeline
        </h2>
        <PipelineStatus />
      </div>

      {!track && (
        <Card>
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            No language track generated yet.{" "}
            <Link to="/script" className="text-indigo-600 hover:underline dark:text-indigo-400">
              Go to the Script tab
            </Link>{" "}
            to review segments and generate narration.
          </p>
        </Card>
      )}
    </div>
  );
}
