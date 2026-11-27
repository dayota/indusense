<script setup lang="ts">
import type { BronzePreparation } from '~/types/bronze'
const props = defineProps<{ versionId: string; contracts: { label: string; value: string }[] }>()
const emit = defineEmits<{ updated: []; ready: [database: string]; state: [value: BronzePreparation]; working: [active: boolean] }>()
const baseURL = useApiBase()
const prefix = computed(() => `/model-versions/${props.versionId}/bronze`)
const state = ref<BronzePreparation | null>(null)
const busy = ref(false)
const failure = ref('')
const notice = ref('')
const loadingPhase = ref('')
type Execution = { id: string; status: 'QUEUED' | 'RUNNING' | 'SUCCESS' | 'FAILED'; phase: string; error: string | null }
const execution = ref<Execution | null>(null)
let disposed = false
onBeforeUnmount(() => { disposed = true })
const contractsDirty = ref(false)
const contractStep = ref<{ openModify: () => void; save: () => Promise<boolean>; accept: () => Promise<boolean>; canSave: boolean; canModify: boolean; canAccept: boolean } | null>(null)
const step = ref('1')
const approved = ref(false)
const pending = ref<File[]>([])
const previewOpen = ref(false)
const previewId = ref('')
const previewEncoding = ref('utf-8')
const previewContent = ref<{ filename: string; path: string; content: string; truncated: boolean } | null>(null)
const fileUpload = useTemplateRef('fileUpload')
const files = computed(() => state.value?.files ?? [])
const archives = computed(() => state.value?.archives ?? [])
const saved = computed(() => !contractsDirty.value && !!files.value.length && files.value.every(file => file.saved_yaml !== null))
const readonly = computed(() => state.value?.readonly ?? true)
const identitiesReady = computed(() => files.value.length > 0 && files.value.every(file => !!file.report && !!file.summary?.identity_path))
const maximum = computed(() => execution.value && ['SUCCESS', 'FAILED'].includes(execution.value.status) ? 5 : state.value?.state !== 'draft' && state.value ? 5 : pending.value.length || !files.value.length ? 1 : !saved.value || !identitiesReady.value ? 2 : !state.value?.identities_reviewed ? 3 : 4)
const steps = computed(() => [
  { label: '1 · Fichiers', value: '1' }, { label: '2. Contrats', value: '2' },
  { label: '3 · Cartes d’identité', value: '3' }, { label: '4. Chargement des données', value: '4' },
  { label: '5 · Rapports et validation', value: '5' },
].map(item => ({ ...item, disabled: busy.value || Number(item.value) > maximum.value })))
const legacy = ref<{ openStep: (value: number) => void } | null>(null)
let requested: number | null = null
function openStep(value: number) {
  if (!state.value) { requested = value; return }
  if (state.value.protocol === 1) legacy.value?.openStep(value)
  else go(String(value))
}
defineExpose({ openStep })
function go(value: string) { if (Number(value) <= maximum.value) step.value = value }
async function refresh() {
  state.value = await $fetch<BronzePreparation>(prefix.value, { baseURL })
  approved.value = false; emit('state', state.value)
}
function errorText(error: unknown) {
  const detail = (error as { data?: { detail?: unknown } }).data?.detail
  return typeof detail === 'string' ? detail : error instanceof Error ? error.message : 'La demande a échoué.'
}
async function perform(action: () => Promise<void>) {
  if (busy.value) return
  busy.value = true; emit('working', true); failure.value = ''; notice.value = ''
  try { await action() }
  catch (error) {
    const detail = (error as { data?: { detail?: unknown } }).data?.detail
    failure.value = typeof detail === 'string' ? detail : error instanceof Error ? error.message : 'La demande a échoué.'
  }
  finally { busy.value = false; emit('working', false) }
}
function upload() { return perform(async () => {
  const form = new FormData()
  for (const file of pending.value) form.append('files', file)
  form.append('manifest', JSON.stringify(pending.value.map(file => ({ dataset_name: file.name.replace(/\.[^.]+$/, '') }))))
  await $fetch(`${prefix.value}/files`, { baseURL, method: 'POST', body: form })
  pending.value = []; await refresh(); emit('updated'); go('2')
}) }
async function contractsSaved() {
  contractsDirty.value = false
  try { await refresh(); emit('updated') }
  catch (error) { failure.value = errorText(error) }
}
function openFiles() { if (!busy.value && !readonly.value) fileUpload.value?.inputRef?.click() }
async function next() {
  if (step.value === '1' && pending.value.length) return upload()
  if (step.value === '2' && !readonly.value) {
    if (!(await contractStep.value?.accept())) return
    return perform(async () => {
      await $fetch(`${prefix.value}/identities/generate`, { baseURL, method: 'POST' })
      await refresh(); emit('updated'); go('3')
    })
  }
  return perform(async () => {
  if (step.value === '1' && files.value.length && !readonly.value) {
    await $fetch(`${prefix.value}/files/archive`, { baseURL, method: 'POST' }); await refresh()
  }
  if (step.value === '3' && !readonly.value) {
    step.value = '4'; loadingPhase.value = 'Préparation de la migration pour revue…'
    try {
      await $fetch(`${prefix.value}/identities/confirm`, { baseURL, method: 'POST' })
      await $fetch(`${prefix.value}/migrations/generate`, { baseURL, method: 'POST' })
      await refresh()
    }
    finally { loadingPhase.value = '' }
    return
  }
  go(String(Number(step.value) + 1))
}) }
function generate() { return perform(async () => {
  await $fetch(`${prefix.value}/migrations/generate`, { baseURL, method: 'POST' }); await refresh()
}) }
function approve() { return perform(async () => {
  await $fetch(`${prefix.value}/migrations/approve`, { baseURL, method: 'POST', body: { hash: state.value?.migration?.hash } }); await refresh()
  await runIngestion()
}) }
async function runIngestion() {
  step.value = '4'; loadingPhase.value = 'Démarrage du chargement…'
  try {
    await $fetch(`${prefix.value}/executions`, { baseURL, method: 'POST', body: { files: files.value.map(file => ({ id: file.id, revision: file.revision })) } })
    await followExecution()
  }
  catch (error) { await refresh(); if (state.value?.database_name) step.value = '5'; throw error }
  finally { loadingPhase.value = '' }
}
function create() { return perform(runIngestion) }
async function followExecution() {
  step.value = '4'
  while (!disposed) {
    try {
      execution.value = await $fetch<Execution | null>(`${prefix.value}/executions/current`, { baseURL })
      if (!execution.value) throw new Error('Exécution introuvable')
      loadingPhase.value = execution.value.phase
      if (['SUCCESS', 'FAILED'].includes(execution.value.status)) {
        await refresh(); emit('updated'); step.value = '5'
        if (execution.value.error) failure.value = execution.value.error
        return
      }
      notice.value = ''
    }
    catch { notice.value = 'Connexion interrompue. Reconnexion au suivi du chargement…' }
    await new Promise(resolve => setTimeout(resolve, 1500))
  }
}
function validate() { return perform(async () => {
  await $fetch(`${prefix.value}/validate`, { baseURL, method: 'POST' }); await refresh(); emit('updated'); emit('ready', state.value?.database_name ?? '')
}) }
function remove(id: string) { return perform(async () => {
  await $fetch(`${prefix.value}/files/${id}`, { baseURL, method: 'DELETE' }); await refresh(); emit('updated')
}) }
function loadPreview() { return perform(async () => {
  previewContent.value = null
  previewContent.value = await $fetch(`${prefix.value}/files/${previewId.value}/preview`, { baseURL, query: { encoding: previewEncoding.value } })
}) }
function showPreview(id: string) { previewId.value = id; previewEncoding.value = 'utf-8'; previewOpen.value = true; return loadPreview() }
onMounted(() => { void perform(async () => {
  await refresh()
  if (state.value?.protocol === 2) execution.value = await $fetch<Execution | null>(`${prefix.value}/executions/current`, { baseURL })
  if (execution.value && ['QUEUED', 'RUNNING'].includes(execution.value.status)) {
    try { await followExecution() }
    finally { loadingPhase.value = '' }
    return
  }
  step.value = String(maximum.value)
  if (requested !== null) openStep(requested)
}) })
</script>

