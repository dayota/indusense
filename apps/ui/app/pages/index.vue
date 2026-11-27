<script setup lang="ts">
import type { TableColumn } from '@nuxt/ui'
import type { Model } from '~/types/workflow'

const baseURL = useApiBase()
const { data: models, error: modelsError, refresh: refreshModels } = await useFetch<Model[]>('/models', { baseURL, default: () => [] })
const { data: contracts } = await useFetch<string[]>('/contracts', { baseURL, default: () => [] })
const { data: health, error: healthError, refresh: refreshHealth } = await useFetch<{ status: string }>('/health', { baseURL })
const stats = computed(() => [
  { label: 'Modèles', value: models.value.length, description: 'Projets de préparation', icon: 'i-lucide-boxes' },
  { label: 'Versions de modèle', value: models.value.reduce((sum, model) => sum + model.versions.length, 0), description: 'États conservés dans le catalogue', icon: 'i-lucide-git-branch' },
  { label: 'Contrats CSV', value: contracts.value.length, description: 'Schémas disponibles à l’import', icon: 'i-lucide-file-check-2' },
  { label: 'Préparation', value: 'Bronze → Silver', description: 'Sources, contrats et résolution des erreurs', icon: 'i-lucide-database' },
])
const columns: TableColumn<Model>[] = [
  { accessorKey: 'name', header: 'Modèle' },
  { accessorKey: 'versions', header: 'Versions' },
  { id: 'status', header: 'Statut de la dernière version' },
  { id: 'actions', header: '' },
]
async function refresh() { await Promise.all([refreshModels(), refreshHealth()]) }
useHead({ title: 'Vue d’ensemble — InduSense' })
</script>

<template>
  <UDashboardPanel id="overview" role="main">
    <template #header>
      <UDashboardNavbar title="Vue d’ensemble">
        <template #leading><UDashboardSidebarCollapse /></template>
        <template #right><UButton icon="i-lucide-plus" to="/modeles?nouveau=1" label="Nouveau modèle" /></template>
      </UDashboardNavbar>
      <UDashboardToolbar>
        <template #left><UBreadcrumb :items="[{ label: 'Préparation des données', icon: 'i-lucide-layers' }, { label: 'Vue d’ensemble' }]" /></template>
        <template #right><UButton color="neutral" variant="ghost" icon="i-lucide-refresh-cw" label="Actualiser" @click="refresh" /></template>
      </UDashboardToolbar>
    </template>
    <template #body>
      <div class="space-y-1">
        <h1 class="text-2xl font-semibold tracking-tight text-highlighted">Un espace pour préparer tes données</h1>
        <p class="text-sm text-muted">Regroupe les sources de tes modèles et conserve chaque étape de leur préparation.</p>
      </div>
      <UAlert v-if="modelsError" color="error" variant="subtle" icon="i-lucide-circle-alert" title="Catalogue indisponible" description="Vérifie la disponibilité de l’API et les migrations." />
      <div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <UCard v-for="stat in stats" :key="stat.label">
          <div class="flex items-center justify-between gap-2"><p class="text-sm font-medium text-muted">{{ stat.label }}</p><UIcon :name="stat.icon" class="size-5 text-primary" /></div>
          <p class="mt-3 text-3xl font-semibold tracking-tight text-highlighted">{{ stat.value }}</p>
          <p class="mt-2 text-xs text-muted">{{ stat.description }}</p>
        </UCard>
      </div>
      <UCard :ui="{ body: 'p-0 sm:p-0' }">
        <template #header>
          <div class="flex items-center justify-between gap-3">
            <div><h2 class="font-semibold text-highlighted">Tes modèles</h2><p class="mt-1 text-sm text-muted">Retrouve les datasets et les versions de chaque projet.</p></div>
            <UButton to="/modeles" color="neutral" variant="outline" label="Ouvrir l’espace" trailing-icon="i-lucide-arrow-right" />
          </div>
        </template>
        <ClientOnly v-if="models.length">
        <UTable :data="models" :columns="columns">
          <template #name-cell="{ row }"><p class="font-medium text-highlighted">{{ row.original.name }}</p><p class="max-w-md truncate text-xs text-muted">{{ row.original.description }}</p></template>
          <template #versions-cell="{ row }"><UBadge color="neutral" variant="subtle">{{ row.original.versions.length }}</UBadge></template>
          <template #status-cell="{ row }"><ModelVersionStatusBadge v-if="row.original.versions[0]?.status" :status="row.original.versions[0].status" /></template>
          <template #actions-cell="{ row }"><UButton :to="`/modeles?modele=${row.original.id}`" color="neutral" variant="ghost" label="Ouvrir" trailing-icon="i-lucide-arrow-up-right" /></template>
        </UTable>
        <template #fallback><USkeleton class="m-5 h-28" /></template>
        </ClientOnly>
        <UEmpty v-else icon="i-lucide-boxes" title="Crée ton premier modèle" description="Commence par un modèle, puis téléverse les datasets complets qui lui sont associés." class="py-12">
          <template #actions><UButton to="/modeles?nouveau=1" icon="i-lucide-plus" label="Nouveau modèle" /></template>
        </UEmpty>
      </UCard>
      <div class="grid gap-4 lg:grid-cols-3">
        <UCard class="border-primary/40">
          <div class="flex items-center justify-between"><UIcon name="i-lucide-database" class="size-6 text-primary" /><UBadge variant="subtle">Disponible</UBadge></div>
          <h2 class="mt-4 font-semibold text-highlighted">01 · Bronze</h2>
          <p class="mt-2 text-sm leading-6 text-muted">Téléversement, cartes d’identité et snapshots versionnés. Les sources brutes restent intactes.</p>
          <UButton to="/modeles" variant="link" label="Préparer un dataset" trailing-icon="i-lucide-arrow-right" class="mt-3 px-0" />
        </UCard>
        <UCard>
          <div class="flex items-center justify-between"><UIcon name="i-lucide-list-filter" class="size-6 text-primary" /><UBadge variant="subtle">Disponible</UBadge></div>
          <h2 class="mt-4 font-semibold text-highlighted">02 · Silver</h2>
          <p class="mt-2 text-sm leading-6 text-muted">Contrats versionnés, typage et empreinte des sources. Corrige ou écarte les lignes en erreur dans la table tampon.</p>
          <UButton to="/modeles" variant="link" label="Préparer en silver" trailing-icon="i-lucide-arrow-right" class="mt-3 px-0" />
        </UCard>
        <UCard>
          <div class="flex items-center justify-between"><UIcon name="i-lucide-sparkles" class="size-6 text-muted" /><UBadge color="neutral" variant="subtle">À définir</UBadge></div>
          <h2 class="mt-4 font-semibold text-highlighted">03 · Gold</h2>
          <p class="mt-2 text-sm leading-6 text-muted">Construction des datasets d’entraînement, variables et cibles, à partir des données préparées.</p>
        </UCard>
      </div>
      <div class="flex flex-wrap items-center justify-between gap-2 border-t border-default pt-4 text-xs text-muted">
        <span>API : {{ !healthError && health?.status === 'ok' ? 'disponible' : 'indisponible' }}</span>
        <span>PostgreSQL · Bronze / Silver / Gold</span>
      </div>
    </template>
  </UDashboardPanel>
</template>
