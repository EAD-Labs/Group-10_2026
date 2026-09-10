export function formatSeconds(seconds: number, decimals = 1): string {
  return `${seconds.toFixed(decimals)}s`;
}

export function formatTimestamp(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds - m * 60;
  return `${String(m).padStart(2, "0")}:${s.toFixed(1).padStart(4, "0")}`;
}

export function formatSigned(seconds: number, decimals = 2): string {
  const sign = seconds >= 0 ? "+" : "";
  return `${sign}${seconds.toFixed(decimals)}s`;
}

export function formatPercent(ratio: number, decimals = 0): string {
  return `${(ratio * 100).toFixed(decimals)}%`;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(1)} ${units[unitIndex]}`;
}

export const LANGUAGE_LABELS: Record<string, string> = {
  en: "English",
  ta: "Tamil",
  hi: "Hindi",
  mr: "Marathi",
};

export function languageLabel(code: string): string {
  return LANGUAGE_LABELS[code] ?? code.toUpperCase();
}
