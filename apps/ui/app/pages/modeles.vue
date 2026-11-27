<script setup lang="ts">
const workspace = ref<{ openNewModel: () => void; openJournal: () => void; openSection: (section: 'contracts' | 'quarantine') => void } | null>(null)
useHead({ title: 'Modèles et datasets — InduSense' })
</script>

<template>
  <UDashboardPanel id="models" role="main" :ui="{ body: 'min-h-0 overflow-hidden' }">
    <template #header>
      <UDashboardNavbar title="Modèles et datasets">
        <template #leading><UDashboardSidebarCollapse /></template>
        <template #right><UButton icon="i-lucide-plus" label="Nouveau modèle" @click="workspace?.openNewModel()" /></template>
      </UDashboardNavbar>
      <UDashboardToolbar>
        <template #left><UBreadcrumb :items="[{ label: 'Préparation des données', icon: 'i-lucide-layers' }]" /></template>
        <template #right>
          <UButton color="neutral" variant="outline" icon="i-lucide-history" label="Journal" @click="workspace?.openJournal()" />
          <UButton color="neutral" variant="outline" icon="i-lucide-list-checks" label="Rapports et anomalies" @click="workspace?.openSection('quarantine')" />
        </template>
      </UDashboardToolbar>
    </template>
    <template #body><BronzeWorkspace ref="workspace" /></template>
  </UDashboardPanel>
</template>
