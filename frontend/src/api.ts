// Typed client for the FastAPI backend. Mirrors backend/app/api/schemas.py.

export type Mode = "auto" | "qa" | "essay" | "artifact";
export type ProviderName = "ollama" | "anthropic";

export interface ApiErrorBody {
  code: string;
  message: string;
  hint?: string | null;
  request_id?: string | null;
}

export class ApiError extends Error {
  constructor(public body: ApiErrorBody, public status: number) {
    super(body.message);
  }
}

export interface Source {
  id: string;
  episode_title: string;
  episode_slug: string;
  guest: string | null;
  speakers: string[];
  start_ts: string | null;
  deep_link: string | null;
  source_url: string;
  snippet: string;
  vector_score: number | null;
}

export interface Message {
  id: string;
  session_id: string;
  role: "user" | "assistant";
  content: string;
  route: string | null;
  provider: string | null;
  model: string | null;
  sources: Source[];
  meta: Record<string, any>;
  created_at: string;
  artifact_id: string | null;
}

export interface Artifact {
  id: string;
  session_id: string;
  message_id: string | null;
  kind: "markdown" | "html";
  title: string;
  content: string;
  sanitizer: Record<string, any>;
  created_at: string;
}

export interface Session {
  id: string;
  user_id: string;
  title: string;
  provider: ProviderName;
  created_at: string;
  updated_at: string;
  message_count?: number | null;
}

export interface SessionDetail extends Session {
  messages: Message[];
  artifacts: Artifact[];
}

export interface ProviderInfo {
  name: ProviderName;
  model: string;
  label: string;
  local: boolean;
  available: boolean;
  reason: string | null;
}

export interface AppConfig {
  version: string;
  default_provider: ProviderName;
  fallback_provider: string;
  agent_engine: string;
  providers: ProviderInfo[];
}

export interface Readiness {
  status: "ready" | "degraded";
  checks: {
    database: { ok: boolean };
    knowledge_base: { ok: boolean; episodes?: number; chunks?: number; embedded_chunks?: number; hint?: string | null };
  };
}

export type StreamEvent =
  | { type: "meta"; route: string; route_reason: string; provider: string | null; model: string | null; engine: string | null; sources: Source[]; notices: string[] }
  | { type: "delta"; text: string }
  | { type: "artifact"; artifact: Artifact }
  | { type: "done"; message: Message }
  | { type: "error"; error: ApiErrorBody };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { ...init, headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) } });
  } catch {
    throw new ApiError({ code: "NETWORK_ERROR", message: "Can't reach the API server.", hint: "Check that the api container is running (docker compose ps)." }, 0);
  }
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    throw new ApiError(data?.error ?? { code: "HTTP_" + res.status, message: res.statusText }, res.status);
  }
  return data as T;
}

export const api = {
  config: () => request<AppConfig>("/api/config"),
  ready: () => fetch("/health/ready").then((r) => r.json() as Promise<Readiness>),
  listSessions: (userId: string) => request<Session[]>(`/api/sessions?user_id=${encodeURIComponent(userId)}`),
  createSession: (userId: string, displayName: string | null, provider: ProviderName) =>
    request<Session>("/api/sessions", {
      method: "POST",
      body: JSON.stringify({ user_id: userId, display_name: displayName, provider, user_metadata: { client: "web", tz: Intl.DateTimeFormat().resolvedOptions().timeZone } }),
    }),
  getSession: (id: string) => request<SessionDetail>(`/api/sessions/${id}`),
  updateSession: (id: string, patch: { title?: string; provider?: ProviderName }) =>
    request<Session>(`/api/sessions/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  deleteSession: (id: string) => request<void>(`/api/sessions/${id}`, { method: "DELETE" }),
};

/** POST + Server-Sent Events via fetch streaming (EventSource cannot POST). */
export async function streamMessage(
  sessionId: string,
  body: { content: string; mode: Mode; provider?: ProviderName },
  onEvent: (ev: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`/api/sessions/${sessionId}/messages/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") return;
    throw new ApiError({ code: "NETWORK_ERROR", message: "Can't reach the API server." }, 0);
  }
  if (!res.ok || !res.body) {
    const data = await res.json().catch(() => null);
    throw new ApiError(data?.error ?? { code: "HTTP_" + res.status, message: res.statusText }, res.status);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const dataLine = frame.split("\n").find((l) => l.startsWith("data:"));
      if (dataLine) onEvent(JSON.parse(dataLine.slice(5)) as StreamEvent);
    }
  }
}
