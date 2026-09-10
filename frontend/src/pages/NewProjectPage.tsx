import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { CheckCircle2, FileText, Film, Languages, Settings2, Upload } from "lucide-react";
import { useProject } from "../context/ProjectContext";
import { Card } from "../components/ui/Card";
import { Button } from "../components/ui/Button";
import { Badge, StubBadge } from "../components/ui/Badge";
import { formatBytes } from "../lib/format";

const LANGUAGES = [
  { code: "en", label: "English" },
  { code: "ta", label: "Tamil" },
  { code: "hi", label: "Hindi" },
  { code: "mr", label: "Marathi" },
];

const STEPS = ["Video", "Script", "Languages", "Settings"] as const;

export function NewProjectPage() {
  const navigate = useNavigate();
  const { parseScript, backendOnline } = useProject();
  const [step, setStep] = useState(0);

  const [videoFile, setVideoFile] = useState<File | null>(null);
  const [duration, setDuration] = useState("663.2");
  const [scriptFile, setScriptFile] = useState<File | null>(null);
  const [sourceLanguage, setSourceLanguage] = useState("en");
  const [targetLanguage, setTargetLanguage] = useState("ta");
  const [translator, setTranslator] = useState("echo");
  const [tts, setTts] = useState("silent");
  const [aligner, setAligner] = useState("clip-bounds");

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const scriptInputRef = useRef<HTMLInputElement>(null);
  const videoInputRef = useRef<HTMLInputElement>(null);

  async function handleCreate() {
    if (!scriptFile) return;
    setSubmitting(true);
    setError(null);
    try {
      await parseScript({
        script: scriptFile,
        language: sourceLanguage,
        video: videoFile,
        duration: videoFile ? undefined : Number(duration) || undefined,
      });
      navigate("/script", { state: { targetLanguage, translator, tts, aligner } });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-5 p-6">
      {backendOnline === false && (
        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-900/50 dark:bg-red-900/20 dark:text-red-400">
          Backend not reachable at the configured API URL. Start it with{" "}
          <code className="rounded bg-red-100 px-1 dark:bg-red-900/40">
            uvicorn app.api:app --port 8123
          </code>{" "}
          in <code className="rounded bg-red-100 px-1 dark:bg-red-900/40">backend/</code>, or load
          the demo project from the Dashboard instead.
        </div>
      )}

      <div className="flex items-center gap-2">
        {STEPS.map((label, i) => (
          <div key={label} className="flex items-center gap-2">
            <button
              onClick={() => setStep(i)}
              className={`flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-semibold ${
                i === step
                  ? "bg-indigo-600 text-white"
                  : i < step
                    ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-400"
                    : "bg-zinc-100 text-zinc-400 dark:bg-zinc-800"
              }`}
            >
              {i < step ? <CheckCircle2 className="h-3.5 w-3.5" /> : i + 1}
            </button>
            <span
              className={`text-xs font-medium ${i === step ? "text-zinc-900 dark:text-zinc-100" : "text-zinc-400"}`}
            >
              {label}
            </span>
            {i < STEPS.length - 1 && <div className="h-px w-8 bg-zinc-200 dark:bg-zinc-800" />}
          </div>
        ))}
      </div>

      {step === 0 && (
        <Card title="Upload base video (optional)">
          <div
            onClick={() => videoInputRef.current?.click()}
            className="flex cursor-pointer flex-col items-center gap-2 rounded-md border-2 border-dashed border-zinc-300 px-6 py-10 text-center hover:border-indigo-400 dark:border-zinc-700"
          >
            <Film className="h-6 w-6 text-zinc-400" />
            <p className="text-sm text-zinc-600 dark:text-zinc-300">
              {videoFile ? videoFile.name : "Drop a .webm/.mkv file, or click to browse"}
            </p>
            {videoFile && (
              <p className="text-xs text-zinc-400">
                {formatBytes(videoFile.size)} · duration read from container on upload
              </p>
            )}
            <input
              ref={videoInputRef}
              type="file"
              accept=".webm,.mkv"
              className="hidden"
              onChange={(e) => setVideoFile(e.target.files?.[0] ?? null)}
            />
          </div>
          {!videoFile && (
            <div className="mt-3 flex items-center gap-2 text-sm">
              <span className="text-zinc-500 dark:text-zinc-400">
                No video? Enter the known duration (seconds):
              </span>
              <input
                type="number"
                value={duration}
                onChange={(e) => setDuration(e.target.value)}
                className="w-24 rounded border border-zinc-300 px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-800"
              />
            </div>
          )}
        </Card>
      )}

      {step === 1 && (
        <Card title="Upload the timed source script">
          <div
            onClick={() => scriptInputRef.current?.click()}
            className="flex cursor-pointer flex-col items-center gap-2 rounded-md border-2 border-dashed border-zinc-300 px-6 py-10 text-center hover:border-indigo-400 dark:border-zinc-700"
          >
            <FileText className="h-6 w-6 text-zinc-400" />
            <p className="text-sm text-zinc-600 dark:text-zinc-300">
              {scriptFile ? scriptFile.name : "Drop a .docx timed script, or click to browse"}
            </p>
            {scriptFile && <p className="text-xs text-zinc-400">{formatBytes(scriptFile.size)}</p>}
            <input
              ref={scriptInputRef}
              type="file"
              accept=".docx"
              className="hidden"
              onChange={(e) => setScriptFile(e.target.files?.[0] ?? null)}
            />
          </div>
          <p className="mt-3 text-xs text-zinc-400">
            Only the <code>Time | Narration</code> timed-script format is supported. The parser
            separates narration rows from action-cue rows (<code>@MM:SS</code>) automatically.
          </p>
        </Card>
      )}

      {step === 2 && (
        <Card title="Languages">
          <div className="grid grid-cols-2 gap-4">
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-zinc-500 dark:text-zinc-400">Source language</span>
              <select
                value={sourceLanguage}
                onChange={(e) => setSourceLanguage(e.target.value)}
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
          </div>
          <div className="mt-4 flex items-center gap-2 rounded-md bg-zinc-50 px-3 py-2 text-xs text-zinc-500 dark:bg-zinc-800/50 dark:text-zinc-400">
            <Languages className="h-3.5 w-3.5" />
            Project scope currently covers English plus Tamil, Hindi or Marathi (HLD §12.2).
          </div>
        </Card>
      )}

      {step === 3 && (
        <Card title="Pipeline settings">
          <div className="grid grid-cols-3 gap-4">
            <label className="flex flex-col gap-1 text-sm">
              <span className="flex items-center gap-1.5 text-zinc-500 dark:text-zinc-400">
                Translator <StubBadge />
              </span>
              <select
                value={translator}
                onChange={(e) => setTranslator(e.target.value)}
                className="rounded border border-zinc-300 px-2 py-1.5 dark:border-zinc-700 dark:bg-zinc-800"
              >
                <option value="echo">EchoTranslator (stub)</option>
              </select>
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="flex items-center gap-1.5 text-zinc-500 dark:text-zinc-400">
                TTS provider <StubBadge />
              </span>
              <select
                value={tts}
                onChange={(e) => setTts(e.target.value)}
                className="rounded border border-zinc-300 px-2 py-1.5 dark:border-zinc-700 dark:bg-zinc-800"
              >
                <option value="silent">SilentTTS (stub)</option>
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
          </div>
          <div className="mt-4 space-y-1 rounded-md bg-zinc-50 px-3 py-2 text-xs text-zinc-500 dark:bg-zinc-800/50 dark:text-zinc-400">
            <div className="flex items-center gap-1.5">
              <Settings2 className="h-3.5 w-3.5" /> Reference rate 3.91 syl/s · pause reserve 0.40s
              · drift tolerance 0.25s <Badge tone="neutral">calibrated, read-only</Badge>
            </div>
          </div>
        </Card>
      )}

      <div className="flex items-center justify-between">
        <Button variant="ghost" disabled={step === 0} onClick={() => setStep((s) => s - 1)}>
          Back
        </Button>
        {step < STEPS.length - 1 ? (
          <Button
            variant="primary"
            disabled={step === 1 && !scriptFile}
            onClick={() => setStep((s) => s + 1)}
          >
            Continue
          </Button>
        ) : (
          <Button variant="primary" disabled={!scriptFile || submitting} onClick={handleCreate}>
            <Upload className="h-3.5 w-3.5" /> {submitting ? "Parsing…" : "Create project"}
          </Button>
        )}
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}
    </div>
  );
}
