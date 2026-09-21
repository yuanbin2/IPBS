const nativeFetch = window.fetch.bind(window);
let refreshPromise: Promise<string> | null = null;

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'https://backend-production-721c.up.railway.app';

async function refreshAccessToken(): Promise<string> {
  const refresh = localStorage.getItem("agent_refresh_token");
  if (!refresh) throw new Error("No refresh token");

  const response = await nativeFetch(`${API_BASE_URL}/api/agent/auth/refresh/`, {
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

    // Check if this is an API call that needs to go to the backend
    const isApiCall = url.startsWith("/api/agent/") || url.startsWith("api/agent/");

    // If it's not an API call, use the original fetch
    if (!isApiCall) return nativeFetch(input, init);

    // Construct the full URL with API_BASE_URL
    let fullUrl = url;
    if (url.startsWith("/api/agent/")) {
      fullUrl = `${API_BASE_URL}${url}`;
    } else if (url.startsWith("api/agent/")) {
      fullUrl = `${API_BASE_URL}/${url}`;
    }

    const headers = new Headers(init.headers || {});
    const token = localStorage.getItem("agent_auth_token");
    if (token && !headers.has("Authorization")) {
      headers.set("Authorization", `Bearer ${token}`);
    }

    // Add CORS headers
    if (!headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }

    let response = await nativeFetch(fullUrl, { ...init, headers });
    const isAuthEndpoint =
      url.includes("/auth/login/") || url.includes("/auth/register/") || url.includes("/auth/refresh/");

    if (response.status === 401 && !isAuthEndpoint && localStorage.getItem("agent_refresh_token")) {
      try {
        refreshPromise ??= refreshAccessToken().finally(() => {
          refreshPromise = null;
        });
        headers.set("Authorization", `Bearer ${await refreshPromise}`);
        response = await nativeFetch(fullUrl, { ...init, headers });
      } catch {
        localStorage.removeItem("agent_auth_token");
        localStorage.removeItem("agent_refresh_token");
      }
    }
    return response;
  };
}
