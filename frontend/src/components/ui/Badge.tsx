type Tone = "ok" | "warning" | "error" | "neutral" | "accent" | "stub";

const TONE_CLASSES: Record<Tone, string> = {
  ok: "bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-600/20 dark:bg-emerald-500/10 dark:text-emerald-400 dark:ring-emerald-500/20",
  warning:
    "bg-amber-50 text-amber-700 ring-1 ring-inset ring-amber-600/20 dark:bg-amber-500/10 dark:text-amber-400 dark:ring-amber-500/20",
  error:
    "bg-red-50 text-red-700 ring-1 ring-inset ring-red-600/20 dark:bg-red-500/10 dark:text-red-400 dark:ring-red-500/20",
  neutral:
    "bg-zinc-100 text-zinc-600 ring-1 ring-inset ring-zinc-500/10 dark:bg-zinc-800 dark:text-zinc-300 dark:ring-zinc-700",
  accent:
    "bg-indigo-50 text-indigo-700 ring-1 ring-inset ring-indigo-600/20 dark:bg-indigo-500/10 dark:text-indigo-400 dark:ring-indigo-500/20",
  stub: "bg-orange-50 text-orange-700 ring-1 ring-inset ring-orange-600/30 dark:bg-orange-500/10 dark:text-orange-400 dark:ring-orange-500/30",
};

export function Badge({
  tone = "neutral",
  children,
  className = "",
}: {
  tone?: Tone;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-medium leading-none ${TONE_CLASSES[tone]} ${className}`}
    >
      {children}
    </span>
  );
}

export function StubBadge() {
  return <Badge tone="stub">STUB</Badge>;
}
