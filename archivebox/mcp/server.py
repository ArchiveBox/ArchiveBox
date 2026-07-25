"""Model Context Protocol server for ArchiveBox.

The server exposes five agent-friendly workflow tools backed by ArchiveBox's
existing Click CLI and newline-delimited JSON-RPC.
"""

import json
import sys
import traceback
from dataclasses import dataclass
from typing import Any

import click
from click.testing import CliRunner

from archivebox.config.version import VERSION

PROTOCOL_VERSION = "2025-11-25"
PUBLIC_TOOLS = ("add", "search", "crawl", "snapshot", "archiveresult", "shell")
ACTION_TOOLS = {"crawl", "snapshot", "archiveresult"}
READ_ONLY_ACTIONS = {"help", "list", "search", "status", "version"}
DESTRUCTIVE_ACTIONS = {"delete", "remove"}


class MCPJSONEncoder(json.JSONEncoder):
    """JSON encoder for UUIDs, paths, Click sentinels, and other CLI values."""

    def default(self, value):
        sentinel_type = getattr(click.core, "_SentinelClass", None)
        if isinstance(sentinel_type, type) and isinstance(value, sentinel_type):
            return None
        if isinstance(value, tuple):
            return list(value)
        try:
            return super().default(value)
        except TypeError:
            return str(value)


@dataclass(frozen=True)
class MCPTool:
    """A discovered leaf Click command and its ArchiveBox command path."""

    name: str
    command_path: tuple[str, ...]
    command: click.Command


def click_type_to_json_schema_type(click_type: click.ParamType) -> dict[str, Any]:
    """Convert a Click parameter type to JSON Schema."""

    if isinstance(click_type, click.types.StringParamType):
        return {"type": "string"}
    if isinstance(click_type, click.types.IntParamType):
        return {"type": "integer"}
    if isinstance(click_type, click.types.FloatParamType):
        return {"type": "number"}
    if isinstance(click_type, click.types.BoolParamType):
        return {"type": "boolean"}
    if isinstance(click_type, click.types.Choice):
        schema: dict[str, Any] = {"enum": list(click_type.choices)}
        if all(isinstance(choice, str) for choice in click_type.choices):
            schema["type"] = "string"
        return schema
    if isinstance(click_type, (click.types.Path, click.types.File)):
        return {"type": "string", "description": "File or directory path"}
    if isinstance(click_type, click.types.Tuple):
        return {
            "type": "array",
            "prefixItems": [click_type_to_json_schema_type(item) for item in click_type.types],
            "minItems": len(click_type.types),
            "maxItems": len(click_type.types),
        }
    return {"type": "string"}


def command_accepts_stdin(click_command: click.Command) -> bool:
    """Return whether a command documents a stdin/JSONL input path."""

    command_help = " ".join(
        value
        for value in (
            click_command.help,
            click_command.short_help,
            click_command.callback.__doc__ if click_command.callback else None,
        )
        if value
    ).lower()
    return "stdin" in command_help


def tool_annotations(command_path: tuple[str, ...]) -> dict[str, Any]:
    """Describe a command's side effects to MCP clients."""

    action = command_path[-1]
    root = command_path[0]
    read_only = action in READ_ONLY_ACTIONS
    destructive = action in DESTRUCTIVE_ACTIONS
    return {
        "title": "ArchiveBox " + " ".join(command_path),
        "readOnlyHint": read_only,
        "destructiveHint": destructive,
        "idempotentHint": read_only or destructive,
        "openWorldHint": root in {"add", "extract", "oneshot", "run", "update"} or (root in {"crawl", "snapshot"} and action == "create"),
    }


