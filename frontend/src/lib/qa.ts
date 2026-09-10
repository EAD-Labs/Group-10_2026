import type { LanguageTrack, ParsedScript, Segment } from "../api/types";

// Backend constants (app/duration/model.py, app/schemas.py) - mirrored here so
// the UI's thresholds never drift from what the QA report actually gates on.
export const DRIFT_TOLERANCE = 0.25;
export const NO_PERCEPTIBLE_PAUSE = 0.15;

export type IssueCategory =
  | "over_budget"
  | "sentence_too_long"
  | "missing_pause"
  | "translation_issue"
  | "cue_collision";

export interface Issue {
  id: string;
  segmentId: string;
  category: IssueCategory;
  severity: "error" | "warning";
  title: string;
  detail: string;
}

const CATEGORY_LABELS: Record<IssueCategory, string> = {
  over_budget: "Over budget",
  sentence_too_long: "Sentence too long",
  missing_pause: "Missing pause",
  translation_issue: "Translation issue",
  cue_collision: "Cue collision",
};

export function categoryLabel(category: IssueCategory): string {
  return CATEGORY_LABELS[category];
}

export function buildIssues(script: ParsedScript | null, track: LanguageTrack | null): Issue[] {
  const issues: Issue[] = [];
  if (!script) return issues;

  const segmentById = new Map<string, Segment>(script.segments.map((s) => [s.id, s]));

  for (const segment of script.segments) {
    for (const violation of segment.violations) {
      if (violation.rule.startsWith("ST-2.3")) {
        issues.push({
          id: `${segment.id}-${violation.rule}-${violation.sentence_index ?? 0}`,
          segmentId: segment.id,
          category: "sentence_too_long",
          severity: violation.severity,
          title: `${segment.id} - sentence too long`,
          detail: violation.message,
        });
      }
    }
    if (segment.cue_ids.length > 0 && segment.narration_budget < 1.0) {
      issues.push({
        id: `${segment.id}-cue-collision`,
        segmentId: segment.id,
        category: "cue_collision",
        severity: "warning",
        title: `${segment.id} - action cue leaves little narration time`,
        detail: `Narration budget is only ${segment.narration_budget.toFixed(2)}s once the embedded clip is reserved.`,
      });
    }
  }

  if (track?.qa) {
    for (const row of track.qa.segments) {
      const segment = segmentById.get(row.segment_id);
      if (row.over_budget) {
        issues.push({
          id: `${row.segment_id}-over-budget`,
          segmentId: row.segment_id,
          category: "over_budget",
          severity: "error",
          title: `${row.segment_id} - timing exceeded`,
          detail: `Expected ${row.budget.toFixed(2)}s, actual ${row.actual.toFixed(2)}s (overflow ${row.drift.toFixed(2)}s).`,
        });
      } else if (segment && row.pause_after < NO_PERCEPTIBLE_PAUSE) {
        issues.push({
          id: `${row.segment_id}-missing-pause`,
          segmentId: row.segment_id,
          category: "missing_pause",
          severity: "warning",
          title: `${row.segment_id} - no audible pause`,
          detail: `Only ${row.pause_after.toFixed(2)}s of silence remains before the next line - it will sound rushed.`,
        });
      }
    }
    for (const translated of track.translations) {
      if (!translated.fitted) {
        issues.push({
          id: `${translated.segment_id}-translation-issue`,
          segmentId: translated.segment_id,
          category: "translation_issue",
          severity: "error",
          title: `${translated.segment_id} - translator could not fit the budget`,
          detail: `Predicted ${translated.predicted_duration.toFixed(2)}s against a ${translated.budget.toFixed(2)}s budget after ${translated.attempts} attempt(s).`,
        });
      }
    }
  }

  return issues;
}

export function issueCounts(issues: Issue[]): Record<IssueCategory, number> {
  const counts: Record<IssueCategory, number> = {
    over_budget: 0,
    sentence_too_long: 0,
    missing_pause: 0,
    translation_issue: 0,
    cue_collision: 0,
  };
  for (const issue of issues) counts[issue.category] += 1;
  return counts;
}
