import type { ModelVersionStatus, Summary } from './workflow'

export interface TechnicalColumn {
  table: string; name: string; source: string; converter: string; type: string
  format?: string | null; pattern?: string | null; nullable: boolean
}
export interface SourceColumn { name: string; spec: { type: string; nullable?: boolean; format?: string; allowed?: unknown[]; min?: number; max?: number } }
export interface PreparationFile {
  sql_choices?: { table: string; mode: 'existing' | 'generate'; contract: string | null }[] | null
  sql_contracts?: { table: string; yaml: string; encoding: string }[]
  id: string; filename: string; dataset_name: string; format: 'csv' | 'sql'; sha256: string
  contract_mode: 'existing' | 'generate'; contract_ref: string | null
  loaded_yaml: string | null; saved_yaml: string | null; revision: number
  summary: (Summary & { identity_path?: string }) | null; report: string | null
  table_specs: Record<string, SourceColumn[]> | null
  types_catalog: { version: number; types: Record<string, { converter: string; format?: string }> } | null
  technical_columns: TechnicalColumn[]
}
export interface BronzeTable { name: string; source: string; filename: string; file_id: string; columns: string[]; rows: number }
export interface BronzePreparation {
  schema_name?: string
  archive_directory?: string | null
  archives?: { id: string; filename: string; path: string; sha256: string; size_bytes: number; created_at: string; active: boolean }[]
  protocol?: number
  migration?: { hash: string; script: string; sql?: string; schema?: string; tables: string[] } | null
  approved_hash?: string | null
  can_validate?: boolean
  batches?: { batch_id: string; source_name: string; target_table: string; status: string; records_read: number; records_inserted: number; records_rejected: number; source_hash: string; config_hash: string; started_at: string; completed_at: string | null; report: Record<string, unknown> | null; dictionary: Record<string, unknown> | null; artifact_path: string | null }[]
  state: 'draft' | 'created' | 'complete'; database_name: string | null; identities_reviewed: boolean
  files: PreparationFile[]; readonly: boolean; status: ModelVersionStatus
  dataset: { pending: number; valid: number; excluded: number; tables: BronzeTable[] } | null
}
export interface BronzeIssue {
  id: string; file_id: string; filename: string; source_table: string; target_table: string; row_number: number
  source: Record<string, unknown>; candidate: Record<string, unknown>
  errors: { column: string; source_column?: string; message: string; sqlstate?: string }[]
  state: 'pending' | 'reintegrated' | 'discarded'; reason: string | null
}
export interface ConverterCatalog { version: number; converters: Record<string, { types: Record<string, { format?: string }> }> }
