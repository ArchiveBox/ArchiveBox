/**
 * Extractor orchestration system
 * Discovers and runs standalone extractor executables
 */

import * as fs from 'fs';
import * as path from 'path';
import { spawn } from 'child_process';
import type { ExtractorName } from './models';

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
  private availableExtractors: Map<ExtractorName, ExtractorInfo>;

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
        const name = file as ExtractorName;

        this.availableExtractors.set(name, {
          name,
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
   * Get list of available extractors
   */
  getAvailableExtractors(): ExtractorName[] {
    return Array.from(this.availableExtractors.keys());
  }

  /**
   * Check if an extractor is available
   */
  hasExtractor(name: ExtractorName): boolean {
    return this.availableExtractors.has(name);
  }

  /**
   * Run an extractor on a URL
   * @param extractorName Name of the extractor to run
   * @param url URL to extract
   * @param outputDir Directory where extractor should output files
   * @param env Environment variables to pass to the extractor
   * @returns Promise with the extraction result
   */
  async runExtractor(
    extractorName: ExtractorName,
    url: string,
    outputDir: string,
    env: Record<string, string> = {}
  ): Promise<ExtractorResult> {
    const extractor = this.availableExtractors.get(extractorName);

    if (!extractor) {
      throw new Error(`Extractor not found: ${extractorName}`);
    }

    // Ensure output directory exists
    if (!fs.existsSync(outputDir)) {
      fs.mkdirSync(outputDir, { recursive: true });
    }

    const start_ts = new Date().toISOString();
    const cmd = [extractor.path, url];

    // Merge environment variables
    const processEnv = {
      ...process.env,
      ...env,
      ARCHIVEBOX_OUTPUT_DIR: outputDir,
    };

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
   * Run multiple extractors in parallel
   */
  async runExtractors(
    extractorNames: ExtractorName[],
    url: string,
    outputDir: string,
    env: Record<string, string> = {}
  ): Promise<Map<ExtractorName, ExtractorResult>> {
    const results = new Map<ExtractorName, ExtractorResult>();

    const promises = extractorNames.map(async (name) => {
      try {
        const result = await this.runExtractor(name, url, outputDir, env);
        results.set(name, result);
      } catch (err) {
        results.set(name, {
          success: false,
          error: err instanceof Error ? err.message : String(err),
          cmd: [name, url],
          start_ts: new Date().toISOString(),
          end_ts: new Date().toISOString(),
          pwd: outputDir,
        });
      }
    });

    await Promise.all(promises);
    return results;
  }
}
