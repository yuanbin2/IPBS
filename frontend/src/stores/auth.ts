import { defineStore } from "pinia";

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

const emptySession: AuthSession = {
  actor: "anonymous",
  role: "visitor",
  workspace_key: "default",
  authenticated: false,
  security_enforced: false
};

export const useAuthStore = defineStore("auth", {
  state: () => ({
    token: localStorage.getItem("agent_auth_token") || "",
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
    async bootstrap() {
      if (!this.token) {
        this.loaded = true;
        return;
      }
      try {
        const payload = await this.requestJson("/api/agent/auth/me/");
        this.session = payload;
      } catch {
        this.logout();
      } finally {
        this.loaded = true;
      }
    },
    async login(username: string, password: string) {
      const payload = await this.requestJson("/api/agent/auth/login/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password })
      });
      this.applyAuthPayload(payload);
    },
    async register(username: string, password: string, role: string, workspaceKey: string) {
      const payload = await this.requestJson("/api/agent/auth/register/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password, role, workspace_key: workspaceKey })
      });
      this.applyAuthPayload(payload);
    },
    logout() {
      this.token = "";
      this.session = { ...emptySession };
      this.user = null;
      localStorage.removeItem("agent_auth_token");
    },
    applyAuthPayload(payload: { token: string; user?: AuthUser; session: AuthSession }) {
      this.token = payload.token;
      this.user = payload.user ?? null;
      this.session = payload.session;
      localStorage.setItem("agent_auth_token", payload.token);
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