def click_command_to_mcp_tool(tool: MCPTool) -> dict[str, Any]:
    """Convert a leaf Click command to an MCP tool definition."""

    properties: dict[str, dict[str, Any]] = {}
    required: list[str] = []

    for param in tool.command.params:
        if param.name is None or param.name in {"help", "version"}:
            continue

        param_schema = click_type_to_json_schema_type(param.type)
        help_text = getattr(param, "help", None)
        if help_text:
            param_schema["description"] = help_text

        default = param.default
        sentinel_type = getattr(click.core, "_SentinelClass", None)
        is_sentinel = isinstance(sentinel_type, type) and isinstance(default, sentinel_type)
        if default is not None and default != () and not is_sentinel:
            param_schema["default"] = default

        if param.multiple or param.nargs != 1:
            item_schema = param_schema
            if isinstance(param.type, click.types.Tuple):
                properties[param.name] = param_schema
            else:
                properties[param.name] = {
                    "type": "array",
                    "items": item_schema,
                    "description": help_text or f"One or more {param.name.replace('_', ' ')} values",
                }
        else:
            properties[param.name] = param_schema

        if param.required:
            required.append(param.name)

    if command_accepts_stdin(tool.command):
        properties["records"] = {
            "type": "array",
            "items": {"type": "object"},
            "description": "Records to pass to the command as JSONL stdin. Use this instead of building a CLI pipeline.",
        }
        properties["stdin"] = {
            "type": "string",
            "description": "Raw stdin text. Prefer records for JSONL commands.",
        }

    command_name = "archivebox " + " ".join(tool.command_path)
    description = tool.command.help or tool.command.short_help or f"Run {command_name}"
    return {
        "name": tool.name,
        "title": " ".join(part.title() for part in tool.command_path),
        "description": f"{description}\n\nEquivalent CLI command: `{command_name}`.",
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
        "outputSchema": tool_output_schema(),
        "annotations": tool_annotations(tool.command_path),
    }


def tool_output_schema() -> dict[str, Any]:
    """Return the shared envelope schema for all CLI-backed tools."""

    return {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "success": {"type": "boolean"},
            "error": {"type": ["string", "null"]},
            "exitCode": {"type": "integer"},
            "records": {"type": "array", "items": {}},
            "stdout": {"type": "string"},
            "stderr": {"type": "string"},
        },
        "required": ["command", "success", "error", "exitCode", "records", "stdout", "stderr"],
    }


def click_group_to_mcp_tool(group_name: str, actions: list[MCPTool]) -> dict[str, Any]:
    """Expose a Click command group as one MCP tool with an action selector."""

    action_names = [tool.command_path[-1] for tool in actions]
    properties: dict[str, dict[str, Any]] = {
        "action": {
            "type": "string",
            "enum": action_names,
            "description": f"{group_name.title()} action to run.",
        },
    }
    action_help = []
    for action_tool in actions:
        action_def = click_command_to_mcp_tool(action_tool)
        action_name = action_tool.command_path[-1]
        action_help.append(f"- {action_name}: {action_tool.command.help or action_tool.command.short_help}")
        for name, schema in action_def["inputSchema"]["properties"].items():
            if name not in properties:
                properties[name] = dict(schema)
            elif properties[name].get("default") != schema.get("default"):
                properties[name].pop("default", None)

    return {
        "name": group_name,
        "title": f"ArchiveBox {group_name.title()}",
        "description": (f"Manage ArchiveBox {group_name} records through the existing CLI.\n\nActions:\n{chr(10).join(action_help)}"),
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": ["action"],
            "additionalProperties": False,
        },
        "outputSchema": tool_output_schema(),
        "annotations": {"title": f"ArchiveBox {group_name.title()}"},
    }


def shell_to_mcp_tool() -> dict[str, Any]:
    """Expose ``archivebox shell -c`` as one explicit Python escape hatch."""

    return {
        "name": "shell",
        "title": "ArchiveBox Python Shell",
        "description": (
            "Run arbitrary Python with ArchiveBox and Django initialized. "
            "Equivalent CLI command: `archivebox shell --plain --quiet-load -c CODE`. "
            "This has full access to the collection database and filesystem."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python source to execute in the initialized ArchiveBox Django shell.",
                },
            },
            "required": ["code"],
            "additionalProperties": False,
        },
        "outputSchema": tool_output_schema(),
        "annotations": {
            "title": "ArchiveBox Python Shell",
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    }


def _option_args(param: click.Option, value: Any) -> list[str]:
    """Serialize one MCP argument using the option's real Click spellings."""

    primary = next((opt for opt in param.opts if opt.startswith("--")), param.opts[0])
    if param.is_bool_flag:
        if value:
            return [primary]
        if param.secondary_opts:
            secondary = next((opt for opt in param.secondary_opts if opt.startswith("--")), param.secondary_opts[0])
            return [secondary]
        return []

    values = value if isinstance(value, list) and param.multiple else [value]
    args: list[str] = []
    for item in values:
        args.extend((primary, str(item)))
    return args


