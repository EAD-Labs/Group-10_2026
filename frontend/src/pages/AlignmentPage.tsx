import { useMemo } from "react";
import { Activity } from "lucide-react";
import { useProject } from "../context/ProjectContext";
import { Card, Stat } from "../components/ui/Card";
import { Badge } from "../components/ui/Badge";
import { EmptyState } from "../components/ui/EmptyState";
import { DRIFT_TOLERANCE } from "../lib/qa";
import { formatSigned } from "../lib/format";

function median(values: number[]): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

export function AlignmentPage() {
  const { parsedScript, tracksByLanguage, activeLanguage } = useProject();
  const track = activeLanguage ? tracksByLanguage[activeLanguage] : null;

  const rows = useMemo(() => {
    if (!track) return [];
    const alignmentBySegment = new Map(track.alignments.map((a) => [a.segment_id, a]));
    const translationBySegment = new Map(track.translations.map((t) => [t.segment_id, t]));
    const qaBySegment = new Map(track.qa?.segments.map((s) => [s.segment_id, s]) ?? []);
    return track.timeline.map((item) => {
      const alignment = alignmentBySegment.get(item.segment_id);
      const translation = translationBySegment.get(item.segment_id);
      const qa = qaBySegment.get(item.segment_id);
      const actual = alignment ? alignment.speech_end - alignment.speech_start : 0;
      return {
        segmentId: item.segment_id,
        budget: translation?.budget ?? 0,
        actual,
        drift: qa?.drift ?? actual - (translation?.budget ?? 0),
        withinTolerance: qa?.within_drift ?? true,
      };
    });
  }, [track]);

  if (!parsedScript || !track) {
    return (
      <div className="p-6">
        <EmptyState
          icon={Activity}
          title="No alignment data yet"
          description="Generate narration for a language on the Script tab to compute alignment."
        />
      </div>
    );
  }

  const drifts = rows.map((r) => r.drift);
  const medianDrift = median(drifts);
  const maxDrift = track.qa?.max_drift ?? Math.max(0, ...drifts);
  const withinCount = rows.filter((r) => r.withinTolerance).length;
  const maxScale = Math.max(...rows.map((r) => Math.max(r.budget, r.actual)), 1);

  return (
    <div className="space-y-3 p-4">
      <Card>
        <div className="flex flex-wrap items-center gap-6">
          <Stat label="Median drift" value={formatSigned(medianDrift)} />
          <Stat label="Max drift" value={formatSigned(maxDrift)} tone={maxDrift > DRIFT_TOLERANCE ? "error" : "ok"} />
          <Stat label="Within tolerance" value={`${withinCount} / ${rows.length}`} tone={withinCount === rows.length ? "ok" : "warning"} />
          <Stat label="Outside tolerance" value={String(rows.length - withinCount)} tone={rows.length - withinCount > 0 ? "error" : "ok"} />
        </div>
        <p className="mt-2 text-xs text-zinc-400">
          Drift is actual speech duration minus the speaking budget (not the raw window) - tolerance is ±{DRIFT_TOLERANCE}s per HLD §14.
        </p>
      </Card>

      <Card title="Expected vs. actual" bodyClassName="p-0 max-h-[620px] overflow-y-auto">
        <table className="w-full text-left text-sm">
          <thead className="sticky top-0 border-b border-zinc-200 bg-white text-xs uppercase text-zinc-400 dark:border-zinc-800 dark:bg-zinc-900">
            <tr>
              <th className="px-3 py-2 font-medium">Segment</th>
              <th className="px-3 py-2 font-medium">Expected / Actual</th>
              <th className="px-3 py-2 font-medium">Drift</th>
              <th className="px-3 py-2 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.segmentId} className="border-t border-zinc-100 dark:border-zinc-800">
                <td className="px-3 py-2 font-mono text-xs text-zinc-400">{r.segmentId}</td>
                <td className="px-3 py-2">
                  <div className="space-y-1">
                    <div className="h-2 rounded-sm bg-zinc-200 dark:bg-zinc-700" style={{ width: `${(r.budget / maxScale) * 100}%` }} />
                    <div
                      className={`h-2 rounded-sm ${r.withinTolerance ? "bg-indigo-400" : "bg-red-400"}`}
                      style={{ width: `${(r.actual / maxScale) * 100}%` }}
                    />
                  </div>
                </td>
                <td className="px-3 py-2 text-xs tabular-nums">{formatSigned(r.drift)}</td>
                <td className="px-3 py-2">
                  <Badge tone={r.withinTolerance ? "ok" : "error"}>
                    {r.withinTolerance ? "within tolerance" : "outside tolerance"}
                  </Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
