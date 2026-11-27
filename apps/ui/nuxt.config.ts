export default defineNuxtConfig({
  modules: ['@nuxt/ui'],
  css: ['~/assets/css/main.css'],
  ui: { fonts: false },
  icon: {
    serverBundle: { collections: ['lucide'] },
    localApiEndpoint: '/_icons',
    fallbackToApi: false,
  },
  compatibilityDate: '2026-11-26',
  devtools: { enabled: false },
  runtimeConfig: {
    apiBase: 'http://api:8000/api',
    public: { apiBase: '/api' },
  },
  vite: {
    // Le routeur ESM doit passer par Vite pour remplacer les flags Vue en SSR dev.
    ssr: { noExternal: ['vue-router'] },
    server: {
      allowedHosts: ['indusense.localhost'],
    },
  },
})
