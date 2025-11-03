#!/usr/bin/env node

/**
 * ArchiveBox TypeScript - Main CLI
 */

import { Command } from 'commander';
import * as path from 'path';
import * as fs from 'fs';
import { ArchiveDatabase } from './db';
import { ExtractorManager } from './extractors';
import type { ExtractorName } from './models';

const program = new Command();

// Default paths
const DEFAULT_DATA_DIR = path.join(process.cwd(), 'data');
const DEFAULT_DB_PATH = path.join(DEFAULT_DATA_DIR, 'index.sqlite3');
const DEFAULT_ARCHIVE_DIR = path.join(DEFAULT_DATA_DIR, 'archive');
const EXTRACTORS_DIR = path.join(__dirname, '..', 'extractors');

// Helper to ensure data directory exists
function ensureDataDir(dataDir: string): void {
  if (!fs.existsSync(dataDir)) {
    fs.mkdirSync(dataDir, { recursive: true });
  }
}

// Helper to get snapshot output directory
function getSnapshotOutputDir(archiveDir: string, snapshotId: string, url: string): string {
  const urlObj = new URL(url);
  const domain = urlObj.hostname;
  const timestamp = Date.now().toString();

  // Create directory structure: archive/<timestamp>_<domain>
  const dirName = `${timestamp}_${domain}`;
  const outputDir = path.join(archiveDir, dirName);

  return outputDir;
}

program
  .name('archivebox-ts')
  .description('TypeScript-based version of ArchiveBox with simplified architecture')
  .version('0.1.0');

// Initialize command
program
  .command('init')
  .description('Initialize ArchiveBox data directory and database')
  .option('-d, --data-dir <path>', 'Data directory path', DEFAULT_DATA_DIR)
  .action((options) => {
    const dataDir = options.dataDir;
    const dbPath = path.join(dataDir, 'index.sqlite3');
    const archiveDir = path.join(dataDir, 'archive');

    console.log('Initializing ArchiveBox...');
    console.log(`Data directory: ${dataDir}`);
    console.log(`Database: ${dbPath}`);
    console.log(`Archive directory: ${archiveDir}`);

    ensureDataDir(dataDir);
    ensureDataDir(archiveDir);

    const db = new ArchiveDatabase(dbPath);
    db.close();

    console.log('✓ Initialization complete!');
  });

// Add command
program
  .command('add')
  .description('Add a URL to archive')
  .argument('<url>', 'URL to archive')
  .option('-d, --data-dir <path>', 'Data directory path', DEFAULT_DATA_DIR)
  .option('-e, --extractors <names>', 'Comma-separated list of extractors to run (default: all)')
  .option('--title <title>', 'Page title')
  .action(async (url, options) => {
    const dataDir = options.dataDir;
    const dbPath = path.join(dataDir, 'index.sqlite3');
    const archiveDir = path.join(dataDir, 'archive');

    ensureDataDir(dataDir);
    ensureDataDir(archiveDir);

    const db = new ArchiveDatabase(dbPath);
    const extractorManager = new ExtractorManager(EXTRACTORS_DIR);

    try {
      console.log(`Adding URL: ${url}`);

      // Check if URL already exists
      let snapshot = db.getSnapshotByUrl(url);
      if (snapshot) {
        console.log(`URL already exists with ID: ${snapshot.id}`);
      } else {
        // Create new snapshot
        snapshot = db.createSnapshot({
          url,
          title: options.title,
        });
        console.log(`✓ Created snapshot: ${snapshot.id}`);
      }

      // Determine which extractors to run
      const availableExtractors = extractorManager.getAvailableExtractors();
      let extractorsToRun: string[];

      if (options.extractors) {
        extractorsToRun = options.extractors.split(',').map((e: string) => e.trim());
        // Validate extractors
        for (const extractor of extractorsToRun) {
          if (!extractorManager.hasExtractor(extractor)) {
            console.warn(`Warning: Extractor not found: ${extractor}`);
          }
        }
      } else {
        extractorsToRun = availableExtractors;
      }

      if (extractorsToRun.length === 0) {
        console.log('No extractors available. Place extractor executables in the extractors/ directory.');
        db.close();
        return;
      }

      console.log(`Will run ${extractorsToRun.length} extractors in serial order`);

      // Update snapshot status
      db.updateSnapshotStatus(snapshot.id, 'started');

      // Create output directory
      const outputDir = getSnapshotOutputDir(archiveDir, snapshot.id, url);
      fs.mkdirSync(outputDir, { recursive: true });
      db.setSnapshotOutputDir(snapshot.id, outputDir);

      console.log(`Output directory: ${outputDir}\n`);

      // Create archive results for each extractor
      const archiveResults = new Map<string, string>();
      for (const extractor of extractorsToRun) {
        if (extractorManager.hasExtractor(extractor)) {
          const result = db.createArchiveResult({
            snapshot_id: snapshot.id,
            extractor: extractor as ExtractorName,
          });
          archiveResults.set(extractor, result.id);
        }
      }

      // Run extractors serially
      const results = await extractorManager.runExtractorsSerial(
        extractorsToRun,
        url,
        outputDir,
        {} // Environment variables can be passed here
      );

      console.log('\n--- Extractor Results ---\n');

      // Update archive results
      for (const [extractorName, result] of results.entries()) {
        const resultId = archiveResults.get(extractorName);
        if (resultId) {
          db.updateArchiveResult(resultId, {
            status: result.success ? 'succeeded' : 'failed',
            start_ts: result.start_ts,
            end_ts: result.end_ts,
            cmd: result.cmd,
            pwd: result.pwd,
            output: result.output,
            notes: result.error || '',
          });

          const status = result.success ? '✓' : '✗';
          console.log(`  ${status} ${extractorName}: ${result.success ? 'succeeded' : 'failed'}`);
          if (result.error && !result.success) {
            // Only show errors for failed extractors (not stderr from successful ones)
            const errorLines = result.error.split('\n').slice(0, 3); // First 3 lines
            console.log(`    ${errorLines.join('\n    ')}`);
          }
        }
      }

      // Update snapshot status
      db.updateSnapshotStatus(snapshot.id, 'sealed', new Date().toISOString());

      console.log(`✓ Archiving complete!`);
      console.log(`Snapshot ID: ${snapshot.id}`);
      console.log(`Output: ${outputDir}`);

    } catch (err) {
      console.error('Error:', err instanceof Error ? err.message : err);
      process.exit(1);
    } finally {
      db.close();
    }
  });

