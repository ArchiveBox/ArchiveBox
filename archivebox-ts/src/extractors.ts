/**
 * Extractor orchestration system
 * Discovers and runs standalone extractor executables in serial order
 */

import * as fs from 'fs';
import * as path from 'path';
import { spawn } from 'child_process';
import type { ExtractorName } from './models';

// Predefined order for running extractors
// puppeteer must be first as it launches the browser
// downloads, images, and infiniscroll run early to capture dynamic content
export const EXTRACTOR_ORDER: string[] = [
  'puppeteer',   // Launches Chrome and writes CDP URL to .env
  'downloads',   // Catches file downloads (reloads page with listeners)
  'images',      // Catches all images (reloads page with listeners)
  'infiniscroll', // Scrolls page to load lazy content
  'favicon',     // Downloads favicon (can work independently)
  'title',       // Extracts title using existing Chrome tab
  'headers',     // Extracts headers using existing Chrome tab
  'screenshot',  // Takes screenshot using existing Chrome tab
  'pdf',         // Generates PDF using existing Chrome tab
  'dom',         // Extracts DOM HTML using existing Chrome tab
  'htmltotext',  // Extracts plain text using existing Chrome tab
  'readability', // Extracts article content using existing Chrome tab
  'singlefile',  // Creates single-file archive (may use existing Chrome)
  'wget',        // Downloads with wget (independent)
  'git',         // Clones git repository (independent)
  'media',       // Downloads media with yt-dlp (independent)
  'archive_org', // Submits to Internet Archive (independent)
];

export interface ExtractorInfo {
  name: ExtractorName;
  path: string;
  executable: boolean;
}

export interface ExtractorResult {
  success: boolean;
  output?: string;
  error?: string;
  cmd: string[];
  cmd_version?: string;
  start_ts: string;
  end_ts: string;
  pwd: string;
}

export class ExtractorManager {
  private extractorsDir: string;
  private availableExtractors: Map<string, ExtractorInfo>;

  constructor(extractorsDir: string) {
    this.extractorsDir = extractorsDir;
    this.availableExtractors = new Map();
    this.discoverExtractors();
  }

  /**
   * Discover all available extractors in the extractors directory
   */
  private discoverExtractors(): void {
    if (!fs.existsSync(this.extractorsDir)) {
      console.warn(`Extractors directory not found: ${this.extractorsDir}`);
      return;
    }

    const files = fs.readdirSync(this.extractorsDir);

    for (const file of files) {
      const filePath = path.join(this.extractorsDir, file);
      const stats = fs.statSync(filePath);

      // Skip directories and non-executable files
      if (stats.isDirectory()) continue;

      // Check if file is executable
      try {
        fs.accessSync(filePath, fs.constants.X_OK);
        const name = file;

        this.availableExtractors.set(name, {
          name: name as ExtractorName,
          path: filePath,
          executable: true,
        });

        console.log(`Discovered extractor: ${name}`);
      } catch (err) {
        // File is not executable, skip it
        console.warn(`Skipping non-executable file: ${file}`);
      }
    }
  }

  /**
   * Get list of available extractors in the predefined order
   */
  getAvailableExtractors(): string[] {
    const available = Array.from(this.availableExtractors.keys());
    // Return in predefined order, only including available extractors
    return EXTRACTOR_ORDER.filter(name => available.includes(name));
  }

  /**
   * Check if an extractor is available
   */
  hasExtractor(name: string): boolean {
    return this.availableExtractors.has(name);
  }

  /**
   * Load environment variables from .env file in the output directory
   */
  private loadEnvFile(outputDir: string): Record<string, string> {
    const envPath = path.join(outputDir, '.env');
    const envVars: Record<string, string> = {};

    if (!fs.existsSync(envPath)) {
      return envVars;
    }

    try {
      const content = fs.readFileSync(envPath, 'utf8');
      const lines = content.split('\n');

      for (const line of lines) {
        // Skip empty lines and comments
        if (!line.trim() || line.trim().startsWith('#')) {
          continue;
        }

        // Parse KEY=VALUE format
        const match = line.match(/^([^=]+)=(.*)$/);
        if (match) {
          const key = match[1].trim();
          let value = match[2].trim();

          // Remove quotes if present
          if ((value.startsWith('"') && value.endsWith('"')) ||
              (value.startsWith("'") && value.endsWith("'"))) {
            value = value.slice(1, -1);
          }

          envVars[key] = value;
        }
      }
    } catch (err) {
      console.warn(`Warning: Could not read .env file: ${err}`);
    }

    return envVars;
  }

  /**
   * Create initial .env file in the output directory
   */
  private createEnvFile(outputDir: string, url: string): void {
    const envPath = path.join(outputDir, '.env');
    const timestamp = new Date().toISOString();

    const content = `# ArchiveBox Snapshot Environment
# Created: ${timestamp}
# URL: ${url}
#
# Extractors can append to this file to pass environment variables
# to subsequent extractors.
#

`;

    fs.writeFileSync(envPath, content);
  }

