export function Progress({
  ratio,
  tone = "accent",
  className = "",
}: {
  ratio: number; // 0..1, may exceed 1 to show overflow
  tone?: "accent" | "ok" | "warning" | "error";
  className?: string;
}) {
  const clamped = Math.min(Math.max(ratio, 0), 1);
  const barClass =
    tone === "error"
      ? "bg-red-500"
      : tone === "warning"
        ? "bg-amber-500"
        : tone === "ok"
          ? "bg-emerald-500"
          : "bg-indigo-500";
  return (
    <div className={`h-1.5 w-full overflow-hidden rounded-full bg-zinc-100 dark:bg-zinc-800 ${className}`}>
      <div
        className={`h-full rounded-full transition-all ${barClass}`}
        style={{ width: `${clamped * 100}%` }}
      />
    </div>
  );
}
