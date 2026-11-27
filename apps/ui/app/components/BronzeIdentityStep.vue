<script setup lang="ts">
import MarkdownIt from 'markdown-it'
import type { PreparationFile } from '~/types/bronze'

const props = defineProps<{ files: PreparationFile[] }>()
const selectedFileId = ref('')
watch(() => props.files.map(file => file.id), ids => {
  if (!ids.includes(selectedFileId.value)) selectedFileId.value = ids[0] ?? ''
}, { immediate: true })
const selectedFile = computed(() => props.files.find(file => file.id === selectedFileId.value))
// Escape HTML originating from source values in the report.
const markdown = new MarkdownIt({ html: false, linkify: false })
const report = computed(() => markdown.render(selectedFile.value?.report ?? ''))
</script>

<template>
  <div class="grid items-start gap-4 md:grid-cols-[max-content_minmax(0,1fr)]">
    <nav aria-label="Cartes d’identité" class="flex min-w-64 flex-col gap-2 overflow-x-auto rounded-lg border border-default p-2 md:sticky md:top-0">
      <p class="px-2 py-1 text-xs font-medium text-muted">Fichiers</p>
      <UButton
        v-for="file in props.files" :key="file.id" :label="file.filename"
        :icon="file.format === 'sql' ? 'i-lucide-database' : 'i-lucide-file-spreadsheet'"
        :variant="selectedFileId === file.id ? 'soft' : 'ghost'"
        :color="selectedFileId === file.id ? 'primary' : 'neutral'"
        :aria-pressed="selectedFileId === file.id" aria-controls="bronze-identity-report"
        class="w-full justify-start" :ui="{ label: 'whitespace-nowrap text-left' }"
        @click="selectedFileId = file.id"
      />
    </nav>
    <UCard v-if="selectedFile" id="bronze-identity-report" class="min-w-0">
      <template #header>
        <h2 class="font-semibold">{{ selectedFile.filename }}</h2>
        <p class="mt-1 break-all text-xs text-muted">{{ selectedFile.summary?.identity_path }}</p>
      </template>
      <article v-if="selectedFile.report" class="identity-markdown min-w-0" :aria-label="`Carte d’identité de ${selectedFile.filename}`" v-html="report" />
      <p v-else class="text-sm text-muted">La carte d’identité de ce fichier n’a pas encore été générée.</p>
    </UCard>
  </div>
</template>

<style scoped>
.identity-markdown { overflow-wrap: anywhere; font-size: 0.875rem; line-height: 1.7; }
.identity-markdown :deep(h1), .identity-markdown :deep(h2), .identity-markdown :deep(h3), .identity-markdown :deep(h4) { margin: 1.5rem 0 0.75rem; font-weight: 600; line-height: 1.4; }
.identity-markdown :deep(h1) { font-size: 1.5rem; }
.identity-markdown :deep(h2) { font-size: 1.25rem; }
.identity-markdown :deep(h3) { font-size: 1.125rem; }
.identity-markdown :deep(> :first-child) { margin-top: 0; }
.identity-markdown :deep(p), .identity-markdown :deep(ul), .identity-markdown :deep(ol) { margin: 0.75rem 0; }
.identity-markdown :deep(ul) { list-style: disc; padding-left: 1.5rem; }
.identity-markdown :deep(ol) { list-style: decimal; padding-left: 1.5rem; }
.identity-markdown :deep(table) { display: block; max-width: 100%; overflow-x: auto; border-collapse: collapse; margin: 1rem 0; }
.identity-markdown :deep(th), .identity-markdown :deep(td) { border: 1px solid var(--ui-border); padding: 0.5rem 0.75rem; text-align: left; }
.identity-markdown :deep(th) { background: var(--ui-bg-elevated); font-weight: 600; }
.identity-markdown :deep(code) { background: var(--ui-bg-elevated); padding: 0.125rem 0.25rem; border-radius: 0.25rem; font-size: 0.85em; }
.identity-markdown :deep(pre) { overflow-x: auto; background: var(--ui-bg-elevated); padding: 1rem; border-radius: 0.5rem; }
.identity-markdown :deep(pre code) { padding: 0; }
.identity-markdown :deep(a) { color: var(--ui-primary); text-decoration: underline; }
.identity-markdown :deep(blockquote) { border-left: 3px solid var(--ui-border); padding-left: 1rem; color: var(--ui-text-muted); }
.identity-markdown :deep(hr) { margin: 1.5rem 0; border-color: var(--ui-border); }
</style>
