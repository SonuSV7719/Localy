// Tracks a streaming download and derives smoothed speed + ETA.
//
// Speed is computed over a sliding time window (not since-start), so it reflects
// the *current* rate and the ETA reacts to network changes instead of lagging.

export interface ProgressStats {
  completed: number;
  total: number;
  percent: number; // 0..100
  speedBps: number; // bytes/sec, smoothed
  etaSeconds: number; // estimated time remaining
  elapsedSeconds: number;
}

const WINDOW_MS = 5000; // speed averaged over the last 5 seconds

export class DownloadTracker {
  private startMs: number | null = null;
  private samples: { t: number; bytes: number }[] = [];

  reset(): void {
    this.startMs = null;
    this.samples = [];
  }

  update(completed: number, total: number): ProgressStats {
    const now = Date.now();
    if (this.startMs === null) this.startMs = now;

    this.samples.push({ t: now, bytes: completed });
    // Drop samples older than the window (keep at least the last two).
    const cutoff = now - WINDOW_MS;
    while (this.samples.length > 2 && this.samples[0].t < cutoff) {
      this.samples.shift();
    }

    const first = this.samples[0];
    const last = this.samples[this.samples.length - 1];
    const dt = (last.t - first.t) / 1000;
    const dBytes = last.bytes - first.bytes;
    const speedBps = dt > 0 ? Math.max(0, dBytes / dt) : 0;

    const percent = total > 0 ? Math.min(100, (completed / total) * 100) : 0;
    const remaining = Math.max(0, total - completed);
    const etaSeconds = speedBps > 0 && total > 0 ? remaining / speedBps : Infinity;
    const elapsedSeconds = (now - this.startMs) / 1000;

    return { completed, total, percent, speedBps, etaSeconds, elapsedSeconds };
  }
}
