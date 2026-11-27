export function useApiBase() {
  const config = useRuntimeConfig()
  return import.meta.server ? config.apiBase : config.public.apiBase
}
