# ArchiveBox MCP Server

ArchiveBox workflow tools over MCP using JSON-RPC 2.0 on stdin/stdout.

## Overview

Tool arguments come from the selected Click commands. Model tools expose their subcommands through an `action` argument.

## Features

- Reuses CLI command definitions, validation, and execution.
- Returns structured records, stdout, stderr, and exit status.

## Usage

### Start the MCP Server

```bash
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' | archivebox mcp
```

The server runs in stdio mode, reading JSON-RPC 2.0 requests from stdin and writing responses to stdout.

### Example Client

```python
import json
import subprocess

request = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
completed = subprocess.run(
    ["archivebox", "mcp"],
    input=json.dumps(request) + "\n",
    capture_output=True,
    text=True,
    check=True,
    timeout=30,
)
response = json.loads(completed.stdout)
assert response["id"] == 1
assert response["result"]["serverInfo"]["name"] == "archivebox-mcp"
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
    "name":"folder",
    "arguments":{"action":"list"}
  }
}
```

## Supported MCP Methods

- `initialize` - Handshake and capability negotiation
- `tools/list` - List the public tools and their schemas
- `tools/call` - Execute a CLI command with arguments

## Available Tools

The public tools are `add`, `search`, `crawl`, `snapshot`, `archiveresult`,
`folder`, `importer`, and `shell`. Model tools group their native CLI subcommands
under an `action` argument. `folder` includes CRUD, rule discovery, and membership
moves. `importer` includes CRUD, catalog discovery, source actions, and run history.
The `snapshot` list action exposes folder selection and static ZIP/unified WACZ
exports using the same options as the CLI.

## Architecture

### Dynamic Introspection

Inspect the public tool definitions:

```python
from archivebox.mcp.server import MCPServer

tools = MCPServer().get_public_tool_definitions()
assert {tool["name"] for tool in tools}
assert all("inputSchema" in tool for tool in tools)
```

### Tool Execution

Commands are executed using Click's `CliRunner`:

```python
from archivebox.mcp.server import MCPServer

response = MCPServer().handle_request(
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
)
assert response["id"] == 2
assert response["result"]["tools"]
assert all("name" in tool and "inputSchema" in tool for tool in response["result"]["tools"])
```

## Files

- `server.py` - Core MCP server with Click introspection
- `archivebox/cli/archivebox_mcp.py` - CLI entry point
- `apps.py`, `__init__.py` - Django app boilerplate

## MCP Specification

Implements the [MCP 2025-11-25 specification](https://modelcontextprotocol.io/specification/2025-11-25).

## Sources

- [MCP Specification](https://modelcontextprotocol.io/specification/2025-11-25)
- [MCP Introduction](https://www.anthropic.com/news/model-context-protocol)
- [MCP GitHub](https://github.com/modelcontextprotocol/modelcontextprotocol)
