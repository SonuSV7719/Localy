// Small formatting helpers for download analytics.

export function humanBytes(bytes: number): string {
  if (!isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  const val = bytes / Math.pow(1024, i);
  return `${val.toFixed(i === 0 ? 0 : val < 10 ? 2 : 1)} ${units[i]}`;
}

export function humanSpeed(bytesPerSec: number): string {
  if (!isFinite(bytesPerSec) || bytesPerSec <= 0) return "—";
  return `${humanBytes(bytesPerSec)}/s`;
}

export function humanTime(seconds: number): string {
  if (!isFinite(seconds) || seconds <= 0) return "—";
  const s = Math.round(seconds);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  if (m < 60) return `${m}m ${rem}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}
