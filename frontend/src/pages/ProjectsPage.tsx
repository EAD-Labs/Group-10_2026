import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { FilePlus2, FolderOpen, PlayCircle } from "lucide-react";
import { Link } from "react-router-dom";
import { useProject } from "../context/ProjectContext";
import { Card } from "../components/ui/Card";
import { Button } from "../components/ui/Button";
import { Badge } from "../components/ui/Badge";
import { EmptyState } from "../components/ui/EmptyState";
import { languageLabel } from "../lib/format";

export function ProjectsPage() {
  const { sessionScripts, refreshSessionScripts, openScript, scriptId, backendOnline, loadDemo } =
    useProject();
  const navigate = useNavigate();

  useEffect(() => {
    refreshSessionScripts();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (backendOnline === false) {
    return (
      <div className="p-6">
        <EmptyState
          icon={FolderOpen}
          title="Backend offline"
          description="The project list is session state held by the API server - it can't be reached right now. Load the demo project to keep exploring the UI."
          action={<Button onClick={loadDemo}><PlayCircle className="h-3.5 w-3.5" /> Load demo project</Button>}
        />
      </div>
    );
  }

  return (
    <div className="space-y-4 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
            Projects this session
          </h1>
          <p className="text-xs text-zinc-400">
            Scripts uploaded to this backend process. There is no database yet (HLD §8 is the
            target) - this list resets when the API server restarts.
          </p>
        </div>
        <Link to="/new">
          <Button variant="primary">
            <FilePlus2 className="h-3.5 w-3.5" /> New project
          </Button>
        </Link>
      </div>

      {sessionScripts.length === 0 ? (
        <EmptyState
          icon={FolderOpen}
          title="No projects yet"
          description="Upload a timed script to create the first one."
          action={
            <Link to="/new">
              <Button variant="primary">
                <FilePlus2 className="h-3.5 w-3.5" /> New project
              </Button>
            </Link>
          }
        />
      ) : (
        <Card bodyClassName="p-0">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-zinc-200 text-xs uppercase text-zinc-400 dark:border-zinc-800">
              <tr>
                <th className="px-4 py-2 font-medium">Source</th>
                <th className="px-4 py-2 font-medium">Language</th>
                <th className="px-4 py-2 font-medium">Duration</th>
                <th className="px-4 py-2 font-medium">Segments</th>
                <th className="px-4 py-2 font-medium">Tracks generated</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {sessionScripts.map((s) => (
                <tr
                  key={s.id}
                  className={`border-t border-zinc-100 dark:border-zinc-800 ${
                    s.id === scriptId ? "bg-indigo-50/60 dark:bg-indigo-500/5" : ""
                  }`}
                >
                  <td className="px-4 py-2 font-medium text-zinc-800 dark:text-zinc-100">
                    {s.source.replace(/^[0-9a-f]{32}-/, "")}
                  </td>
                  <td className="px-4 py-2">{languageLabel(s.language)}</td>
                  <td className="px-4 py-2 tabular-nums text-zinc-500">{s.duration.toFixed(1)}s</td>
                  <td className="px-4 py-2 tabular-nums text-zinc-500">{s.segment_count}</td>
                  <td className="px-4 py-2">
                    {s.languages_run.length === 0 ? (
                      <span className="text-xs text-zinc-400">none</span>
                    ) : (
                      <div className="flex gap-1">
                        {s.languages_run.map((l) => (
                          <Badge key={l} tone="accent">
                            {languageLabel(l)}
                          </Badge>
                        ))}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-2 text-right">
                    <Button
                      size="sm"
                      onClick={async () => {
                        await openScript(s.id);
                        navigate("/script");
                      }}
                    >
                      Open
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
