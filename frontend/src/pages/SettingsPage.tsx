import { useState } from "react";
import { useProject } from "../context/ProjectContext";
import { Card } from "../components/ui/Card";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { API_BASE_URL, checkHealth } from "../api/client";

export function SettingsPage() {
  const { backendOnline, mode } = useProject();
  const [checking, setChecking] = useState(false);
  const [online, setOnline] = useState(backendOnline);

  async function recheck() {
    setChecking(true);
    setOnline(await checkHealth());
    setChecking(false);
  }

  return (
    <div className="max-w-xl space-y-4 p-6">
      <Card title="Backend connection">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-zinc-700 dark:text-zinc-200">{API_BASE_URL}</p>
            <p className="text-xs text-zinc-400">
              Set via <code>VITE_API_BASE_URL</code> - see <code>frontend/.env.example</code>.
            </p>
          </div>
          <Badge tone={online ? "ok" : "error"}>{online ? "Online" : "Offline"}</Badge>
        </div>
        <Button size="sm" className="mt-3" onClick={recheck} disabled={checking}>
          {checking ? "Checking…" : "Re-check"}
        </Button>
      </Card>

      <Card title="Data source">
        <p className="text-sm text-zinc-600 dark:text-zinc-300">
          Current mode: <Badge tone={mode === "demo" ? "stub" : "ok"}>{mode}</Badge>
        </p>
        <p className="mt-1 text-xs text-zinc-400">
          "Live" calls the FastAPI backend directly. "Demo" replays a frozen snapshot of a real
          pipeline run (the repository's own English/Tamil sample scripts) captured once, for
          browsing the UI without a running backend.
        </p>
      </Card>

      <Card title="Pipeline defaults">
        <dl className="grid grid-cols-2 gap-y-2 text-sm">
          <dt className="text-zinc-400">Reference articulation rate</dt>
          <dd>3.91 syl/s (English, measured)</dd>
          <dt className="text-zinc-400">Pause reserve</dt>
          <dd>0.40s per segment</dd>
          <dt className="text-zinc-400">Drift tolerance</dt>
          <dd>±0.25s</dd>
          <dt className="text-zinc-400">Rate tolerance</dt>
          <dd>±10%</dd>
        </dl>
        <p className="mt-2 text-xs text-zinc-400">
          Calibrated from the client's Synfig recordings (backend/app/duration/model.py) - not yet
          editable from this UI.
        </p>
      </Card>
    </div>
  );
}