  /**
   * Run an extractor on a URL
   * @param extractorName Name of the extractor to run
   * @param url URL to extract
   * @param outputDir Directory where extractor should output files
   * @param baseEnv Base environment variables to pass to the extractor
   * @returns Promise with the extraction result
   */
  async runExtractor(
    extractorName: string,
    url: string,
    outputDir: string,
    baseEnv: Record<string, string> = {}
  ): Promise<ExtractorResult> {
    const extractor = this.availableExtractors.get(extractorName);

    if (!extractor) {
      throw new Error(`Extractor not found: ${extractorName}`);
    }

    // Ensure output directory exists
    if (!fs.existsSync(outputDir)) {
      fs.mkdirSync(outputDir, { recursive: true });
    }

    // Load environment variables from .env file
    const envFromFile = this.loadEnvFile(outputDir);

    const start_ts = new Date().toISOString();
    const cmd = [extractor.path, url];

    // Merge environment variables (priority: baseEnv > envFromFile > process.env)
    const processEnv = {
      ...process.env,
      ...envFromFile,
      ...baseEnv,
      ARCHIVEBOX_OUTPUT_DIR: outputDir,
    };

    console.error(`Running extractor: ${extractorName}`);
    console.error(`  Environment vars from .env: ${Object.keys(envFromFile).length}`);

    return new Promise((resolve) => {
      let stdout = '';
      let stderr = '';

      const child = spawn(extractor.path, [url], {
        cwd: outputDir,
        env: processEnv,
        stdio: ['ignore', 'pipe', 'pipe'],
      });

      child.stdout?.on('data', (data) => {
        stdout += data.toString();
      });

      child.stderr?.on('data', (data) => {
        stderr += data.toString();
      });

      child.on('close', (code) => {
        const end_ts = new Date().toISOString();

        const result: ExtractorResult = {
          success: code === 0,
          output: stdout.trim(),
          error: stderr.trim() || undefined,
          cmd,
          start_ts,
          end_ts,
          pwd: outputDir,
        };

        resolve(result);
      });

      child.on('error', (err) => {
        const end_ts = new Date().toISOString();

        const result: ExtractorResult = {
          success: false,
          error: err.message,
          cmd,
          start_ts,
          end_ts,
          pwd: outputDir,
        };

        resolve(result);
      });
    });
  }

  /**
   * Run extractors serially in the predefined order
   * Each extractor can read/write to the .env file to pass state to the next
   */
  async runExtractorsSerial(
    extractorNames: string[],
    url: string,
    outputDir: string,
    baseEnv: Record<string, string> = {}
  ): Promise<Map<string, ExtractorResult>> {
    const results = new Map<string, ExtractorResult>();

    // Ensure output directory exists
    if (!fs.existsSync(outputDir)) {
      fs.mkdirSync(outputDir, { recursive: true });
    }

    // Create initial .env file
    this.createEnvFile(outputDir, url);

    // Filter to only requested extractors that are available, in the predefined order
    const extractorsToRun = EXTRACTOR_ORDER.filter(
      name => extractorNames.includes(name) && this.hasExtractor(name)
    );

    console.error(`\nRunning ${extractorsToRun.length} extractors in serial order:`);
    console.error(`  ${extractorsToRun.join(' → ')}\n`);

    // Run each extractor serially
    for (const name of extractorsToRun) {
      try {
        console.error(`[${name}] Starting...`);
        const result = await this.runExtractor(name, url, outputDir, baseEnv);
        results.set(name, result);

        if (result.success) {
          console.error(`[${name}] ✓ Success`);
        } else {
          console.error(`[${name}] ✗ Failed: ${result.error}`);
        }
      } catch (err) {
        const errorMsg = err instanceof Error ? err.message : String(err);
        console.error(`[${name}] ✗ Error: ${errorMsg}`);

        results.set(name, {
          success: false,
          error: errorMsg,
          cmd: [name, url],
          start_ts: new Date().toISOString(),
          end_ts: new Date().toISOString(),
          pwd: outputDir,
        });
      }
    }

    return results;
  }

  /**
   * Legacy method for parallel execution (deprecated, use runExtractorsSerial)
   */
  async runExtractors(
    extractorNames: ExtractorName[],
    url: string,
    outputDir: string,
    env: Record<string, string> = {}
  ): Promise<Map<ExtractorName, ExtractorResult>> {
    console.warn('Warning: runExtractors (parallel) is deprecated, use runExtractorsSerial instead');
    return this.runExtractorsSerial(extractorNames, url, outputDir, env) as Promise<Map<ExtractorName, ExtractorResult>>;
  }
}
