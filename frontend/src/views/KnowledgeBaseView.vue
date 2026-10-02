<script setup lang="ts">
import { computed } from "vue";
import KnowledgeBaseSidebar from "../features/knowledge/components/KnowledgeBaseSidebar.vue";
import DocumentManager from "../features/knowledge/components/DocumentManager.vue";
import KnowledgeSearchPanel from "../features/knowledge/components/KnowledgeSearchPanel.vue";
import { useKnowledgeBase } from "../features/knowledge/composables/useKnowledgeBase";

const knowledge = useKnowledgeBase();

const kbCount = computed(
  () => knowledge.knowledgeBases.value.filter((kb) => !kb.is_archived).length
);
const docCount = computed(() =>
  knowledge.knowledgeBases.value.reduce((sum, kb) => sum + (kb.document_count || 0), 0)
);
const chunkCount = computed(() =>
  knowledge.knowledgeBases.value.reduce((sum, kb) => sum + (kb.chunk_count || 0), 0)
);
</script>

<template>
  <section class="knowledge-workspace">
    <header class="knowledge-header">
      <div>
        <span class="knowledge-eyebrow">Knowledge Ops</span>
        <h1>知识库</h1>
        <p>沉淀团队文档并自动切分、向量化，为智能体提供可检索、可溯源的私有知识。</p>
      </div>
      <dl class="knowledge-header-stats">
        <div>
          <dt>知识库</dt>
          <dd>{{ kbCount }}</dd>
        </div>
        <div>
          <dt>文档</dt>
          <dd>{{ docCount }}</dd>
        </div>
        <div>
          <dt>片段</dt>
          <dd>{{ chunkCount }}</dd>
        </div>
      </dl>
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
        @archive="knowledge.archiveKnowledgeBase"
        @create="knowledge.createKnowledgeBase"
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
</template>
