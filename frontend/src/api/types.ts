// Hand-written mirror of backend/app/schemas.py. Keep field names identical -
// they are the API's response shapes verbatim (see backend/app/api.py).

export type Severity = "error" | "warning";

export interface Violation {
  rule: string;
  severity: Severity;
  message: string;
  sentence_index: number | null;
}

export interface Sentence {
  index: number;
  text: string;
  char_count: number;
  syllables: number;
  violations: Violation[];
}

export interface ActionCue {
  id: string;
  at: number;
  raw: string;
  description: string;
  clip_start: number | null;
  clip_end: number | null;
  clip_duration: number;
}

export interface Segment {
  id: string;
  index: number;
  start: number;
  end: number;
  raw_budget: number;
  cue_reserved: number;
  narration_budget: number;
  trailing_slack: number;
  text: string;
  char_count: number;
  syllables: number;
  sentences: Sentence[];
  cue_ids: string[];
  bold_terms: string[];
  violations: Violation[];
}

export interface ParsedScript {
  source: string;
  language: string;
  duration: number;
  segments: Segment[];
  cues: ActionCue[];
  error_count: number;
  warning_count: number;
  narration_budget_total: number;
}

export interface TranslatedSegment {
  segment_id: string;
  language: string;
  source_text: string;
  text: string;
  syllables: number;
  predicted_duration: number;
  budget: number;
  attempts: number;
  fitted: boolean;
  translator: string;
}

export interface AudioAsset {
  segment_id: string;
  language: string;
  path: string;
  duration: number;
  sample_rate: number;
  provider: string;
  voice: string | null;
}

export interface AlignmentResult {
  segment_id: string;
  speech_start: number;
  speech_end: number;
  aligner: string;
}

export interface TimelineItem {
  segment_id: string;
  start: number;
  end: number;
  audio_path: string;
  audio_offset: number;
  hold_after: number;
  anchored: boolean;
}

export interface SegmentQA {
  segment_id: string;
  budget: number;
  predicted: number;
  actual: number;
  drift: number;
  pause_after: number;
  rate_ratio: number;
  within_drift: boolean;
  over_budget: boolean;
  unrushed: boolean;
}

export interface QAReport {
  language: string;
  segments: SegmentQA[];
  reference_rate: number;
  max_drift: number;
  largest_gap: number;
  mean_rate_ratio: number;
  over_budget_count: number;
  segments_without_pause: number;
  median_pause: number;
}

export interface LanguageTrack {
  source: string;
  language: string;
  duration: number;
  translations: TranslatedSegment[];
  audio: AudioAsset[];
  alignments: AlignmentResult[];
  timeline: TimelineItem[];
  qa: QAReport | null;
  exports: string[];
  unfitted: TranslatedSegment[];
}

export interface ScriptResponse {
  id: string;
  script: ParsedScript;
}

export interface ScriptSummary {
  id: string;
  source: string;
  language: string;
  duration: number;
  segment_count: number;
  languages_run: string[];
}

export interface TrackResponse {
  track: LanguageTrack;
  stubbed_stages: string[];
  audio_urls: Record<string, string>;
  export_urls: string[];
}
