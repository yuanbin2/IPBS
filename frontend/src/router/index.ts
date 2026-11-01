import { createRouter, createWebHistory } from "vue-router";
import { useAuthStore } from "../stores/auth";

// Route-level lazy loading keeps the editor and visualization dependencies out
// of the first screen's bundle. Each view becomes an independently cached chunk.
const AgentChatView = () => import("../views/AgentChatView.vue");
const AdminApprovalView = () => import("../views/AdminApprovalView.vue");
const BlogView = () => import("../views/BlogView.vue");
const BlogSettingsView = () => import("../features/blog/components/BlogSettingsView.vue");
const CollectionDetailView = () => import("../views/CollectionDetailView.vue");
const CollectionManagerView = () => import("../views/CollectionManagerView.vue");
const CollectionsView = () => import("../views/CollectionsView.vue");
const HomeView = () => import("../views/HomeView.vue");
const KnowledgeBaseView = () => import("../views/KnowledgeBaseView.vue");
const LoginView = () => import("../views/LoginView.vue");
const MCPToolsView = () => import("../views/MCPToolsView.vue");
const ObservabilityView = () => import("../views/ObservabilityView.vue");
const LandingView = () => import("../views/LandingView.vue");
const SecurityView = () => import("../views/SecurityView.vue");

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/landing",
      name: "landing",
      component: LandingView,
      meta: { public: true, guestOnly: true }
    },
    {
      path: "/login",
      name: "login",
      component: LoginView,
      meta: { public: true, guestOnly: true }
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
      path: "/blog/collections",
      name: "blog-collections",
      component: CollectionsView,
      meta: { public: true }
    },
    {
      path: "/blog/collections/mine",
      name: "blog-collection-mine",
      component: CollectionManagerView
    },
    {
      path: "/blog/collections/:publicId",
      name: "blog-collection-detail",
      component: CollectionDetailView,
      meta: { public: true }
    },
    {
      path: "/blog/settings",
      name: "blog-settings",
      component: BlogSettingsView
    },
    {
      path: "/blog/:slug?",
      name: "blog",
      component: BlogView,
      meta: { public: true }
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
      component: ObservabilityView,
      meta: { requiresOperator: true }
    },
    {
      path: "/security",
      name: "security",
      component: SecurityView,
      meta: { requiresAdmin: true }
    }
  ]
});

router.beforeEach(async (to) => {
  const auth = useAuthStore();
  if (!auth.loaded) {
    await auth.bootstrap();
  }
  if (to.meta.guestOnly) {
    return auth.isAuthenticated ? "/" : true;
  }
  if (to.meta.public) return true;
  if (!auth.isAuthenticated) {
    // If going to root, show landing page; otherwise redirect to login
    if (to.path === "/") {
      return { path: "/landing" };
    }
    return { path: "/login", query: { redirect: to.fullPath } };
  }
  if (to.meta.requiresOperator && !auth.canViewObservability) {
    return "/";
  }
  if (to.meta.requiresAdmin && auth.session.role !== "admin") {
    return "/";
  }
  return true;
});

export default router;
