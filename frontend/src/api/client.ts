const nativeFetch = window.fetch.bind(window);
let refreshPromise: Promise<string> | null = null;

async function refreshAccessToken(): Promise<string> {
  const refresh = localStorage.getItem("agent_refresh_token");
  if (!refresh) throw new Error("No refresh token");

  const response = await nativeFetch("/api/agent/auth/refresh/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh })
  });
  if (!response.ok) throw new Error("JWT refresh failed");

  const payload = await response.json();
  localStorage.setItem("agent_auth_token", payload.access);
  if (payload.refresh) localStorage.setItem("agent_refresh_token", payload.refresh);
  return payload.access;
}

/**
 * Install one authenticated fetch boundary for the SPA.
 *
 * Existing feature modules may continue using fetch while authorization,
 * refresh de-duplication and one-time retry remain centralized here.
 */
export function installApiClient() {
  window.fetch = async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    if (!url.startsWith("/api/agent/")) return nativeFetch(input, init);

    const headers = new Headers(init.headers || {});
    const token = localStorage.getItem("agent_auth_token");
    if (token && !headers.has("Authorization")) {
      headers.set("Authorization", `Bearer ${token}`);
    }

    let response = await nativeFetch(input, { ...init, headers });
    const isAuthEndpoint =
      url.includes("/auth/login/") || url.includes("/auth/register/") || url.includes("/auth/refresh/");

    if (response.status === 401 && !isAuthEndpoint && localStorage.getItem("agent_refresh_token")) {
      try {
        refreshPromise ??= refreshAccessToken().finally(() => {
          refreshPromise = null;
        });
        headers.set("Authorization", `Bearer ${await refreshPromise}`);
        response = await nativeFetch(input, { ...init, headers });
      } catch {
        localStorage.removeItem("agent_auth_token");
        localStorage.removeItem("agent_refresh_token");
      }
    }
    return response;
  };
}
