<script setup lang="ts">
const value = defineModel<string>({ required: true })
const props = defineProps<{ items: string[]; disabled: boolean }>()
const emit = defineEmits<{ dirty: [] }>()

const selectedType = ref('')
const modifiers = ref('')
let lastWritten: string | undefined
// Garder la saisie locale intacte, même pendant la frappe d'une parenthèse ou d'un crochet.
watch(() => value.value, (next) => {
  if (next === lastWritten) return
  const arrays = next.match(/(?:\[\])+$/)?.[0] ?? ''
  const scalar = next.slice(0, next.length - arrays.length)
  const match = scalar.match(/^(.*?)\(([^)]*)\)(.*)$/)
  selectedType.value = match ? (match[1]!.trimEnd() + match[3]!).trim() : scalar
  modifiers.value = (match ? `(${match[2]})` : '') + arrays
}, { immediate: true })

const scalarType = computed(() => selectedType.value.toUpperCase())
const serialTypes = new Set(['SERIAL', 'SMALLSERIAL', 'BIGSERIAL', 'SERIAL2', 'SERIAL4', 'SERIAL8'])
const supportsModifiers = computed(() => !serialTypes.has(scalarType.value))
const parameterHint = computed(() => {
  const type = scalarType.value
  const arrays = 'Ajouter [] pour un tableau, [][] pour plusieurs dimensions.'
  if (['NUMERIC', 'DECIMAL'].includes(type)) return { example: '(6,2)[]', detail: `Précision et échelle : (6,2). ${arrays}` }
  if (['CHARACTER', 'CHAR', 'CHARACTER VARYING', 'VARCHAR', 'BPCHAR', 'BIT', 'BIT VARYING', 'VARBIT'].includes(type)) {
    return { example: '(255)[]', detail: `Longueur : (255). ${arrays}` }
  }
  if (type === 'FLOAT') return { example: '(53)[]', detail: `Précision binaire de 1 à 53. ${arrays}` }
  if (/^(?:TIME|TIMESTAMP)(?: WITH(?:OUT)? TIME ZONE)?$/.test(type) || ['TIMETZ', 'TIMESTAMPTZ'].includes(type) || /^INTERVAL(?: |$)/.test(type)) {
    return { example: '(3)[]', detail: `Précision des secondes de 0 à 6. ${arrays}` }
  }
  return { example: '[]', detail: arrays }
})
const options = computed(() => [...new Set([
  ...props.items.map(type => type.replace(/(?:\[\])+$/, '')),
  ...(selectedType.value ? [selectedType.value] : []),
])])

function selectType(type: string) {
  if (type === selectedType.value) return
  selectedType.value = type
  modifiers.value = ''
  lastWritten = type
  value.value = type
  emit('dirty')
}
function setParameters(parameters: string | number) {
  modifiers.value = String(parameters)
  const text = modifiers.value.trim()
  const arrays = text.match(/(?:\[\])+$/)?.[0] ?? ''
  const rawParameters = text.slice(0, text.length - arrays.length).trim()
  // Accepter aussi l'ancienne saisie sans parenthèses : 6,2 ou 6,2[].
  const parametersSql = rawParameters && !rawParameters.startsWith('(') ? `(${rawParameters})` : rawParameters
  const temporal = selectedType.value.match(/^((?:TIME|TIMESTAMP))( WITH(?:OUT)? TIME ZONE)$/i)
  lastWritten = temporal
    ? `${temporal[1]}${parametersSql}${temporal[2]}${arrays}`
    : `${selectedType.value}${parametersSql}${arrays}`
  value.value = lastWritten
  emit('dirty')
}
</script>

<template>
  <div class="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] items-end gap-2">
    <UFormField label="Type PostgreSQL Silver" required class="min-w-0" :class="{ 'col-span-2': !supportsModifiers }">
      <USelectMenu :model-value="selectedType" :items="options" :disabled="disabled" class="w-full" @update:model-value="selectType" />
    </UFormField>
    <UFormField v-if="supportsModifiers" label="Paramètres" class="min-w-0">
      <template #label>
        <span class="inline-flex items-center gap-1">
          Paramètres
          <UTooltip :text="parameterHint.detail">
            <UButton icon="i-lucide-circle-help" aria-label="Aide sur les paramètres PostgreSQL Silver" color="neutral" variant="ghost" size="xs" class="p-0.5" />
          </UTooltip>
        </span>
      </template>
      <UInput :model-value="modifiers" :placeholder="parameterHint.example" :disabled="disabled || !selectedType" aria-label="Paramètres PostgreSQL Silver" class="w-full" @update:model-value="setParameters" />
    </UFormField>
    <p v-if="supportsModifiers && modifiers" class="col-span-2 break-all font-mono text-xs text-muted">{{ value }}</p>
  </div>
</template>
