<script setup lang="ts">
import type { TableColumn, TimelineItem } from '@nuxt/ui'
import type { Model, Dataset, Snapshot, VersionDetail, UploadResult, Summary } from '~/types/workflow'
import type { BronzePreparation } from '~/types/bronze'

// L’exposition doit précéder les await du setup pour les actions de la barre d’outils.
defineExpose({ openNewModel, openJournal, openSection })

const baseURL = useApiBase()
const { data: models, error: modelsError, refresh: refreshModels } = await useFetch<Model[]>('/models', { baseURL, default: () => [] })
const { data: contracts, refresh: refreshContracts } = await useFetch<{ label: string; value: string }[]>('/contracts/catalogue', { baseURL, default: () => [] })
const route = useRoute()
const router = useRouter()
const modelId = ref(typeof route.query.modele === 'string' ? route.query.modele : '')
const versionId = ref(models.value.find(model => model.id === modelId.value)?.versions[0]?.id ?? '')
const detail = ref<VersionDetail | null>(null)
const bronzePreparation = ref<BronzePreparation | null>(null)
const bronzeWizard = ref<{ openStep: (step: number) => void } | null>(null)
const wizardMode = computed(() => !detail.value || !!detail.value.preparation || detail.value.datasets.length === 0)
const bronzeEditable = computed(() => detail.value?.status === 'ingestion-bronze' && !detail.value.read_only)
const busy = ref(false)
const silverBlocked = ref(true)
const message = ref('')
const failure = ref('')
const newName = ref('')
const description = ref('')
const inherit = ref(true)
type QueueEntry = { file: File; dataset_name: string; contract: string; contract_mode: 'existing' | 'generate'; contract_yaml: string; sha256: string; preloaded: boolean; summary: Summary | null }
type PreloadResult = { filename: string; sha256: string; format: string; contract_yaml: string | null; contract_mode: 'existing' | 'generate' | null; contract_name: string | null; summary: Summary }
const queue = ref<QueueEntry[]>([])
const allPreloaded = computed(() => queue.value.length > 0 && queue.value.every(entry => entry.preloaded))
const contractModes = [{ label: 'Générer un nouveau contrat', value: 'generate' }, { label: 'Choisir un contrat existant', value: 'existing' }]
const results = ref<UploadResult[]>([])
const datasetHistory = ref<{ name: string; versions: Snapshot[] } | null>(null)
const selectedSnapshot = ref<Snapshot | null>(null)
const selectedTable = ref('')
const preview = ref<{ row_number: number; data: Record<string, unknown> }[]>([])
const previewLoading = ref(false)
const newModelOpen = ref(route.query.nouveau === '1')
const newVersionOpen = ref(false)
const historyOpen = ref(false)
const historyLoading = ref(false)
const journalOpen = ref(false)
const journalLoading = ref(false)
const activeStep = ref('bronze')
const silverWorkspace = ref<{ openContracts: () => void } | null>(null)
const workflowSteps = computed(() => [
  { label: 'Bronze', icon: 'i-lucide-database', value: 'bronze', slot: 'bronze' },
  ...(!wizardMode.value || bronzePreparation.value?.state === 'complete' ? [{ label: 'Silver', icon: 'i-lucide-layers', value: 'silver', slot: 'silver' }] : []),
])
const files = computed({ get: () => queue.value.map(entry => entry.file), set: (value: File[] | null | undefined) => chooseFiles(value ?? []) })
const selectedModel = computed(() => models.value.find(model => model.id === modelId.value))
const format = (value: string) => new Date(value).toLocaleString('fr-FR')
let selectionSequence = 0
let previewSequence = 0
let historySequence = 0

function explain(error: unknown) {
  const data = (error as { data?: { detail?: unknown } })?.data
  return typeof data?.detail === 'string' ? data.detail : 'La demande a échoué. Vérifie les fichiers et réessaie.'
}

async function loadDetail() {
  const sequence = ++selectionSequence
  const selected = versionId.value
  if (!selected) { detail.value = null; return }
  try {
    const response = await $fetch<VersionDetail>(`/model-versions/${selected}`, { baseURL })
    if (sequence === selectionSequence) {
      detail.value = response
    }
  }
  catch (error) { if (sequence === selectionSequence) failure.value = explain(error) }
}

async function silverUpdated() {
  await Promise.all([refreshModels(), refreshContracts()])
  await loadDetail()
}

watch(modelId, () => {
  versionId.value = selectedModel.value?.versions[0]?.id ?? ''
  datasetHistory.value = null
  selectedSnapshot.value = null
})
watch(versionId, () => {
  activeStep.value = 'bronze'
  bronzePreparation.value = null
  silverBlocked.value = true
  detail.value = null; datasetHistory.value = null; selectedSnapshot.value = null
  results.value = []; queue.value = []; historyOpen.value = false; journalOpen.value = false
  historySequence++; previewSequence++; previewLoading.value = false
  void loadDetail()
})

