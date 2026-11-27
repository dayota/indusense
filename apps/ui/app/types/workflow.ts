export const MODEL_VERSION_STATUSES = ['ingestion-bronze', 'ingestion-silver', 'ingestion-gold', 'training', 'challenger', 'champion'] as const
export type ModelVersionStatus = typeof MODEL_VERSION_STATUSES[number]
export interface ModelVersion { id: string; model_id: string; number: number; status: ModelVersionStatus }
export interface Model { id: string; name: string; description: string; versions: ModelVersion[] }
export interface TableSummary {
  name: string; rows: number; cols: number; duplicate_rows: number
  columns: { name: string; type: string }[]
}
export interface Summary { rows: number; tables: TableSummary[]; duplicate_rows: number; notes: string[] }
export interface Dataset {
  id: string; name: string; snapshot_id: string; number: number; filename: string
  summary: Summary; sha256: string; created_at: string
}
export interface Snapshot {
  id: string; number: number; filename: string; summary: Summary; sha256: string; created_at: string
}
export interface HistoryEntry {
  id: number; action: string; created_at: string; dataset_version_id: string | null
  details: { filename?: string; reason?: string; number?: number; name?: string; from_status?: ModelVersionStatus; to_status?: ModelVersionStatus; table?: string; revision?: number; row_number?: number; valid_rows?: number; pending_rows?: number; decision?: string; stage?: 'bronze' | 'silver'; database?: string }
}
export interface VersionDetail extends ModelVersion {
  read_only?: boolean
  datasets: Dataset[]; history: HistoryEntry[]
  preparation?: { state: 'draft' | 'created' | 'complete'; database_name: string | null; files: number; rows: number } | null
}
export interface UploadResult { filename: string; status: 'created' | 'reused' | 'duplicate'; number: number; snapshot_id: string; summary: Summary }
