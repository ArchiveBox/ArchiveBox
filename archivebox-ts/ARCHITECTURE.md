# ArchiveBox-TS Architecture

This document explains the architectural decisions and design philosophy of ArchiveBox-TS.

## Design Philosophy

### 1. Simplicity Over Flexibility

Rather than building a complex plugin system, we use the simplest possible approach: standalone executable files. This makes the system easier to understand, debug, and extend.

### 2. Convention Over Configuration

- Extractors are discovered by scanning a directory
- URL is always the first argument
- Output always goes to current directory
- Config always via environment variables

### 3. Language Agnostic

Extractors can be written in any language (bash, Python, Node.js, Go, Rust, etc.) as long as they follow the simple contract: executable with shebang, URL as $1, files to current dir.

### 4. Self-Contained

Each extractor is responsible for its own dependencies. This removes the need for a central dependency management system.

### 5. Fail Fast, Recover Gracefully

Individual extractor failures don't stop the whole archiving process. Each extractor runs independently and reports its own status.

## Core Components

### 1. Database Layer (`src/db.ts`)

Uses better-sqlite3 for synchronous SQLite operations.

**Key Design Decisions:**

- **Synchronous API**: Simpler to use than async for CLI applications
- **WAL Mode**: Better concurrency support
- **Compatible Schema**: Matches ArchiveBox's schema for potential data migration
- **JSON Storage**: Config and cmd stored as JSON for flexibility
- **UUID Primary Keys**: Globally unique, can be generated client-side

**Schema Simplifications:**

- No user system (single-user mode)
- No tags (can be added later)
- No crawls (can be added later)
- Simplified state machine (queued → started → sealed)

### 2. Extractor Manager (`src/extractors.ts`)

Discovers and orchestrates extractor execution.

**Discovery Process:**

1. Scan extractors directory
2. Check file execute permissions
3. Register available extractors

**Execution Process:**

1. Create output directory
2. Spawn process with URL as first argument
3. Set working directory to output directory
4. Pass environment variables
5. Capture stdout (output file) and stderr (logs)
6. Record exit code (0 = success)

**Parallelization:**

Extractors run in parallel using Promise.all(). Each extractor is independent and failures are isolated.

### 3. CLI (`src/cli.ts`)

Uses Commander.js for CLI argument parsing.

**Commands:**

- `init` - Set up data directory and database
- `add` - Archive a URL
- `list` - Show all snapshots
- `status` - Show snapshot details
- `extractors` - List available extractors

**Flow for `add` command:**

```
1. Parse arguments
2. Open database
3. Check if URL exists
4. Create snapshot (or reuse existing)
5. Determine extractors to run
6. Update snapshot status to 'started'
7. Create output directory
8. Create ArchiveResult records for each extractor
9. Run extractors in parallel
10. Update ArchiveResult records with results
11. Update snapshot status to 'sealed'
12. Close database
```

## Data Model

### Snapshot

Represents a URL that has been (or is being) archived.

**States:**
- `queued` - Created but not started
- `started` - Currently archiving
- `sealed` - Archiving complete

**Key Fields:**
- `id` - UUID
- `abid` - ArchiveBox ID (for compatibility)
- `url` - The URL being archived
- `timestamp` - Unix timestamp string
- `output_dir` - Where files are stored

### ArchiveResult

Represents one extractor's result for one snapshot.

**States:**
- `queued` - Waiting to run
- `started` - Currently running
- `succeeded` - Completed successfully
- `failed` - Failed with error
- `skipped` - Intentionally skipped
- `backoff` - Waiting to retry

**Key Fields:**
- `id` - UUID
- `snapshot_id` - Foreign key to snapshot
- `extractor` - Name of extractor
- `cmd` - Command that was executed
- `output` - Main output file path
- `start_ts`, `end_ts` - Execution timing

## Extractor Contract

### Input

1. **URL** - First positional argument (`$1`, `process.argv[2]`, `sys.argv[1]`)
2. **Environment Variables** - All configuration
3. **Working Directory** - Where to write output files

### Output

1. **Files** - Written to current working directory
2. **stdout** - Main output filename (e.g., "screenshot.png")
3. **stderr** - Logs, progress, errors
4. **Exit Code** - 0 for success, non-zero for failure

### Lifecycle

```
1. Extractor spawned by ExtractorManager
2. Changes to output directory
3. Reads config from environment
4. (Optional) Auto-installs dependencies
5. Processes URL
6. Writes output files
7. Prints main file to stdout
8. Logs to stderr
9. Exits with status code
```

## File Organization

```
archivebox-ts/
├── src/                    # TypeScript source
│   ├── cli.ts             # CLI entry point
│   ├── db.ts              # Database operations
│   ├── models.ts          # TypeScript types
│   └── extractors.ts      # Extractor orchestration
├── extractors/            # Extractor executables
│   ├── favicon            # Bash script
│   ├── title              # Node.js script
│   ├── headers            # Bash script
│   ├── wget               # Bash script
│   └── screenshot         # Python script
├── dist/                  # Compiled JavaScript (gitignored)
├── data/                  # Runtime data (gitignored)
│   ├── index.sqlite3      # Database
│   └── archive/           # Archived content
│       └── <timestamp>_<domain>/
│           ├── favicon.ico
│           ├── title.txt
│           └── ...
├── package.json
├── tsconfig.json
├── README.md
├── QUICKSTART.md
├── EXTRACTOR_GUIDE.md
└── ARCHITECTURE.md (this file)
```