async function createModel() {
  busy.value = true; failure.value = ''; message.value = ''
  try {
    const created = await $fetch<{ id: string; version_id: string }>('/models', {
      baseURL, method: 'POST', body: { name: newName.value, description: description.value },
    })
    await refreshModels()
    modelId.value = created.id
    versionId.value = created.version_id
    newName.value = ''; description.value = ''; newModelOpen.value = false
    await router.replace({ query: { modele: created.id } })
    message.value = 'Modèle créé. Téléverse ses datasets initiaux ci-dessous.'
    await loadDetail()
  }
  catch (error) { failure.value = explain(error) }
  finally { busy.value = false }
}

async function createVersion() {
  busy.value = true; failure.value = ''; message.value = ''
  try {
    const created = await $fetch<{ id: string }>(`/models/${modelId.value}/versions`, {
      baseURL, method: 'POST', body: { from_version_id: inherit.value ? versionId.value : null, preparation: true },
    })
    await refreshModels()
    versionId.value = created.id
    newVersionOpen.value = false
    await router.replace({ query: { ...route.query, modele: modelId.value }, hash: '' })
    message.value = inherit.value ? 'Nouvelle version créée avec les sources et contrats de la version de départ.' : 'Nouvelle version vide créée.'
    await loadDetail()
  }
  catch (error) { failure.value = explain(error) }
  finally { busy.value = false }
}

async function validateStage(stage: 'bronze' | 'silver') {
  busy.value = true; failure.value = ''; message.value = ''
  try {
    await $fetch(`/model-versions/${versionId.value}/validate-stage`, {
      baseURL, method: 'POST', body: { stage },
    })
    message.value = stage === 'bronze' ? 'Étape Bronze validée. Tu peux préparer les données silver.' : 'Étape Silver validée. La version est prête pour la préparation gold.'
    await refreshModels()
    await loadDetail()
    activeStep.value = 'silver'
  }
  catch (error) {
    failure.value = explain(error)
    await refreshModels()
    await loadDetail()
  }
  finally { busy.value = false }
}

function chooseFiles(files: File[]) {
  failure.value = ''; results.value = []
  if (files.length > 10 || files.some(file => file.size > 25 * 1024 * 1024)) {
    failure.value = 'Choisis au maximum 10 fichiers, de 25 Mio chacun.'
    queue.value = []; return
  }
  const previous = new Map(queue.value.map(entry => [entry.file, entry]))
  queue.value = files.map(file => previous.get(file) ?? ({
    file, dataset_name: file.name.replace(/\.[^.]+$/, ''), contract: '', contract_mode: 'generate',
    contract_yaml: '', sha256: '', preloaded: false, summary: null,
  }))
}

function isCsv(entry: QueueEntry) { return entry.file.name.toLowerCase().endsWith('.csv') }
function contractLabel(entry: QueueEntry) { return contracts.value.find(contract => contract.value === entry.contract)?.label ?? entry.contract }
function invalidatePreload(entry: QueueEntry) {
  entry.preloaded = false; entry.contract_yaml = ''; entry.sha256 = ''; entry.summary = null
  message.value = ''
}
async function uploadForm(preload: boolean) {
  const form = new FormData()
  const manifest = []
  for (const entry of queue.value) {
    const digest = await crypto.subtle.digest('SHA-256', await entry.file.arrayBuffer())
    const sha256 = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('')
    if (!preload && entry.sha256 !== sha256) throw new Error('Le fichier a changé depuis son préchargement.')
    form.append('files', entry.file)
    manifest.push({ dataset_name: entry.dataset_name, contract: isCsv(entry) && entry.contract_mode === 'existing' ? entry.contract : null,
      contract_mode: isCsv(entry) ? entry.contract_mode : 'existing',
      contract_yaml: !preload && isCsv(entry) ? entry.contract_yaml : null, sha256, mode: 'snapshot' })
  }
  form.append('manifest', JSON.stringify(manifest))
  return form
}
async function preloadFiles() {
  if (queue.value.some(entry => !entry.dataset_name.trim() || (isCsv(entry) && entry.contract_mode === 'existing' && !entry.contract))) {
    failure.value = 'Renseigne le nom de chaque dataset et choisis un contrat existant ou sa génération.'
    return
  }
  busy.value = true; failure.value = ''; message.value = ''; results.value = []
  for (const entry of queue.value) invalidatePreload(entry)
  try {
    const response = await $fetch<{ results: PreloadResult[] }>(`/model-versions/${versionId.value}/preload`, {
      baseURL, method: 'POST', body: await uploadForm(true),
    })
    if (response.results.length !== queue.value.length || response.results.some((result, index) => {
      const entry = queue.value[index]
      return !entry || result.filename !== entry.file.name || (isCsv(entry) && (result.contract_mode !== entry.contract_mode || (entry.contract_mode === 'existing' && result.contract_name !== entry.contract)))
    })) throw new Error('Réponse de préchargement incohérente.')
    response.results.forEach((result, index) => {
      const entry = queue.value[index]!
      entry.contract_yaml = result.contract_yaml ?? ''; entry.sha256 = result.sha256
      entry.summary = result.summary; entry.preloaded = true
    })
    message.value = 'Fichiers préchargés. Vérifie et modifie chaque contrat, puis clique sur Charger en bronze.'
  }
  catch (error) { failure.value = explain(error) }
  finally { busy.value = false }
}

