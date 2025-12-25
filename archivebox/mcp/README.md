# ArchiveBox MCP Server

Model Context Protocol (MCP) server for ArchiveBox that exposes all CLI commands as tools for AI agents.

## Overview

This is a lightweight, stateless MCP server that dynamically introspects ArchiveBox's Click CLI commands and exposes them as MCP tools. It requires **zero manual schema definitions** - everything is auto-generated from the existing CLI metadata.

## Features

- ✅ **Auto-discovery**: Dynamically discovers all 19+ ArchiveBox CLI commands
- ✅ **Zero duplication**: Reuses existing Click command definitions, types, and help text
- ✅ **Auto-sync**: Changes to CLI commands automatically reflected in MCP tools
- ✅ **Stateless**: No database models or state management required
- ✅ **Lightweight**: ~200 lines of code

## Usage

### Start the MCP Server

```bash
archivebox mcp
```

The server runs in stdio mode, reading JSON-RPC 2.0 requests from stdin and writing responses to stdout.

### Example Client

```python
import subprocess
import json

# Start MCP server
proc = subprocess.Popen(
    ['archivebox', 'mcp'],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    text=True
)

# Send initialize request
request = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
proc.stdin.write(json.dumps(request) + '\n')
proc.stdin.flush()

# Read response
response = json.loads(proc.stdout.readline())
print(response)
```

### Example Requests

**Initialize:**
```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}
```

**List all available tools:**
```json
{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}
```

**Call a tool:**
```json
{
  "jsonrpc":"2.0",
  "id":3,
  "method":"tools/call",
  "params":{
    "name":"version",
    "arguments":{"quiet":true}
  }
}
```

## Supported MCP Methods

- `initialize` - Handshake and capability negotiation
- `tools/list` - List all available CLI commands as MCP tools
- `tools/call` - Execute a CLI command with arguments

## Available Tools

The server exposes all ArchiveBox CLI commands:

**Meta**: `help`, `version`, `mcp`
**Setup**: `init`, `install`
**Archive**: `add`, `remove`, `update`, `search`, `status`, `config`
**Workers**: `orchestrator`, `worker`
**Tasks**: `crawl`, `snapshot`, `extract`
**Server**: `server`, `schedule`
**Utilities**: `shell`, `manage`

## Architecture

### Dynamic Introspection

Instead of manually defining schemas, the server uses Click's introspection API to automatically generate MCP tool definitions:

```python
# Auto-discover commands
from archivebox.cli import ArchiveBoxGroup
cli_group = ArchiveBoxGroup()
all_commands = cli_group.all_subcommands

# Auto-generate schemas from Click metadata
for cmd_name in all_commands:
    click_cmd = cli_group.get_command(None, cmd_name)
    # Extract params, types, help text, etc.
    tool_schema = click_command_to_mcp_tool(cmd_name, click_cmd)
```

### Tool Execution

Commands are executed using Click's `CliRunner`:

```python
from click.testing import CliRunner

runner = CliRunner()
result = runner.invoke(click_command, args)
```

## Files

- `server.py` (~350 lines) - Core MCP server with Click introspection
- `archivebox/cli/archivebox_mcp.py` (~50 lines) - CLI entry point
- `apps.py`, `__init__.py` - Django app boilerplate

## MCP Specification

Implements the [MCP 2025-11-25 specification](https://modelcontextprotocol.io/specification/2025-11-25).

## Sources

- [MCP Specification](https://modelcontextprotocol.io/specification/2025-11-25)
- [MCP Introduction](https://www.anthropic.com/news/model-context-protocol)
- [MCP GitHub](https://github.com/modelcontextprotocol/modelcontextprotocol)
