/**
 * Database layer using SQLite with schema matching ArchiveBox
 */

import Database from 'better-sqlite3';
import { randomUUID } from 'crypto';
import { nanoid } from 'nanoid';
import * as path from 'path';
import * as fs from 'fs';
import type {
  Snapshot,
  ArchiveResult,
  CreateSnapshotInput,
  CreateArchiveResultInput,
  SnapshotStatus,
  ArchiveResultStatus,
} from './models';

export class ArchiveDatabase {
  private db: Database.Database;

  constructor(dbPath: string) {
    // Ensure the directory exists
    const dir = path.dirname(dbPath);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }

    this.db = new Database(dbPath);
    this.db.pragma('journal_mode = WAL');
    this.initSchema();
  }

  private initSchema(): void {
    // Create snapshots table (simplified from ArchiveBox schema)
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS snapshots (
        id TEXT PRIMARY KEY,
        abid TEXT NOT NULL UNIQUE,
        url TEXT NOT NULL UNIQUE,
        timestamp TEXT NOT NULL UNIQUE,
        title TEXT,
        created_at TEXT NOT NULL,
        bookmarked_at TEXT NOT NULL,
        downloaded_at TEXT,
        modified_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'queued',
        retry_at TEXT NOT NULL,
        config TEXT NOT NULL DEFAULT '{}',
        notes TEXT NOT NULL DEFAULT '',
        output_dir TEXT
      );

      CREATE INDEX IF NOT EXISTS idx_snapshots_url ON snapshots(url);
      CREATE INDEX IF NOT EXISTS idx_snapshots_timestamp ON snapshots(timestamp);
      CREATE INDEX IF NOT EXISTS idx_snapshots_created_at ON snapshots(created_at);
      CREATE INDEX IF NOT EXISTS idx_snapshots_status ON snapshots(status);
    `);

    // Create archive_results table (simplified from ArchiveBox schema)
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS archive_results (
        id TEXT PRIMARY KEY,
        abid TEXT NOT NULL UNIQUE,
        snapshot_id TEXT NOT NULL,
        extractor TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'queued',
        created_at TEXT NOT NULL,
        modified_at TEXT NOT NULL,
        start_ts TEXT,
        end_ts TEXT,
        cmd TEXT,
        pwd TEXT,
        cmd_version TEXT,
        output TEXT,
        retry_at TEXT NOT NULL,
        config TEXT NOT NULL DEFAULT '{}',
        notes TEXT NOT NULL DEFAULT '',
        FOREIGN KEY (snapshot_id) REFERENCES snapshots(id) ON DELETE CASCADE
      );

      CREATE INDEX IF NOT EXISTS idx_archive_results_snapshot_id ON archive_results(snapshot_id);
      CREATE INDEX IF NOT EXISTS idx_archive_results_extractor ON archive_results(extractor);
      CREATE INDEX IF NOT EXISTS idx_archive_results_status ON archive_results(status);
      CREATE INDEX IF NOT EXISTS idx_archive_results_created_at ON archive_results(created_at);
    `);
  }

  /**
   * Generate ABID (Archivable Bytes Identifier) similar to ArchiveBox
   */
  private generateABID(prefix: string, url: string): string {
    const randomPart = nanoid(8);
    return `${prefix}${randomPart}`;
  }

  /**
   * Create a new snapshot
   */
  createSnapshot(input: CreateSnapshotInput): Snapshot {
    const now = new Date().toISOString();
    const timestamp = Date.now().toString();
    const id = randomUUID();
    const abid = this.generateABID('snp_', input.url);

    const snapshot: Snapshot = {
      id,
      abid,
      url: input.url,
      timestamp,
      title: input.title || null,
      created_at: now,
      bookmarked_at: input.bookmarked_at || now,
      downloaded_at: null,
      modified_at: now,
      status: 'queued',
      retry_at: now,
      config: JSON.stringify(input.config || {}),
      notes: input.notes || '',
      output_dir: null,
    } as any;

    const stmt = this.db.prepare(`
      INSERT INTO snapshots (
        id, abid, url, timestamp, title, created_at, bookmarked_at,
        downloaded_at, modified_at, status, retry_at, config, notes, output_dir
      ) VALUES (
        @id, @abid, @url, @timestamp, @title, @created_at, @bookmarked_at,
        @downloaded_at, @modified_at, @status, @retry_at, @config, @notes, @output_dir
      )
    `);

    stmt.run(snapshot);
    return this.getSnapshot(id)!;
  }

  /**
   * Get a snapshot by ID
   */
  getSnapshot(id: string): Snapshot | null {
    const stmt = this.db.prepare('SELECT * FROM snapshots WHERE id = ?');
    const row = stmt.get(id) as any;
    if (!row) return null;

    return {
      ...row,
      config: JSON.parse(row.config || '{}'),
    } as Snapshot;
  }

  /**
   * Get a snapshot by URL
   */
  getSnapshotByUrl(url: string): Snapshot | null {
    const stmt = this.db.prepare('SELECT * FROM snapshots WHERE url = ?');
    const row = stmt.get(url) as any;
    if (!row) return null;

    return {
      ...row,
      config: JSON.parse(row.config || '{}'),
    } as Snapshot;
  }

  /**
   * Get all snapshots
   */
  getAllSnapshots(limit: number = 100, offset: number = 0): Snapshot[] {
    const stmt = this.db.prepare(
      'SELECT * FROM snapshots ORDER BY created_at DESC LIMIT ? OFFSET ?'
    );
    const rows = stmt.all(limit, offset) as any[];

    return rows.map(row => ({
      ...row,
      config: JSON.parse(row.config || '{}'),
    })) as Snapshot[];
  }

  /**
   * Update snapshot status
   */
  updateSnapshotStatus(id: string, status: SnapshotStatus, downloaded_at?: string): void {
    const modified_at = new Date().toISOString();

    if (downloaded_at) {
      const stmt = this.db.prepare(`
        UPDATE snapshots
        SET status = ?, modified_at = ?, downloaded_at = ?
        WHERE id = ?
      `);
      stmt.run(status, modified_at, downloaded_at, id);
    } else {
      const stmt = this.db.prepare(`
        UPDATE snapshots
        SET status = ?, modified_at = ?
        WHERE id = ?
      `);
      stmt.run(status, modified_at, id);
    }
  }

  /**
   * Set snapshot output directory
   */
  setSnapshotOutputDir(id: string, output_dir: string): void {
    const stmt = this.db.prepare(`
      UPDATE snapshots SET output_dir = ?, modified_at = ? WHERE id = ?
    `);
    stmt.run(output_dir, new Date().toISOString(), id);
  }

  /**
   * Create a new archive result
   */
  createArchiveResult(input: CreateArchiveResultInput): ArchiveResult {
    const now = new Date().toISOString();
    const id = randomUUID();
    const snapshot = this.getSnapshot(input.snapshot_id);
    if (!snapshot) {
      throw new Error(`Snapshot ${input.snapshot_id} not found`);
    }

    const abid = this.generateABID('res_', snapshot.url);

    const result: ArchiveResult = {
      id,
      abid,
      snapshot_id: input.snapshot_id,
      extractor: input.extractor,
      status: 'queued',
      created_at: now,
      modified_at: now,
      start_ts: null,
      end_ts: null,
      cmd: null,
      pwd: null,
      cmd_version: null,
      output: null,
      retry_at: now,
      config: JSON.stringify(input.config || {}),
      notes: input.notes || '',
    } as any;

    const stmt = this.db.prepare(`
      INSERT INTO archive_results (
        id, abid, snapshot_id, extractor, status, created_at, modified_at,
        start_ts, end_ts, cmd, pwd, cmd_version, output, retry_at, config, notes
      ) VALUES (
        @id, @abid, @snapshot_id, @extractor, @status, @created_at, @modified_at,
        @start_ts, @end_ts, @cmd, @pwd, @cmd_version, @output, @retry_at, @config, @notes
      )
    `);

    stmt.run(result);
    return this.getArchiveResult(id)!;
  }

  /**
   * Get an archive result by ID
   */
  getArchiveResult(id: string): ArchiveResult | null {
    const stmt = this.db.prepare('SELECT * FROM archive_results WHERE id = ?');
    const row = stmt.get(id) as any;
    if (!row) return null;

    return {
      ...row,
      cmd: row.cmd ? JSON.parse(row.cmd) : null,
      config: JSON.parse(row.config || '{}'),
    } as ArchiveResult;
  }

  /**
   * Get all archive results for a snapshot
   */
  getArchiveResults(snapshot_id: string): ArchiveResult[] {
    const stmt = this.db.prepare(
      'SELECT * FROM archive_results WHERE snapshot_id = ? ORDER BY created_at ASC'
    );
    const rows = stmt.all(snapshot_id) as any[];

    return rows.map(row => ({
      ...row,
      cmd: row.cmd ? JSON.parse(row.cmd) : null,
      config: JSON.parse(row.config || '{}'),
    })) as ArchiveResult[];
  }

  /**
   * Get archive results by status
   */
  getArchiveResultsByStatus(status: ArchiveResultStatus): ArchiveResult[] {
    const stmt = this.db.prepare(
      'SELECT * FROM archive_results WHERE status = ? ORDER BY created_at ASC'
    );
    const rows = stmt.all(status) as any[];

    return rows.map(row => ({
      ...row,
      cmd: row.cmd ? JSON.parse(row.cmd) : null,
      config: JSON.parse(row.config || '{}'),
    })) as ArchiveResult[];
  }

  /**
   * Update archive result
   */
  updateArchiveResult(
    id: string,
    updates: {
      status?: ArchiveResultStatus;
      start_ts?: string;
      end_ts?: string;
      cmd?: string[];
      pwd?: string;
      cmd_version?: string;
      output?: string;
      notes?: string;
    }
  ): void {
    const fields: string[] = ['modified_at = ?'];
    const values: any[] = [new Date().toISOString()];

    if (updates.status !== undefined) {
      fields.push('status = ?');
      values.push(updates.status);
    }
    if (updates.start_ts !== undefined) {
      fields.push('start_ts = ?');
      values.push(updates.start_ts);
    }
    if (updates.end_ts !== undefined) {
      fields.push('end_ts = ?');
      values.push(updates.end_ts);
    }
    if (updates.cmd !== undefined) {
      fields.push('cmd = ?');
      values.push(JSON.stringify(updates.cmd));
    }
    if (updates.pwd !== undefined) {
      fields.push('pwd = ?');
      values.push(updates.pwd);
    }
    if (updates.cmd_version !== undefined) {
      fields.push('cmd_version = ?');
      values.push(updates.cmd_version);
    }
    if (updates.output !== undefined) {
      fields.push('output = ?');
      values.push(updates.output);
    }
    if (updates.notes !== undefined) {
      fields.push('notes = ?');
      values.push(updates.notes);
    }

    values.push(id);

    const stmt = this.db.prepare(`
      UPDATE archive_results SET ${fields.join(', ')} WHERE id = ?
    `);

    stmt.run(...values);
  }

  /**
   * Close the database connection
   */
  close(): void {
    this.db.close();
  }
}
