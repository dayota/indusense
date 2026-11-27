<script setup lang="ts">
import type { PreparationFile } from '~/types/bronze'
import type { ContractEditor, ContractEditorFile, ContractEditorResponse } from '~/types/contract'
const props = defineProps<{ versionId: string; files: PreparationFile[]; readonly: boolean }>()
const emit = defineEmits<{ saved: []; dirty: [value: boolean]; working: [value: boolean] }>()
const baseURL = useApiBase()
const prefix = computed(() => `/model-versions/${props.versionId}/bronze`)
const editors = ref<ContractEditorFile[]>([])
const selectedFileId = ref('')
const selectedTables = ref<Record<string, string>>({})
watch(() => editors.value.map(file => ({ id: file.id, tables: file.editors.flatMap(editor => editor.table ? [editor.table] : []) })), (files) => {
  for (const file of files) {
    if (!file.tables.includes(selectedTables.value[file.id] ?? '')) selectedTables.value[file.id] = file.tables[0] ?? ''
  }
}, { immediate: true })
watch(() => props.files.map(file => file.id), (ids) => {
  if (!ids.includes(selectedFileId.value)) selectedFileId.value = ids[0] ?? ''
}, { immediate: true })
const types = ref<string[]>([])
const operations = ref<string[]>([])
const timezones = ref<string[]>([])
const silverTypes = ref<Record<string, string[]>>({})
const postgresTypes = ref<string[]>([])
const busy = ref(false)
const failure = ref('')
const modifyOpen = ref(false)
const modifyTarget = ref<{ editor: ContractEditor; filename: string; version: string } | null>(null)
const versionChoices = computed(() => {
  const match = modifyTarget.value?.version.match(/^([0-9]+)\.([0-9]+)\.([0-9]+)$/)
  if (!match) return []
  const major = BigInt(match[1]!), minor = BigInt(match[2]!), patch = BigInt(match[3]!)
  return [
    { label: 'Correctif', version: `${major}.${minor}.${patch + 1n}` },
    { label: 'Mineur', version: `${major}.${minor + 1n}.0` },
    { label: 'Majeur', version: `${major + 1n}.0.0` },
  ]
})
const settings = ref<Record<string, { encoding: string; delimiter: string; row_delimiter: string }>>({})
for (const file of props.files) settings.value[file.id] = { encoding: file.sql_contracts?.[0]?.encoding ?? 'utf-8', delimiter: ',', row_delimiter: '\n' }
async function perform(action: () => Promise<void>) {
  if (busy.value) return false
  busy.value = true; emit('working', true); failure.value = ''
  try { await action(); return true }
  catch (error) { const detail = (error as { data?: { detail?: unknown } }).data?.detail; failure.value = typeof detail === 'string' ? detail : 'La demande a échoué. Vérifie les sources et les contrats locaux.'; return false }
  finally { busy.value = false; emit('working', false) }
}
function load() { return perform(async () => {
  const result = await $fetch<ContractEditorResponse>(`${prefix.value}/contracts/editor`, { baseURL, method: 'POST', body: { files: props.files.map(file => ({ id: file.id, ...settings.value[file.id] })) } })
  editors.value = result.files; types.value = result.column_types; operations.value = result.operations
  timezones.value = result.timezones; silverTypes.value = result.silver_types
  postgresTypes.value = result.postgres_types
  for (const file of result.files) {
    const source = file.editors[0]?.config.source
    if (source) settings.value[file.id] = { encoding: source.encoding, delimiter: source.field_delimiter ?? ',', row_delimiter: source.row_delimiter ?? '\n' }
  }
  emit('dirty', result.files.some(file => !file.saved || file.editors.some(editor => !editor.existing)))
}) }
function save(notify = true) { return perform(async () => {
  const files = editors.value.map(file => {
    const original = props.files.find(item => item.id === file.id)!
    const payload = (editor: ContractEditorFile['editors'][number]) => ({ config: editor.config })
    return original.format === 'sql'
      ? { id: file.id, revision: file.revision, tables: file.editors.map(editor => ({ table: editor.table, ...payload(editor) })) }
      : { id: file.id, revision: file.revision, ...payload(file.editors[0]!) }
  })
  await $fetch(`${prefix.value}/contracts/save`, { baseURL, method: 'POST', body: { files } })
  for (const file of editors.value) {
    file.revision++
    for (const editor of file.editors) { editor.existing = true; editor.editing = false }
  }
  emit('dirty', false)
  if (notify) emit('saved')
}) }
function fileSettingsChanged(id: string) {
  for (const editor of editors.value.find(file => file.id === id)?.editors ?? []) {
    if (editor.existing && !editor.editing) continue
    editor.config.source.encoding = settings.value[id]!.encoding
    if (editor.config.source.format === 'CSV') editor.config.source.field_delimiter = settings.value[id]!.delimiter
  }
  emit('dirty', true)
}
function showFileSettings(id: string) {
  const file = editors.value.find(item => item.id === id)
  return !file
}
function showSourceFields(id: string, editor: ContractEditorFile['editors'][number]) {
  return editors.value.find(file => file.id === id)?.editors[0] === editor
}
function formChanged(id: string, editor: ContractEditorFile['editors'][number]) {
  if (showSourceFields(id, editor)) {
    const source = editor.config.source
    settings.value[id] = { encoding: source.encoding, delimiter: source.field_delimiter ?? ',', row_delimiter: source.row_delimiter ?? '\n' }
    fileSettingsChanged(id)
  }
  emit('dirty', true)
}
const selectedEditor = computed(() => {
  const file = editors.value.find(file => file.id === selectedFileId.value)
  return file?.editors.find(editor => editor.table === selectedTables.value[file.id]) ?? file?.editors[0]
})
const canSave = computed(() => !props.readonly && !!selectedEditor.value &&
  (!selectedEditor.value.existing || !!selectedEditor.value.editing) &&
  editors.value.length === props.files.length && !!editors.value.length)
