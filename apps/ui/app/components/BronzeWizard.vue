<script setup lang="ts">
import type { TableColumn } from '@nuxt/ui'
import type { BronzePreparation, BronzeIssue, ConverterCatalog, PreparationFile, SourceColumn, TechnicalColumn } from '~/types/bronze'

const props = defineProps<{ versionId: string; contracts: { label: string; value: string }[] }>()
const emit = defineEmits<{ updated: []; ready: [database: string]; state: [value: BronzePreparation]; working: [active: boolean] }>()
const baseURL = useApiBase()
const prefix = computed(() => `/model-versions/${props.versionId}/bronze`)
const state = ref<BronzePreparation | null>(null)
const busy = ref(false)
const failure = ref('')
const notice = ref('')
const step = ref('1')
const requestedStep = ref<number | null>(null)
const direction = ref('forward')
const converters = ref<ConverterCatalog['converters']>({})
type Draft = { mode: 'existing' | 'generate'; contract: string; yaml: string; loaded: boolean }
const drafts = ref<Record<string, Draft>>({})
const technical = ref<Record<string, TechnicalColumn[]>>({})
const pending = ref<{ file: File; name: string }[]>([])
const selectedFiles = computed({ get: () => pending.value.map(item => item.file), set: (value: File[] | null | undefined) => {
  const previous = new Map(pending.value.map(item => [item.file, item]))
  pending.value = (value ?? []).map(file => previous.get(file) ?? { file, name: file.name.replace(/\.[^.]+$/, '') })
} })
const files = computed(() => state.value?.files ?? [])
const readonly = computed(() => state.value?.readonly ?? true)
const contractsLoaded = computed(() => files.value.length > 0 && files.value.every(file => drafts.value[file.id]?.loaded))
const contractsSaved = computed(() => files.value.length > 0 && files.value.every(file => {
  const draft = drafts.value[file.id]
  return !!draft && file.saved_yaml !== null && draft.yaml === file.saved_yaml && draft.mode === file.contract_mode && draft.contract === (file.contract_ref ?? '')
}))
const maximum = computed(() => readonly.value && state.value?.state !== 'draft' ? 5 : pending.value.length ? 1 : !files.value.length ? 1 : !contractsSaved.value ? 2 : !state.value?.identities_reviewed ? 3 : 4)
const steps = computed(() => [
  { label: '1 · Fichiers', value: '1', icon: 'i-lucide-upload' },
  { label: '2 · Contrats', value: '2', icon: 'i-lucide-file-check-2' },
  { label: '3 · Cartes d’identité', value: '3', icon: 'i-lucide-id-card' },
  { label: '4. Chargement des données', value: '4', icon: 'i-lucide-database' },
  { label: '5 · Table tampon', value: '5', icon: 'i-lucide-list-checks' },
].map(item => ({ ...item, disabled: busy.value || Number(item.value) > maximum.value })))
const modes = [{ label: 'Choisir un contrat existant', value: 'existing' }, { label: 'Générer un nouveau contrat', value: 'generate' }]
const issueFilter = ref('pending')
const issuePage = ref(1)
const issues = ref<BronzeIssue[]>([])
const issueTotal = ref(0)
const editOpen = ref(false)
const editing = ref<BronzeIssue | null>(null)
const fields = ref<{ name: string; value: string; isNull: boolean }[]>([])
const correctionErrors = ref<string[]>([])
const issueColumns: TableColumn<BronzeIssue>[] = [
  { accessorKey: 'filename', header: 'Fichier' }, { accessorKey: 'row_number', header: 'Ligne' },
  { id: 'values', header: 'Valeurs non insérées' }, { id: 'errors', header: 'Erreur / décision' }, { id: 'actions', header: 'Actions' },
]
const sourceColumns: TableColumn<SourceColumn>[] = [{ accessorKey: 'name', header: 'Colonne source' }, { id: 'type', header: 'Type retenu' }, { id: 'rules', header: 'Règles du contrat' }]
function explain(error: unknown) {
  const detail = (error as { data?: { detail?: unknown } })?.data?.detail
  if (typeof detail === 'string') return detail
  return error instanceof Error && !(error as { data?: unknown }).data ? error.message : 'La demande a échoué. Vérifie les données et réessaie.'
}
function updateState(value: BronzePreparation, preserve = false) {
  state.value = value
  const next: Record<string, Draft> = {}
  const additions: Record<string, TechnicalColumn[]> = {}
  for (const file of value.files) {
    next[file.id] = preserve && drafts.value[file.id] ? drafts.value[file.id]! : {
      mode: file.contract_mode, contract: file.contract_ref ?? '', yaml: file.loaded_yaml ?? '', loaded: file.loaded_yaml !== null,
    }
    additions[file.id] = value.state === 'draft' && technical.value[file.id] ? technical.value[file.id]! : file.technical_columns.map(column => ({ ...column }))
  }
  drafts.value = next; technical.value = additions
  emit('state', value)
}
async function refresh(preserve = false) { updateState(await $fetch<BronzePreparation>(prefix.value, { baseURL }), preserve) }
function go(value: string) {
  if (Number(value) > maximum.value) { failure.value = 'Termine les étapes précédentes pour accéder à cette étape.'; return }
  direction.value = Number(value) < Number(step.value) ? 'backward' : 'forward'
  step.value = value
}
function openStep(value: number) {
  if (!state.value) { requestedStep.value = value; return }
  go(String(value))
}
defineExpose({ openStep })
async function perform(action: () => Promise<void>) {
  if (busy.value) return
  busy.value = true; emit('working', true); failure.value = ''; notice.value = ''
  try { await action() }
  catch (error) { failure.value = explain(error) }
  finally { busy.value = false; emit('working', false) }
}
async function loadErrors() {
  if (!state.value?.database_name) { issues.value = []; issueTotal.value = 0; return }
  const response = await $fetch<{ rows: BronzeIssue[]; total: number }>(`${prefix.value}/errors`, { baseURL, query: { state: issueFilter.value, offset: (issuePage.value - 1) * 20, limit: 20 } })
  issues.value = response.rows; issueTotal.value = response.total
}
function upload() {
  return perform(async () => {
    if (!pending.value.length || pending.value.some(item => !item.name.trim())) throw new Error('Sélectionne au moins un fichier avec un nom de dataset.')
    const form = new FormData()
    const manifest = []
    for (const item of pending.value) {
      const digest = await crypto.subtle.digest('SHA-256', await item.file.arrayBuffer())
      const sha256 = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('')
      form.append('files', item.file)
      manifest.push({ dataset_name: item.name, sha256 })
    }
    form.append('manifest', JSON.stringify(manifest))
    const response = await $fetch<{ results: { status: string }[] }>(`${prefix.value}/files`, { baseURL, method: 'POST', body: form })
    pending.value = []
    await refresh(true); emit('updated'); go('2')
    notice.value = response.results.some(item => item.status === 'duplicate') ? 'Téléversement terminé. Les fichiers identiques déjà présents ont été reconnus.' : 'Fichiers téléversés. Choisis leurs contrats.'
  })
}
function removeFile(file: PreparationFile) {
  return perform(async () => { await $fetch(`${prefix.value}/files/${file.id}`, { baseURL, method: 'DELETE' }); await refresh(true); emit('updated') })
}
function invalidate(file: PreparationFile) {
  const draft = drafts.value[file.id]!
  draft.loaded = false; draft.yaml = ''
}
function loadContracts() {
  return perform(async () => {
    if (files.value.some(file => file.format === 'csv' && drafts.value[file.id]?.mode === 'existing' && !drafts.value[file.id]?.contract)) throw new Error('Choisis un contrat existant pour chaque CSV concerné.')
    await $fetch(`${prefix.value}/contracts/load`, { baseURL, method: 'POST', body: { files: files.value.map(file => ({
      id: file.id, mode: drafts.value[file.id]!.mode, contract: drafts.value[file.id]!.mode === 'existing' ? drafts.value[file.id]!.contract || null : null,
    })) } })
    await refresh(); notice.value = 'Contrats chargés. Tu peux les modifier avant de les sauvegarder.'
  })
}
function saveContracts() {
  return perform(async () => {
    await $fetch(`${prefix.value}/contracts/save`, { baseURL, method: 'POST', body: { files: files.value.map(file => ({
      id: file.id, revision: file.revision, yaml: file.format === 'csv' ? drafts.value[file.id]!.yaml : null,
    })) } })
    await refresh(); emit('updated'); go('3'); notice.value = 'Contrats sauvegardés. Consulte les cartes d’identité.'
  })
}
function next() {
  if (step.value === '3' && !readonly.value) return perform(async () => {
    await $fetch(`${prefix.value}/identities/confirm`, { baseURL, method: 'POST' }); await refresh(true); emit('updated'); go('4')
  })
  go(String(Number(step.value) + 1))
}
function addTechnical(file: PreparationFile, table: string) {
  const firstConverter = Object.keys(converters.value)[0] ?? 'string'
  const firstType = Object.keys(converters.value[firstConverter]?.types ?? {})[0] ?? 'TEXT'
  technical.value[file.id]!.push({ table, name: `technical_${technical.value[file.id]!.length + 1}`, source: file.table_specs?.[table]?.[0]?.name ?? '', converter: firstConverter, type: firstType, nullable: true, format: '' })
}
function converterChanged(column: TechnicalColumn) { column.type = Object.keys(converters.value[column.converter]?.types ?? {})[0] ?? ''; column.format = '' }
function createDataset() {
  return perform(async () => {
    const response = await $fetch<BronzePreparation>(`${prefix.value}/create`, { baseURL, method: 'POST', body: { files: files.value.map(file => ({
      id: file.id, revision: file.revision, technical_columns: technical.value[file.id]!.map(column => ({ ...column, format: column.format || null, pattern: column.pattern || null })),
    })) } })
    updateState(response); emit('updated'); go('5'); await loadErrors()
    if (response.state === 'complete') emit('ready', response.database_name ?? '')
  })
}
function edit(row: BronzeIssue) {
  editing.value = row; correctionErrors.value = []
  const names = [...new Set([...Object.keys(row.candidate), ...row.errors.map(error => error.source_column || error.column).filter(Boolean)])]
  const sourceNames = state.value?.files.find(file => file.id === row.file_id)?.table_specs?.[row.source_table]?.map(column => column.name) ?? names
  fields.value = [...new Set([...names.filter(name => sourceNames.includes(name)), ...sourceNames])].map(name => ({
    name, value: row.candidate[name] == null ? '' : typeof row.candidate[name] === 'object' ? JSON.stringify(row.candidate[name]) : String(row.candidate[name]), isNull: row.candidate[name] == null,
  }))
  editOpen.value = true
}
function resolve(row: BronzeIssue, action: 'discard' | 'reintegrate') {
  return perform(async () => {
    const values = action === 'reintegrate' ? Object.fromEntries(fields.value.map(field => [field.name, field.isNull ? null : field.value])) : null
    const response = await $fetch<{ resolved: boolean; errors?: { column: string; message: string }[] }>(`${prefix.value}/errors/${row.id}/resolve`, { baseURL, method: 'POST', body: {
      action, values, reason: action === 'discard' ? 'Exclusion humaine depuis la table tampon Bronze' : 'Correction humaine depuis la table tampon Bronze',
    } })
    if (!response.resolved) { correctionErrors.value = response.errors?.map(error => `${error.column} : ${error.message}`) ?? []; await loadErrors(); return }
    editOpen.value = false; issuePage.value = 1; await refresh(); await loadErrors(); emit('updated')
    if (state.value?.state === 'complete') emit('ready', state.value.database_name ?? '')
  })
}
watch(issueFilter, () => { issuePage.value = 1; void perform(loadErrors) })
watch(issuePage, () => { void perform(loadErrors) })
onMounted(() => { void perform(async () => {
  const catalog = await $fetch<ConverterCatalog>('/converters', { baseURL }); converters.value = catalog.converters
  await refresh()
  step.value = state.value?.state !== 'draft' ? '5' : String(maximum.value)
  const explicitStep = requestedStep.value !== null
  if (requestedStep.value !== null) { go(String(requestedStep.value)); requestedStep.value = null }
  await loadErrors()
  if (state.value?.state === 'complete' && !explicitStep) emit('ready', state.value.database_name ?? '')
}) })
</script>

