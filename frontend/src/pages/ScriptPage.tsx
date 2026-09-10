import { useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Lock, LockOpen, PlayCircle, RefreshCw, Waypoints } from "lucide-react";
import { useProject } from "../context/ProjectContext";
import { Card, Stat } from "../components/ui/Card";
import { Button } from "../components/ui/Button";
import { Badge } from "../components/ui/Badge";
import { EmptyState } from "../components/ui/EmptyState";
import { Segmented } from "../components/ui/Segmented";
import { formatSigned, formatTimestamp, languageLabel } from "../lib/format";
import { mediaUrl } from "../api/client";
import type { Segment } from "../api/types";
import { FileText } from "lucide-react";

const LANGUAGES = [
  { code: "en", label: "English" },
  { code: "ta", label: "Tamil" },
  { code: "hi", label: "Hindi" },
  { code: "mr", label: "Marathi" },
];

type StatusFilter = "all" | "errors" | "warnings" | "passed";

function segmentStatus(segment: Segment, overBudget: boolean | undefined): "error" | "warning" | "ok" {
  if (overBudget || segment.violations.some((v) => v.severity === "error")) return "error";
  if (segment.violations.some((v) => v.severity === "warning")) return "warning";
  return "ok";
}

export function ScriptPage() {
  const {
    mode,
    parsedScript,
    tracksByLanguage,
    audioUrlsByLanguage,
    activeLanguage,
    setActiveLanguage,
    generateTrack,
    rerunSegments,
    lockedSegments,
    toggleSegmentLock,
    loadDemo,
  } = useProject();
  const navigate = useNavigate();
  const location = useLocation() as {
    state?: { targetLanguage?: string; translator?: string; tts?: string; aligner?: string; segmentId?: string };
  };

  const [selectedId, setSelectedId] = useState<string | null>(location.state?.segmentId ?? null);
  const [filter, setFilter] = useState<StatusFilter>("all");
  const [targetLanguage, setTargetLanguage] = useState(
    location.state?.targetLanguage ?? activeLanguage ?? "ta",
  );
  const [aligner, setAligner] = useState(location.state?.aligner ?? "clip-bounds");
  const [generating, setGenerating] = useState(false);
  const [rerunningId, setRerunningId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const track = activeLanguage ? tracksByLanguage[activeLanguage] : null;
  const audioUrls = activeLanguage ? audioUrlsByLanguage[activeLanguage] : {};
  const qaBySegment = new Map(track?.qa?.segments.map((s) => [s.segment_id, s]) ?? []);
  const translationBySegment = new Map(track?.translations.map((t) => [t.segment_id, t]) ?? []);

  const selected = parsedScript?.segments.find((s) => s.id === selectedId) ?? null;
  const selectedQA = selected ? qaBySegment.get(selected.id) : undefined;
  const selectedTranslation = selected ? translationBySegment.get(selected.id) : undefined;

  const filtered = useMemo(() => {
    if (!parsedScript) return [];
    return parsedScript.segments.filter((s) => {
      const status = segmentStatus(s, qaBySegment.get(s.id)?.over_budget);
      if (filter === "all") return true;
      if (filter === "errors") return status === "error";
      if (filter === "warnings") return status === "warning";
      return status === "ok";
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [parsedScript, filter, track]);

  if (!parsedScript) {
    return (
      <div className="p-6">
        <EmptyState
          icon={FileText}
          title="No script loaded"
          description="Start a new project to upload a timed script, or load the demo project."
          action={
            <div className="flex gap-2">
              <Button variant="primary" onClick={() => navigate("/new")}>
                New project
              </Button>
              <Button onClick={loadDemo}>Load demo project</Button>
            </div>
          }
        />
      </div>
    );
  }

  async function handleGenerate() {
    setGenerating(true);
    setError(null);
    try {
      await generateTrack({ language: targetLanguage, aligner });
      setActiveLanguage(targetLanguage);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setGenerating(false);
    }
  }

  async function handleRerun(segmentId: string) {
    if (!activeLanguage) return;
    setRerunningId(segmentId);
    setError(null);
    try {
      await rerunSegments(activeLanguage, [segmentId]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRerunningId(null);
    }
  }

  const counts = {
    all: parsedScript.segments.length,
    errors: parsedScript.segments.filter((s) => segmentStatus(s, qaBySegment.get(s.id)?.over_budget) === "error").length,
    warnings: parsedScript.segments.filter((s) => segmentStatus(s, qaBySegment.get(s.id)?.over_budget) === "warning").length,
    passed: parsedScript.segments.filter((s) => segmentStatus(s, qaBySegment.get(s.id)?.over_budget) === "ok").length,
  };

  return (
    <div className="grid grid-cols-[1fr_340px] gap-4 p-4">
      <div className="min-w-0 space-y-3">
        <Card>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="grid grid-cols-4 gap-6">
              <Stat label="Segments" value={String(parsedScript.segments.length)} />
              <Stat label="Action cues" value={String(parsedScript.cues.length)} />
              <Stat label="Errors" value={String(parsedScript.error_count)} tone={parsedScript.error_count ? "error" : "ok"} />
              <Stat label="Warnings" value={String(parsedScript.warning_count)} tone={parsedScript.warning_count ? "warning" : "ok"} />
            </div>
            <Segmented
              value={filter}
              onChange={setFilter}
              options={[
                { value: "all", label: "All", count: counts.all },
                { value: "errors", label: "Errors", count: counts.errors },
                { value: "warnings", label: "Warnings", count: counts.warnings },
                { value: "passed", label: "Passed", count: counts.passed },
              ]}
            />
          </div>
        </Card>

        <Card bodyClassName="p-0 max-h-[620px] overflow-y-auto">
          <table className="w-full text-left text-sm">
            <thead className="sticky top-0 border-b border-zinc-200 bg-white text-xs uppercase text-zinc-400 dark:border-zinc-800 dark:bg-zinc-900">
              <tr>
                <th className="px-3 py-2 font-medium">#</th>
                <th className="px-3 py-2 font-medium">Time</th>
                <th className="px-3 py-2 font-medium">Narration</th>
                <th className="px-3 py-2 font-medium">Budget</th>
                <th className="px-3 py-2 font-medium">Cue</th>
                <th className="px-3 py-2 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((s) => {
                const qa = qaBySegment.get(s.id);
                const status = segmentStatus(s, qa?.over_budget);
                return (
                  <tr
                    key={s.id}
                    onClick={() => setSelectedId(s.id)}
                    className={`cursor-pointer border-t border-zinc-100 hover:bg-zinc-50 dark:border-zinc-800 dark:hover:bg-zinc-800/60 ${
                      selectedId === s.id ? "bg-indigo-50/60 dark:bg-indigo-500/5" : ""
                    }`}
                  >
                    <td className="px-3 py-2 font-mono text-xs text-zinc-400">{s.id}</td>
                    <td className="px-3 py-2 text-xs tabular-nums text-zinc-500">
                      {formatTimestamp(s.start)}
                    </td>
                    <td className="max-w-sm truncate px-3 py-2 text-zinc-700 dark:text-zinc-200">
                      {s.text}
                      {lockedSegments.has(s.id) && <Lock className="ml-1.5 inline h-3 w-3 text-zinc-400" />}
                    </td>
                    <td className="px-3 py-2 text-xs tabular-nums text-zinc-500">
                      {s.narration_budget.toFixed(1)}s
                    </td>
                    <td className="px-3 py-2 text-xs text-zinc-400">
                      {s.cue_ids.length > 0 ? s.cue_ids.join(", ") : "—"}
                    </td>
                    <td className="px-3 py-2">
                      <Badge tone={status === "error" ? "error" : status === "warning" ? "warning" : "ok"}>
                        {status}
                      </Badge>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
      </div>

      <div className="space-y-3">
        {selected && (
          <Card title={`Segment ${selected.id}`}>
            <p className="text-xs font-medium uppercase tracking-wide text-zinc-400">Source</p>
            <p className="text-sm text-zinc-800 dark:text-zinc-100">{selected.text}</p>

            {selectedTranslation && (
              <>
                <p className="mt-3 text-xs font-medium uppercase tracking-wide text-zinc-400">
                  Translation ({languageLabel(selectedTranslation.language)})
                </p>
                <p className="text-sm text-zinc-800 dark:text-zinc-100">{selectedTranslation.text}</p>
              </>
            )}

            <div className="mt-3 grid grid-cols-2 gap-3">
              <Stat label="Raw budget" value={`${selected.raw_budget.toFixed(2)}s`} />
              <Stat label="Cue reserved" value={`${selected.cue_reserved.toFixed(2)}s`} />
              <Stat label="Narration budget" value={`${selected.narration_budget.toFixed(2)}s`} />
              <Stat label="Trailing slack" value={`${selected.trailing_slack.toFixed(2)}s`} />
            </div>

            {selectedTranslation && (
              <div className="mt-3 grid grid-cols-2 gap-3 border-t border-zinc-100 pt-3 dark:border-zinc-800">
                <Stat label="Predicted" value={`${selectedTranslation.predicted_duration.toFixed(2)}s`} />
                <Stat
                  label="Drift"
                  value={selectedQA ? formatSigned(selectedQA.drift) : "—"}
                  tone={selectedQA?.over_budget ? "error" : "ok"}
                />
              </div>
            )}

            {selected.violations.length > 0 && (
              <div className="mt-3 space-y-1">
                {selected.violations.map((v, i) => (
                  <div key={i} className="flex items-start gap-2 text-xs">
                    <Badge tone={v.severity === "error" ? "error" : "warning"}>{v.rule}</Badge>
                    <span className="text-zinc-500 dark:text-zinc-400">{v.message}</span>
                  </div>
                ))}
              </div>
            )}

            <div className="mt-4 flex flex-wrap gap-2">
              {audioUrls?.[selected.id] && mode === "live" && (
                <audio controls src={mediaUrl(audioUrls[selected.id])} className="h-8 w-full" />
              )}
              {activeLanguage && mode === "live" && (
                <Button
                  size="sm"
                  onClick={() => handleRerun(selected.id)}
                  disabled={rerunningId === selected.id || lockedSegments.has(selected.id)}
                >
                  <RefreshCw className={`h-3.5 w-3.5 ${rerunningId === selected.id ? "animate-spin" : ""}`} />
                  Re-run segment
                </Button>
              )}
              <Button size="sm" onClick={() => toggleSegmentLock(selected.id)}>
                {lockedSegments.has(selected.id) ? (
                  <>
                    <LockOpen className="h-3.5 w-3.5" /> Unlock
                  </>
                ) : (
                  <>
                    <Lock className="h-3.5 w-3.5" /> Lock
                  </>
                )}
              </Button>
              {track && (
                <Button size="sm" onClick={() => navigate("/timeline", { state: { segmentId: selected.id } })}>
                  <Waypoints className="h-3.5 w-3.5" /> Timeline
                </Button>
              )}
            </div>
            {mode === "demo" && (
              <p className="mt-2 text-xs text-orange-500">
                Demo snapshot - re-run/play are disabled (no live backend to call).
              </p>
            )}
          </Card>
        )}

        {mode === "live" && (
          <Card title="Generate narration">
            <div className="flex flex-col gap-2">
              <label className="flex flex-col gap-1 text-sm">
                <span className="text-zinc-500 dark:text-zinc-400">Target language</span>
                <select
                  value={targetLanguage}
                  onChange={(e) => setTargetLanguage(e.target.value)}
                  className="rounded border border-zinc-300 px-2 py-1.5 dark:border-zinc-700 dark:bg-zinc-800"
                >
                  {LANGUAGES.map((l) => (
                    <option key={l.code} value={l.code}>
                      {l.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1 text-sm">
                <span className="text-zinc-500 dark:text-zinc-400">Aligner</span>
                <select
                  value={aligner}
                  onChange={(e) => setAligner(e.target.value)}
                  className="rounded border border-zinc-300 px-2 py-1.5 dark:border-zinc-700 dark:bg-zinc-800"
                >
                  <option value="clip-bounds">ClipBoundsAligner (stub)</option>
                  <option value="vad">VAD aligner (real)</option>
                </select>
              </label>
              <Button variant="primary" onClick={handleGenerate} disabled={generating}>
                <PlayCircle className="h-3.5 w-3.5" />
                {generating ? "Running pipeline…" : tracksByLanguage[targetLanguage] ? "Regenerate" : "Generate narration"}
              </Button>
              <p className="text-xs text-zinc-400">
                Runs the full pipeline for this language (translator/TTS are currently stubs) and
                opens the results here and on the Timeline tab.
              </p>
            </div>
          </Card>
        )}
        {error && <p className="text-sm text-red-600">{error}</p>}
      </div>
    </div>
  );
}
