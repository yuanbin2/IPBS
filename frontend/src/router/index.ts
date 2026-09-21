import { createRouter, createWebHistory } from "vue-router";
import { useAuthStore } from "../stores/auth";

// Route-level lazy loading keeps the editor and visualization dependencies out
// of the first screen's bundle. Each view becomes an independently cached chunk.
const AgentChatView = () => import("../views/AgentChatView.vue");
const AdminApprovalView = () => import("../views/AdminApprovalView.vue");
const BlogView = () => import("../views/BlogView.vue");
const HomeView = () => import("../views/HomeView.vue");
const KnowledgeBaseView = () => import("../views/KnowledgeBaseView.vue");
const LoginView = () => import("../views/LoginView.vue");
const MCPToolsView = () => import("../views/MCPToolsView.vue");
const ObservabilityView = () => import("../views/ObservabilityView.vue");

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
      component: AdminApprovalView,
      meta: { requiresAdmin: true }
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
  if (to.meta.requiresAdmin && auth.session.role !== "admin") {
    return "/";
  }
  return true;
});

export default router;