def arguments_to_cli(
    click_command: click.Command,
    arguments: dict[str, Any],
) -> tuple[list[str], str | None]:
    """Convert MCP JSON arguments into Click argv and optional stdin."""

    supplied = dict(arguments)
    records = supplied.pop("records", None)
    stdin_text = supplied.pop("stdin", None)
    if records is not None and stdin_text is not None:
        raise ValueError("Pass either records or stdin, not both")
    if records is not None:
        stdin_text = "".join(json.dumps(record, cls=MCPJSONEncoder) + "\n" for record in records)

    param_map = {param.name: param for param in click_command.params}
    unknown = sorted(set(supplied) - set(param_map))
    if unknown:
        raise ValueError(f"Unknown argument(s): {', '.join(unknown)}")

    option_args: list[str] = []
    positional_args: list[str] = []
    for key, value in supplied.items():
        if value is None:
            continue
        param = param_map[key]
        if isinstance(param, click.Argument):
            values = value if isinstance(value, list) else [value]
            positional_args.extend(str(item) for item in values)
        else:
            option_args.extend(_option_args(param, value))

    return [*option_args, *positional_args], stdin_text


def parse_structured_records(stdout: str) -> list[Any]:
    """Parse a CLI JSON array or JSONL stream without guessing at human output."""

    stripped = stdout.strip()
    if not stripped:
        return []
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        records = []
        for line in stripped.splitlines():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                return []
        return records
    return parsed if isinstance(parsed, list) else [parsed]


