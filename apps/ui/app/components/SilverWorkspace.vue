<script setup lang="ts">
import type { TableColumn } from '@nuxt/ui'
import type { Dataset, ModelVersionStatus } from '~/types/workflow'

type CellError = { column: string; message: string }
type Revision = { id: string; number: number; yaml: string; created_at: string }
type Run = { id: string; dataset_version_id: string; table_name: string; contract_revision: number; columns: string[]; source_rows: number; valid_rows: number; pending: number; discarded: number; reintegrated: number }
type Issue = { id: string; run_id: string; row_number: number; filename: string; table_name: string; source: Record<string, unknown>; candidate: Record<string, unknown>; errors: CellError[]; state: string; reason: string | null }
type PreviewRow = { row_number: number; data: Record<string, unknown> }
const props = defineProps<{ versionId: string; datasets: Dataset[]; status: ModelVersionStatus; parentBusy: boolean }>()
const emit = defineEmits<{ updated: []; gate: [blocked: boolean]; working: [active: boolean] }>()
const baseURL = useApiBase()
const prefix = computed(() => `/model-versions/${props.versionId}/silver`)
const state = ref<{ pending: number; can_advance: boolean; blocking_reason: string | null; runs: Run[] } | null>(null)
const busy = ref(false)
const failure = ref('')
const message = ref('')
const selected = ref('')
const yamlText = ref('')
const revisions = ref<Revision[]>([])
const revision = ref(0)
const savedId = ref('')
const savedYaml = ref('')
const revisionChoice = ref<number>()
const issuePage = ref(1)
const issueFilter = ref('pending')
const issues = ref<Issue[]>([])
const issueTotal = ref(0)
const issue = ref<Issue | null>(null)
const fields = ref<{ name: string; value: string; isNull: boolean }[]>([])
const reason = ref('')
const resolutionErrors = ref<CellError[]>([])
const resolutionOpen = ref(false)
const previewOpen = ref(false)
const contractsOpen = ref(false)
const previewRun = ref<Run | null>(null)
const previewPage = ref(1)
const preview = ref<PreviewRow[]>([])
const locked = computed(() => busy.value || props.parentBusy)
const editable = computed(() => ['ingestion-bronze', 'ingestion-silver'].includes(props.status))
const sourceItems = computed(() => props.datasets.flatMap(dataset => dataset.summary.tables.map(table => ({
  value: `${dataset.snapshot_id}/${table.name}`, label: `${dataset.name} · ${table.name}`, snapshot: dataset.snapshot_id, table: table.name,
}))))
const source = computed(() => sourceItems.value.find(item => item.value === selected.value))
const dirty = computed(() => yamlText.value !== savedYaml.value)
const contractPath = computed(() => source.value ? `${prefix.value}/contracts/${source.value.snapshot}` : '')
const query = computed(() => ({ table: source.value?.table ?? 'data' }))
const revisionItems = computed(() => revisions.value.map(item => ({ label: `Révision ${item.number} · ${new Date(item.created_at).toLocaleString('fr-FR')}`, value: item.number })))
let editorSequence = 0
function explain(error: unknown) {
  const detail = (error as { data?: { detail?: unknown } })?.data?.detail
  return typeof detail === 'string' ? detail : 'La demande a échoué. Réessaie après avoir vérifié les données.'
}
async function perform(action: () => Promise<void>) {
  if (busy.value) return
  emit('working', true)
  busy.value = true; failure.value = ''; message.value = ''
  try { await action() }
  catch (error) { failure.value = explain(error) }
  finally { busy.value = false; emit('working', false) }
}
async function refresh() {
  state.value = await $fetch(prefix.value, { baseURL })
  emit('gate', !state.value?.can_advance || dirty.value)
  await loadIssues()
}
async function loadIssues() {
  const result = await $fetch<{ rows: Issue[]; total: number }>(`${prefix.value}/quarantine`, { baseURL, query: { state: issueFilter.value, offset: (issuePage.value - 1) * 20, limit: 20 } })
  issues.value = result.rows; issueTotal.value = result.total
}
async function loadEditor() {
  const sequence = ++editorSequence
  yamlText.value = ''; savedYaml.value = ''; savedId.value = ''; revisions.value = []; revision.value = 0
  if (!source.value) return
  try {
    const result = await $fetch<{ yaml: string; revisions: Revision[] }>(contractPath.value, { baseURL, query: query.value })
    if (sequence !== editorSequence) return
    yamlText.value = result.yaml; savedYaml.value = result.yaml
    revisions.value = result.revisions
    revision.value = result.revisions[0]?.number ?? 0
    revisionChoice.value = revision.value || undefined
    savedId.value = result.revisions[0]?.id ?? ''
  }
  catch (error) { if (sequence === editorSequence) failure.value = explain(error) }
}
async function uploadContract(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  if (file.size > 200000) { failure.value = 'Le contrat doit faire moins de 200 Ko.'; input.value = ''; return }
  yamlText.value = await file.text(); message.value = 'Contrat chargé dans l’éditeur. Valide puis enregistre cette révision.'
  input.value = ''
}
function chooseRevision(value: number | undefined) {
  const chosen = revisions.value.find(item => item.number === value)
  if (chosen) yamlText.value = chosen.yaml
}
function validate() {
  return perform(async () => {
    await $fetch(`${contractPath.value}/validate`, { baseURL, method: 'POST', query: query.value, body: { yaml: yamlText.value } })
    message.value = 'Contrat valide. Enregistre sa révision avant de préparer la table.'
  })
}
function save() {
  return perform(async () => {
    const result = await $fetch<Revision>(contractPath.value, { baseURL, method: 'POST', query: query.value, body: { yaml: yamlText.value, base_revision: revision.value } })
    savedId.value = result.id; savedYaml.value = result.yaml; revision.value = result.number
    await loadEditor(); await refresh(); emit('updated')
    message.value = `Révision ${result.number} validée et enregistrée.`
  })
}
function prepare() {
  return perform(async () => {
    if (!source.value) return
    await $fetch(`${prefix.value}/prepare/${source.value.snapshot}`, { baseURL, method: 'POST', query: query.value, body: { contract_id: savedId.value } })
    await refresh(); emit('updated')
    message.value = 'Préparation terminée. Les lignes en erreur attendent ta décision dans la table tampon.'
  })
}
function openResolution(row: Issue) {
  issue.value = row; reason.value = ''; resolutionErrors.value = []; failure.value = ''
  const keys = [...new Set([...Object.keys(row.candidate), ...row.errors.map(error => error.column)])]
  fields.value = keys.map(name => ({ name, value: row.candidate[name] == null ? '' : typeof row.candidate[name] === 'object' ? JSON.stringify(row.candidate[name]) : String(row.candidate[name]), isNull: row.candidate[name] == null }))
  resolutionOpen.value = true
}
function resolve(action: 'discard' | 'reintegrate') {
  return perform(async () => {
    if (!issue.value) return
    const values = Object.fromEntries(fields.value.map(field => [field.name, field.isNull ? null : field.value]))
    const result = await $fetch<{ resolved: boolean; errors?: CellError[] }>(`${prefix.value}/quarantine/${issue.value.id}/resolve`, { baseURL, method: 'POST', body: { action, values: action === 'reintegrate' ? values : null, reason: reason.value } })
    if (!result.resolved) { resolutionErrors.value = result.errors ?? []; await loadIssues(); return }
    resolutionOpen.value = false
    await refresh(); emit('updated')
    message.value = action === 'discard' ? 'Ligne écartée définitivement pour cette version et cette source.' : 'Correction validée et ligne réintégrée en silver.'
  })
}
async function loadPreview() {
  if (!previewRun.value) return
  const result = await $fetch<{ rows: PreviewRow[] }>(`${prefix.value}/runs/${previewRun.value.id}/rows`, { baseURL, query: { offset: (previewPage.value - 1) * 20, limit: 20 } })
  preview.value = result.rows
}
function openPreview(run: Run) {
  previewRun.value = run; previewPage.value = 1; previewOpen.value = true
  void perform(loadPreview)
}
const previewColumns = computed<TableColumn<PreviewRow>[]>(() => [
  { accessorKey: 'row_number', header: '#' },
  ...(previewRun.value?.columns ?? []).map((name, index) => ({ id: `c-${index}`, header: name, cell: ({ row }: { row: { original: PreviewRow } }) => row.original.data[name] == null ? 'NULL' : String(row.original.data[name]) })),
])
watch(selected, () => { void loadEditor() })
watch(() => sourceItems.value.map(item => item.value).join('|'), () => {
  if (!sourceItems.value.some(item => item.value === selected.value)) selected.value = sourceItems.value[0]?.value ?? ''
}, { immediate: true })
watch(issueFilter, () => { issuePage.value = 1; void perform(loadIssues) })
watch(issuePage, () => { void perform(loadIssues) })
watch(previewPage, () => { void perform(loadPreview) })
watch(dirty, value => { emit('gate', !state.value?.can_advance || value) })
watch(() => props.status, () => { if (!busy.value) void perform(refresh) })
watch(() => props.datasets.map(dataset => dataset.snapshot_id).join('|'), () => { if (!busy.value) void perform(refresh) })
onMounted(() => { void perform(async () => { await refresh(); if (selected.value && !yamlText.value) await loadEditor() }) })
function openContracts() { contractsOpen.value = true }
defineExpose({ refresh, openContracts })
</script>