## Output Directory Naming

Pattern: `<timestamp>_<domain>`

Example: `1762193664373_example.com`

**Why?**
- Timestamp ensures uniqueness
- Domain provides human-readable context
- Simple flat structure (no deep nesting)

## Comparison to Original ArchiveBox

### What We Kept

1. **Database Schema** - Compatible with ArchiveBox for potential migration
2. **Snapshot/ArchiveResult Model** - Same conceptual model
3. **Extractor Names** - Same names (favicon, title, headers, etc.)
4. **Output Structure** - Similar file organization

### What We Simplified

1. **Plugin System** → Executable files
2. **Configuration Files** → Environment variables
3. **Django ORM** → Raw SQLite
4. **Web UI** → CLI only (for now)
5. **Background Workers** → Direct execution
6. **Multi-user** → Single-user
7. **ABX Framework** → Simple directory scan

### What We Improved

1. **Easier to Extend** - Just drop an executable in a directory
2. **Language Agnostic** - Use any language for extractors
3. **Simpler Dependencies** - Each extractor manages its own
4. **Easier to Test** - Extractors can be tested standalone
5. **Smaller Codebase** - ~500 lines vs thousands

## Performance Characteristics

### Time Complexity

- **Add URL**: O(n) where n = number of extractors
- **List Snapshots**: O(n) where n = number of snapshots (with pagination)
- **Get Status**: O(1) for snapshot, O(m) for results where m = extractors used
- **Discover Extractors**: O(e) where e = files in extractors directory

### Space Complexity

- **Database**: O(n * m) where n = snapshots, m = extractors per snapshot
- **Archive Files**: Depends on content (potentially large)

### Concurrency

- **Extractors**: Run in parallel (Promise.all)
- **CLI Commands**: Sequential (SQLite has one writer)
- **Future**: Could add job queue for background processing

## Scaling Considerations

### Current Limits

- Single machine
- One CLI command at a time
- No distributed execution
- Limited by SQLite write throughput

### Future Enhancements

1. **Job Queue** - Redis or database-based queue
2. **Worker Processes** - Multiple workers processing queue
3. **Distributed Execution** - Run extractors on different machines
4. **Caching** - Cache extractor results
5. **Incremental Archiving** - Only run changed extractors

## Error Handling

### Extractor Failures

- Captured and stored in ArchiveResult.notes
- Don't stop other extractors
- Exit code determines success/failure
- stderr captured for debugging

### Database Errors

- Propagated to CLI
- Transaction rollback on failure
- Clear error messages

### Network Errors

- Handled by individual extractors
- Timeout via environment variables
- Retry logic in extractors (optional)

## Testing Strategy

### Unit Tests (Future)

- Database operations
- Extractor discovery
- Model validation

### Integration Tests (Future)

- Full CLI commands
- Database + extractors
- Error scenarios

### Extractor Tests

- Manual testing (run standalone)
- Test with various URLs
- Test error conditions
- Test configuration options

## Security Considerations

### Current State

- Runs with user permissions
- No input sanitization (URLs passed directly)
- Extractors can run arbitrary code
- No sandbox

### Recommendations for Production

1. **Input Validation** - Validate and sanitize URLs
2. **Sandboxing** - Run extractors in containers/VMs
3. **Resource Limits** - CPU, memory, disk quotas
4. **Authentication** - Add user system for web UI
5. **HTTPS Only** - Validate SSL certificates
6. **Rate Limiting** - Prevent abuse

## Future Architecture Enhancements

### 1. Background Processing

```typescript
// Job queue pattern
interface Job {
  id: string;
  snapshot_id: string;
  extractor: string;
  status: 'pending' | 'running' | 'completed';
}

class JobQueue {
  enqueue(snapshot_id: string, extractor: string): Job;
  dequeue(): Job | null;
  complete(job_id: string, result: ExtractorResult): void;
}
```

### 2. Web UI

- Express/Fastify server
- Browse archived snapshots
- Trigger new archives
- View extractor results
- Search functionality

### 3. API

- RESTful API
- POST /snapshots - Create snapshot
- GET /snapshots - List snapshots
- GET /snapshots/:id - Get snapshot details
- POST /snapshots/:id/extract - Run extractors

### 4. Plugins

While keeping the extractor model simple, could add:
- Pre-processors (URL transformation)
- Post-processors (Content analysis)
- Notifications (Email, webhook)
- Storage backends (S3, B2)

### 5. Distributed Execution

- Extract coordinator and workers
- gRPC or HTTP API between coordinator/workers
- Shared database or message queue
- Worker pools by extractor type

## Conclusion

ArchiveBox-TS demonstrates that complex functionality can be achieved with simple, composable components. By embracing Unix philosophy (do one thing well, text streams, exit codes), we've created a system that's both powerful and easy to understand.

The key insight is that **extractors don't need to be plugins** - they can be simple executables that follow a convention. This drastically simplifies the architecture while maintaining flexibility and extensibility.
