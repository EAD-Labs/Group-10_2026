import { CheckCircle2, Circle, TriangleAlert } from "lucide-react";
import { useProject } from "../context/ProjectContext";
import { Badge } from "./ui/Badge";

type StageState = "pending" | "done" | "stub";

interface Stage {
  key: string;
  label: string;
  count: string;
  state: StageState;
  provider?: string;
}

export function PipelineStatus() {
  const { parsedScript, tracksByLanguage, activeLanguage, stubbedStagesByLanguage } = useProject();
  const track = activeLanguage ? tracksByLanguage[activeLanguage] : null;
  const stubbed = new Set(activeLanguage ? stubbedStagesByLanguage[activeLanguage] : []);
  const total = parsedScript?.segments.length ?? 0;

  const stages: Stage[] = [
    {
      key: "parse",
      label: "Parse",
      count: parsedScript ? `${total} / ${total}` : "0 / 0",
      state: parsedScript ? "done" : "pending",
    },
    {
      key: "translate",
      label: "Translate",
      count: track ? `${track.translations.length} / ${total}` : "0 / 0",
      state: !track ? "pending" : stubbed.has("echo") ? "stub" : "done",
      provider: stubbed.has("echo") ? "EchoTranslator (STUB)" : "LLM translator",
    },
    {
      key: "synthesise",
      label: "Synthesise",
      count: track ? `${track.audio.length} / ${total}` : "0 / 0",
      state: !track ? "pending" : stubbed.has("silent") ? "stub" : "done",
      provider: stubbed.has("silent") ? "SilentTTS (STUB)" : "TTS provider",
    },
    {
      key: "align",
      label: "Align",
      count: track ? `${track.alignments.length} / ${total}` : "0 / 0",
      state: !track ? "pending" : stubbed.has("clip-bounds") ? "stub" : "done",
      provider: stubbed.has("clip-bounds") ? "ClipBoundsAligner (STUB)" : "VAD aligner",
    },
    {
      key: "timeline",
      label: "Timeline",
      count: track ? `${track.timeline.length} / ${total}` : "0 / 0",
      state: !track ? "pending" : "done",
    },
    {
      key: "qa",
      label: "QA",
      count: track?.qa ? `${track.qa.over_budget_count} issues` : "-",
      state: !track?.qa ? "pending" : track.qa.over_budget_count > 0 ? "stub" : "done",
    },
    {
      key: "export",
      label: "Export",
      count: track ? `${track.exports.length} files` : "0 files",
      state: !track ? "pending" : stubbed.has("manifest") ? "stub" : "done",
      provider: stubbed.has("manifest") ? "manifest (stand-in)" : undefined,
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
      {stages.map((stage) => (
        <div
          key={stage.key}
          className="rounded-lg border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900"
        >
          <div className="flex items-center gap-1.5">
            {stage.state === "done" && <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />}
            {stage.state === "stub" && <TriangleAlert className="h-3.5 w-3.5 text-amber-500" />}
            {stage.state === "pending" && <Circle className="h-3.5 w-3.5 text-zinc-300 dark:text-zinc-700" />}
            <span className="text-xs font-semibold text-zinc-700 dark:text-zinc-200">{stage.label}</span>
          </div>
          <div className="mt-1.5 text-sm font-medium tabular-nums text-zinc-900 dark:text-zinc-100">
            {stage.count}
          </div>
          {stage.provider && (
            <div className="mt-1">
              <Badge tone={stage.state === "stub" ? "stub" : "neutral"}>{stage.provider}</Badge>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
