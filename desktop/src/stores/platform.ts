import { defineStore } from "pinia";

export const usePlatformStore = defineStore("platform", {
  state: () => ({
    projectName: "企业知识智能体平台 + 个人博客智能体系统",
    stack: ["Vue 3", "Django", "LangChain-style Tools", "Agentic RAG", "MCP", "SQLite/PostgreSQL"]
  })
});

