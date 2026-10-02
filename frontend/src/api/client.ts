const nativeFetch = window.fetch.bind(window);
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "";

export function apiUrl(path: string): string {
  return `${API_BASE_URL}${path}`;
}

let accessToken = "";
let csrfToken: string | null = null;
let refreshPromise: Promise<string> | null = null;

export function getAccessToken(): string {
  return accessToken;
}

export function setAccessToken(token: string): void {
  accessToken = token;
  window.dispatchEvent(new CustomEvent("blog-access-changed", { detail: token }));
}

export function clearAccessToken(): void {
  setAccessToken("");
}

async function getCsrfToken(): Promise<string> {
  if (csrfToken) return csrfToken;
  const response = await nativeFetch(apiUrl("/api/agent/auth/csrf/"), {
    credentials: "include"
  });
  if (!response.ok) throw new Error(`CSRF 初始化失败 (${response.status})`);
  const payload = await response.json();
  csrfToken = payload.csrfToken;
  if (!csrfToken) throw new Error("CSRF 初始化失败");
  return csrfToken;
}

export async function authPost(path: string, body?: Record<string, unknown>): Promise<Record<string, unknown>> {
  const response = await nativeFetch(apiUrl(`/api/agent/auth/cookie/${path}/`), {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": await getCsrfToken()
    },
    body: JSON.stringify(body ?? {})
  });
  const text = await response.text();
  let payload: Record<string, unknown> = {};
  if (text && (response.headers.get("content-type") ?? "").includes("application/json")) {
    payload = JSON.parse(text);
  }
  if (!response.ok) {
    const detail = typeof payload.detail === "string" ? payload.detail : `HTTP ${response.status}`;
    throw new Error(detail);
  }
  return payload;
}

async function withRefreshLock<T>(action: () => Promise<T>): Promise<T> {
  if (navigator.locks) {
    return navigator.locks.request("blog-refresh", action);
  }
  return action();
}

export async function refreshAccessToken(): Promise<string> {
  refreshPromise ??= withRefreshLock(async () => {
    const payload = await authPost("refresh");
    const token = String(payload.access ?? "");
    if (!token) throw new Error("刷新响应缺少访问令牌");
    setAccessToken(token);
    return token;
  }).finally(() => {
    refreshPromise = null;
  });
  return refreshPromise;
}

/** Keep feature requests on one authenticated boundary; tokens never enter storage. */
export function installApiClient(): void {
  window.fetch = async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    const isApiCall = url.startsWith("/api/agent/") || url.startsWith("api/agent/");
    if (!isApiCall) return nativeFetch(input, init);

    const fullUrl = url.startsWith("/") ? `${API_BASE_URL}${url}` : `${API_BASE_URL}/${url}`;
    const headers = new Headers(init.headers || {});
    if (accessToken && !headers.has("Authorization")) {
      headers.set("Authorization", `Bearer ${accessToken}`);
    }
    if (!headers.has("Content-Type") && !(init.body instanceof FormData)) {
      headers.set("Content-Type", "application/json");
    }

    const options: RequestInit = { ...init, headers, credentials: "include" };
    let response = await nativeFetch(fullUrl, options);
    if (response.status === 401 && !url.includes("/auth/")) {
      try {
        headers.set("Authorization", `Bearer ${await refreshAccessToken()}`);
        response = await nativeFetch(fullUrl, options);
      } catch {
        clearAccessToken();
      }
    }
    return response;
  };
}
