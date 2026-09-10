// DEMO DATA - a frozen snapshot of a real backend run, not fabricated numbers.
//
// Captured once by uploading the repository's own sample files
// (Timed-script-sample-english.docx, Tamil-script-sample.docx) to a running
// `uvicorn app.api:app`, then saving the JSON responses verbatim
// (see demoBundle.json). Used only when the backend at VITE_API_BASE_URL is
// unreachable, so the UI is still fully browsable offline - every screen that
// uses this data is labeled "DEMO SNAPSHOT" so nobody mistakes it for a live
// run. audio/alignments/exports were stripped (no files exist for a frozen
// snapshot); everything else - segments, budgets, violations, translations,
// timeline, QA report - is real pipeline output for the README's own sample
// pair (95 segments, 663.2s video, 11 action cues).

import demoBundle from "./demoBundle.json";
import type { LanguageTrack, ParsedScript, TrackResponse } from "../api/types";

export const DEMO_SCRIPT_ID = "demo";

export const DEMO_EN_SCRIPT = demoBundle.enScript as unknown as ParsedScript;
export const DEMO_TA_SCRIPT = demoBundle.taScript as unknown as ParsedScript;

export const DEMO_EN_RUN = demoBundle.enRun as unknown as TrackResponse;
export const DEMO_TA_RUN = demoBundle.taRun as unknown as TrackResponse;

export const DEMO_TRACKS: Record<string, LanguageTrack> = {
  en: DEMO_EN_RUN.track,
  ta: DEMO_TA_RUN.track,
};

export const DEMO_STUBBED_STAGES = DEMO_EN_RUN.stubbed_stages;

// The demo bundle only contains English's own parse (source script). Tamil's
// parse is its own independently-authored script, not a translation of it -
// keep both so the Script tab can show either as the "uploaded" script.
export const DEMO_SCRIPTS_BY_LANGUAGE: Record<string, ParsedScript> = {
  en: DEMO_EN_SCRIPT,
  ta: DEMO_TA_SCRIPT,
};