<template>
  <div id="contrats-yaml" class="flex min-h-0 flex-1 scroll-mt-4 flex-col gap-5">
    <UAlert v-if="failure" color="error" variant="subtle" :description="failure" role="alert" />
    <UAlert v-if="notice" color="success" variant="subtle" :description="notice" role="status" />
    <UAlert v-if="readonly && state" color="info" variant="subtle" title="Consultation seule" description="Les fichiers, contrats et colonnes sont figés après la création du Bronze. Tu peux revenir sur chaque étape pour les consulter." />
    <div id="table-tampon" class="shrink-0 scroll-mt-4"><UTabs :model-value="step" :items="steps" :content="false" variant="link" :ui="{ list: 'overflow-x-auto justify-start' }" aria-label="Étapes du formulaire Bronze" @update:model-value="value => go(String(value))" /></div>
    <Transition :name="direction === 'forward' ? 'step-forward' : 'step-backward'" mode="out-in">
      <div :key="step" class="min-h-0 flex-1 space-y-5 overflow-y-auto overscroll-contain px-1 pb-1 pt-2" role="tabpanel" :aria-label="steps.find(item => item.value === step)?.label">
        <template v-if="step === '1'">
          <UCard>
            <template #header><h2 class="font-semibold text-highlighted">Téléverser les fichiers</h2><p class="mt-1 text-sm text-muted">Les fichiers sont conservés dans le brouillon de cette version. Le Bronze sera créé à l’étape 4.</p></template>
            <div class="space-y-4">
              <template v-if="!readonly">
                <UFileUpload v-model="selectedFiles" multiple accept=".csv,.sql" :disabled="busy" label="Sélectionner des fichiers CSV ou SQL PostgreSQL" description="10 fichiers et 100 Mio maximum au total · 25 Mio par fichier" class="min-h-36 w-full" aria-label="Fichiers à téléverser" />
                <UFormField v-for="(item, index) in pending" :key="index" :label="item.file.name"><UInput v-model="item.name" :disabled="busy" maxlength="120" class="w-full" :aria-label="`Nom du dataset — ${item.file.name}`" /></UFormField>
                <UButton label="Téléverser" icon="i-lucide-upload" :loading="busy" :disabled="busy || !pending.length" @click="upload" />
              </template>
              <div v-for="file in files" :key="file.id" class="flex flex-wrap items-center justify-between gap-3 rounded-md border border-default p-3">
                <div><p class="font-medium">{{ file.filename }}</p><p class="text-xs text-muted">{{ file.dataset_name }} · {{ file.format.toUpperCase() }} · SHA-256 {{ file.sha256.slice(0, 12) }}…</p></div>
                <UButton v-if="!readonly" label="Retirer" color="error" variant="ghost" :disabled="busy" :aria-label="`Retirer ${file.filename}`" @click="removeFile(file)" />
              </div>
              <p v-if="!files.length" class="text-sm text-muted">Téléverse au moins un fichier pour accéder à l’étape suivante.</p>
            </div>
          </UCard>
        </template>
        <template v-else-if="step === '2'">
          <UCard>
            <template #header><h2 class="font-semibold text-highlighted">Choisir et sauvegarder les contrats</h2></template>
            <div class="space-y-6">
              <div v-for="file in files" :key="file.id" class="grid gap-4 rounded-lg border border-default p-4 lg:grid-cols-3">
                <div class="space-y-4"><p class="font-medium text-highlighted">{{ file.filename }}</p>
                  <template v-if="file.format === 'csv' && drafts[file.id]">
                    <UFormField label="Choix du contrat"><USelect v-model="drafts[file.id]!.mode" :items="modes" :disabled="busy || readonly" class="w-full" :aria-label="`Mode de contrat — ${file.filename}`" @update:model-value="invalidate(file)" /></UFormField>
                    <UFormField v-if="drafts[file.id]!.mode === 'existing'" label="Contrat existant"><USelect v-model="drafts[file.id]!.contract" :items="contracts" :disabled="busy || readonly" class="w-full" :aria-label="`Contrat existant — ${file.filename}`" @update:model-value="invalidate(file)" /></UFormField>
                  </template>
                  <p v-else class="text-xs text-muted">Le schéma est extrait du fichier SQL, sans exécuter ses instructions.</p>
                </div>
                <div class="lg:col-span-2">
                  <UFormField v-if="file.format === 'csv' && drafts[file.id]?.loaded" :label="`Contrat YAML — ${file.filename}`" :hint="drafts[file.id]!.mode === 'existing' ? 'Contrat existant chargé' : 'Proposition générée'">
                    <UTextarea v-model="drafts[file.id]!.yaml" :rows="16" :maxlength="200000" :readonly="readonly" :disabled="busy" class="w-full" :ui="{ base: 'font-mono text-xs' }" :aria-label="`Contrat YAML — ${file.filename}`" spellcheck="false" />
                  </UFormField>
                  <p v-else class="text-sm text-muted">{{ drafts[file.id]?.loaded ? 'Schéma SQL chargé.' : 'Clique sur « Charger le(s) contrat(s) » pour afficher le contrat correspondant.' }}</p>
                </div>
              </div>
              <div v-if="!readonly" class="flex flex-wrap gap-3">
                <UButton label="Charger le(s) contrat(s)" color="neutral" variant="outline" :loading="busy" :disabled="busy || !files.length" @click="loadContracts" />
                <UButton label="Sauvegarder le(s) contrat(s)" icon="i-lucide-save" :loading="busy" :disabled="busy || !contractsLoaded" @click="saveContracts" />
              </div>
            </div>
          </UCard>
        </template>
        <template v-else-if="step === '3'">
          <UCard v-for="file in files" :key="file.id">
            <template #header><h2 class="font-semibold text-highlighted">Carte d’identité · {{ file.filename }}</h2></template>
            <div class="mb-4 flex flex-wrap gap-3"><UBadge>{{ file.summary?.rows.toLocaleString('fr-FR') }} lignes sources</UBadge><UBadge color="neutral">{{ file.summary?.tables.length }} table(s)</UBadge><UBadge color="neutral">Contrat r{{ file.revision }}</UBadge></div>
            <pre class="max-h-[32rem] overflow-auto whitespace-pre-wrap rounded-lg bg-elevated p-4 text-xs leading-6">{{ file.report }}</pre>
          </UCard>
        </template>
        <template v-else-if="step === '4'">
          <UCard v-for="file in files" :key="file.id">
            <template #header><h2 class="font-semibold text-highlighted">Colonnes · {{ file.filename }}</h2></template>
            <div v-for="(columns, table) in file.table_specs" :key="table" class="mb-6 space-y-4">
              <h3 class="font-medium">{{ table }}</h3>
              <UTable :data="columns" :columns="sourceColumns">
                <template #type-cell="{ row }"><UBadge color="neutral" variant="subtle">{{ row.original.spec.type }}</UBadge></template>
                <template #rules-cell="{ row }"><span class="text-xs text-muted">{{ JSON.stringify(row.original.spec) }}</span></template>
              </UTable>
              <h4 class="text-sm font-medium">Colonnes techniques</h4>
              <div v-for="(column, index) in technical[file.id]" :key="index">
                <div v-if="column.table === table" class="grid gap-3 rounded-lg border border-default p-3 md:grid-cols-2 xl:grid-cols-3">
                  <UFormField label="Nom"><UInput v-model="column.name" :disabled="busy || readonly" maxlength="58" class="w-full" :aria-label="`Nom colonne technique ${index + 1} — ${file.filename}`" /></UFormField>
                  <UFormField label="Colonne source"><USelect v-model="column.source" :items="columns.map(item => item.name)" :disabled="busy || readonly" class="w-full" :aria-label="`Source colonne technique ${index + 1}`" /></UFormField>
                  <UFormField label="Convertisseur"><USelect v-model="column.converter" :items="Object.keys(converters)" :disabled="busy || readonly" class="w-full" :aria-label="`Convertisseur colonne technique ${index + 1}`" @update:model-value="converterChanged(column)" /></UFormField>
                  <UFormField label="Type"><USelect v-model="column.type" :items="Object.keys(converters[column.converter]?.types ?? {})" :disabled="busy || readonly" class="w-full" :aria-label="`Type colonne technique ${index + 1}`" /></UFormField>
                  <UFormField v-if="converters[column.converter]?.types[column.type]?.format" label="Format" hint="Facultatif"><UInput :model-value="column.format ?? ''" :placeholder="converters[column.converter]?.types[column.type]?.format" :disabled="busy || readonly" class="w-full" :aria-label="`Format colonne technique ${index + 1}`" @update:model-value="column.format = String($event ?? '')" /></UFormField>
                  <div class="flex items-center justify-between gap-2"><UCheckbox v-model="column.nullable" label="NULL autorisé" :disabled="busy || readonly" /><UButton v-if="!readonly" color="error" variant="ghost" label="Retirer" :disabled="busy" @click="technical[file.id]!.splice(index, 1)" /></div>
                </div>
              </div>
              <UButton v-if="!readonly" label="Ajouter une colonne technique" icon="i-lucide-plus" variant="outline" :disabled="busy" @click="addTechnical(file, String(table))" />
            </div>
          </UCard>
          <UCard>
            <p class="mb-4 text-sm text-muted">Le Bronze contiendra une colonne « nom-type » après chaque colonne et un hash de la ligne originale. Les lignes en erreur seront isolées pour résolution humaine.</p>
            <UButton v-if="!readonly" label="Créer le bronze dataset" icon="i-lucide-database" :loading="busy" :disabled="busy || !contractsSaved || !state?.identities_reviewed" @click="createDataset" />
            <p v-else class="font-medium">Base créée : {{ state?.database_name }}</p>
          </UCard>
        </template>
        <template v-else-if="step === '5'">
          <UAlert v-if="state?.state === 'complete'" color="success" icon="i-lucide-circle-check" title="Bronze dataset créé" :description="`${state.dataset?.valid ?? 0} lignes intégrées · ${state.dataset?.excluded ?? 0} écartées · base ${state.database_name}`" />
          <UCard>
            <template #header><div class="flex flex-wrap items-center justify-between gap-3"><h2 class="font-semibold text-highlighted">Table tampon Bronze · {{ state?.dataset?.pending ?? 0 }} erreur(s) à résoudre</h2><USelect v-model="issueFilter" :items="[{label:'À résoudre',value:'pending'},{label:'Exclues',value:'discarded'},{label:'Réintégrées',value:'reintegrated'},{label:'Toutes',value:'all'}]" :disabled="busy" aria-label="Filtrer les erreurs Bronze" /></div></template>
            <p class="mb-4 text-sm text-muted">Silver restera inaccessible tant que les lignes en erreur ne sont pas corrigées ou exclues.</p>
            <UTable :data="issues" :columns="issueColumns" :loading="busy">
              <template #values-cell="{ row }"><pre class="max-w-md whitespace-pre-wrap text-xs">{{ JSON.stringify(row.original.candidate, null, 2) }}</pre></template>
              <template #errors-cell="{ row }"><p v-for="(error, index) in row.original.errors" :key="index" class="text-xs text-error">{{ error.column }} {{ error.message }}</p><p v-if="row.original.state !== 'pending'" class="text-xs">{{ row.original.state === 'discarded' ? 'Exclue' : 'Réintégrée' }} · {{ row.original.reason }}</p></template>
              <template #actions-cell><span class="text-xs text-muted">Consultation seule</span></template>
            </UTable>
            <p v-if="!issues.length" class="py-4 text-sm text-muted">Aucune ligne dans cette sélection.</p>
            <UPagination v-if="issueTotal > 20" v-model:page="issuePage" :total="issueTotal" :items-per-page="20" :disabled="busy" />
          </UCard>
        </template>
      </div>
    </Transition>
    <div class="flex shrink-0 justify-between gap-3 border-t border-default bg-default pt-4">
      <UButton v-if="step !== '1'" label="Retour" color="neutral" variant="outline" icon="i-lucide-arrow-left" :disabled="busy" @click="go(String(Number(step) - 1))" />
      <UButton v-if="Number(step) < 5" label="Suivant" class="ml-auto" trailing-icon="i-lucide-arrow-right" :disabled="busy || (Number(step) >= maximum && !(step === '3' && contractsSaved))" @click="next" />
    </div>
    <UModal v-model:open="editOpen" :transition="false" title="Modifier la ligne en erreur" description="La correction sera validée avec le contrat et les convertisseurs de cette version." :dismissible="!busy" :close="busy ? false : undefined" :ui="{ content: 'sm:max-w-2xl' }">
      <template #body><div class="space-y-4">
        <UAlert v-if="failure" color="error" :description="failure" role="alert" />
        <p v-for="(error, index) in correctionErrors" :key="index" class="text-sm text-error" role="alert">{{ error }}</p>
        <div v-for="field in fields" :key="field.name" class="flex items-end gap-3"><UFormField :label="field.name" class="flex-1"><UInput v-model="field.value" :disabled="busy || field.isNull" class="w-full" :aria-label="`Corriger ${field.name}`" /></UFormField><UCheckbox v-model="field.isNull" label="NULL" :disabled="busy" class="mb-2" /></div>
        <div class="flex justify-end"><UButton label="Valider et intégrer la ligne" :disabled="busy || !editing" :loading="busy" @click="editing && resolve(editing, 'reintegrate')" /></div>
      </div></template>
    </UModal>
  </div>
</template>

<style scoped>
.step-forward-enter-active, .step-forward-leave-active, .step-backward-enter-active, .step-backward-leave-active { transition: opacity .14s ease, transform .14s ease; }
.step-forward-enter-from, .step-backward-leave-to { opacity: 0; transform: translateX(16px); }
.step-forward-leave-to, .step-backward-enter-from { opacity: 0; transform: translateX(-16px); }
@media (prefers-reduced-motion: reduce) { .step-forward-enter-active, .step-forward-leave-active, .step-backward-enter-active, .step-backward-leave-active { transition: none; } }
</style>
