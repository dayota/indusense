<script setup lang="ts">
import type { TableColumn } from '@nuxt/ui'
const props = defineProps<{ versionId: string }>()
type Definition = { name: string; rows: number; columns: { name: string; type: string; nullable: boolean }[] }
type Entry = { data: Record<string, unknown> }
const baseURL = useApiBase()
const tables = ref<Definition[]>([])
const selected = ref('')
const currentPage = ref(1)
const rows = ref<Entry[]>([])
const loading = ref(false)
const failure = ref('')
const schema = ref('')
const definition = computed(() => tables.value.find(table => table.name === selected.value))
const columns = computed<TableColumn<Entry>[]>(() => (definition.value?.columns ?? []).map((column, index) => ({
  id: `column-${index}`, header: column.name,
  cell: ({ row }) => {
    const value = row.original.data[column.name]
    return value == null ? 'NULL' : typeof value === 'object' ? JSON.stringify(value) : String(value)
  },
})))
let sequence = 0
async function loadRows() {
  const request = ++sequence
  rows.value = []
  if (!selected.value) return
  loading.value = true; failure.value = ''
  try {
    const result = await $fetch<{ rows: Entry[] }>(`/model-versions/${props.versionId}/bronze/schema/rows`, {
      baseURL, query: { table: selected.value, offset: (currentPage.value - 1) * 20, limit: 20 },
    })
    if (sequence === request) rows.value = result.rows
  }
  catch { if (sequence === request) failure.value = 'Le contenu de la table n’est pas accessible.' }
  finally { if (sequence === request) loading.value = false }
}
watch([selected, currentPage], ([table], [previousTable]) => {
  if (table !== previousTable && currentPage.value !== 1) { currentPage.value = 1; return }
  void loadRows()
})
onMounted(async () => {
  try {
    const result = await $fetch<{ schema: string; tables: Definition[] }>(`/model-versions/${props.versionId}/bronze/schema`, { baseURL })
    schema.value = result.schema; tables.value = result.tables; selected.value = result.tables[0]?.name ?? ''
  }
  catch { failure.value = 'Le schéma Bronze n’est pas accessible.' }
})
</script>

<template>
  <div class="space-y-4">
    <UAlert color="info" :title="`Revue du schéma ${schema} — lecture seule`" description="Données et logs d’erreurs de la version sélectionnée. Les versions précédentes restent isolées dans leurs propres schémas." />
    <UAlert v-if="failure" color="error" :description="failure" />
    <div class="grid items-start gap-4 md:grid-cols-[max-content_minmax(0,1fr)]">
      <nav aria-label="Tables du schéma bronze" class="flex min-w-64 flex-col gap-2 overflow-x-auto rounded-lg border border-default p-2 md:sticky md:top-0">
        <UButton v-for="table in tables" :key="table.name" :label="table.name" icon="i-lucide-table-2" :variant="selected === table.name ? 'soft' : 'ghost'" :color="selected === table.name ? 'primary' : 'neutral'" :aria-pressed="selected === table.name" class="justify-start" @click="selected = table.name" />
      </nav>
      <UCard v-if="definition" class="min-w-0">
        <template #header><h3 class="font-semibold">{{ schema }}.{{ definition.name }}</h3><p class="mt-1 text-sm text-muted">{{ definition.rows.toLocaleString('fr-FR') }} lignes</p></template>
        <div class="space-y-4">
          <UAccordion :items="[{ label: 'Structure de la table', slot: 'structure' }]"><template #structure><div class="overflow-x-auto"><table class="w-full text-left text-sm"><thead><tr><th>Colonne</th><th>Type PostgreSQL</th><th>Nullable</th></tr></thead><tbody><tr v-for="column in definition.columns" :key="column.name"><td class="py-1">{{ column.name }}</td><td>{{ column.type }}</td><td>{{ column.nullable ? 'Oui' : 'Non' }}</td></tr></tbody></table></div></template></UAccordion>
          <UTable :data="rows" :columns="columns" :loading="loading" />
          <UPagination v-if="definition.rows > 20" v-model:page="currentPage" :total="definition.rows" :items-per-page="20" :disabled="loading" />
        </div>
      </UCard>
    </div>
  </div>
</template>