const canModify = computed(() => !props.readonly && !busy.value && !!selectedEditor.value?.existing && !selectedEditor.value.editing)
function openModify() {
  if (!canModify.value) return
  const file = editors.value.find(file => file.id === selectedFileId.value)!
  modifyTarget.value = { editor: selectedEditor.value!, filename: file.filename, version: selectedEditor.value!.config.version }
  modifyOpen.value = true
}
function startEditing(version: string) {
  const target = modifyTarget.value
  if (!target || busy.value || props.readonly || target.editor.editing) return
  if (!versionChoices.value.some(choice => choice.version === version)) return
  const editor = target.editor
  editor.config.version = version
  editor.editing = true
  const name = editor.table ?? target.filename.replace(/\.[^.]+$/, '')
  editor.path = `${editor.path.slice(0, editor.path.lastIndexOf('/'))}/${name}-${version}.yml`
  modifyOpen.value = false
  emit('dirty', true)
}
const canAccept = computed(() => !!editors.value.length && editors.value.length === props.files.length)
function accept() { return save(false) }
defineExpose({ openModify, save, accept, canSave, canModify, canAccept })
onMounted(() => { void load() })
</script>

<template>
  <div class="space-y-5">
    <UAlert v-if="failure" title="Contrat refusé" color="error" :description="failure" class="whitespace-pre-wrap" role="alert" />
    <div class="grid items-start gap-4 md:grid-cols-[max-content_minmax(0,1fr)]">
      <nav aria-label="Fichiers et contrats" class="flex min-w-64 flex-col gap-2 overflow-x-auto rounded-lg border border-default p-2 md:sticky md:top-0">
        <p class="px-2 py-1 text-xs font-medium text-muted">Fichiers</p>
        <div v-for="file in props.files" :key="file.id" class="space-y-1">
          <UButton :label="file.filename"
            :icon="file.format === 'sql' ? 'i-lucide-database' : 'i-lucide-file-spreadsheet'"
            :variant="selectedFileId === file.id ? 'soft' : 'ghost'" :color="selectedFileId === file.id ? 'primary' : 'neutral'"
            :aria-pressed="selectedFileId === file.id" class="w-full justify-start" :ui="{ label: 'whitespace-nowrap text-left' }"
            @click="selectedFileId = file.id" />
          <ul v-if="file.format === 'sql'" :aria-label="`Tables de ${file.filename}`" class="ml-4 space-y-1 border-l border-default pl-2">
            <li v-for="editor in editors.find(item => item.id === file.id)?.editors ?? []" :key="editor.table ?? 'sql'">
              <UButton :label="editor.table ?? ''" icon="i-lucide-table-2"
                :variant="selectedFileId === file.id && selectedTables[file.id] === editor.table ? 'soft' : 'ghost'"
                :color="selectedFileId === file.id && selectedTables[file.id] === editor.table ? 'primary' : 'neutral'"
                :aria-pressed="selectedFileId === file.id && selectedTables[file.id] === editor.table"
                class="w-full justify-start" :ui="{ label: 'whitespace-nowrap text-left' }"
                @click="selectedFileId = file.id; selectedTables[file.id] = editor.table ?? ''" />
            </li>
          </ul>
        </div>
      </nav>
      <div class="min-w-0 space-y-5">
        <UCard v-for="file in props.files" v-show="selectedFileId === file.id" :key="file.id">
          <template #header><h2>{{ file.filename }}</h2></template>
          <div class="space-y-5">
            <div v-if="!readonly && showFileSettings(file.id)" class="flex flex-wrap items-end gap-3">
              <UFormField label="Encodage du fichier"><UInput v-model="settings[file.id]!.encoding" :disabled="busy" @update:model-value="fileSettingsChanged(file.id)" /></UFormField>
              <UFormField v-if="file.format === 'csv'" label="Séparateur de champs"><UInput v-model="settings[file.id]!.delimiter" maxlength="1" :disabled="busy" @update:model-value="fileSettingsChanged(file.id)" /></UFormField>
            </div>
            <div v-for="editor in editors.find(item => item.id === file.id)?.editors ?? []" v-show="file.format !== 'sql' || selectedTables[file.id] === editor.table" :key="editor.table ?? 'csv'" class="space-y-4 rounded-lg border border-default p-4">
              <h3 v-if="editor.table" class="font-medium">{{ editor.table }}</h3>
              <p class="break-all text-xs text-muted">{{ editor.path }}</p>
              <UBadge v-if="editor.existing" :color="editor.editing ? 'warning' : 'success'">{{ editor.editing ? 'Contrat en cours de modification' : 'Contrat existant · consultation' }}</UBadge>
              <UAlert v-else-if="!readonly" color="info" title="Aucun contrat local correspondant" description="Complète le formulaire pour générer un contrat conforme au schéma Bronze." />
              <BronzeContractForm v-model="editor.config" :column-types="types" :operations="operations" :timezones="timezones" :silver-types="silverTypes" :postgres-types="postgresTypes" :source-fields="showSourceFields(file.id, editor)" :disabled="busy || readonly || (editor.existing && !editor.editing)" @dirty="formChanged(file.id, editor)" />
            </div>
          </div>
        </UCard>
      </div>
    </div>
    <UModal v-model:open="modifyOpen" title="Modifier le contrat" description="Choisis la nouvelle version pour activer l’édition du contrat." :ui="{ content: 'sm:max-w-sm' }">
      <template #body>
        <div class="space-y-4">
          <p class="text-sm text-muted">Version actuelle : {{ modifyTarget?.version }}</p>
          <div class="flex flex-col gap-2">
            <UButton v-for="choice in versionChoices" :key="choice.label" :label="`${choice.label} (${choice.version})`" color="neutral" variant="outline" class="justify-center" @click="startEditing(choice.version)" />
          </div>
          <div class="flex justify-end"><UButton label="Annuler" color="neutral" variant="ghost" @click="modifyOpen = false" /></div>
        </div>
      </template>
    </UModal>
  </div>
</template>