async function upload() {
  if (!allPreloaded.value || queue.value.some(entry => isCsv(entry) && !entry.contract_yaml.trim())) {
    failure.value = 'Précharge les fichiers et vérifie le contrat de chaque CSV avant de charger en bronze.'
    return
  }
  busy.value = true; failure.value = ''; message.value = ''; results.value = []
  try {
    const response = await $fetch<{ results: UploadResult[] }>(`/model-versions/${versionId.value}/uploads`, {
      baseURL, method: 'POST', body: await uploadForm(false),
    })
    results.value = response.results
    queue.value = []
    message.value = 'Lot traité. Consulte le résultat de chaque fichier.'
    datasetHistory.value = null
    await refreshContracts()
    await loadDetail()
  }
  catch (error) { failure.value = explain(error); await loadDetail() }
  finally { busy.value = false }
}

async function openDataset(id: string) {
  const sequence = ++historySequence
  historyOpen.value = true; historyLoading.value = true; datasetHistory.value = null
  failure.value = ''
  try {
    const response = await $fetch<{ name: string; versions: Snapshot[] }>(`/datasets/${id}`, { baseURL })
    if (sequence !== historySequence) return
    datasetHistory.value = response
    selectedSnapshot.value = datasetHistory.value.versions[0] ?? null
    selectedTable.value = selectedSnapshot.value?.summary.tables[0]?.name ?? ''
    await loadPreview()
  }
  catch (error) { if (sequence === historySequence) failure.value = explain(error) }
  finally { if (sequence === historySequence) historyLoading.value = false }
}

async function loadPreview() {
  const sequence = ++previewSequence
  preview.value = []
  if (!selectedSnapshot.value || !selectedTable.value) return
  previewLoading.value = true
  try {
    const result = await $fetch<{ rows: typeof preview.value }>(`/dataset-versions/${selectedSnapshot.value.id}/rows`, {
      baseURL, query: { table: selectedTable.value, limit: 20 },
    })
    if (sequence === previewSequence) preview.value = result.rows
  }
  catch (error) { if (sequence === previewSequence) failure.value = explain(error) }
  finally { if (sequence === previewSequence) previewLoading.value = false }
}

function selectSnapshot(id: string | undefined) {
  selectedSnapshot.value = datasetHistory.value?.versions.find(version => version.id === id) ?? null
  selectedTable.value = selectedSnapshot.value?.summary.tables[0]?.name ?? ''
  void loadPreview()
}

const actionLabel: Record<string, string> = {
  model_created: 'Modèle créé', version_created: 'Version du modèle créée',
  dataset_uploaded: 'Snapshot bronze créé', dataset_reused: 'Snapshot réutilisé',
  upload_duplicate: 'Fichier déjà présent : données inchangées', upload_rejected: 'Lot refusé',
  status_changed: 'Statut de la version modifié',
  silver_contract_saved: 'Contrat silver validé et enregistré', silver_prepared: 'Table préparée en silver',
  silver_row_resolved: 'Ligne tampon résolue',
  stage_validated: 'Étape de préparation validée',
  file_staged: 'Fichier téléversé', staged_file_removed: 'Fichier retiré du brouillon',
  bronze_contract_loaded: 'Contrat Bronze chargé', bronze_contract_saved: 'Contrat Bronze sauvegardé',
  bronze_identities_reviewed: 'Cartes d’identité validées', bronze_dataset_created: 'Bronze dataset créé',
  bronze_row_resolved: 'Erreur Bronze résolue',
  source_archived: 'Fichier original archivé',
  bronze_migration_generated: 'Migration Bronze générée', bronze_migration_approved: 'Migration Bronze approuvée',
  bronze_batch_finished: 'Lot d’ingestion terminé',
}


