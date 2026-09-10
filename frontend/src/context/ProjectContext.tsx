import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import {
  checkHealth,
  getScript as apiGetScript,
  listScripts,
  runSegments as apiRunSegments,
  runTrack as apiRunTrack,
  uploadScript as apiUploadScript,
  type RunTrackArgs,
  type UploadScriptArgs,
} from "../api/client";
import type { LanguageTrack, ParsedScript, ScriptSummary } from "../api/types";
import {
  DEMO_EN_RUN,
  DEMO_EN_SCRIPT,
  DEMO_SCRIPT_ID,
  DEMO_STUBBED_STAGES,
  DEMO_TA_RUN,
  DEMO_TRACKS,
} from "../data/demoData";

export type DataMode = "live" | "demo";

interface ProjectContextValue {
  mode: DataMode;
  backendOnline: boolean | null; // null = still checking

  scriptId: string | null;
  parsedScript: ParsedScript | null;
  tracksByLanguage: Record<string, LanguageTrack>;
  audioUrlsByLanguage: Record<string, Record<string, string>>;
  exportUrlsByLanguage: Record<string, string[]>;
  stubbedStagesByLanguage: Record<string, string[]>;
  activeLanguage: string | null;
  sessionScripts: ScriptSummary[];

  lockedSegments: Set<string>;
  toggleSegmentLock: (segmentId: string) => void;

  loadDemo: () => void;
  exitDemo: () => void;
  parseScript: (args: UploadScriptArgs) => Promise<void>;
  openScript: (id: string) => Promise<void>;
  generateTrack: (args: Omit<RunTrackArgs, "scriptId">) => Promise<void>;
  rerunSegments: (language: string, segmentIds: string[]) => Promise<void>;
  setActiveLanguage: (language: string) => void;
  refreshSessionScripts: () => Promise<void>;
}

const ProjectContext = createContext<ProjectContextValue | null>(null);

