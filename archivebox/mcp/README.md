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
from archivebox.mcp.server import MCPServer, click_command_to_mcp_tool

tools = []
for discovered_tool in MCPServer().get_tools().values():
    tools.append(click_command_to_mcp_tool(discovered_tool))

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

- `server.py` (~350 lines) - Core MCP server with Click introspection
- `archivebox/cli/archivebox_mcp.py` (~50 lines) - CLI entry point
- `apps.py`, `__init__.py` - Django app boilerplate

## MCP Specification

Implements the [MCP 2025-11-25 specification](https://modelcontextprotocol.io/specification/2025-11-25).

## Sources

- [MCP Specification](https://modelcontextprotocol.io/specification/2025-11-25)
- [MCP Introduction](https://www.anthropic.com/news/model-context-protocol)
- [MCP GitHub](https://github.com/modelcontextprotocol/modelcontextprotocol)