<template>
  <BronzeWizard v-if="state?.protocol === 1" ref="legacy" :version-id="versionId" :contracts="contracts" @updated="emit('updated')" @state="emit('state', $event)" @working="emit('working', $event)" @ready="emit('ready', $event)" />
  <div v-else id="contrats-yaml" class="flex min-h-0 flex-1 flex-col gap-5">
    <UAlert v-if="failure" color="error" title="Préparation refusée" :description="failure" class="whitespace-pre-wrap" role="alert" />
    <UAlert v-if="notice" color="success" :description="notice" role="status" />
    <UAlert v-if="readonly" color="info" title="Consultation seule" description="Les sources, contrats et migrations sont figés. Les corrections et transformations métier sont réalisées en Silver." />
    <UTabs :model-value="step" :items="steps" :content="false" variant="link" class="shrink-0" aria-label="Étapes Bronze v2" @update:model-value="go(String($event))" />
    <Transition name="slide" mode="out-in">
      <div :key="step" class="min-h-0 flex-1 space-y-5 overflow-y-auto overscroll-contain px-1 pb-1 pt-2" role="tabpanel" aria-label="Contenu de l’étape Bronze">
        <UCard v-if="step === '1'">
          <template #header><h2>Téléverser les fichiers sources</h2></template>
          <div class="space-y-4">
            <template v-if="!readonly">
              <UFileUpload ref="fileUpload" v-model="pending" multiple accept=".csv,.sql" label="Fichiers CSV ou SQL PostgreSQL" description="25 Mio par fichier · 10 fichiers · 100 Mio au total" :disabled="busy" />
              <UButton label="Téléverser les fichiers" icon="i-lucide-upload" :disabled="busy" @click="openFiles" />
              <p class="text-sm text-muted">Choisis les fichiers, puis clique sur Suivant pour les téléverser.</p>
            </template>
            <p v-if="state?.archive_directory" class="break-all text-xs text-muted">Dossier d’historique : {{ state.archive_directory }}</p>
            <div v-for="file in files" :key="file.id" class="flex flex-wrap items-center justify-between gap-3 rounded border border-default p-3">
              <div><p>{{ file.filename }}</p><p class="break-all text-xs text-muted">SHA-256 {{ file.sha256 }}</p></div>
              <div class="flex flex-wrap gap-2">
                <template v-if="archives.some(archive => archive.id === file.id)">
                  <UButton label="Consulter" icon="i-lucide-eye" color="neutral" :disabled="busy" @click="showPreview(file.id)" />
                  <UButton :to="baseURL + prefix + '/files/' + file.id + '/download'" external label="Télécharger l’original" icon="i-lucide-download" color="neutral" />
                </template>
                <UButton v-if="!readonly" label="Retirer du brouillon" color="neutral" :disabled="busy" @click="remove(file.id)" />
              </div>
            </div>
            <template v-if="archives.some(archive => !archive.active)">
              <h3 class="font-medium">Historique des fichiers retirés du brouillon</h3>
              <div v-for="archive in archives.filter(item => !item.active)" :key="archive.id" class="flex flex-wrap items-center justify-between gap-3 rounded border border-default p-3">
                <div><p>{{ archive.filename }}</p><p class="text-xs text-muted">{{ archive.path }}</p></div>
                <div class="flex flex-wrap gap-2"><UButton label="Consulter" color="neutral" :disabled="busy" @click="showPreview(archive.id)" /><UButton :to="baseURL + prefix + '/files/' + archive.id + '/download'" external label="Télécharger l’original" color="neutral" /></div>
              </div>
            </template>
          </div>
        </UCard>
        <template v-else-if="step === '2'">
          <BronzeContractStep ref="contractStep" :version-id="versionId" :files="files" :readonly="readonly" @dirty="contractsDirty = $event" @working="busy = $event; emit('working', $event)" @saved="contractsSaved" />
        </template>
        <template v-else-if="step === '3'">
          <BronzeIdentityStep :files="files" />
        </template>
        <UCard v-else-if="step === '4'">
          <template #header><h2>{{ loadingPhase ? 'Chargement des données' : 'Revue de la migration Bronze' }}</h2></template>
          <BronzeLoadingRobot v-if="loadingPhase" :phase="loadingPhase" />
          <div v-else class="space-y-4">
            <p class="text-sm text-muted">Chaque colonne source conserve sa valeur brute et sa valeur typée au mieux. Les colonnes dérivées seront produites en Silver.</p>
            <UButton v-if="!readonly" label="Générer la migration" :disabled="busy || !saved || !state?.identities_reviewed" @click="generate" />
            <template v-if="state?.migration">
              <p class="break-all text-xs text-muted">Schéma : {{ state.migration.schema ?? 'bronze' }} · Empreinte de la revue : {{ state.migration.hash }}</p><pre class="max-h-96 overflow-auto rounded bg-elevated p-4 text-xs">{{ state.migration.sql ?? state.migration.script }}</pre>
              <template v-if="!readonly && state.approved_hash !== state.migration.hash"><UCheckbox v-model="approved" label="J’ai relu les changements de schéma et je les approuve." :disabled="busy" /><UButton label="Approuver et lancer le chargement" :disabled="busy || !approved" @click="approve" /></template>
              <UBadge v-else-if="state.approved_hash === state.migration.hash" color="success">Migration approuvée</UBadge>
            </template>
          </div>
        </UCard>
          <BronzeIngestionReport v-else-if="step === '5' && state" :version-id="versionId" :preparation="state" />
      </div>
    </Transition>
    <div class="grid shrink-0 grid-cols-2 items-center gap-3 border-t border-default bg-default pt-4 sm:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)]" aria-label="Actions de l’étape Bronze">
      <div class="col-start-1 row-start-1 justify-self-start">
        <UButton v-if="step !== '1'" label="Retour" color="neutral" :disabled="busy" @click="go(String(Number(step) - 1))" />
      </div>
      <div class="col-span-2 row-start-2 flex flex-wrap justify-center gap-3 justify-self-center sm:col-span-1 sm:col-start-2 sm:row-start-1">
        <template v-if="step === '2' && !readonly">
          <UButton label="Modifier le contrat" color="neutral" :disabled="busy || !contractStep?.canModify" @click="contractStep?.openModify()" />
          <UButton label="Sauvegarder le(s) contrat(s)" :disabled="busy || !contractStep?.canSave" @click="contractStep?.save()" />
        </template>
      </div>
      <div class="col-start-2 row-start-1 flex flex-wrap justify-end gap-3 justify-self-end sm:col-start-3">
        <UButton v-if="step === '4' && !readonly && state?.migration && state.approved_hash === state.migration.hash" label="Lancer le chargement" :disabled="busy || !saved" :loading="busy" @click="create" />
        <template v-if="step === '5' && state?.status === 'ingestion-bronze' && state.protocol === 2">
          <UButton v-if="state.database_name" label="Rejouer l’ingestion" color="neutral" :disabled="busy" @click="create" />
          <UButton label="Valider le bronze dataset" :disabled="busy || !state.can_validate" :loading="busy" @click="validate" />
        </template>
        <UButton v-if="Number(step) < 5 && step !== '4'" label="Suivant" :disabled="busy || (Number(step) >= maximum && !(step === '2' && contractStep?.canAccept) && !(step === '3' && saved) && !(step === '1' && pending.length))" @click="next" />
      </div>
    </div>
    <UModal v-model:open="previewOpen" :title="previewContent?.filename ?? 'Fichier original'" description="Consultation de l’archive originale, sans modification." :ui="{ content: 'sm:max-w-5xl' }">
      <template #body>
        <div class="space-y-4">
          <UFormField label="Encodage de consultation"><USelect v-model="previewEncoding" :items="[{label:'UTF-8',value:'utf-8'},{label:'Windows-1252',value:'cp1252'},{label:'Latin-1',value:'latin-1'}]" :disabled="busy" @update:model-value="loadPreview" /></UFormField>
          <p v-if="previewContent" class="break-all text-xs text-muted">{{ previewContent.path }}</p>
          <UAlert v-if="failure" color="error" :description="failure" />
          <UAlert v-if="previewContent?.truncated" color="info" description="Aperçu limité aux premiers 128 Kio. Le téléchargement conserve le fichier complet." />
          <pre class="max-h-[60vh] overflow-auto whitespace-pre text-xs">{{ busy ? 'Chargement…' : previewContent?.content }}</pre>
        </div>
      </template>
    </UModal>
  </div>
</template>

<style scoped>
.slide-enter-active,.slide-leave-active{transition:opacity .14s ease,transform .14s ease}
.slide-enter-from{opacity:0;transform:translateX(16px)}.slide-leave-to{opacity:0;transform:translateX(-16px)}
@media(prefers-reduced-motion:reduce){.slide-enter-active,.slide-leave-active{transition:none}}
</style>
