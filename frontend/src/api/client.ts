import type { ScriptResponse, ScriptSummary, TrackResponse } from "./types";

// Real backend base URL. Override with VITE_API_BASE_URL for a non-local
// deployment; defaults to the uvicorn dev port documented in backend/README.md.
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8123";

export function mediaUrl(path: string): string {
  return path.startsWith("http") ? path : `${API_BASE_URL}${path}`;
}

async function unwrap<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${body}`);
  }
  return res.json() as Promise<T>;
}

export async function checkHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/health`, { signal: AbortSignal.timeout(2000) });
    return res.ok;
  } catch {
    return false;
  }
}

export interface UploadScriptArgs {
  script: File;
  language: string;
  duration?: number;
  video?: File | null;
}

export async function uploadScript(args: UploadScriptArgs): Promise<ScriptResponse> {
  const form = new FormData();
  form.append("script", args.script);
  form.append("language", args.language);
  if (args.video) form.append("video", args.video);
  else if (args.duration != null) form.append("duration", String(args.duration));

  const res = await fetch(`${API_BASE_URL}/api/scripts`, { method: "POST", body: form });
  return unwrap<ScriptResponse>(res);
}

export async function getScript(scriptId: string): Promise<ScriptResponse> {
  const res = await fetch(`${API_BASE_URL}/api/scripts/${scriptId}`);
  return unwrap<ScriptResponse>(res);
}

export async function listScripts(): Promise<ScriptSummary[]> {
  const res = await fetch(`${API_BASE_URL}/api/scripts`);
  return unwrap<ScriptSummary[]>(res);
}

export interface RunTrackArgs {
  scriptId: string;
  language: string;
  sourceLanguage?: string;
  translator?: string;
  tts?: string;
  aligner?: string;
}

export async function runTrack(args: RunTrackArgs): Promise<TrackResponse> {
  const res = await fetch(`${API_BASE_URL}/api/scripts/${args.scriptId}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      language: args.language,
      source_language: args.sourceLanguage ?? "en",
      ...(args.translator ? { translator: args.translator } : {}),
      ...(args.tts ? { tts: args.tts } : {}),
      ...(args.aligner ? { aligner: args.aligner } : {}),
    }),
  });
  return unwrap<TrackResponse>(res);
}

export async function runSegments(
  scriptId: string,
  language: string,
  segmentIds: string[],
): Promise<TrackResponse> {
  const res = await fetch(`${API_BASE_URL}/api/scripts/${scriptId}/run-segments`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ language, segment_ids: segmentIds }),
  });
  return unwrap<TrackResponse>(res);
}
