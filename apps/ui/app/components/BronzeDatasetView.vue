<script setup lang="ts">
import type { TableColumn } from '@nuxt/ui'
import type { BronzePreparation } from '~/types/bronze'
const props = defineProps<{ versionId: string; preparation: BronzePreparation }>()
type Row = { row_number: number; data: Record<string, unknown> }
const baseURL = useApiBase()
const table = ref(props.preparation.dataset?.tables[0]?.name ?? '')
const page = ref(1)
const rows = ref<Row[]>([])
const loading = ref(false)
const failure = ref('')
const definition = computed(() => props.preparation.dataset?.tables.find(item => item.name === table.value))
const columns = computed<TableColumn<Row>[]>(() => [
  { accessorKey: 'row_number', header: 'Ligne source' },
  ...(definition.value?.columns ?? []).map((name, index) => ({ id: `column-${index}`, header: name,
    cell: ({ row }: { row: { original: Row } }) => row.original.data[name] == null ? 'NULL' : typeof row.original.data[name] === 'object' ? JSON.stringify(row.original.data[name]) : String(row.original.data[name]),
  })),
])
let sequence = 0
async function load() {
  const current = ++sequence
  if (!table.value) return
  loading.value = true; failure.value = ''
  try {
    const result = await $fetch<{ rows: Row[] }>(`/model-versions/${props.versionId}/bronze/rows`, { baseURL, query: { table: table.value, offset: (page.value - 1) * 20, limit: 20 } })
    if (current === sequence) rows.value = result.rows
  }
  catch { if (current === sequence) failure.value = 'Les données Bronze ne sont pas accessibles.' }
  finally { if (current === sequence) loading.value = false }
}
watch(table, () => { page.value = 1; void load() })
watch(page, () => { void load() })
onMounted(() => { void load() })
</script>

<template>
  <div class="space-y-5">
    <UAlert color="info" variant="subtle" icon="i-lucide-database" title="Données Bronze" :description="`${preparation.dataset?.valid ?? 0} lignes intégrées. ${preparation.state === 'complete' ? 'Bronze validé pour Silver.' : 'Consulte les rapports avant de valider Bronze.'}`" />
    <UCard>
      <template #header><h2 class="font-semibold text-highlighted">Données disponibles pour Silver</h2><p class="mt-1 break-all text-sm text-muted">Base : {{ preparation.database_name }} · schéma : {{ preparation.schema_name ?? 'bronze' }}</p></template>
      <div class="space-y-4">
        <UAlert v-if="failure" color="error" :description="failure" role="alert" />
        <UFormField label="Table Bronze"><USelect v-model="table" :items="preparation.dataset?.tables.map(item => ({ label: `${item.name} · ${item.rows} lignes`, value: item.name })) ?? []" :disabled="loading" class="w-full" aria-label="Table Bronze à consulter" /></UFormField>
        <UTable :data="rows" :columns="columns" :loading="loading" />
        <UPagination v-if="definition && definition.rows > 20" v-model:page="page" :total="definition.rows" :items-per-page="20" :disabled="loading" />
      </div>
    </UCard>
  </div>
</template>
