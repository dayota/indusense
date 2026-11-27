<script setup lang="ts">
import type { BronzePreparation } from '~/types/bronze'
const props = defineProps<{ versionId: string; preparation: BronzePreparation }>()
const baseURL = useApiBase()
const batches = computed(() => props.preparation.batches ?? [])
const latest = computed(() => {
  const result = new Map<string, (typeof batches.value)[number]>()
  for (const batch of batches.value) {
    const key = `${batch.target_table}:${batch.source_hash}`
    if (!result.has(key)) result.set(key, batch)
  }
  return [...result.values()]
})
const metrics = computed(() => [
  { label: 'Lignes lues (dernières tentatives)', value: latest.value.reduce((sum, batch) => sum + batch.records_read, 0) },
  { label: 'Lignes présentes en Bronze', value: props.preparation.dataset?.valid ?? 0 },
  { label: 'Lignes annulées / rejetées', value: latest.value.reduce((sum, batch) => sum + batch.records_rejected, 0) },
  { label: 'Lignes avec anomalie de cast', value: latest.value.reduce((sum, batch) => sum + Number(batch.report?.cast_error_rows ?? 0), 0) },
])
const date = (value?: string | null) => value ? new Date(value).toLocaleString('fr-FR') : '—'
const duration = (start?: string, end?: string | null) => start && end ? `${((Date.parse(end) - Date.parse(start)) / 1000).toFixed(2)} s` : '—'
</script>

<template>
  <UTabs :items="[{ label: 'Rapport d’ingestion', slot: 'report', value: 'report' }, { label: 'Revue', slot: 'review', value: 'review' }]" variant="link" class="w-full items-stretch" aria-label="Rapport et revue Bronze">
    <template #report>
      <div class="space-y-5 pt-4">
        <UAlert v-if="preparation.state === 'complete'" color="success" title="Bronze dataset validé" />
        <UAlert v-else-if="latest.some(batch => batch.status === 'FAILED')" color="error" title="L’ingestion comporte des échecs" description="Consulte les diagnostics. La validation reste bloquée tant que les lots requis et leurs rapports ne sont pas complets." />
        <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><UCard v-for="metric in metrics" :key="metric.label"><p class="text-xs text-muted">{{ metric.label }}</p><p class="mt-2 text-2xl font-semibold tabular-nums">{{ metric.value.toLocaleString('fr-FR') }}</p></UCard></div>
        <p class="text-sm text-muted">Un cast impossible conserve la valeur brute et son motif. Un dépassement du seuil annule toute la table concernée. Les rejouages sont tracés séparément et ne multiplient pas les données.</p>
        <UButton :to="baseURL + `/model-versions/${versionId}/bronze/export`" external label="Exporter les sources, contrats et rapports" icon="i-lucide-download" color="neutral" />
        <UCard v-for="batch in batches" :key="batch.batch_id">
          <template #header><div class="flex flex-wrap items-center justify-between gap-3"><h3 class="font-semibold">{{ batch.target_table }}</h3><UBadge :color="batch.status === 'FAILED' ? 'error' : batch.status === 'RUNNING' ? 'info' : batch.status === 'PARTIAL' ? 'warning' : 'success'">{{ batch.status }}</UBadge></div></template>
          <div class="space-y-4">
            <dl class="grid gap-3 text-sm sm:grid-cols-2">
              <div><dt class="text-muted">Batch ID</dt><dd class="break-all font-mono text-xs">{{ batch.batch_id }}</dd></div>
              <div><dt class="text-muted">Source</dt><dd class="break-all">{{ batch.source_name }}</dd></div>
              <div><dt class="text-muted">Début / fin</dt><dd>{{ date(batch.started_at) }} → {{ date(batch.completed_at) }}</dd></div>
              <div><dt class="text-muted">Durée</dt><dd>{{ duration(batch.started_at, batch.completed_at) }}</dd></div>
              <div><dt class="text-muted">Lues / insérées / annulées</dt><dd>{{ batch.records_read }} / {{ batch.records_inserted }} / {{ batch.records_rejected }}</dd></div>
              <div><dt class="text-muted">Anomalies de cast</dt><dd>{{ batch.report?.cast_error_rows ?? 0 }}</dd></div>
              <div><dt class="text-muted">SHA-256 source</dt><dd class="break-all font-mono text-xs">{{ batch.source_hash }}</dd></div>
              <div><dt class="text-muted">Empreinte du contrat</dt><dd class="break-all font-mono text-xs">{{ batch.config_hash }}</dd></div>
            </dl>
            <UAlert v-if="batch.report?.error" color="error" :description="String(batch.report.error)" />
            <UAccordion :items="[{label:'Rapport détaillé',slot:'report'},{label:'Dictionnaire de données et transformations',slot:'dictionary'}]"><template #report><pre class="overflow-auto whitespace-pre-wrap text-xs">{{ JSON.stringify(batch.report, null, 2) }}</pre></template><template #dictionary><pre class="overflow-auto whitespace-pre-wrap text-xs">{{ JSON.stringify(batch.dictionary, null, 2) }}</pre></template></UAccordion>
          </div>
        </UCard>
      </div>
    </template>
    <template #review><div class="pt-4"><BronzeSchemaReview v-if="preparation.database_name" :version-id="versionId" /><UEmpty v-else title="Aucune base disponible" /></div></template>
  </UTabs>
</template>
