<script setup lang="ts">
import { fr } from '@nuxt/ui/locale'
useHead({ htmlAttrs: { lang: 'fr' } })
</script>

<template>
  <UApp :locale="fr">
    <NuxtLoadingIndicator color="var(--ui-primary)" />
    <NuxtLayout><NuxtPage /></NuxtLayout>
  </UApp>
</template>
