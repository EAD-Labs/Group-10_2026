import {
  Activity,
  AudioLines,
  Download,
  FilePlus2,
  FileText,
  FolderOpen,
  GitBranch,
  LayoutDashboard,
  Languages,
  Settings,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { NavLink } from "react-router-dom";

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13px] font-medium transition-colors ${
    isActive
      ? "bg-indigo-50 text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300"
      : "text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
  }`;

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-4">
      <div className="mb-1 px-2.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-400 dark:text-zinc-600">
        {title}
      </div>
      <div className="flex flex-col gap-0.5">{children}</div>
    </div>
  );
}

export function Sidebar() {
  return (
    <aside className="flex h-screen w-56 shrink-0 flex-col border-r border-zinc-200 bg-zinc-50/60 dark:border-zinc-800 dark:bg-zinc-950">
      <div className="flex items-center gap-2 px-4 py-4">
        <div className="flex h-6 w-6 items-center justify-center rounded bg-indigo-600 text-white">
          <Sparkles className="h-3.5 w-3.5" />
        </div>
        <span className="text-[13px] font-semibold text-zinc-900 dark:text-zinc-100">
          Spoken Tutorial
        </span>
      </div>

      <nav className="flex-1 overflow-y-auto px-2 py-2">
        <Section title="Workspace">
          <NavLink to="/" end className={linkClass}>
            <LayoutDashboard className="h-4 w-4" /> Dashboard
          </NavLink>
          <NavLink to="/new" className={linkClass}>
            <FilePlus2 className="h-4 w-4" /> New Project
          </NavLink>
          <NavLink to="/projects" className={linkClass}>
            <FolderOpen className="h-4 w-4" /> Projects
          </NavLink>
        </Section>

        <Section title="Production">
          <NavLink to="/script" className={linkClass}>
            <FileText className="h-4 w-4" /> Script
          </NavLink>
          <NavLink to="/translation" className={linkClass}>
            <Languages className="h-4 w-4" /> Translation
          </NavLink>
          <NavLink to="/audio" className={linkClass}>
            <AudioLines className="h-4 w-4" /> Audio
          </NavLink>
          <NavLink to="/timeline" className={linkClass}>
            <GitBranch className="h-4 w-4 rotate-90" /> Timeline
          </NavLink>
        </Section>

        <Section title="Quality">
          <NavLink to="/qa" className={linkClass}>
            <ShieldCheck className="h-4 w-4" /> QA Review
          </NavLink>
          <NavLink to="/alignment" className={linkClass}>
            <Activity className="h-4 w-4" /> Alignment
          </NavLink>
        </Section>

        <Section title="Output">
          <NavLink to="/exports" className={linkClass}>
            <Download className="h-4 w-4" /> Exports
          </NavLink>
        </Section>
      </nav>

      <div className="border-t border-zinc-200 px-2 py-2 dark:border-zinc-800">
        <NavLink to="/settings" className={linkClass}>
          <Settings className="h-4 w-4" /> Settings
        </NavLink>
        <div className="mt-1 flex items-center gap-2 rounded-md px-2.5 py-1.5">
          <div className="flex h-6 w-6 items-center justify-center rounded-full bg-zinc-200 text-[10px] font-semibold text-zinc-600 dark:bg-zinc-700 dark:text-zinc-300">
            G10
          </div>
          <div className="text-[11px] text-zinc-500 dark:text-zinc-400">Group 10 · EduPyramids</div>
        </div>
      </div>
    </aside>
  );
}
