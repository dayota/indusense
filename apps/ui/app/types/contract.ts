export interface BronzeContractConfig {
  version: string; kind: string; timezone: string; max_cast_error_ratio?: number
  source: { path: string; format: string; encoding: string; table?: string; field_delimiter?: string; row_delimiter?: string; has_header?: boolean }
  target: { schema: string; table: string; natural_key: string[] }
  columns: { source_name: string; target_name: string; type: string; silver_type: string; nullable?: boolean; description?: string; unit?: string | null }[]
  derived_columns?: { target_name: string; operation: string; operate_on_columns: string[]; silver_type: string; parameters?: Record<string, unknown> }[]
}
export interface ContractEditor {
  table: string | null; path: string; existing: boolean; yaml: string | null; config: BronzeContractConfig; editing?: boolean
}
export interface ContractEditorFile { id: string; filename: string; revision: number; editors: ContractEditor[]; saved: boolean }
export interface ContractEditorResponse { files: ContractEditorFile[]; column_types: string[]; operations: string[]; timezones: string[]; silver_types: Record<string, string[]>; postgres_types: string[] }
