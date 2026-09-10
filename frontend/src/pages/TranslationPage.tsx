import { useState } from "react";
import { Languages, RefreshCw } from "lucide-react";
import { useProject } from "../context/ProjectContext";
import { Card, Stat } from "../components/ui/Card";
import { Button } from "../components/ui/Button";
import { Badge } from "../components/ui/Badge";
import { Progress } from "../components/ui/Progress";
import { EmptyState } from "../components/ui/EmptyState";
import { languageLabel } from "../lib/format";

export function TranslationPage() {
  const { parsedScript, tracksByLanguage, activeLanguage, mode, rerunSegments } = useProject();
  const track = activeLanguage ? tracksByLanguage[activeLanguage] : null;
  const [rerunningId, setRerunningId] = useState<string | null>(null);

  if (!parsedScript || !track) {
    return (
      <div className="p-6">
        <EmptyState
          icon={Languages}
          title="No translation to review"
          description="Generate narration for a target language on the Script tab first."
        />
      </div>
    );
  }

  const segmentById = new Map(parsedScript.segments.map((s) => [s.id, s]));

  async function handleRegenerate(segmentId: string) {
    if (!activeLanguage) return;
    setRerunningId(segmentId);
    try {
      await rerunSegments(activeLanguage, [segmentId]);
    } finally {
      setRerunningId(null);
    }
  }

  return (
    <div className="space-y-3 p-4">
      <Card>
        <div className="flex items-center justify-between">
          <div className="text-sm text-zinc-500 dark:text-zinc-400">
            {languageLabel(parsedScript.language)} → {languageLabel(activeLanguage!)} · translator{" "}
            <Badge tone="stub">EchoTranslator (STUB)</Badge> - text passes through unchanged, but
            duration/budget math below is real.
          </div>
        </div>
      </Card>

      <div className="space-y-2">
        {track.translations.map((t) => {
          const segment = segmentById.get(t.segment_id);
          if (!segment) return null;
          const overrun = t.predicted_duration - t.budget;
          const ratio = t.budget > 0 ? t.predicted_duration / t.budget : 0;
          const tone = overrun > 0 ? "error" : ratio > 0.85 ? "warning" : "ok";

          return (
            <Card key={t.segment_id} bodyClassName="p-3">
              <div className="mb-2 flex items-center justify-between">
                <span className="font-mono text-xs text-zinc-400">{t.segment_id}</span>
                <div className="flex items-center gap-2">
                  {overrun > 0.001 ? (
                    <Badge tone="error">Too long by {overrun.toFixed(2)}s</Badge>
                  ) : (
                    <Badge tone="ok">Fits</Badge>
                  )}
                  {!t.fitted && <Badge tone="error">translator gave up</Badge>}
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-[11px] font-medium uppercase tracking-wide text-zinc-400">
                    Source
                  </p>
                  <p className="text-sm text-zinc-700 dark:text-zinc-200">{t.source_text}</p>
                </div>
                <div>
                  <p className="text-[11px] font-medium uppercase tracking-wide text-zinc-400">
                    Target ({languageLabel(t.language)})
                  </p>
                  <p className="text-sm text-zinc-700 dark:text-zinc-200">{t.text}</p>
                </div>
              </div>

              <div className="mt-3 grid grid-cols-4 gap-3">
                <Stat label="Characters" value={String(t.text.length)} />
                <Stat label="Syllables" value={String(t.syllables)} />
                <Stat label="Predicted" value={`${t.predicted_duration.toFixed(2)}s`} />
                <Stat label="Budget" value={`${t.budget.toFixed(2)}s`} />
              </div>

              <div className="mt-2">
                <div className="mb-1 flex items-center justify-between text-[11px] text-zinc-400">
                  <span>
                    Target duration {t.predicted_duration.toFixed(1)}s / {t.budget.toFixed(1)}s
                  </span>
                  <span>{(ratio * 100).toFixed(0)}%</span>
                </div>
                <Progress ratio={ratio} tone={tone} />
              </div>

              <div className="mt-3 flex gap-2">
                <Button size="sm" disabled title="Not available: EchoTranslator does not rephrase text - Module 2 adds this">
                  Shorten
                </Button>
                <Button
                  size="sm"
                  disabled={mode !== "live" || rerunningId === t.segment_id}
                  onClick={() => handleRegenerate(t.segment_id)}
                >
                  <RefreshCw className={`h-3 w-3 ${rerunningId === t.segment_id ? "animate-spin" : ""}`} />
                  Regenerate
                </Button>
                <Button size="sm" disabled title="Not available: no override-storage endpoint yet">
                  Accept anyway
                </Button>
              </div>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