const modelItems = computed(() => models.value.map(model => ({ label: model.name, value: model.id })))
const versionItems = computed(() => selectedModel.value?.versions.map(version => ({ label: `Version ${version.number} · ${version.status}`, value: version.id })) ?? [])
const snapshotItems = computed(() => datasetHistory.value?.versions.map(snapshot => ({ label: `v${snapshot.number} · ${format(snapshot.created_at)} · ${snapshot.filename}`, value: snapshot.id })) ?? [])
const tableItems = computed(() => selectedSnapshot.value?.summary.tables.map(table => ({ label: `${table.name} · ${table.rows.toLocaleString('fr-FR')} lignes`, value: table.name })) ?? [])
const datasetColumns: TableColumn<Dataset>[] = [
  { accessorKey: 'name', header: 'Dataset' },
  { accessorKey: 'number', header: 'Version' },
  { accessorKey: 'summary', header: 'Lignes' },
  { id: 'actions', header: '' },
]
type PreviewRow = { row_number: number; data: Record<string, unknown> }
const previewColumns = computed<TableColumn<PreviewRow>[]>(() => [
  { accessorKey: 'row_number', header: '#' },
  ...(selectedSnapshot.value?.summary.tables.find(table => table.name === selectedTable.value)?.columns ?? []).map((column, index) => ({
    id: `column-${index}`, header: column.name,
    cell: ({ row }: { row: { original: PreviewRow } }) => {
      const value = row.original.data[column.name]
      return value === undefined ? '(omis)' : value === null ? 'NULL' : typeof value === 'object' ? JSON.stringify(value) : String(value)
    },
  })),
])
const historyItems = computed<TimelineItem[]>(() => detail.value?.history.map(event => ({
  date: format(event.created_at), title: actionLabel[event.action] ?? event.action,
  description: event.action === 'status_changed' ? `${event.details.from_status} → ${event.details.to_status}`
    : event.action === 'stage_validated' ? `Étape ${event.details.stage === 'bronze' ? 'Bronze' : 'Silver'} validée`
    : event.action === 'silver_contract_saved' ? `${event.details.table} · révision ${event.details.revision}`
    : event.action === 'silver_prepared' ? `${event.details.table} · ${event.details.valid_rows} lignes valides · ${event.details.pending_rows} en attente`
    : event.action === 'bronze_dataset_created' ? `${event.details.database} · ${event.details.valid_rows} lignes intégrées · ${event.details.pending_rows} en attente`
    : ['silver_row_resolved', 'bronze_row_resolved'].includes(event.action) ? `Ligne ${event.details.row_number} · ${event.details.decision === 'discarded' ? 'écartée' : 'réintégrée'} · ${event.details.reason}`
    : event.details.filename ?? event.details.reason ?? event.details.name,
  icon: event.action === 'upload_rejected' ? 'i-lucide-circle-alert' : event.action === 'upload_duplicate' ? 'i-lucide-copy-check' : 'i-lucide-check',
})) ?? [])
function openNewModel() { failure.value = ''; newModelOpen.value = true }
async function openJournal() {
  journalOpen.value = true
  if (!versionId.value) return
  journalLoading.value = true
  try { await loadDetail() }
  finally { journalLoading.value = false }
}
async function openSection(section: 'contracts' | 'quarantine') {
  if (wizardMode.value && detail.value) {
    activeStep.value = 'bronze'
    await nextTick()
    bronzeWizard.value?.openStep(section === 'contracts' ? 2 : 5)
    return
  }
  if (section === 'contracts' && detail.value) {
    await nextTick()
    silverWorkspace.value?.openContracts()
    return
  }
  if (section === 'contracts') {
    document.getElementById('contrats-yaml')?.scrollIntoView({ block: 'start' })
    return
  }
  activeStep.value = 'silver'
  await nextTick()
  document.getElementById('table-tampon')?.scrollIntoView({ block: 'start' })
}
function bronzeReady(database: string) {
  activeStep.value = 'silver'
  message.value = `Bronze dataset créé · ${database}`
}
function updateBronzeState(value: BronzePreparation) {
  const initialLoad = bronzePreparation.value === null
  bronzePreparation.value = value
  if (detail.value) detail.value.status = value.status
  if (initialLoad && value.state === 'complete' && !route.hash) activeStep.value = 'silver'
}
watch(() => route.hash, value => {
  if (value === '#contrats-yaml') void openSection('contracts')
  if (value === '#table-tampon') void openSection('quarantine')
})
watch(detail, (value, previous) => {
  if (value && !previous && !wizardMode.value && value.status !== 'ingestion-bronze' && !route.hash) activeStep.value = 'silver'
  if (value && !previous && route.hash === '#contrats-yaml') void openSection('contracts')
  if (value && !previous && route.hash === '#table-tampon') void openSection('quarantine')
})
watch(() => route.query.nouveau, value => { if (value === '1') openNewModel() })
watch(() => route.query.modele, value => { if (typeof value === 'string') modelId.value = value })
onMounted(() => { if (versionId.value) void loadDetail() })
</script>

