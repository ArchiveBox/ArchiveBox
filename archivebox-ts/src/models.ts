/**
 * TypeScript models matching ArchiveBox database schema
 */

export type SnapshotStatus = 'queued' | 'started' | 'sealed';
export type ArchiveResultStatus = 'queued' | 'started' | 'backoff' | 'succeeded' | 'failed' | 'skipped';

export type ExtractorName =
  | '2captcha'
  | 'puppeteer'
  | 'downloads'
  | 'images'
  | 'infiniscroll'
  | 'favicon'
  | 'title'
  | 'headers'
  | 'screenshot'
  | 'pdf'
  | 'dom'
  | 'htmltotext'
  | 'readability'
  | 'singlefile'
  | 'wget'
  | 'git'
  | 'media'
  | 'archive_org'
  | 'outlinks';

/**
 * Snapshot represents a single URL being archived
 */
export interface Snapshot {
  id: string;                    // UUID primary key
  abid: string;                  // ABID identifier (snp_...)
  url: string;                   // The URL being archived (unique)
  timestamp: string;             // Unix timestamp string (unique)
  title: string | null;          // Page title
  created_at: string;            // ISO datetime
  bookmarked_at: string;         // ISO datetime
  downloaded_at: string | null;  // ISO datetime when archiving completed
  modified_at: string;           // ISO datetime
  status: SnapshotStatus;        // Current status
  retry_at: string;              // ISO datetime for retry logic
  config: Record<string, any>;   // JSON configuration
  notes: string;                 // Extra notes
  output_dir: string | null;     // Path to output directory
}

/**
 * ArchiveResult represents the result of running one extractor on one Snapshot
 */
export interface ArchiveResult {
  id: string;                    // UUID primary key
  abid: string;                  // ABID identifier (res_...)
  snapshot_id: string;           // Foreign key to Snapshot
  extractor: ExtractorName;      // Name of the extractor
  status: ArchiveResultStatus;   // Current status
  created_at: string;            // ISO datetime
  modified_at: string;           // ISO datetime
  start_ts: string | null;       // ISO datetime when extraction started
  end_ts: string | null;         // ISO datetime when extraction ended
  cmd: string[] | null;          // Command that was executed
  pwd: string | null;            // Working directory
  cmd_version: string | null;    // Version of the binary used
  output: string | null;         // Main output file path or result
  retry_at: string;              // ISO datetime for retry logic
  config: Record<string, any>;   // JSON configuration
  notes: string;                 // Extra notes
}

/**
 * Simplified snapshot for creation
 */
export interface CreateSnapshotInput {
  url: string;
  title?: string | null;
  bookmarked_at?: string;
  config?: Record<string, any>;
  notes?: string;
}

/**
 * Simplified archive result for creation
 */
export interface CreateArchiveResultInput {
  snapshot_id: string;
  extractor: ExtractorName;
  config?: Record<string, any>;
  notes?: string;
}