// List command
program
  .command('list')
  .description('List all archived snapshots')
  .option('-d, --data-dir <path>', 'Data directory path', DEFAULT_DATA_DIR)
  .option('-l, --limit <number>', 'Number of snapshots to show', '20')
  .option('-o, --offset <number>', 'Offset for pagination', '0')
  .action((options) => {
    const dataDir = options.dataDir;
    const dbPath = path.join(dataDir, 'index.sqlite3');

    const db = new ArchiveDatabase(dbPath);

    try {
      const snapshots = db.getAllSnapshots(
        parseInt(options.limit),
        parseInt(options.offset)
      );

      if (snapshots.length === 0) {
        console.log('No snapshots found.');
        return;
      }

      console.log(`\nFound ${snapshots.length} snapshot(s):\n`);

      for (const snapshot of snapshots) {
        console.log(`ID: ${snapshot.id}`);
        console.log(`URL: ${snapshot.url}`);
        console.log(`Title: ${snapshot.title || '(none)'}`);
        console.log(`Status: ${snapshot.status}`);
        console.log(`Created: ${snapshot.created_at}`);
        console.log(`Output: ${snapshot.output_dir || '(none)'}`);
        console.log('---');
      }
    } catch (err) {
      console.error('Error:', err instanceof Error ? err.message : err);
      process.exit(1);
    } finally {
      db.close();
    }
  });

// Status command
program
  .command('status')
  .description('Show status of a snapshot')
  .argument('<id>', 'Snapshot ID')
  .option('-d, --data-dir <path>', 'Data directory path', DEFAULT_DATA_DIR)
  .action((id, options) => {
    const dataDir = options.dataDir;
    const dbPath = path.join(dataDir, 'index.sqlite3');

    const db = new ArchiveDatabase(dbPath);

    try {
      const snapshot = db.getSnapshot(id);
      if (!snapshot) {
        console.error(`Snapshot not found: ${id}`);
        process.exit(1);
      }

      console.log(`\nSnapshot: ${snapshot.id}`);
      console.log(`URL: ${snapshot.url}`);
      console.log(`Title: ${snapshot.title || '(none)'}`);
      console.log(`Status: ${snapshot.status}`);
      console.log(`Created: ${snapshot.created_at}`);
      console.log(`Downloaded: ${snapshot.downloaded_at || '(in progress)'}`);
      console.log(`Output: ${snapshot.output_dir || '(none)'}`);

      const results = db.getArchiveResults(snapshot.id);
      if (results.length > 0) {
        console.log(`\nArchive Results (${results.length}):`);
        for (const result of results) {
          const statusIcon = result.status === 'succeeded' ? '✓' :
                           result.status === 'failed' ? '✗' :
                           result.status === 'started' ? '⋯' : '○';
          console.log(`  ${statusIcon} ${result.extractor}: ${result.status}`);
          if (result.output) {
            console.log(`    Output: ${result.output}`);
          }
          if (result.notes) {
            console.log(`    Notes: ${result.notes}`);
          }
        }
      }
    } catch (err) {
      console.error('Error:', err instanceof Error ? err.message : err);
      process.exit(1);
    } finally {
      db.close();
    }
  });

// Extractors command
program
  .command('extractors')
  .description('List available extractors')
  .action(() => {
    const extractorManager = new ExtractorManager(EXTRACTORS_DIR);
    const extractors = extractorManager.getAvailableExtractors();

    if (extractors.length === 0) {
      console.log('No extractors found.');
      console.log(`Place executable files in: ${EXTRACTORS_DIR}`);
      return;
    }

    console.log(`\nAvailable extractors (${extractors.length}):\n`);
    for (const extractor of extractors) {
      console.log(`  - ${extractor}`);
    }
    console.log();
  });

program.parse();
