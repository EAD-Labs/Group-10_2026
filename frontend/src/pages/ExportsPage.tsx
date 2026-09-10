import { Download, FileJson, FileText, FolderKanban } from "lucide-react";
import { useProject } from "../context/ProjectContext";
import { Card } from "../components/ui/Card";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { EmptyState } from "../components/ui/EmptyState";
import { languageLabel } from "../lib/format";
import { mediaUrl } from "../api/client";

function describe(path: string): { label: string; icon: typeof FileText } {
  if (path.endsWith(".srt")) return { label: "Subtitles (SRT)", icon: FileText };
  if (path.endsWith(".json")) return { label: "Project manifest (JSON)", icon: FileJson };
  return { label: path, icon: FileText };
}

export function ExportsPage() {
  const { tracksByLanguage, exportUrlsByLanguage, mode } = useProject();
  const languages = Object.keys(tracksByLanguage);

  if (languages.length === 0) {
    return (
      <div className="p-6">
        <EmptyState
          icon={Download}
          title="Nothing to export yet"
          description="Generate narration for at least one language before exporting deliverables."
        />
      </div>
    );
  }

  return (
    <div className="space-y-4 p-4">
      {languages.map((lang) => {
        const track = tracksByLanguage[lang];
        const urls = exportUrlsByLanguage[lang] ?? [];
        return (
          <Card key={lang} title={`${languageLabel(lang)} track`}>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {track.exports.length === 0 && (
                <p className="text-sm text-zinc-400">No exports recorded for this track.</p>
              )}
              {track.exports.map((path, i) => {
                const { label, icon: Icon } = describe(path);
                const url = urls[i];
                return (
                  <div
                    key={path}
                    className="flex items-center justify-between rounded-md border border-zinc-200 px-3 py-2 dark:border-zinc-800"
                  >
                    <div className="flex items-center gap-2">
                      <Icon className="h-4 w-4 text-zinc-400" />
                      <div>
                        <p className="text-sm text-zinc-800 dark:text-zinc-100">{label}</p>
                        <Badge tone="ok">Ready</Badge>
                      </div>
                    </div>
                    {url && mode === "live" ? (
                      <a href={mediaUrl(url)} download>
                        <Button size="sm">
                          <Download className="h-3.5 w-3.5" /> Download
                        </Button>
                      </a>
                    ) : (
                      <Button size="sm" disabled>
                        <Download className="h-3.5 w-3.5" /> Download
                      </Button>
                    )}
                  </div>
                );
              })}

              <div className="flex items-center justify-between rounded-md border border-dashed border-zinc-200 px-3 py-2 text-zinc-400 dark:border-zinc-800">
                <div className="flex items-center gap-2">
                  <FolderKanban className="h-4 w-4" />
                  <div>
                    <p className="text-sm">Editable project (OpenTimelineIO / Kdenlive XML)</p>
                    <Badge tone="neutral">Planned</Badge>
                  </div>
                </div>
              </div>
            </div>
          </Card>
        );
      })}
    </div>
  );
}
