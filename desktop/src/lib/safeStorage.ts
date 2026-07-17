// Quota-safe localStorage helpers.
//
// Large chat histories can exceed the ~5 MB localStorage quota. When
// `setItem` throws QuotaExceededError, the naive code path aborted the React
// state update mid-flight, which is why long responses appeared to "vanish".
// These helpers never throw: they report success/failure so callers can trim
// old data and retry, and always keep the in-memory state intact.

export interface SaveResult {
  ok: boolean;
  quotaExceeded: boolean;
}

function isQuotaError(e: unknown): boolean {
  if (!(e instanceof DOMException)) return false;
  return (
    e.code === 22 || // legacy
    e.code === 1014 || // Firefox
    e.name === "QuotaExceededError" ||
    e.name === "NS_ERROR_DOM_QUOTA_REACHED"
  );
}

/** Write a value, never throwing. Returns whether it succeeded. */
export function safeSetItem(key: string, value: string): SaveResult {
  try {
    localStorage.setItem(key, value);
    return { ok: true, quotaExceeded: false };
  } catch (e) {
    return { ok: false, quotaExceeded: isQuotaError(e) };
  }
}

/**
 * Persist a JSON-serialisable list under `key`. If the quota is hit, drop the
 * oldest entries (assumed to be at the END of the array — callers keep newest
 * first) until it fits, so recent conversations always survive.
 * Returns the (possibly trimmed) list that was actually stored.
 */
export function saveListWithTrim<T>(key: string, list: T[]): { stored: T[]; trimmed: number } {
  let working = list;
  let trimmed = 0;

  // At most a few iterations: each drops the oldest 20% of remaining items.
  while (working.length > 0) {
    const res = safeSetItem(key, JSON.stringify(working));
    if (res.ok) return { stored: working, trimmed };
    if (!res.quotaExceeded) return { stored: working, trimmed }; // non-quota error: give up quietly
    const dropCount = Math.max(1, Math.floor(working.length * 0.2));
    working = working.slice(0, working.length - dropCount);
    trimmed += dropCount;
  }

  // Even an empty list failed to write — clear the key to unwedge storage.
  try {
    localStorage.removeItem(key);
  } catch {
    /* ignore */
  }
  return { stored: [], trimmed };
}
