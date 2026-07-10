import { createApp } from "vue";
import { createPinia } from "pinia";
import ElementPlus from "element-plus";
import "element-plus/dist/index.css";

import App from "./App.vue";
import router from "./router";
import "./style.css";

const nativeFetch = window.fetch.bind(window);
window.fetch = (input: RequestInfo | URL, init: RequestInit = {}) => {
  const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
  if (url.startsWith("/api/agent/")) {
    const headers = new Headers(init.headers || {});
    const token = localStorage.getItem("agent_auth_token");
    if (token && !headers.has("Authorization")) {
      headers.set("Authorization", `Bearer ${token}`);
    }
    return nativeFetch(input, { ...init, headers });
  }
  return nativeFetch(input, init);
};

createApp(App).use(createPinia()).use(router).use(ElementPlus).mount("#app");
