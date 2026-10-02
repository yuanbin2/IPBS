import { defineStore } from "pinia";
import { authPost, clearAccessToken, getAccessToken, refreshAccessToken, setAccessToken } from "../api/client";

interface AuthSession {
  actor: string;
  role: "admin" | "operator" | "visitor";
  workspace_key: string;
  authenticated: boolean;
  security_enforced: boolean;
}

interface AuthUser {
  username: string;
  role: "admin" | "operator" | "visitor";
  workspace_key: string;
}

interface AuthPayload {
  token?: string;
  access?: string;
  user?: AuthUser;
  session: AuthSession;
}

const emptySession: AuthSession = {
  actor: "anonymous",
  role: "visitor",
  workspace_key: "default",
  authenticated: false,
  security_enforced: false
};

let syncStarted = false;
let authChannel: BroadcastChannel | null = null;

export const useAuthStore = defineStore("auth", {
  state: () => ({
    token: "",
    session: { ...emptySession },
    user: null as AuthUser | null,
    loaded: false
  }),
  getters: {
    isAuthenticated: (state) => Boolean(state.token) && state.session.authenticated,
    roleLabel: (state) => {
      const labels = { admin: "管理员", operator: "操作员", visitor: "访客" };
      return labels[state.session.role] ?? state.session.role;
    }
  },
  actions: {
    startSync() {
      if (syncStarted) return;
      syncStarted = true;
      window.addEventListener("blog-access-changed", (event) => {
        this.token = (event as CustomEvent<string>).detail;
        if (!this.token) this.session = { ...emptySession };
      });
      if (typeof BroadcastChannel !== "undefined") {
        authChannel = new BroadcastChannel("blog-auth");
        authChannel.onmessage = (event) => {
          if (event.data?.type !== "logout") return;
          this.clearLocalSession();
          window.location.replace("/login");
        };
      }
    },
    clearLocalSession() {
      clearAccessToken();
      this.token = "";
      this.session = { ...emptySession };
      this.user = null;
      localStorage.removeItem("agent_auth_token");
      localStorage.removeItem("agent_refresh_token");
    },
    async bootstrap() {
      this.startSync();
      const legacyRefresh = localStorage.getItem("agent_refresh_token");
      localStorage.removeItem("agent_auth_token");
      localStorage.removeItem("agent_refresh_token");
      try {
        try {
          await refreshAccessToken();
        } catch {
          if (!legacyRefresh) throw new Error("No session");
          const upgraded = await authPost("upgrade", { refresh: legacyRefresh });
          setAccessToken(String(upgraded.access ?? ""));
        }
        this.token = getAccessToken();
        this.session = await this.requestJson("/api/agent/auth/me/");
      } catch {
        this.clearLocalSession();
      } finally {
        this.loaded = true;
      }
    },
    async login(username: string, password: string) {
      this.startSync();
      const payload = await authPost("login", { username, password }) as unknown as AuthPayload;
      this.applyAuthPayload(payload);
    },
    async register(username: string, password: string) {
      this.startSync();
      const payload = await authPost("register", { username, password }) as unknown as AuthPayload;
      this.applyAuthPayload(payload);
    },
    async logout() {
      await authPost("logout");
      this.clearLocalSession();
      authChannel?.postMessage({ type: "logout" });
    },
    applyAuthPayload(payload: AuthPayload) {
      setAccessToken(payload.access ?? payload.token ?? "");
      this.token = getAccessToken();
      this.user = payload.user ?? null;
      this.session = payload.session;
      this.loaded = true;
      localStorage.removeItem("agent_auth_token");
      localStorage.removeItem("agent_refresh_token");
    },
    async requestJson(url: string, options: RequestInit = {}) {
      const response = await fetch(url, options);
      const text = await response.text();
      const payload = text ? JSON.parse(text) : null;
      if (!response.ok) {
        throw new Error(payload?.detail ?? `HTTP ${response.status}`);
      }
      return payload;
    }
  }
});
