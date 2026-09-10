import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ShieldCheck } from "lucide-react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useProject } from "../context/ProjectContext";
import { Card, Stat } from "../components/ui/Card";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Segmented } from "../components/ui/Segmented";
import { EmptyState } from "../components/ui/EmptyState";
import { buildIssues, categoryLabel, issueCounts, type Issue } from "../lib/qa";

type Filter = "all" | "errors" | "warnings";

export function QAReviewPage() {
  const { parsedScript, tracksByLanguage, activeLanguage, rerunSegments, mode } = useProject();
  const navigate = useNavigate();
  const [filter, setFilter] = useState<Filter>("all");

  const track = activeLanguage ? tracksByLanguage[activeLanguage] : null;
  const issues = useMemo(() => buildIssues(parsedScript, track), [parsedScript, track]);
  const counts = issueCounts(issues);
  const chartData = (Object.keys(counts) as (keyof typeof counts)[]).map((key) => ({
    name: categoryLabel(key),
    count: counts[key],
  }));

  const filtered = issues.filter((issue) => {
    if (filter === "all") return true;
    return issue.severity === (filter === "errors" ? "error" : "warning");
  });

  if (!parsedScript || !track) {
    return (
      <div className="p-6">
        <EmptyState
          icon={ShieldCheck}
          title="No QA data yet"
          description="Generate narration for a language on the Script tab to produce a QA report."
        />
      </div>
    );
  }

  const totalSegments = parsedScript.segments.length;
  const attentionSegments = new Set(issues.map((i) => i.segmentId)).size;

  async function handleRegenerate(issue: Issue) {
    if (!activeLanguage || mode !== "live") return;
    await rerunSegments(activeLanguage, [issue.segmentId]);
  }

  return (
    <div className="space-y-3 p-4">
      <Card>
        <div className="flex flex-wrap items-center gap-6">
          <Stat
            label="Segments needing attention"
            value={`${attentionSegments} / ${totalSegments}`}
            tone={attentionSegments > 0 ? "warning" : "ok"}
          />
          <Stat label="Worst overrun" value={`${track.qa?.max_drift.toFixed(2) ?? "0.00"}s`} hint="threshold 0.25s" />
          <Stat label="Mean rate ratio" value={track.qa?.mean_rate_ratio.toFixed(2) ?? "—"} hint="target 1.00" />
          <Stat label="Median pause left" value={`${track.qa?.median_pause.toFixed(2) ?? "0.00"}s`} />
        </div>
      </Card>

      <Card title="Issues by category">
        <ResponsiveContainer width="100%" height={180}>
          <BarChart data={chartData} layout="vertical" margin={{ left: 24 }}>
            <CartesianGrid strokeDasharray="3 3" horizontal={false} className="stroke-zinc-100 dark:stroke-zinc-800" />
            <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11 }} />
            <YAxis type="category" dataKey="name" width={130} tick={{ fontSize: 11 }} />
            <Tooltip contentStyle={{ fontSize: 12, borderRadius: 6 }} formatter={(value) => [value, "issues"]} />
            <Bar dataKey="count" fill="#6366f1" radius={[0, 4, 4, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </Card>

      <div className="flex items-center justify-between">
        <Segmented
          value={filter}
          onChange={setFilter}
          options={[
            { value: "all", label: "All", count: issues.length },
            { value: "errors", label: "Errors", count: issues.filter((i) => i.severity === "error").length },
            { value: "warnings", label: "Warnings", count: issues.filter((i) => i.severity === "warning").length },
          ]}
        />
      </div>

      <div className="space-y-2">
        {filtered.length === 0 && (
          <Card>
            <p className="text-sm text-zinc-400">No issues in this filter.</p>
          </Card>
        )}
        {filtered.map((issue) => (
          <Card key={issue.id} bodyClassName="p-3">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <Badge tone={issue.severity === "error" ? "error" : "warning"}>
                    {categoryLabel(issue.category)}
                  </Badge>
                  <span className="text-sm font-medium text-zinc-800 dark:text-zinc-100">
                    {issue.title}
                  </span>
                </div>
                <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">{issue.detail}</p>
              </div>
              <div className="flex shrink-0 gap-1.5">
                <Button size="sm" onClick={() => navigate("/translation", { state: { segmentId: issue.segmentId } })}>
                  Edit translation
                </Button>
                <Button size="sm" disabled={mode !== "live"} onClick={() => handleRegenerate(issue)}>
                  Regenerate
                </Button>
                <Button size="sm" onClick={() => navigate("/timeline", { state: { segmentId: issue.segmentId } })}>
                  Open timeline
                </Button>
              </div>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