<template>
  <div class="flex h-full min-h-0 flex-col gap-6 overflow-hidden">
    <UAlert v-if="modelsError" color="error" variant="subtle" icon="i-lucide-circle-alert" title="Catalogue indisponible" description="Vérifie que les migrations sont terminées." />
    <UAlert v-if="failure && !newModelOpen && !historyOpen" color="error" variant="subtle" icon="i-lucide-circle-alert" title="La demande n’a pas abouti" :description="failure" role="alert" />
    <UAlert v-if="message" color="success" variant="subtle" icon="i-lucide-circle-check" :title="message" role="status" />

    <UCard class="shrink-0">
      <div class="flex flex-col gap-4 lg:flex-row lg:items-end">
        <UFormField label="Modèle" name="model" class="min-w-0 flex-1">
          <USelect v-model="modelId" :items="modelItems" placeholder="Choisir un modèle" :disabled="busy" icon="i-lucide-boxes" class="w-full" aria-label="Modèle" />
        </UFormField>
        <template v-if="selectedModel">
          <UFormField label="Version du modèle" name="version" class="min-w-0 flex-1">
            <USelect v-model="versionId" :items="versionItems" :disabled="busy" icon="i-lucide-git-branch" class="w-full" aria-label="Version du modèle" />
          </UFormField>
          <UButton color="neutral" variant="outline" icon="i-lucide-git-branch-plus" label="Nouvelle version du modèle" class="shrink-0 self-start lg:self-auto" :disabled="busy" @click="newVersionOpen = true" />
        </template>
      </div>
    </UCard>

    <template v-if="versionId">

      <UTabs v-model="activeStep" :items="workflowSteps" :unmount-on-hide="false" variant="link" class="min-h-0 w-full flex-1 items-stretch" :ui="{ list: 'shrink-0', content: 'flex min-h-0 flex-1 flex-col gap-6 overflow-hidden pt-4' }" aria-label="Étapes de préparation">
      <template #bronze>
      <BronzeV2Wizard v-if="wizardMode && detail" :key="versionId" ref="bronzeWizard" :version-id="versionId" :contracts="contracts" @state="updateBronzeState" @updated="silverUpdated" @ready="bronzeReady" @working="busy = $event" />
      <div v-else-if="!wizardMode" class="min-h-0 flex-1 space-y-6 overflow-y-auto">
      <UCard>
        <template #header><h2 class="font-semibold text-highlighted">Téléverser des datasets complets</h2><p class="mt-1 text-sm text-muted">Précharge les fichiers, vérifie leurs contrats puis charge-les en bronze. Conserve le nom du dataset pour le mettre à jour.</p></template>
        <form class="space-y-5" @submit.prevent="upload">
          <fieldset :disabled="busy || !bronzeEditable" class="space-y-5">
          <UFileUpload v-model="files" multiple accept=".csv,.sql" :disabled="busy || !bronzeEditable" icon="i-lucide-cloud-upload" label="Dépose tes fichiers ici ou clique pour les sélectionner" description="CSV ou SQL PostgreSQL · 25 Mio par fichier · 10 fichiers maximum" class="min-h-40 w-full" aria-label="Fichiers CSV ou SQL PostgreSQL" />
          <div v-for="(entry, index) in queue" :key="index" class="grid gap-5 rounded-lg border border-default bg-elevated/30 p-4 lg:grid-cols-3">
            <div class="space-y-4">
              <div class="flex min-w-0 items-center gap-3"><UIcon :name="isCsv(entry) ? 'i-lucide-file-spreadsheet' : 'i-lucide-file-code-2'" class="size-5 shrink-0 text-primary" /><div class="min-w-0"><p class="truncate text-sm font-medium text-highlighted">{{ entry.file.name }}</p><p class="text-xs text-muted">{{ (entry.file.size / 1024).toFixed(1) }} Kio</p></div></div>
              <UFormField label="Nom du dataset" :name="`dataset-${index}`" required><UInput v-model="entry.dataset_name" required maxlength="120" :disabled="busy" class="w-full" list="dataset-names" :aria-label="`Nom du dataset — ${entry.file.name}`" @update:model-value="invalidatePreload(entry)" /></UFormField>
              <template v-if="isCsv(entry)">
                <UFormField label="Contrat CSV" :name="`contract-mode-${index}`"><USelect v-model="entry.contract_mode" :items="contractModes" :disabled="busy" class="w-full" :aria-label="`Mode de contrat — ${entry.file.name}`" @update:model-value="invalidatePreload(entry)" /></UFormField>
                <UFormField v-if="entry.contract_mode === 'existing'" label="Contrat existant" :name="`contract-${index}`" required><USelect v-model="entry.contract" :items="contracts" placeholder="Choisir un contrat" :disabled="busy" class="w-full" :aria-label="`Contrat CSV — ${entry.file.name}`" @update:model-value="invalidatePreload(entry)" /></UFormField>
              </template>
              <template v-if="entry.preloaded">
                <UBadge color="success" variant="subtle">Préchargé · {{ entry.summary?.rows.toLocaleString('fr-FR') }} lignes</UBadge>
                <p v-if="isCsv(entry)" class="text-xs text-muted">{{ entry.contract_mode === 'existing' ? `Contrat existant chargé : ${contractLabel(entry)}` : 'Nouveau contrat proposé par l’analyse du fichier' }}</p>
              </template>
              <p v-else class="text-xs text-muted">En attente de préchargement · aucune donnée bronze créée.</p>
            </div>
            <div class="space-y-3 lg:col-span-2">
              <UFormField v-if="entry.preloaded && isCsv(entry)" :label="`Contrat YAML — ${entry.file.name}`" :hint="entry.contract_mode === 'existing' ? 'Contrat existant · modifiable' : 'Proposition générée · modifiable'">
                <UTextarea v-model="entry.contract_yaml" :rows="16" :maxlength="200000" :disabled="busy" class="w-full" :ui="{ base: 'font-mono text-xs' }" :aria-label="`Contrat YAML — ${entry.file.name}`" spellcheck="false" />
              </UFormField>
              <p v-else-if="isCsv(entry)" class="rounded-md border border-dashed border-default p-5 text-sm text-muted">{{ entry.contract_mode === 'existing' ? 'Clique sur « Précharger » pour charger le contrat sélectionné et vérifier le fichier avec ses règles.' : 'Clique sur « Précharger » pour générer une proposition de contrat à partir de ce fichier.' }} Le contrat sera modifiable avant le chargement en bronze.</p>
              <p v-else class="text-sm leading-5 text-muted">Le schéma est extrait du SQL lors du préchargement. Aucune instruction du fichier n’est exécutée.</p>
              <UAccordion v-if="entry.summary?.notes.length" :items="[{ label: `${entry.summary.notes.length} observation(s) au préchargement`, icon: 'i-lucide-list-checks' }]"><template #content><ul class="list-disc space-y-2 ps-5 pb-4 text-sm text-muted"><li v-for="(note, noteIndex) in entry.summary.notes" :key="noteIndex">{{ note }}</li></ul></template></UAccordion>
            </div>
          </div>
          <datalist id="dataset-names"><option v-for="dataset in detail?.datasets" :key="dataset.id" :value="dataset.name" /></datalist>
          <div class="flex flex-wrap items-center justify-between gap-4">
            <p class="max-w-xl text-xs leading-5 text-muted">Le préchargement n’insère aucune donnée. Au chargement, les contrats modifiés sont revalidés et conservés avec les sources. 100 Mio maximum par lot ; un fichier invalide annule le lot.</p>
            <div class="flex flex-wrap gap-3">
              <UButton type="button" icon="i-lucide-scan-search" color="neutral" variant="outline" :loading="busy" :disabled="busy || !queue.length" label="Précharger" @click="preloadFiles" />
              <UButton type="submit" icon="i-lucide-upload" :loading="busy" :disabled="busy || !allPreloaded" label="Charger en bronze" />
            </div>
          </div>
          </fieldset>
        </form>
        <p v-if="detail && !bronzeEditable" class="mt-4 text-sm text-muted">L’étape Bronze est validée. Crée une nouvelle version du modèle pour changer ses sources.</p>
        <div v-if="results.length" class="mt-5 space-y-2" aria-label="Résultats du téléversement">
          <UAlert v-for="(result, index) in results" :key="index" :color="result.status === 'created' ? 'success' : 'info'" variant="subtle" :icon="result.status === 'created' ? 'i-lucide-circle-check' : 'i-lucide-copy-check'" :title="result.filename" :description="`${result.status === 'created' ? 'Nouvelle version créée' : result.status === 'reused' ? 'Version existante réutilisée, sans copie des données' : 'Fichier déjà présent, aucun doublon ajouté'} · dataset v${result.number} · ${result.summary.rows.toLocaleString('fr-FR')} lignes`" />
        </div>
      </UCard>

      <UCard :ui="{ body: 'p-0 sm:p-0' }">
        <template #header><div class="flex items-center gap-2"><h2 class="font-semibold text-highlighted">Datasets de cette version du modèle</h2><UBadge color="neutral" variant="subtle">{{ detail?.datasets.length ?? 0 }}</UBadge></div></template>
        <UTable v-if="detail?.datasets.length" :data="detail.datasets" :columns="datasetColumns">
          <template #name-cell="{ row }"><div class="flex items-center gap-3"><UIcon name="i-lucide-database" class="size-5 text-muted" /><div><p class="font-medium text-highlighted">{{ row.original.name }}</p><p class="text-xs text-muted">{{ row.original.filename }}</p></div></div></template>
          <template #number-cell="{ row }"><UBadge color="neutral" variant="subtle">v{{ row.original.number }}</UBadge></template>
          <template #summary-cell="{ row }">{{ row.original.summary.rows.toLocaleString('fr-FR') }}</template>
          <template #actions-cell="{ row }"><UButton color="neutral" variant="ghost" icon="i-lucide-history" label="Historique et aperçu" @click="openDataset(row.original.id)" /></template>
        </UTable>
        <UEmpty v-else icon="i-lucide-database" title="Aucun dataset pour cette version" description="Téléverse les fichiers initiaux dans l’espace ci-dessus." class="py-10" />
      </UCard>

      <UCard v-if="bronzeEditable">
        <template #header><h2 class="font-semibold text-highlighted">Valider l’étape Bronze</h2></template>
        <p class="mb-4 text-sm text-muted">Vérifie que tous les fichiers attendus sont chargés. La validation fige les sources de cette version et ouvre l’étape Silver.</p>
        <UButton label="Valider l’étape Bronze" icon="i-lucide-check" :loading="busy" :disabled="busy || !detail?.datasets.length || !!queue.length" @click="validateStage('bronze')" />
        <p v-if="queue.length" class="mt-3 text-xs text-muted">Charge ou retire les fichiers encore en attente avant de valider.</p>
      </UCard>
      </div>
      </template>
      <template #silver>
        <div class="min-h-0 flex-1 space-y-6 overflow-y-auto">
        <BronzeDatasetView v-if="wizardMode && bronzePreparation?.state === 'complete'" :key="versionId" :version-id="versionId" :preparation="bronzePreparation" />
        <SilverWorkspace v-else-if="!wizardMode && detail" :key="versionId" ref="silverWorkspace" :version-id="versionId" :datasets="detail.datasets" :status="detail.status" :parent-busy="busy || !!detail.read_only" @updated="silverUpdated" @gate="silverBlocked = $event" @working="busy = $event" />
        <UCard v-if="!wizardMode && detail?.status === 'ingestion-silver' && !detail.read_only">
          <template #header><h2 class="font-semibold text-highlighted">Valider l’étape Silver</h2></template>
          <p class="mb-4 text-sm text-muted">Toutes les tables doivent être préparées avec leur dernier contrat enregistré et toutes les erreurs de la table tampon doivent être résolues. La validation ouvre l’étape Gold.</p>
        </UCard>
        </div>
        <div v-if="!wizardMode && detail?.status === 'ingestion-silver' && !detail.read_only" class="flex shrink-0 justify-end border-t border-default bg-default pt-4">
          <UButton label="Valider l’étape Silver" icon="i-lucide-check" :loading="busy" :disabled="busy || silverBlocked" @click="validateStage('silver')" />
        </div>
      </template>
      </UTabs>
    </template>

    <USlideover v-model:open="journalOpen" :transition="false" :title="detail ? `Journal · ${selectedModel?.name} · version ${detail.number}` : 'Journal de la version du modèle'" description="Créations, imports, changements de statut et préparations : les 200 derniers événements, du plus récent au plus ancien." :ui="{ content: 'sm:max-w-2xl' }">
      <template #body>
        <div class="space-y-5">
          <UAlert v-if="failure" color="error" variant="subtle" :description="failure" role="alert" />
          <div v-if="journalLoading" class="space-y-4"><USkeleton class="h-16 w-full" /><USkeleton class="h-16 w-full" /></div>
          <UEmpty v-else-if="!versionId" icon="i-lucide-git-branch" title="Sélectionne une version du modèle" description="Choisis un modèle et sa version pour consulter son journal." />
          <UTimeline v-else-if="historyItems.length" :items="historyItems" :default-value="historyItems.length - 1" />
          <p v-else class="text-sm text-muted">Aucun événement pour cette version.</p>
        </div>
      </template>
    </USlideover>

    <UModal v-model:open="newModelOpen" :transition="false" title="Nouveau modèle" description="Crée un modèle et sa première version pour regrouper tes datasets." :dismissible="!busy" :close="busy ? false : undefined">
      <template #body>
        <form class="space-y-5" @submit.prevent="createModel">
          <UAlert v-if="failure" color="error" variant="subtle" :description="failure" role="alert" />
          <UFormField label="Nom du modèle" name="name" required><UInput v-model="newName" required maxlength="120" :disabled="busy" autofocus placeholder="Ex. Prévision des incidents" class="w-full" /></UFormField>
          <UFormField label="Objectif du modèle" name="description" hint="Facultatif"><UTextarea v-model="description" maxlength="2000" :disabled="busy" placeholder="Que souhaites-tu préparer ou prédire ?" class="w-full" /></UFormField>
          <div class="flex justify-end gap-2"><UButton color="neutral" variant="outline" label="Annuler" :disabled="busy" @click="newModelOpen = false" /><UButton type="submit" icon="i-lucide-plus" label="Créer le modèle" :loading="busy" :disabled="busy || !newName.trim()" /></div>
        </form>
      </template>
    </UModal>

    <UModal v-model:open="newVersionOpen" :transition="false" title="Nouvelle version du modèle" description="Les versions existantes et leurs données restent accessibles." :dismissible="!busy" :close="busy ? false : undefined">
      <template #body>
        <div class="space-y-5">
          <UCheckbox v-model="inherit" :disabled="busy" label="Réutiliser les sources de la version sélectionnée" description="Les fichiers et contrats sont repris dans un nouveau brouillon. La base de données sera propre à la nouvelle version. Décoche pour commencer sans fichier." />
          <div class="flex justify-end gap-2"><UButton color="neutral" variant="outline" label="Annuler" :disabled="busy" @click="newVersionOpen = false" /><UButton icon="i-lucide-git-branch-plus" label="Créer la version" :loading="busy" :disabled="busy" @click="createVersion" /></div>
        </div>
      </template>
    </UModal>

    <USlideover v-model:open="historyOpen" :transition="false" :title="datasetHistory ? `Dataset · ${datasetHistory.name}` : 'Historique du dataset'" description="Versions complètes, cartes d’identité et aperçu des données brutes." :ui="{ content: 'sm:max-w-4xl' }">
      <template #body>
        <div class="space-y-6">
          <UAlert v-if="failure" color="error" variant="subtle" :description="failure" role="alert" />
          <div v-if="historyLoading" class="space-y-4"><USkeleton class="h-10 w-full" /><USkeleton class="h-60 w-full" /></div>
          <template v-else-if="datasetHistory && selectedSnapshot">
            <UFormField label="Version du dataset"><USelect :model-value="selectedSnapshot.id" :items="snapshotItems" class="w-full" aria-label="Version du dataset" @update:model-value="selectSnapshot" /></UFormField>
            <div class="flex flex-wrap items-center justify-between gap-3"><UBadge variant="subtle">Bronze · {{ selectedSnapshot.summary.rows.toLocaleString('fr-FR') }} lignes</UBadge><UButton :to="`/api/dataset-versions/${selectedSnapshot.id}/report`" external color="neutral" variant="outline" icon="i-lucide-download" label="Carte d’identité" /></div>
            <p class="break-all rounded-md bg-elevated p-3 font-mono text-xs text-muted">SHA-256 : {{ selectedSnapshot.sha256 }}</p>
            <UAlert v-if="selectedSnapshot.summary.duplicate_rows" color="warning" variant="subtle" icon="i-lucide-copy" title="Lignes répétées dans la source" :description="`${selectedSnapshot.summary.duplicate_rows} ligne(s) conservée(s) en bronze. Leur traitement sera défini en silver.`" />
            <UAccordion v-if="selectedSnapshot.summary.notes.length" :items="[{ label: `${selectedSnapshot.summary.notes.length} observation(s) de qualité`, icon: 'i-lucide-list-checks' }]">
              <template #content><ul class="list-disc space-y-2 ps-5 pb-4 text-sm text-muted"><li v-for="(note, index) in selectedSnapshot.summary.notes" :key="index">{{ note }}</li></ul></template>
            </UAccordion>
            <UFormField label="Table à examiner"><USelect v-model="selectedTable" :items="tableItems" class="w-full" aria-label="Table à examiner" @update:model-value="loadPreview" /></UFormField>
            <div><p class="mb-3 text-xs text-muted">Aperçu des 20 premières lignes brutes.</p><UTable :data="preview" :columns="previewColumns" :loading="previewLoading" class="rounded-lg border border-default" /></div>
          </template>
        </div>
      </template>
    </USlideover>
  </div>
</template>
