// API Client wrapper for backend communication
import { ChatCompletionRequest } from "./types";

export const API_BASE_URL = "http://127.0.0.1:11434";

export class APIError extends Error {
  constructor(public status: number, message: string, public code?: string) {
    super(message);
    this.name = "APIError";
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE_URL}${path}`;
  const response = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });

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

export const apiClient = {
  get<T>(path: string, options?: RequestInit): Promise<T> {
    return request<T>(path, { ...options, method: "GET" });
  },

  post<T>(path: string, body: any, options?: RequestInit): Promise<T> {
    return request<T>(path, {
      ...options,
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  delete<T>(path: string, body?: any, options?: RequestInit): Promise<T> {
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
    onError: (err: Error) => void
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
