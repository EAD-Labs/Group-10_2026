import type { LucideIcon } from "lucide-react";

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-zinc-300 px-6 py-16 text-center dark:border-zinc-700">
      <Icon className="h-8 w-8 text-zinc-300 dark:text-zinc-600" strokeWidth={1.5} />
      <div>
        <p className="text-sm font-medium text-zinc-700 dark:text-zinc-200">{title}</p>
        <p className="mt-1 max-w-sm text-xs text-zinc-400 dark:text-zinc-500">{description}</p>
      </div>
      {action}
    </div>
  );
}
