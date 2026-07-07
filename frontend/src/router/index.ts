import { createRouter, createWebHistory } from "vue-router";
import AgentChatView from "../views/AgentChatView.vue";
import HomeView from "../views/HomeView.vue";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/",
      name: "home",
      component: HomeView
    },
    {
      path: "/chat",
      name: "agent-chat",
      component: AgentChatView
    }
  ]
});

export default router;
