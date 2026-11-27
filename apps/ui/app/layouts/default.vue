<!-- Adapté du template MIT nuxt-ui-templates/dashboard. Voir LICENSE.nuxt-dashboard. -->
<script setup lang="ts">
import type { NavigationMenuItem } from '@nuxt/ui'

const open = ref(false)
const links = [
  { label: 'Vue d’ensemble', icon: 'i-lucide-layout-dashboard', to: '/', exact: true, onSelect: () => { open.value = false } },
  { label: 'Modèles et datasets', icon: 'i-lucide-boxes', to: '/modeles', onSelect: () => { open.value = false } },
] satisfies NavigationMenuItem[]
const resources = [
  { label: 'Documentation API', icon: 'i-lucide-book-open', to: '/api/docs', target: '_blank' },
  { label: 'Monitoring Grafana', icon: 'i-lucide-activity', to: 'http://grafana.indusense.localhost', target: '_blank' },
] satisfies NavigationMenuItem[]
const groups = computed(() => [{ id: 'navigation', label: 'Navigation', items: links }])
</script>

<template>
  <UDashboardGroup unit="rem">
    <UDashboardSidebar id="indusense" v-model:open="open" collapsible resizable :menu="{ transition: false }" class="bg-elevated/25" :ui="{ footer: 'lg:border-t lg:border-default' }">
      <template #header="{ collapsed }">
        <NuxtLink to="/" class="flex min-w-0 items-center gap-2.5 py-2" aria-label="InduSense — accueil">
          <div class="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary text-inverted"><UIcon name="i-lucide-layers" class="size-5" /></div>
          <span v-if="!collapsed" class="text-lg font-semibold tracking-tight">InduSense</span>
        </NuxtLink>
      </template>
      <template #default="{ collapsed }">
        <UNavigationMenu :collapsed="collapsed" :items="links" orientation="vertical" tooltip popover />
        <div class="mt-auto pt-7">
          <div v-if="!collapsed" class="px-2 text-xs font-medium uppercase tracking-wider text-muted">Ressources</div>
          <UNavigationMenu :collapsed="collapsed" :items="resources" orientation="vertical" tooltip class="mt-1" />
        </div>
      </template>
      <template #footer="{ collapsed }">
        <div class="flex w-full items-center gap-2" :class="collapsed ? 'justify-center' : 'justify-between'">
          <div v-if="!collapsed" class="flex items-center gap-2 text-xs text-muted"><span class="size-2 rounded-full bg-primary" />Environnement local</div>
          <UColorModeButton />
        </div>
      </template>
    </UDashboardSidebar>
    <UDashboardSearch :groups="groups" :transition="false" placeholder="Rechercher une page…" />
    <slot />
  </UDashboardGroup>
</template>