<template>
  <UCard>
    <template #header>
      <h2 class="font-semibold text-highlighted">Préparation bronze → silver</h2>
      <p class="mt-1 text-sm text-muted">Contrats versionnés, données typées et résolution humaine des erreurs.</p>
    </template>
    <div class="space-y-5">
      <UAlert v-if="failure" color="error" variant="subtle" :description="failure" role="alert" />
      <UAlert v-if="message" color="success" variant="subtle" :description="message" role="status" />
      <UAlert v-if="state?.blocking_reason" color="warning" variant="subtle" icon="i-lucide-lock-keyhole" title="Étape suivante bloquée" :description="state.blocking_reason" />
      <p v-if="!editable" class="text-sm text-muted">L’étape Silver est validée. Crée une nouvelle version du modèle pour modifier sa préparation.</p>
      <p v-else-if="status === 'ingestion-bronze'" class="text-sm text-muted">Valide l’étape Bronze pour commencer la préparation silver.</p>
      <template v-if="sourceItems.length">
        <UFormField label="Table source à préparer"><USelect v-model="selected" :items="sourceItems" :disabled="locked" class="w-full" aria-label="Table source silver" /></UFormField>
        <p class="text-sm text-muted">{{ savedId ? `Préparation avec la révision ${revision} du contrat.` : 'Valide et enregistre un contrat depuis le bouton « Contrats YAML » avant de préparer cette table.' }}</p>
        <p v-if="dirty" class="text-sm text-warning">Le contrat contient des modifications non enregistrées.</p>
        <UButton label="Préparer en silver" icon="i-lucide-layers" :disabled="locked || status !== 'ingestion-silver' || !savedId || dirty" @click="prepare" />
      </template>
      <p v-else class="text-sm text-muted">Ajoute un dataset bronze pour commencer la préparation silver.</p>
      <div v-if="state?.runs.length" class="space-y-3 border-t border-default pt-5">
        <h3 class="font-medium text-highlighted">Historique des préparations</h3>
        <div v-for="run in state.runs" :key="run.id" class="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-default p-3">
          <div><p class="text-sm font-medium">{{ datasets.find(dataset => dataset.snapshot_id === run.dataset_version_id)?.name ?? 'Source historique' }} · {{ run.table_name }} · contrat r{{ run.contract_revision }}</p><p class="mt-1 text-xs text-muted">{{ run.valid_rows }} lignes silver · {{ run.pending }} en attente · {{ run.discarded }} écartées · {{ run.reintegrated }} réintégrées</p></div>
          <UButton label="Voir les données silver" color="neutral" variant="outline" :disabled="locked" @click="openPreview(run)" />
        </div>
      </div>
      <div id="table-tampon" class="scroll-mt-4 space-y-4 border-t border-default pt-5">
        <div class="flex flex-wrap items-center justify-between gap-3"><h3 class="font-medium text-highlighted">Table tampon · {{ state?.pending ?? 0 }} ligne(s) à résoudre</h3><USelect v-model="issueFilter" :items="[{ label: 'En attente', value: 'pending' }, { label: 'Réintégrées', value: 'reintegrated' }, { label: 'Écartées', value: 'discarded' }, { label: 'Toutes les décisions', value: 'all' }]" :disabled="locked" aria-label="Filtrer la table tampon" /></div>
        <p class="text-xs text-muted">Toutes les erreurs associées à cette version doivent être résolues avant de poursuivre vers gold ou une étape ultérieure.</p>
        <div v-for="row in issues" :key="row.id" class="space-y-2 rounded-lg border border-default p-4">
          <div class="flex flex-wrap items-center justify-between gap-3"><p class="text-sm font-medium">{{ row.filename }} · {{ row.table_name }} · ligne {{ row.row_number }}</p><UBadge :color="row.state === 'pending' ? 'warning' : 'neutral'" variant="subtle">{{ row.state === 'pending' ? 'En attente' : row.state === 'discarded' ? 'Écartée' : 'Réintégrée' }}</UBadge></div>
          <p v-for="(error, index) in row.errors" :key="index" class="text-xs text-error">{{ error.column }} : {{ error.message }}</p>
          <pre class="max-h-40 overflow-auto rounded-md bg-elevated p-3 text-xs">{{ JSON.stringify(row.candidate, null, 2) }}</pre>
          <p v-if="row.reason" class="text-xs text-muted">Décision : {{ row.reason }}</p>
          <UButton v-if="row.state === 'pending'" label="Résoudre la ligne" icon="i-lucide-pencil-line" :disabled="locked || !editable" @click="openResolution(row)" />
        </div>
        <p v-if="!issues.length" class="text-sm text-muted">Aucune ligne dans cette sélection.</p>
        <UPagination v-if="issueTotal > 20" v-model:page="issuePage" :total="issueTotal" :items-per-page="20" :disabled="locked" />
      </div>
    </div>
  </UCard>
  <USlideover v-model:open="contractsOpen" :transition="false" title="Contrats YAML" description="Importe, modifie et valide les contrats de préparation de cette version du modèle." :ui="{ content: 'sm:max-w-3xl' }" :dismissible="!busy" :close="busy ? false : undefined">
    <template #body>
      <div class="space-y-5">
        <UAlert v-if="failure" color="error" variant="subtle" :description="failure" role="alert" />
        <UAlert v-if="message" color="success" variant="subtle" :description="message" role="status" />
        <template v-if="sourceItems.length">
          <UFormField label="Table source"><USelect v-model="selected" :items="sourceItems" :disabled="locked" class="w-full" aria-label="Table source du contrat" /></UFormField>
          <div class="flex flex-wrap items-end gap-3">
            <UFormField label="Importer un contrat YAML" class="flex-1"><input type="file" accept=".yaml,.yml" :disabled="locked || !editable" class="block w-full text-sm file:me-3 file:rounded-md file:border file:border-default file:bg-elevated file:px-3 file:py-2" aria-label="Importer un contrat YAML" @change="uploadContract"></UFormField>
            <UFormField v-if="revisions.length" label="Historique du contrat" class="min-w-64"><USelect v-model="revisionChoice" :items="revisionItems" :disabled="locked" class="w-full" aria-label="Historique du contrat" @update:model-value="chooseRevision" /></UFormField>
          </div>
          <UFormField label="Contrat de préparation" :hint="dirty ? 'Modifications non enregistrées' : revision ? `Révision ${revision}` : 'Brouillon issu du bronze'">
            <UTextarea v-model="yamlText" :rows="18" :disabled="locked || !editable" class="w-full" :ui="{ base: 'font-mono text-xs' }" aria-label="Contrat de préparation YAML" spellcheck="false" />
          </UFormField>
          <p class="text-xs leading-5 text-muted">Chaque colonne reçoit une colonne __type contenant le type déclaré dans ce contrat. Le hash SHA-256 identifie les valeurs sources bronze avant toute transformation. Les doublons de lignes restent conservés.</p>
          <div class="flex flex-wrap gap-3">
            <UButton label="Valider le contrat" color="neutral" variant="outline" :disabled="locked || !editable || !yamlText" @click="validate" />
            <UButton label="Enregistrer une révision" icon="i-lucide-save" :disabled="locked || !editable || !yamlText || (!dirty && !!savedId)" @click="save" />
          </div>
        </template>
        <p v-else class="text-sm text-muted">Ajoute un dataset bronze pour gérer ses contrats de préparation.</p>
      </div>
    </template>
  </USlideover>
  <UModal v-model:open="resolutionOpen" :transition="false" title="Résoudre une ligne en erreur" description="Corrige les valeurs puis réintègre la ligne, ou décide de l’écarter définitivement." :dismissible="!busy" :close="busy ? false : undefined" :ui="{ content: 'sm:max-w-2xl' }">
    <template #body>
      <div class="space-y-5">
        <UAlert v-if="failure" color="error" :description="failure" role="alert" />
        <p class="text-xs text-muted">Ligne {{ issue?.row_number }} · La source bronze reste conservée. La correction sera validée avec le contrat de cette préparation.</p>
        <p v-for="(error, index) in resolutionErrors" :key="index" class="text-sm text-error" role="alert">{{ error.column }} : {{ error.message }}</p>
        <div v-for="field in fields" :key="field.name" class="flex items-end gap-3">
          <UFormField :label="field.name" class="flex-1"><UInput v-model="field.value" :disabled="busy || field.isNull" class="w-full" :aria-label="`Corriger ${field.name}`" /></UFormField><UCheckbox v-model="field.isNull" label="NULL" :disabled="busy" class="mb-2" />
        </div>
        <UFormField label="Motif de la décision" required><UTextarea v-model="reason" :disabled="busy" maxlength="2000" class="w-full" aria-label="Motif de la décision" /></UFormField>
        <div class="flex flex-wrap justify-end gap-3"><UButton label="Écarter définitivement" color="error" variant="outline" :disabled="busy || !reason.trim()" @click="resolve('discard')" /><UButton label="Valider et réintégrer" :disabled="busy || !reason.trim()" @click="resolve('reintegrate')" /></div>
      </div>
    </template>
  </UModal>
  <USlideover v-model:open="previewOpen" :transition="false" title="Données silver" description="Valeurs préparées, types du contrat et empreinte de la source bronze." :ui="{ content: 'sm:max-w-6xl' }">
    <template #body><div class="space-y-4"><UTable :data="preview" :columns="previewColumns" :loading="busy" /><UPagination v-if="previewRun && previewRun.valid_rows > 20" v-model:page="previewPage" :total="previewRun.valid_rows" :items-per-page="20" :disabled="busy" /></div></template>
  </USlideover>
</template>
