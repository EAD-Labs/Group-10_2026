import { useMemo, useRef, useState } from "react";
import { AudioLines, Pause, Play, RefreshCw } from "lucide-react";
import { useProject } from "../context/ProjectContext";
import { Card, Stat } from "../components/ui/Card";
import { Button } from "../components/ui/Button";
import { Badge } from "../components/ui/Badge";
import { EmptyState } from "../components/ui/EmptyState";
import { mediaUrl } from "../api/client";

const PROVIDERS = [
  { value: "silent", label: "Silent TTS", stub: true },
  { value: "piper", label: "Piper", stub: true, planned: true },
  { value: "sarvam", label: "Sarvam AI", stub: true, planned: true },
];

// Deterministic pseudo-waveform bars for visual texture only - the audio is
// silence (SilentTTS), so this never claims to represent real amplitude.
function pseudoBars(seed: string, count = 60): number[] {
  let h = 0;
  for (const ch of seed) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  const bars: number[] = [];
  for (let i = 0; i < count; i++) {
    h = (h * 1103515245 + 12345) >>> 0;
    bars.push(0.15 + ((h >> 8) % 100) / 100 * 0.85);
  }
  return bars;
}

export function AudioPage() {
  const { parsedScript, tracksByLanguage, audioUrlsByLanguage, activeLanguage, mode, rerunSegments } =
    useProject();
  const track = activeLanguage ? tracksByLanguage[activeLanguage] : null;
  const audioUrls = activeLanguage ? audioUrlsByLanguage[activeLanguage] : {};
  const [selectedId, setSelectedId] = useState<string | null>(track?.translations[0]?.segment_id ?? null);
  const [speed, setSpeed] = useState(1);
  const [playing, setPlaying] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const audioRef = useRef<HTMLAudioElement>(null);

  const translation = track?.translations.find((t) => t.segment_id === selectedId);
  const asset = track?.audio.find((a) => a.segment_id === selectedId);
  const bars = useMemo(() => pseudoBars(selectedId ?? "x"), [selectedId]);

  if (!parsedScript || !track) {
    return (
      <div className="p-6">
        <EmptyState
          icon={AudioLines}
          title="No audio generated yet"
          description="Generate narration for a target language on the Script tab first."
        />
      </div>
    );
  }

  function togglePlay() {
    const el = audioRef.current;
    if (!el) return;
    if (playing) el.pause();
    else el.play();
  }

  async function handleRegenerate() {
    if (!activeLanguage || !selectedId) return;
    setRegenerating(true);
    try {
      await rerunSegments(activeLanguage, [selectedId]);
    } finally {
      setRegenerating(false);
    }
  }

  const audioUrl = selectedId ? audioUrls?.[selectedId] : undefined;

  return (
    <div className="grid grid-cols-[280px_1fr] gap-4 p-4">
      <Card title="Segments" bodyClassName="p-0 max-h-[640px] overflow-y-auto">
        {track.translations.map((t) => (
          <button
            key={t.segment_id}
            onClick={() => setSelectedId(t.segment_id)}
            className={`block w-full truncate border-b border-zinc-100 px-3 py-2 text-left text-xs dark:border-zinc-800 ${
              selectedId === t.segment_id
                ? "bg-indigo-50 text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300"
                : "text-zinc-600 hover:bg-zinc-50 dark:text-zinc-300 dark:hover:bg-zinc-800/60"
            }`}
          >
            <span className="font-mono text-zinc-400">{t.segment_id}</span> {t.text}
          </button>
        ))}
      </Card>

      <div className="space-y-3">
        {translation ? (
          <>
            <Card title={`Segment ${translation.segment_id}`}>
              <p className="text-sm text-zinc-800 dark:text-zinc-100">{translation.text}</p>
              <div className="mt-3 grid grid-cols-3 gap-4">
                <Stat label="Predicted duration" value={`${translation.predicted_duration.toFixed(2)}s`} />
                <Stat label="Generated duration" value={asset ? `${asset.duration.toFixed(2)}s` : "—"} />
                <Stat label="Provider" value={asset?.provider ?? "—"} />
              </div>
            </Card>

            <Card title="Waveform preview">
              <div className="flex h-20 items-end gap-[2px] rounded bg-zinc-50 p-2 dark:bg-zinc-800/50">
                {bars.map((h, i) => (
                  <div
                    key={i}
                    className="flex-1 rounded-sm bg-indigo-300 dark:bg-indigo-500/60"
                    style={{ height: `${h * 100}%` }}
                  />
                ))}
              </div>
              <p className="mt-1 text-[11px] text-zinc-400">
                Visual placeholder only - SilentTTS produces silence, so there is no real waveform
                to draw yet.
              </p>

              {audioUrl && mode === "live" ? (
                <div className="mt-3 flex items-center gap-3">
                  <button
                    onClick={togglePlay}
                    className="flex h-9 w-9 items-center justify-center rounded-full bg-indigo-600 text-white hover:bg-indigo-500"
                  >
                    {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                  </button>
                  <audio
                    ref={audioRef}
                    src={mediaUrl(audioUrl)}
                    onPlay={() => setPlaying(true)}
                    onPause={() => setPlaying(false)}
                    onEnded={() => setPlaying(false)}
                  />
                  <label className="flex items-center gap-2 text-xs text-zinc-500">
                    Speed
                    <select
                      value={speed}
                      onChange={(e) => {
                        const v = Number(e.target.value);
                        setSpeed(v);
                        if (audioRef.current) audioRef.current.playbackRate = v;
                      }}
                      className="rounded border border-zinc-300 px-1.5 py-0.5 dark:border-zinc-700 dark:bg-zinc-800"
                    >
                      {[0.5, 0.75, 1, 1.25, 1.5].map((v) => (
                        <option key={v} value={v}>
                          {v}x
                        </option>
                      ))}
                    </select>
                  </label>
                  <Button size="sm" onClick={handleRegenerate} disabled={regenerating}>
                    <RefreshCw className={`h-3.5 w-3.5 ${regenerating ? "animate-spin" : ""}`} /> Regenerate
                  </Button>
                </div>
              ) : (
                <p className="mt-3 text-xs text-orange-500">
                  {mode === "demo"
                    ? "Demo snapshot - no playable file (audio wasn't kept in the frozen bundle)."
                    : "No audio file for this segment yet."}
                </p>
              )}
            </Card>

            <Card title="TTS provider">
              <div className="flex gap-2">
                {PROVIDERS.map((p) => (
                  <label
                    key={p.value}
                    className={`flex items-center gap-2 rounded-md border px-3 py-1.5 text-xs ${
                      p.value === "silent"
                        ? "border-indigo-300 bg-indigo-50 dark:border-indigo-500/40 dark:bg-indigo-500/10"
                        : "border-zinc-200 text-zinc-400 dark:border-zinc-800"
                    }`}
                  >
                    <input type="radio" checked={p.value === "silent"} disabled={p.value !== "silent"} readOnly />
                    {p.label}
                    {p.stub && <Badge tone="stub">{p.planned ? "PLANNED" : "STUB"}</Badge>}
                  </label>
                ))}
              </div>
            </Card>
          </>
        ) : (
          <EmptyState icon={AudioLines} title="Select a segment" description="Pick a segment from the list to inspect its audio." />
        )}
      </div>
    </div>
  );
}
