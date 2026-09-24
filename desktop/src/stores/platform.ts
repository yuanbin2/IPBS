import { defineStore } from "pinia";

export const usePlatformStore = defineStore("platform", {
  state: () => ({
    projectName: "智能个人博客系统",
    stack: ["Vue 3", "Django", "LangChain-style Tools", "Agentic RAG", "MCP", "SQLite/PostgreSQL"]
  })
});

