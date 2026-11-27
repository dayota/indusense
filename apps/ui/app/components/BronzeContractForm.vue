<script setup lang="ts">
import type { BronzeContractConfig } from '~/types/contract'
const config = defineModel<BronzeContractConfig>({ required: true })
const props = defineProps<{ columnTypes: string[]; operations: string[]; timezones: string[]; silverTypes: Record<string, string[]>; postgresTypes: string[]; sourceFields: boolean; disabled: boolean }>()
const emit = defineEmits<{ dirty: [] }>()
const names = computed(() => config.value.columns.map(column => column.target_name).filter(Boolean))
const sections = [
  { label: 'Général', slot: 'general' as const },
  { label: 'Colonnes sources', slot: 'sources' as const },
  { label: 'Colonnes dérivées à produire en Silver', slot: 'derived' as const },
]
function addDerived() {
  config.value.derived_columns ??= []
  config.value.derived_columns.push({ target_name: '', operation: '', operate_on_columns: [], silver_type: '' })
  emit('dirty')
}
</script>

<template>
  <fieldset class="space-y-5" @input="emit('dirty')" @change="emit('dirty')">
    <UTabs :items="sections" :unmount-on-hide="false" variant="link" class="w-full" :ui="{ list: 'flex-wrap', content: 'pt-4' }" aria-label="Sections du contrat">
      <template #general>
        <div class="space-y-5">
          <div class="flex flex-wrap gap-2"><UBadge color="neutral">{{ config.kind }}</UBadge><UBadge color="neutral">Schéma {{ config.target.schema }}</UBadge><UBadge color="neutral">Version {{ config.version }}</UBadge></div>
          <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <UFormField label="Table cible" required><UInput v-model="config.target.table" :disabled="disabled" maxlength="63" class="w-full" /></UFormField>
            <UFormField label="Clé métier" required><USelect v-model="config.target.natural_key" :items="names" multiple :disabled="disabled" class="w-full" @update:model-value="emit('dirty')" /></UFormField>
            <UFormField label="Timezone" required><USelect v-model="config.timezone" :items="props.timezones" :disabled="disabled" class="w-full" @update:model-value="emit('dirty')" /></UFormField>
          </div>
          <div v-if="sourceFields || config.source.format === 'CSV'" class="grid items-end gap-4 sm:grid-cols-[repeat(3,minmax(0,1fr))_auto]">
            <UFormField v-if="sourceFields" label="Encodage du fichier" required><UInput v-model="config.source.encoding" :disabled="disabled" class="w-full" /></UFormField>
            <UFormField v-if="sourceFields && config.source.format === 'CSV'" label="Séparateur de champs" required><UInput v-model="config.source.field_delimiter" maxlength="1" :disabled="disabled" class="w-full" /></UFormField>
            <UFormField v-if="config.source.format === 'CSV'" label="Fin de ligne" required><USelect v-model="config.source.row_delimiter" :items="[{label:'LF',value:'\n'},{label:'CRLF',value:'\r\n'}]" :disabled="disabled" class="w-full" @update:model-value="emit('dirty')" /></UFormField>
            <UCheckbox v-if="config.source.format === 'CSV'" :model-value="config.source.has_header ?? true" label="has_header" disabled class="shrink-0 pb-2" />
          </div>
          <div class="flex items-end gap-4">
            <UFormField label="Part maximale de lignes en erreur" hint="Entre 0 et 1 ; 0 annule le lot à la première erreur de conversion." class="min-w-0 flex-1"><UInput :model-value="config.max_cast_error_ratio ?? 0" type="number" min="0" max="1" step="0.01" :disabled="disabled" class="w-full" @update:model-value="config.max_cast_error_ratio = Number($event); emit('dirty')" /></UFormField>
          </div>
        </div>
      </template>
      <template #sources>
        <div class="space-y-3">
          <h4 class="font-medium">Colonnes sources</h4>
          <div v-for="(column, index) in config.columns" :key="index" class="space-y-3 rounded border border-default p-3">
            <div class="flex items-center justify-between gap-4">
              <p class="min-w-0 break-all font-mono text-sm">{{ column.source_name }}</p>
              <UCheckbox v-model="column.nullable" :disabled="disabled" label="Valeur nulle autorisée en Silver" class="shrink-0" @update:model-value="emit('dirty')" />
            </div>
            <div class="grid items-end gap-3 sm:grid-cols-2 lg:grid-cols-[minmax(0,6fr)_minmax(0,4fr)_minmax(0,4fr)_minmax(0,3fr)_minmax(0,3fr)]">
              <UFormField label="Nom cible" required class="min-w-0"><UInput v-model="column.target_name" :disabled="disabled" maxlength="63" class="w-full" /></UFormField>
              <UFormField label="Type" required class="min-w-0"><USelect v-model="column.type" :items="props.columnTypes" :disabled="disabled" class="w-full" :aria-label="`Type de ${column.source_name}`" @update:model-value="emit('dirty')" /></UFormField>
              <PostgresSilverTypeField v-model="column.silver_type" :items="props.postgresTypes" :disabled="disabled" class="lg:col-span-2 lg:row-span-2 lg:grid-cols-subgrid lg:grid-rows-subgrid lg:self-stretch lg:gap-3" @dirty="emit('dirty')" />
              <UFormField v-if="column.type === 'NUMBER'" label="Unité" required class="min-w-0 lg:col-start-5 lg:row-start-1"><UInput :model-value="column.unit ?? ''" :disabled="disabled" placeholder="CELSIUS, HOUR…" class="w-full" @update:model-value="column.unit = String($event); emit('dirty')" /></UFormField>
            </div>
            <UFormField label="Description"><UInput v-model="column.description" :disabled="disabled" class="w-full" /></UFormField>
          </div>
        </div>
      </template>
      <template #derived>
        <div class="space-y-3">
          <h4 class="font-medium">Colonnes dérivées à produire en Silver</h4>
          <div v-for="(column, index) in config.derived_columns ?? []" :key="index" class="space-y-3 rounded border border-default p-3">
            <div class="grid gap-3 sm:grid-cols-2">
              <UFormField label="Nom cible" required><UInput v-model="column.target_name" :disabled="disabled" maxlength="63" class="w-full" /></UFormField>
              <UFormField label="Opération" required><USelect v-model="column.operation" :items="props.operations" :disabled="disabled" class="w-full" @update:model-value="emit('dirty')" /></UFormField>
              <UFormField label="Colonnes d’entrée" :hint="column.operation === 'MERGE' ? 'Au moins deux colonnes pour MERGE.' : undefined" required><USelect v-model="column.operate_on_columns" :items="names" multiple :disabled="disabled" class="w-full" @update:model-value="emit('dirty')" /></UFormField>
              <PostgresSilverTypeField v-model="column.silver_type" :items="props.postgresTypes" :disabled="disabled" @dirty="emit('dirty')" />
            </div>
            <UButton v-if="!disabled" label="Retirer cette déclaration" color="neutral" variant="ghost" @click="config.derived_columns?.splice(index, 1); emit('dirty')" />
          </div>
          <UButton v-if="!disabled" label="Ajouter une colonne dérivée" color="neutral" variant="outline" @click="addDerived" />
        </div>
      </template>
    </UTabs>
  </fieldset>
</template>