export function ProjectProvider({ children }: { children: React.ReactNode }) {
  const [mode, setMode] = useState<DataMode>("live");
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);

  const [scriptId, setScriptId] = useState<string | null>(null);
  const [parsedScript, setParsedScript] = useState<ParsedScript | null>(null);
  const [tracksByLanguage, setTracksByLanguage] = useState<Record<string, LanguageTrack>>({});
  const [audioUrlsByLanguage, setAudioUrlsByLanguage] = useState<Record<string, Record<string, string>>>({});
  const [exportUrlsByLanguage, setExportUrlsByLanguage] = useState<Record<string, string[]>>({});
  const [stubbedStagesByLanguage, setStubbedStagesByLanguage] = useState<Record<string, string[]>>({});
  const [activeLanguage, setActiveLanguageState] = useState<string | null>(null);
  const [sessionScripts, setSessionScripts] = useState<ScriptSummary[]>([]);
  const [lockedSegments, setLockedSegments] = useState<Set<string>>(new Set());

  const refreshSessionScripts = useCallback(async () => {
    if (mode !== "live") return;
    try {
      const scripts = await listScripts();
      setSessionScripts(scripts);
    } catch {
      // backend went away mid-session; health check below will catch it
    }
  }, [mode]);

  useEffect(() => {
    let cancelled = false;
    checkHealth().then((ok) => {
      if (cancelled) return;
      setBackendOnline(ok);
      if (ok) refreshSessionScripts();
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadDemo = useCallback(() => {
    setMode("demo");
    setScriptId(DEMO_SCRIPT_ID);
    setParsedScript(DEMO_EN_SCRIPT);
    setTracksByLanguage(DEMO_TRACKS);
    setAudioUrlsByLanguage({ en: DEMO_EN_RUN.audio_urls, ta: DEMO_TA_RUN.audio_urls });
    setExportUrlsByLanguage({ en: DEMO_EN_RUN.export_urls, ta: DEMO_TA_RUN.export_urls });
    setStubbedStagesByLanguage({ en: DEMO_STUBBED_STAGES, ta: DEMO_STUBBED_STAGES });
    setActiveLanguageState("ta");
    setLockedSegments(new Set());
  }, []);

  const exitDemo = useCallback(() => {
    setMode("live");
    setScriptId(null);
    setParsedScript(null);
    setTracksByLanguage({});
    setAudioUrlsByLanguage({});
    setExportUrlsByLanguage({});
    setStubbedStagesByLanguage({});
    setActiveLanguageState(null);
    setLockedSegments(new Set());
  }, []);

  const parseScript = useCallback(
    async (args: UploadScriptArgs) => {
      const res = await apiUploadScript(args);
      setMode("live");
      setScriptId(res.id);
      setParsedScript(res.script);
      setTracksByLanguage({});
      setAudioUrlsByLanguage({});
      setExportUrlsByLanguage({});
      setStubbedStagesByLanguage({});
      setActiveLanguageState(null);
      setLockedSegments(new Set());
      await refreshSessionScripts();
    },
    [refreshSessionScripts],
  );

  const openScript = useCallback(async (id: string) => {
    const res = await apiGetScript(id);
    setMode("live");
    setScriptId(res.id);
    setParsedScript(res.script);
    setTracksByLanguage({});
    setAudioUrlsByLanguage({});
    setExportUrlsByLanguage({});
    setStubbedStagesByLanguage({});
    setActiveLanguageState(null);
    setLockedSegments(new Set());
  }, []);

  const generateTrack = useCallback(
    async (args: Omit<RunTrackArgs, "scriptId">) => {
      if (!scriptId || mode !== "live") return;
      const res = await apiRunTrack({ scriptId, ...args });
      setTracksByLanguage((prev) => ({ ...prev, [args.language]: res.track }));
      setAudioUrlsByLanguage((prev) => ({ ...prev, [args.language]: res.audio_urls }));
      setExportUrlsByLanguage((prev) => ({ ...prev, [args.language]: res.export_urls }));
      setStubbedStagesByLanguage((prev) => ({ ...prev, [args.language]: res.stubbed_stages }));
      setActiveLanguageState(args.language);
      await refreshSessionScripts();
    },
    [scriptId, mode, refreshSessionScripts],
  );

  const rerunSegments = useCallback(
    async (language: string, segmentIds: string[]) => {
      if (!scriptId || mode !== "live") return;
      const res = await apiRunSegments(scriptId, language, segmentIds);
      setTracksByLanguage((prev) => ({ ...prev, [language]: res.track }));
      setAudioUrlsByLanguage((prev) => ({ ...prev, [language]: res.audio_urls }));
      setExportUrlsByLanguage((prev) => ({ ...prev, [language]: res.export_urls }));
      setStubbedStagesByLanguage((prev) => ({ ...prev, [language]: res.stubbed_stages }));
    },
    [scriptId, mode],
  );

  const toggleSegmentLock = useCallback((segmentId: string) => {
    setLockedSegments((prev) => {
      const next = new Set(prev);
      if (next.has(segmentId)) next.delete(segmentId);
      else next.add(segmentId);
      return next;
    });
  }, []);

  const value = useMemo<ProjectContextValue>(
    () => ({
      mode,
      backendOnline,
      scriptId,
      parsedScript,
      tracksByLanguage,
      audioUrlsByLanguage,
      exportUrlsByLanguage,
      stubbedStagesByLanguage,
      activeLanguage,
      sessionScripts,
      lockedSegments,
      toggleSegmentLock,
      loadDemo,
      exitDemo,
      parseScript,
      openScript,
      generateTrack,
      rerunSegments,
      setActiveLanguage: setActiveLanguageState,
      refreshSessionScripts,
    }),
    [
      mode,
      backendOnline,
      scriptId,
      parsedScript,
      tracksByLanguage,
      audioUrlsByLanguage,
      exportUrlsByLanguage,
      stubbedStagesByLanguage,
      activeLanguage,
      sessionScripts,
      lockedSegments,
      toggleSegmentLock,
      loadDemo,
      exitDemo,
      parseScript,
      openScript,
      generateTrack,
      rerunSegments,
      refreshSessionScripts,
    ],
  );

  return <ProjectContext.Provider value={value}>{children}</ProjectContext.Provider>;
}

export function useProject(): ProjectContextValue {
  const ctx = useContext(ProjectContext);
  if (!ctx) throw new Error("useProject must be used within a ProjectProvider");
  return ctx;
}
