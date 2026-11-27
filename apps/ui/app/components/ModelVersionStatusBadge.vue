<script setup lang="ts">
import type { ModelVersionStatus } from '~/types/workflow'

defineProps<{ status: ModelVersionStatus }>()
const colors: Record<ModelVersionStatus, 'neutral' | 'info' | 'warning' | 'primary' | 'success'> = {
  'ingestion-bronze': 'neutral',
  'ingestion-silver': 'info',
  'ingestion-gold': 'warning',
  training: 'primary',
  challenger: 'warning',
  champion: 'success',
}
</script>

<template>
  <UBadge :color="colors[status]" variant="subtle">{{ status }}</UBadge>
</template>
