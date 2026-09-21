<script setup lang="ts">
import { Back } from "@element-plus/icons-vue";
import { RouterLink } from "vue-router";
import KnowledgeBaseSidebar from "../features/knowledge/components/KnowledgeBaseSidebar.vue";
import DocumentManager from "../features/knowledge/components/DocumentManager.vue";
import KnowledgeSearchPanel from "../features/knowledge/components/KnowledgeSearchPanel.vue";
import { useKnowledgeBase } from "../features/knowledge/composables/useKnowledgeBase";

const knowledge = useKnowledgeBase();
</script>

<template>
  <main class="shell">
    <aside class="sidebar">
      <div class="brand">Knowledge Agent</div>
      <nav class="nav">
        <RouterLink to="/">概览</RouterLink>
        <RouterLink to="/blog">博客</RouterLink>
        <RouterLink class="active" to="/knowledge">知识库</RouterLink>
        <RouterLink to="/chat">对话</RouterLink>
      </nav>
    </aside>

    <section class="workspace knowledge-workspace">
      <header class="topbar">
        <div><p class="eyebrow">Day 4 RAG + Vector Search</p><h1>知识库与文档检索</h1></div>
        <RouterLink to="/chat"><el-button :icon="Back">回到对话</el-button></RouterLink>
      </header>

      <section class="knowledge-layout">
        <KnowledgeBaseSidebar
          :items="knowledge.knowledgeBases.value"
          :selected-id="knowledge.selectedKnowledgeBaseId.value"
          :loading="knowledge.loading.value"
          :deleting-id="knowledge.deletingKnowledgeBaseId.value"
          @select="knowledge.selectKnowledgeBase"
          @refresh="knowledge.loadKnowledgeBases"
          @remove="knowledge.deleteKnowledgeBase"
        />
        <section class="knowledge-main">
          <DocumentManager
            :documents="knowledge.documents.value"
            :upload-title="knowledge.uploadTitle.value"
            :has-file="Boolean(knowledge.uploadFile.value)"
            :uploading="knowledge.uploading.value"
            :upload-progress="knowledge.uploadProgress.value"
            :upload-stage="knowledge.uploadStage.value"
            :reindexing-id="knowledge.reindexingDocumentId.value"
            :deleting-id="knowledge.deletingDocumentId.value"
            @update:upload-title="knowledge.uploadTitle.value = $event"
            @file-change="knowledge.handleFileChange"
            @upload="knowledge.uploadDocument"
            @refresh="knowledge.loadDocuments"
            @reindex="knowledge.reindexDocument"
            @remove="knowledge.deleteDocument"
          />
          <KnowledgeSearchPanel
            :query="knowledge.searchQuery.value"
            :results="knowledge.searchResults.value"
            :searching="knowledge.searching.value"
            @update:query="knowledge.searchQuery.value = $event"
            @search="knowledge.searchKnowledge"
          />
        </section>
      </section>
    </section>
  </main>
</template>
