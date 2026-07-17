// API Client wrapper for backend communication
import { ChatCompletionRequest } from "./types";

export const API_BASE_URL = "http://127.0.0.1:11434";

export class APIError extends Error {
  constructor(public status: number, message: string, public code?: string) {
    super(message);
    this.name = "APIError";
  }
}

/** Default per-request timeout (ms). Kept generous so a busy backend
 * (e.g. loading a model) is not mistaken for a dead one. */
const DEFAULT_TIMEOUT_MS = 12000;

async function request<T>(
  path: string,
  options?: RequestInit & { timeoutMs?: number }
): Promise<T> {
  const url = `${API_BASE_URL}${path}`;

  // Attach a timeout so a hung request cannot wedge the UI. If the caller
  // passed their own signal, honour it too. A timeoutMs <= 0 disables the
  // timeout entirely — required for genuinely long operations like loading a
  // model across the pool, which can take minutes to stream weights to workers.
  const controller = new AbortController();
  const timeoutMs = options?.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  let timedOut = false;
  const timer = timeoutMs > 0 ? setTimeout(() => { timedOut = true; controller.abort(); }, timeoutMs) : null;
  if (options?.signal) {
    if (options.signal.aborted) controller.abort();
    else options.signal.addEventListener("abort", () => controller.abort(), { once: true });
  }

  let response: Response;
  try {
    response = await fetch(url, {
      ...options,
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...options?.headers,
      },
    });
  } catch (e: any) {
    if (e?.name === "AbortError") {
      if (timedOut) throw new APIError(0, `Request to ${path} timed out`, "timeout");
      throw new APIError(0, `Request to ${path} was cancelled`, "aborted");
    }
    throw new APIError(0, e?.message || "Network error", "network");
  } finally {
    if (timer) clearTimeout(timer);
  }

  if (!response.ok) {
    let message = "An error occurred with the API server.";
    let code: string | undefined;

    try {
      const errorJson = await response.json();
      message = errorJson.message || message;
      code = errorJson.error_code;
    } catch {
      // Fallback if not JSON
    }

    throw new APIError(response.status, message, code);
  }

  return response.json() as Promise<T>;
}

type ReqOptions = RequestInit & { timeoutMs?: number };

export const apiClient = {
  get<T>(path: string, options?: ReqOptions): Promise<T> {
    return request<T>(path, { ...options, method: "GET" });
  },

  post<T>(path: string, body: any, options?: ReqOptions): Promise<T> {
    return request<T>(path, {
      ...options,
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  delete<T>(path: string, body?: any, options?: ReqOptions): Promise<T> {
    return request<T>(path, {
      ...options,
      method: "DELETE",
      body: body ? JSON.stringify(body) : undefined,
    });
  },

  /**
   * Helper to perform SSE streaming for chat completions
   */
  async streamChat(
    req: ChatCompletionRequest,
    onChunk: (token: string) => void,
    onDone: () => void,
    onError: (err: Error) => void,
    signal?: AbortSignal
  ): Promise<void> {
    try {
      const response = await fetch(`${API_BASE_URL}/v1/chat/completions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          ...req,
          stream: true,
        }),
        signal,
      });

      if (!response.ok) {
        throw new Error(`Streaming failed with status: ${response.status}`);
      }

      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error("Response body reader not available");
      }

      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        // Keep the last partial line in the buffer
        buffer = lines.pop() || "";

        for (const line of lines) {
          const cleanedLine = line.trim();
          if (!cleanedLine) continue;

          if (cleanedLine.startsWith("data: ")) {
            const dataStr = cleanedLine.slice(6);
            
            if (dataStr === "[DONE]") {
              onDone();
              return;
            }

            try {
              const data = JSON.parse(dataStr);
              const token = data.choices?.[0]?.delta?.content;
              if (token) {
                onChunk(token);
              }
            } catch (e) {
              // Ignore parse errors on malformed lines
            }
          }
        }
      }

      onDone();
    } catch (e: any) {
      // A user-initiated abort (Stop button / unmount) is a graceful end,
      // not an error — keep whatever tokens were already streamed.
      if (e?.name === "AbortError") {
        onDone();
        return;
      }
      onError(e);
    }
  },

  /**
   * Helper to perform NDJSON progress streaming for pulling models
   */
  async streamPull(
    modelId: string,
    onProgress: (completedBytes: number, totalBytes: number, status: string) => void,
    onDone: () => void,
    onError: (err: Error) => void
  ): Promise<void> {
    try {
      const response = await fetch(`${API_BASE_URL}/api/pull`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          name: modelId,
          stream: true,
        }),
      });

      if (!response.ok) {
        throw new Error(`Download request failed with status: ${response.status}`);
      }

      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error("Response body reader not available");
      }

      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          const cleanedLine = line.trim();
          if (!cleanedLine) continue;

          try {
            const progress = JSON.parse(cleanedLine);
            const status: string = progress.status || "";
            if (status === "success") {
              onDone();
              return;
            } else if (status.startsWith("error")) {
              onError(new Error(status));
              return;
            } else if (typeof progress.total === "number" && progress.total > 0) {
              // Backend sends "downloading NN%" with completed/total byte counts.
              onProgress(progress.completed || 0, progress.total || 0, "downloading");
            } else {
              // Status-only line (e.g. "pulling manifest").
              onProgress(0, 0, status);
            }
          } catch {
            // Ignore JSON parse errors on partial/malformed lines
          }
        }
      }

      onDone();
    } catch (e: any) {
      onError(e);
    }
  }
};
