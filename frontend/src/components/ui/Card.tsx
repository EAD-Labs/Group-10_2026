export function Card({
  title,
  action,
  children,
  className = "",
  bodyClassName = "p-4",
}: {
  title?: React.ReactNode;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <div
      className={`rounded-lg border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900 ${className}`}
    >
      {(title || action) && (
        <div className="flex items-center justify-between border-b border-zinc-200 px-4 py-2.5 dark:border-zinc-800">
          {title && (
            <h3 className="text-[13px] font-semibold text-zinc-700 dark:text-zinc-200">{title}</h3>
          )}
          {action}
        </div>
      )}
      <div className={bodyClassName}>{children}</div>
    </div>
  );
}

export function Stat({
  label,
  value,
  hint,
  tone = "default",
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "default" | "error" | "warning" | "ok";
}) {
  const toneClass =
    tone === "error"
      ? "text-red-600 dark:text-red-400"
      : tone === "warning"
        ? "text-amber-600 dark:text-amber-400"
        : tone === "ok"
          ? "text-emerald-600 dark:text-emerald-400"
          : "text-zinc-900 dark:text-zinc-100";
  return (
    <div>
      <div className="text-[11px] font-medium uppercase tracking-wide text-zinc-400 dark:text-zinc-500">
        {label}
      </div>
      <div className={`text-xl font-semibold tabular-nums ${toneClass}`}>{value}</div>
      {hint && <div className="text-[11px] text-zinc-400 dark:text-zinc-500">{hint}</div>}
    </div>
  );
}
