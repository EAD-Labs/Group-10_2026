import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { GitBranch, ZoomIn, ZoomOut } from "lucide-react";
import { useProject } from "../context/ProjectContext";
import { Card, Stat } from "../components/ui/Card";
import { Badge } from "../components/ui/Badge";
import { EmptyState } from "../components/ui/EmptyState";
import { formatSigned, formatTimestamp, languageLabel } from "../lib/format";

const MIN_PX_PER_SEC = 0.6;
const MAX_PX_PER_SEC = 12;

export function TimelinePage() {
  const { parsedScript, tracksByLanguage, activeLanguage, setActiveLanguage, mode } = useProject();
  const location = useLocation() as { state?: { segmentId?: string } };
  const [pxPerSec, setPxPerSec] = useState(1.2);
  const [selectedId, setSelectedId] = useState<string | null>(location.state?.segmentId ?? null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const languages = Object.keys(tracksByLanguage);
  const active = activeLanguage && tracksByLanguage[activeLanguage] ? activeLanguage : languages[0];
  const track = active ? tracksByLanguage[active] : null;

  useEffect(() => {
    if (active && active !== activeLanguage) setActiveLanguage(active);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  if (!parsedScript || !track) {
    return (
      <div className="p-6">
        <EmptyState
          icon={GitBranch}
          title="No timeline yet"
          description="Generate narration for a language on the Script tab to build its timeline."
        />
      </div>
    );
  }

  const qaBySegment = new Map(track.qa?.segments.map((s) => [s.segment_id, s]) ?? []);
  const width = Math.max(track.duration * pxPerSec, 600);
  const selected = track.timeline.find((i) => i.segment_id === selectedId);
  const selectedQA = selectedId ? qaBySegment.get(selectedId) : undefined;

  return (
    <div className="space-y-3 p-4">
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex gap-2">
            {languages.map((lang) => (
              <button
                key={lang}
                onClick={() => setActiveLanguage(lang)}
                className={`rounded px-3 py-1.5 text-sm font-medium ${
                  lang === active
                    ? "bg-indigo-600 text-white"
                    : "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300"
                }`}
              >
                {languageLabel(lang)}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-2">
            <button onClick={() => setPxPerSec((v) => Math.max(v / 1.4, MIN_PX_PER_SEC))} className="text-zinc-400 hover:text-zinc-600">
              <ZoomOut className="h-4 w-4" />
            </button>
            <input
              type="range"
              min={MIN_PX_PER_SEC}
              max={MAX_PX_PER_SEC}
              step={0.1}
              value={pxPerSec}
              onChange={(e) => setPxPerSec(Number(e.target.value))}
              className="w-32"
            />
            <button onClick={() => setPxPerSec((v) => Math.min(v * 1.4, MAX_PX_PER_SEC))} className="text-zinc-400 hover:text-zinc-600">
              <ZoomIn className="h-4 w-4" />
            </button>
          </div>
        </div>
      </Card>

      {mode === "demo" && (
        <p className="text-xs text-orange-500">
          Demo snapshot - frozen output of a real pipeline run, not a live backend.
        </p>
      )}

      <Card title={`Timeline (${track.duration.toFixed(1)}s)`} bodyClassName="p-3">
        <div ref={scrollRef} className="overflow-x-auto">
          <div style={{ width }}>
            <TrackRow label="VIDEO">
              <div className="absolute inset-0 rounded bg-zinc-300 dark:bg-zinc-700" />
            </TrackRow>

            <TrackRow label="NARRATION">
              {track.timeline.map((item) => {
                const qa = qaBySegment.get(item.segment_id);
                const color = qa?.over_budget
                  ? "bg-red-400"
                  : item.anchored
                    ? "bg-indigo-400"
                    : "bg-emerald-400";
                return (
                  <button
                    key={item.segment_id}
                    onClick={() => setSelectedId(item.segment_id)}
                    title={`${item.segment_id} · ${item.start.toFixed(1)}-${item.end.toFixed(1)}s`}
                    className={`absolute top-0 h-full rounded-sm ${color} ${
                      selectedId === item.segment_id ? "ring-2 ring-offset-1 ring-zinc-900 dark:ring-white" : ""
                    }`}
                    style={{
                      left: item.start * pxPerSec,
                      width: Math.max((item.end - item.start) * pxPerSec, 2),
                    }}
                  />
                );
              })}
            </TrackRow>

            <TrackRow label="ACTION CUE">
              {parsedScript.cues.map((cue) => (
                <div
                  key={cue.id}
                  title={cue.description}
                  className="absolute top-0 h-full rounded-sm bg-zinc-500/70"
                  style={{ left: cue.at * pxPerSec, width: Math.max(cue.clip_duration * pxPerSec, 2) }}
                />
              ))}
            </TrackRow>

            <TrackRow label="PAUSE">
              {track.timeline.map((item) =>
                item.hold_after > 0.05 ? (
                  <div
                    key={item.segment_id}
                    className="absolute top-1/2 h-0.5 -translate-y-1/2 bg-amber-400"
                    style={{ left: item.end * pxPerSec, width: Math.max(item.hold_after * pxPerSec, 2) }}
                  />
                ) : null,
              )}
            </TrackRow>

            <div className="mt-1 flex justify-between text-[10px] text-zinc-400">
              <span>{formatTimestamp(0)}</span>
              <span>{formatTimestamp(track.duration)}</span>
            </div>
          </div>
        </div>

        <div className="mt-3 flex gap-4 text-xs text-zinc-500 dark:text-zinc-400">
          <Legend color="bg-emerald-400" label="fits budget" />
          <Legend color="bg-indigo-400" label="anchored to a cue" />
          <Legend color="bg-red-400" label="over budget" />
          <Legend color="bg-zinc-500/70" label="embedded action clip" />
          <Legend color="bg-amber-400" label="pause / hold" />
        </div>
      </Card>

      {selected && selectedQA && (
        <Card title={`Segment ${selected.segment_id}`}>
          <div className="grid grid-cols-4 gap-4">
            <Stat label="Start" value={formatTimestamp(selected.start)} />
            <Stat label="End" value={formatTimestamp(selected.end)} />
            <Stat label="Hold after" value={`${selected.hold_after.toFixed(2)}s`} />
            <Stat
              label="Drift"
              value={formatSigned(selectedQA.drift)}
              tone={selectedQA.over_budget ? "error" : "ok"}
            />
          </div>
          <div className="mt-2 flex gap-2">
            {selected.anchored && <Badge tone="accent">anchored to action cue</Badge>}
            {selectedQA.over_budget && <Badge tone="error">over budget</Badge>}
          </div>
        </Card>
      )}
    </div>
  );
}

function TrackRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mb-2 flex items-center gap-2">
      <div className="w-24 shrink-0 text-[10px] font-semibold uppercase tracking-wide text-zinc-400">
        {label}
      </div>
      <div className="relative h-7 flex-1 rounded bg-zinc-50 dark:bg-zinc-800/40">{children}</div>
    </div>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1">
      <span className={`inline-block h-2 w-2 rounded-full ${color}`} /> {label}
    </span>
  );
}
