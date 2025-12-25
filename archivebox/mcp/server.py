__package__ = 'archivebox.mcp'

"""
Model Context Protocol (MCP) server implementation for ArchiveBox.

Dynamically exposes all ArchiveBox CLI commands as MCP tools by introspecting
Click command metadata. Handles JSON-RPC 2.0 requests over stdio transport.
"""

import sys
import json
import traceback
from typing import Any, Dict, List, Optional
from io import StringIO
from contextlib import redirect_stdout, redirect_stderr

import click
from click.testing import CliRunner

from archivebox.config.version import VERSION


class MCPJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles Click sentinel values and other special types"""

    def default(self, obj):
        # Handle Click's sentinel values
        if hasattr(click, 'core') and hasattr(click.core, '_SentinelClass'):
            if isinstance(obj, click.core._SentinelClass):
                return None

        # Handle tuples (convert to lists)
        if isinstance(obj, tuple):
            return list(obj)

        # Handle any other non-serializable objects
        try:
            return super().default(obj)
        except TypeError:
            return str(obj)


# Type mapping from Click types to JSON Schema types
def click_type_to_json_schema_type(click_type) -> dict:
    """Convert a Click parameter type to JSON Schema type definition"""

    if isinstance(click_type, click.types.StringParamType):
        return {"type": "string"}
    elif isinstance(click_type, click.types.IntParamType):
        return {"type": "integer"}
    elif isinstance(click_type, click.types.FloatParamType):
        return {"type": "number"}
    elif isinstance(click_type, click.types.BoolParamType):
        return {"type": "boolean"}
    elif isinstance(click_type, click.types.Choice):
        return {"type": "string", "enum": click_type.choices}
    elif isinstance(click_type, click.types.Path):
        return {"type": "string", "description": "File or directory path"}
    elif isinstance(click_type, click.types.File):
        return {"type": "string", "description": "File path"}
    elif isinstance(click_type, click.types.Tuple):
        # Multiple arguments of same type
        return {"type": "array", "items": {"type": "string"}}
    else:
        # Default to string for unknown types
        return {"type": "string"}


def click_command_to_mcp_tool(cmd_name: str, click_command: click.Command) -> dict:
    """
    Convert a Click command to an MCP tool definition with JSON Schema.

    Introspects the Click command's parameters to automatically generate
    the input schema without manual definition.
    """

    properties = {}
    required = []

    # Extract parameters from Click command
    for param in click_command.params:
        # Skip internal parameters
        if param.name in ('help', 'version'):
            continue

        param_schema = click_type_to_json_schema_type(param.type)

        # Add description from Click help text
        if param.help:
            param_schema["description"] = param.help

        # Handle default values
        if param.default is not None and param.default != ():
            param_schema["default"] = param.default

        # Handle multiple values (like multiple URLs)
        if param.multiple:
            properties[param.name] = {
                "type": "array",
                "items": param_schema,
                "description": param_schema.get("description", f"Multiple {param.name} values")
            }
        else:
            properties[param.name] = param_schema

        # Mark as required if Click requires it
        if param.required:
            required.append(param.name)

    return {
        "name": cmd_name,
        "description": click_command.help or click_command.short_help or f"Run archivebox {cmd_name} command",
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required
        }
    }


def execute_click_command(cmd_name: str, click_command: click.Command, arguments: dict) -> dict:
    """
    Execute a Click command programmatically with given arguments.

    Returns MCP-formatted result with captured output and error status.
    """

    # Setup Django for archive commands (commands that need database access)
    from archivebox.cli import ArchiveBoxGroup
    if cmd_name in ArchiveBoxGroup.archive_commands:
        try:
            from archivebox.config.django import setup_django
            from archivebox.misc.checks import check_data_folder
            setup_django()
            check_data_folder()
        except Exception as e:
            # If Django setup fails, return error (unless it's manage/shell which handle this themselves)
            if cmd_name not in ('manage', 'shell'):
                return {
                    "content": [{
                        "type": "text",
                        "text": f"Error setting up Django: {str(e)}\n\nMake sure you're running the MCP server from inside an ArchiveBox data directory."
                    }],
                    "isError": True
                }

    # Use Click's test runner to invoke command programmatically
    runner = CliRunner()

    # Build a map of parameter names to their Click types (Argument vs Option)
    param_map = {param.name: param for param in click_command.params}

    # Convert arguments dict to CLI args list
    args = []
    positional_args = []

    for key, value in arguments.items():
        param_name = key.replace('_', '-')  # Click uses dashes
        param = param_map.get(key)

        # Check if this is a positional Argument (not an Option)
        is_argument = isinstance(param, click.Argument)

        if is_argument:
            # Positional arguments - add them without dashes
            if isinstance(value, list):
                positional_args.extend([str(v) for v in value])
            elif value is not None:
                positional_args.append(str(value))
        else:
            # Options - add with dashes
            if isinstance(value, bool):
                if value:
                    args.append(f'--{param_name}')
            elif isinstance(value, list):
                # Multiple values for an option (rare)
                for item in value:
                    args.append(f'--{param_name}')
                    args.append(str(item))
            elif value is not None:
                args.append(f'--{param_name}')
                args.append(str(value))

    # Add positional arguments at the end
    args.extend(positional_args)

    # Execute the command
    try:
        result = runner.invoke(click_command, args, catch_exceptions=False)

        # Format output as MCP content
        content = []

        if result.output:
            content.append({
                "type": "text",
                "text": result.output
            })

        if result.stderr_bytes:
            stderr_text = result.stderr_bytes.decode('utf-8', errors='replace')
            if stderr_text.strip():
                content.append({
                    "type": "text",
                    "text": f"[stderr]\n{stderr_text}"
                })

        # Check exit code
        is_error = result.exit_code != 0

        if is_error and not content:
            content.append({
                "type": "text",
                "text": f"Command failed with exit code {result.exit_code}"
            })

        return {
            "content": content or [{"type": "text", "text": "(no output)"}],
            "isError": is_error
        }

    except Exception as e:
        # Capture any exceptions during execution
        error_trace = traceback.format_exc()
        return {
            "content": [{
                "type": "text",
                "text": f"Error executing {cmd_name}: {str(e)}\n\n{error_trace}"
            }],
            "isError": True
        }


class MCPServer:
    """
    Model Context Protocol server for ArchiveBox.

    Provides JSON-RPC 2.0 interface over stdio, dynamically exposing
    all Click commands as MCP tools.
    """

    def __init__(self):
        # Import here to avoid circular imports
        from archivebox.cli import ArchiveBoxGroup

        self.cli_group = ArchiveBoxGroup()
        self.protocol_version = "2025-11-25"
        self._tool_cache = {}  # Cache loaded Click commands

    def get_click_command(self, cmd_name: str) -> Optional[click.Command]:
        """Get a Click command by name, with caching"""
        if cmd_name not in self._tool_cache:
            if cmd_name not in self.cli_group.all_subcommands:
                return None
            self._tool_cache[cmd_name] = self.cli_group.get_command(None, cmd_name)
        return self._tool_cache[cmd_name]

    def handle_initialize(self, params: dict) -> dict:
        """Handle MCP initialize request"""
        return {
            "protocolVersion": self.protocol_version,
            "capabilities": {
                "tools": {}
            },
            "serverInfo": {
                "name": "archivebox-mcp",
                "version": VERSION
            }
        }

    def handle_tools_list(self, params: dict) -> dict:
        """Handle MCP tools/list request - returns all available CLI commands as tools"""
        tools = []

        for cmd_name in self.cli_group.all_subcommands.keys():
            click_cmd = self.get_click_command(cmd_name)
            if click_cmd:
                try:
                    tool_def = click_command_to_mcp_tool(cmd_name, click_cmd)
                    tools.append(tool_def)
                except Exception as e:
                    # Log but don't fail - skip problematic commands
                    print(f"Warning: Could not generate tool for {cmd_name}: {e}", file=sys.stderr)

        return {"tools": tools}

    def handle_tools_call(self, params: dict) -> dict:
        """Handle MCP tools/call request - executes a CLI command"""
        tool_name = params.get('name')
        arguments = params.get('arguments', {})

        if not tool_name:
            raise ValueError("Missing required parameter: name")

        click_cmd = self.get_click_command(tool_name)
        if not click_cmd:
            raise ValueError(f"Unknown tool: {tool_name}")

        # Execute the command and return MCP-formatted result
        return execute_click_command(tool_name, click_cmd, arguments)

    def handle_request(self, request: dict) -> dict:
        """
        Handle a JSON-RPC 2.0 request and return response.

        Supports MCP methods: initialize, tools/list, tools/call
        """

        method = request.get('method')
        params = request.get('params', {})
        request_id = request.get('id')

        try:
            # Route to appropriate handler
            if method == 'initialize':
                result = self.handle_initialize(params)
            elif method == 'tools/list':
                result = self.handle_tools_list(params)
            elif method == 'tools/call':
                result = self.handle_tools_call(params)
            else:
                # Method not found
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: {method}"
                    }
                }

            # Success response
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result
            }

        except Exception as e:
            # Error response
            error_trace = traceback.format_exc()
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32603,
                    "message": str(e),
                    "data": error_trace
                }
            }

    def run_stdio_server(self):
        """
        Run the MCP server in stdio mode.

        Reads JSON-RPC requests from stdin (one per line),
        writes JSON-RPC responses to stdout (one per line).
        """

        # Read requests from stdin line by line
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue

            try:
                # Parse JSON-RPC request
                request = json.loads(line)

                # Handle request
                response = self.handle_request(request)

                # Write response to stdout (use custom encoder for Click types)
                print(json.dumps(response, cls=MCPJSONEncoder), flush=True)

            except json.JSONDecodeError as e:
                # Invalid JSON
                error_response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32700,
                        "message": "Parse error",
                        "data": str(e)
                    }
                }
                print(json.dumps(error_response, cls=MCPJSONEncoder), flush=True)


def run_mcp_server():
    """Main entry point for MCP server"""
    server = MCPServer()
    server.run_stdio_server()
