import { createRouter, createWebHistory } from "vue-router";
import AgentChatView from "../views/AgentChatView.vue";
import AdminApprovalView from "../views/AdminApprovalView.vue";
import BlogView from "../views/BlogView.vue";
import HomeView from "../views/HomeView.vue";
import KnowledgeBaseView from "../views/KnowledgeBaseView.vue";
import LoginView from "../views/LoginView.vue";
import MCPToolsView from "../views/MCPToolsView.vue";
import ObservabilityView from "../views/ObservabilityView.vue";
import SecurityView from "../views/SecurityView.vue";
import { useAuthStore } from "../stores/auth";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/login",
      name: "login",
      component: LoginView,
      meta: { public: true }
    },
    {
      path: "/",
      name: "home",
      component: HomeView
    },
    {
      path: "/chat",
      name: "agent-chat",
      component: AgentChatView
    },
    {
      path: "/blog/:slug?",
      name: "blog",
      component: BlogView
    },
    {
      path: "/knowledge",
      name: "knowledge-base",
      component: KnowledgeBaseView
    },
    {
      path: "/admin-approvals",
      name: "admin-approvals",
      component: AdminApprovalView
    },
    {
      path: "/mcp-tools",
      name: "mcp-tools",
      component: MCPToolsView
    },
    {
      path: "/observability",
      name: "observability",
      component: ObservabilityView
    },
    {
      path: "/security",
      name: "security",
      component: SecurityView
    }
  ]
});

router.beforeEach(async (to) => {
  const auth = useAuthStore();
  if (!auth.loaded) {
    await auth.bootstrap();
  }
  if (to.meta.public) {
    return auth.isAuthenticated ? "/" : true;
  }
  if (!auth.isAuthenticated) {
    return { path: "/login", query: { redirect: to.fullPath } };
  }
  return true;
});

export default router;