def execute_click_command(tool: MCPTool, arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute one discovered CLI command and return MCP structured content."""

    from archivebox.cli import cli

    try:
        cli_args, stdin_text = arguments_to_cli(tool.command, arguments)
        result = CliRunner().invoke(
            cli,
            [*tool.command_path, *cli_args],
            input=stdin_text,
            prog_name="archivebox",
            catch_exceptions=False,
        )
        return _tool_result(
            tool,
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            is_error=result.exit_code != 0,
        )
    except (click.ClickException, click.UsageError, OSError, SystemExit, ValueError) as err:
        print(traceback.format_exc(), file=sys.stderr)
        return _tool_result(
            tool,
            exit_code=1,
            stderr=f"Could not invoke archivebox {' '.join(tool.command_path)}: {err}",
            is_error=True,
        )


def _tool_result(
    tool: MCPTool,
    *,
    exit_code: int,
    stdout: str = "",
    stderr: str = "",
    is_error: bool,
) -> dict[str, Any]:
    error = None
    if is_error:
        error = stderr.strip() or stdout.strip() or f"Command failed with exit code {exit_code}"
    structured = {
        "command": "archivebox " + " ".join(tool.command_path),
        "success": not is_error,
        "error": error,
        "exitCode": exit_code,
        "records": parse_structured_records(stdout),
        "stdout": stdout,
        "stderr": stderr,
    }
    return {
        "content": [{"type": "text", "text": json.dumps(structured, cls=MCPJSONEncoder)}],
        "structuredContent": structured,
        "isError": is_error,
    }


class MCPServer:
    """ArchiveBox MCP server using JSON-RPC 2.0 over stdio."""

    def __init__(self):
        from archivebox.cli import ArchiveBoxGroup

        self.cli_group = ArchiveBoxGroup()
        self.protocol_version = PROTOCOL_VERSION
        self._tools: dict[str, MCPTool] | None = None

    def _discover_command(
        self,
        command: click.Command,
        command_path: tuple[str, ...],
        tools: dict[str, MCPTool],
    ) -> None:
        if isinstance(command, click.Group):
            context = click.Context(command)
            for child_name in command.list_commands(context):
                child = command.get_command(context, child_name)
                if child is not None:
                    self._discover_command(child, (*command_path, child_name), tools)
            return

        tool_name = "_".join(command_path).replace("-", "_")
        tools[tool_name] = MCPTool(tool_name, command_path, command)

    def get_tools(self) -> dict[str, MCPTool]:
        """Discover and cache the CLI commands backing the five public tools."""

        if self._tools is None:
            tools: dict[str, MCPTool] = {}
            context = click.Context(self.cli_group)
            for command_name in PUBLIC_TOOLS:
                command = self.cli_group.get_command(context, command_name)
                if command is not None:
                    self._discover_command(command, (command_name,), tools)
            self._tools = tools
        return self._tools

    def get_public_tool_definitions(self) -> list[dict[str, Any]]:
        """Build the small agent-facing surface from the existing Click tree."""

        commands = self.get_tools()
        definitions = [
            shell_to_mcp_tool() if name == "shell" else click_command_to_mcp_tool(commands[name])
            for name in PUBLIC_TOOLS
            if name not in ACTION_TOOLS
        ]
        for group_name in PUBLIC_TOOLS:
            if group_name not in ACTION_TOOLS:
                continue
            actions = sorted(
                (tool for tool in commands.values() if tool.command_path[0] == group_name),
                key=lambda tool: tool.command_path,
            )
            definitions.append(click_group_to_mcp_tool(group_name, actions))
        return definitions

    def handle_initialize(self, params: dict) -> dict:
        return {
            "protocolVersion": self.protocol_version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {
                "name": "archivebox-mcp",
                "title": "ArchiveBox",
                "version": VERSION,
            },
            "instructions": (
                "Use add to archive URLs and search for deep search. Use crawl, snapshot, or archiveresult "
                "with action=create/list/update/delete to manage records. Pass returned records directly "
                "to update/delete actions through the records argument. Use shell only when the curated "
                "tools cannot express the operation; it runs arbitrary Python with full collection access."
            ),
        }

    def handle_tools_list(self, params: dict) -> dict:
        return {"tools": self.get_public_tool_definitions()}

    def handle_tools_call(self, params: dict) -> dict:
        tool_name = params.get("name")
        if not tool_name:
            raise ValueError("Missing required parameter: name")
        if tool_name not in PUBLIC_TOOLS:
            raise ValueError(f"Unknown tool: {tool_name}")
        arguments = params.get("arguments", {})
        if not isinstance(arguments, dict):
            raise TypeError("Tool arguments must be an object")
        arguments = dict(arguments)
        command_name = tool_name
        if tool_name == "shell":
            unknown = sorted(set(arguments) - {"code"})
            if unknown:
                raise ValueError(f"Unknown shell argument(s): {', '.join(unknown)}")
            code = arguments.get("code")
            if not isinstance(code, str) or not code.strip():
                raise ValueError("shell requires a non-empty code string")
            arguments = {"args": ["--plain", "--quiet-load", "-c", code]}
        elif tool_name in ACTION_TOOLS:
            action = arguments.pop("action", None)
            available_actions = sorted(tool.command_path[-1] for tool in self.get_tools().values() if tool.command_path[0] == tool_name)
            if action not in available_actions:
                raise ValueError(
                    f"Unknown {tool_name} action: {action!r}. Choose one of: {', '.join(available_actions)}",
                )
            command_name = f"{tool_name}_{action}"
        tool = self.get_tools().get(command_name)
        if tool is None:
            raise ValueError(f"ArchiveBox CLI command is unavailable: {command_name}")
        return execute_click_command(tool, arguments)

    def handle_request(self, request: dict) -> dict | None:
        method = request.get("method")
        params = request.get("params", {})
        request_id = request.get("id")
        is_notification = "id" not in request

        if is_notification:
            return None

        try:
            if method == "initialize":
                result = self.handle_initialize(params)
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = self.handle_tools_list(params)
            elif method == "tools/call":
                result = self.handle_tools_call(params)
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                }
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except (TypeError, ValueError) as err:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32602, "message": str(err)},
            }
        except (click.ClickException, click.UsageError, OSError, RuntimeError) as err:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32603,
                    "message": str(err),
                    "data": traceback.format_exc(),
                },
            }

    def run_stdio_server(self) -> None:
        """Read and write one UTF-8 JSON-RPC message per line."""

        for line in sys.stdin:
            if not line.strip():
                continue
            try:
                request = json.loads(line)
                response = self.handle_request(request)
                if response is not None:
                    print(json.dumps(response, cls=MCPJSONEncoder), flush=True)
            except json.JSONDecodeError as err:
                response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "Parse error", "data": str(err)},
                }
                print(json.dumps(response, cls=MCPJSONEncoder), flush=True)


def run_mcp_server() -> None:
    """Start the ArchiveBox MCP stdio server."""

    MCPServer().run_stdio_server()
