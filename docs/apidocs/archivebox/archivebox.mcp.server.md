# {py:mod}`archivebox.mcp.server`

```{py:module} archivebox.mcp.server
```

```{autodoc2-docstring} archivebox.mcp.server
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`MCPJSONEncoder <archivebox.mcp.server.MCPJSONEncoder>`
  - ```{autodoc2-docstring} archivebox.mcp.server.MCPJSONEncoder
    :summary:
    ```
* - {py:obj}`MCPTool <archivebox.mcp.server.MCPTool>`
  - ```{autodoc2-docstring} archivebox.mcp.server.MCPTool
    :summary:
    ```
* - {py:obj}`MCPServer <archivebox.mcp.server.MCPServer>`
  - ```{autodoc2-docstring} archivebox.mcp.server.MCPServer
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`click_type_to_json_schema_type <archivebox.mcp.server.click_type_to_json_schema_type>`
  - ```{autodoc2-docstring} archivebox.mcp.server.click_type_to_json_schema_type
    :summary:
    ```
* - {py:obj}`command_accepts_stdin <archivebox.mcp.server.command_accepts_stdin>`
  - ```{autodoc2-docstring} archivebox.mcp.server.command_accepts_stdin
    :summary:
    ```
* - {py:obj}`tool_annotations <archivebox.mcp.server.tool_annotations>`
  - ```{autodoc2-docstring} archivebox.mcp.server.tool_annotations
    :summary:
    ```
* - {py:obj}`click_command_to_mcp_tool <archivebox.mcp.server.click_command_to_mcp_tool>`
  - ```{autodoc2-docstring} archivebox.mcp.server.click_command_to_mcp_tool
    :summary:
    ```
* - {py:obj}`tool_output_schema <archivebox.mcp.server.tool_output_schema>`
  - ```{autodoc2-docstring} archivebox.mcp.server.tool_output_schema
    :summary:
    ```
* - {py:obj}`click_group_to_mcp_tool <archivebox.mcp.server.click_group_to_mcp_tool>`
  - ```{autodoc2-docstring} archivebox.mcp.server.click_group_to_mcp_tool
    :summary:
    ```
* - {py:obj}`shell_to_mcp_tool <archivebox.mcp.server.shell_to_mcp_tool>`
  - ```{autodoc2-docstring} archivebox.mcp.server.shell_to_mcp_tool
    :summary:
    ```
* - {py:obj}`_option_args <archivebox.mcp.server._option_args>`
  - ```{autodoc2-docstring} archivebox.mcp.server._option_args
    :summary:
    ```
* - {py:obj}`arguments_to_cli <archivebox.mcp.server.arguments_to_cli>`
  - ```{autodoc2-docstring} archivebox.mcp.server.arguments_to_cli
    :summary:
    ```
* - {py:obj}`parse_structured_records <archivebox.mcp.server.parse_structured_records>`
  - ```{autodoc2-docstring} archivebox.mcp.server.parse_structured_records
    :summary:
    ```
* - {py:obj}`execute_click_command <archivebox.mcp.server.execute_click_command>`
  - ```{autodoc2-docstring} archivebox.mcp.server.execute_click_command
    :summary:
    ```
* - {py:obj}`_tool_result <archivebox.mcp.server._tool_result>`
  - ```{autodoc2-docstring} archivebox.mcp.server._tool_result
    :summary:
    ```
* - {py:obj}`run_mcp_server <archivebox.mcp.server.run_mcp_server>`
  - ```{autodoc2-docstring} archivebox.mcp.server.run_mcp_server
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`PROTOCOL_VERSION <archivebox.mcp.server.PROTOCOL_VERSION>`
  - ```{autodoc2-docstring} archivebox.mcp.server.PROTOCOL_VERSION
    :summary:
    ```
* - {py:obj}`PUBLIC_TOOLS <archivebox.mcp.server.PUBLIC_TOOLS>`
  - ```{autodoc2-docstring} archivebox.mcp.server.PUBLIC_TOOLS
    :summary:
    ```
* - {py:obj}`ACTION_TOOLS <archivebox.mcp.server.ACTION_TOOLS>`
  - ```{autodoc2-docstring} archivebox.mcp.server.ACTION_TOOLS
    :summary:
    ```
* - {py:obj}`READ_ONLY_ACTIONS <archivebox.mcp.server.READ_ONLY_ACTIONS>`
  - ```{autodoc2-docstring} archivebox.mcp.server.READ_ONLY_ACTIONS
    :summary:
    ```
* - {py:obj}`DESTRUCTIVE_ACTIONS <archivebox.mcp.server.DESTRUCTIVE_ACTIONS>`
  - ```{autodoc2-docstring} archivebox.mcp.server.DESTRUCTIVE_ACTIONS
    :summary:
    ```
````

### API

````{py:data} PROTOCOL_VERSION
:canonical: archivebox.mcp.server.PROTOCOL_VERSION
:value: >
   '2025-11-25'

```{autodoc2-docstring} archivebox.mcp.server.PROTOCOL_VERSION
```

````

````{py:data} PUBLIC_TOOLS
:canonical: archivebox.mcp.server.PUBLIC_TOOLS
:value: >
   ('add', 'search', 'crawl', 'snapshot', 'archiveresult', 'folder', 'importer', 'shell')

```{autodoc2-docstring} archivebox.mcp.server.PUBLIC_TOOLS
```

````

````{py:data} ACTION_TOOLS
:canonical: archivebox.mcp.server.ACTION_TOOLS
:value: >
   None

```{autodoc2-docstring} archivebox.mcp.server.ACTION_TOOLS
```

````

````{py:data} READ_ONLY_ACTIONS
:canonical: archivebox.mcp.server.READ_ONLY_ACTIONS
:value: >
   None

```{autodoc2-docstring} archivebox.mcp.server.READ_ONLY_ACTIONS
```

````

````{py:data} DESTRUCTIVE_ACTIONS
:canonical: archivebox.mcp.server.DESTRUCTIVE_ACTIONS
:value: >
   None

```{autodoc2-docstring} archivebox.mcp.server.DESTRUCTIVE_ACTIONS
```

````

`````{py:class} MCPJSONEncoder(*, skipkeys=False, ensure_ascii=True, check_circular=True, allow_nan=True, sort_keys=False, indent=None, separators=None, default=None)
:canonical: archivebox.mcp.server.MCPJSONEncoder

Bases: {py:obj}`json.JSONEncoder`

```{autodoc2-docstring} archivebox.mcp.server.MCPJSONEncoder
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.mcp.server.MCPJSONEncoder.__init__
```

````{py:method} default(value)
:canonical: archivebox.mcp.server.MCPJSONEncoder.default

````

`````

`````{py:class} MCPTool
:canonical: archivebox.mcp.server.MCPTool

```{autodoc2-docstring} archivebox.mcp.server.MCPTool
```

````{py:attribute} name
:canonical: archivebox.mcp.server.MCPTool.name
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.mcp.server.MCPTool.name
```

````

````{py:attribute} command_path
:canonical: archivebox.mcp.server.MCPTool.command_path
:type: tuple[str, ...]
:value: >
   None

```{autodoc2-docstring} archivebox.mcp.server.MCPTool.command_path
```

````

````{py:attribute} command
:canonical: archivebox.mcp.server.MCPTool.command
:type: click.Command
:value: >
   None

```{autodoc2-docstring} archivebox.mcp.server.MCPTool.command
```

````

`````

````{py:function} click_type_to_json_schema_type(click_type: click.ParamType) -> dict[str, typing.Any]
:canonical: archivebox.mcp.server.click_type_to_json_schema_type

```{autodoc2-docstring} archivebox.mcp.server.click_type_to_json_schema_type
```
````

````{py:function} command_accepts_stdin(click_command: click.Command) -> bool
:canonical: archivebox.mcp.server.command_accepts_stdin

```{autodoc2-docstring} archivebox.mcp.server.command_accepts_stdin
```
````

````{py:function} tool_annotations(command_path: tuple[str, ...]) -> dict[str, typing.Any]
:canonical: archivebox.mcp.server.tool_annotations

```{autodoc2-docstring} archivebox.mcp.server.tool_annotations
```
````

````{py:function} click_command_to_mcp_tool(tool: archivebox.mcp.server.MCPTool) -> dict[str, typing.Any]
:canonical: archivebox.mcp.server.click_command_to_mcp_tool

```{autodoc2-docstring} archivebox.mcp.server.click_command_to_mcp_tool
```
````

````{py:function} tool_output_schema() -> dict[str, typing.Any]
:canonical: archivebox.mcp.server.tool_output_schema

```{autodoc2-docstring} archivebox.mcp.server.tool_output_schema
```
````

````{py:function} click_group_to_mcp_tool(group_name: str, actions: list[archivebox.mcp.server.MCPTool]) -> dict[str, typing.Any]
:canonical: archivebox.mcp.server.click_group_to_mcp_tool

```{autodoc2-docstring} archivebox.mcp.server.click_group_to_mcp_tool
```
````

````{py:function} shell_to_mcp_tool() -> dict[str, typing.Any]
:canonical: archivebox.mcp.server.shell_to_mcp_tool

```{autodoc2-docstring} archivebox.mcp.server.shell_to_mcp_tool
```
````

````{py:function} _option_args(param: click.Option, value: typing.Any) -> list[str]
:canonical: archivebox.mcp.server._option_args

```{autodoc2-docstring} archivebox.mcp.server._option_args
```
````

````{py:function} arguments_to_cli(click_command: click.Command, arguments: dict[str, typing.Any]) -> tuple[list[str], str | None]
:canonical: archivebox.mcp.server.arguments_to_cli

```{autodoc2-docstring} archivebox.mcp.server.arguments_to_cli
```
````

````{py:function} parse_structured_records(stdout: str) -> list[typing.Any]
:canonical: archivebox.mcp.server.parse_structured_records

```{autodoc2-docstring} archivebox.mcp.server.parse_structured_records
```
````

````{py:function} execute_click_command(tool: archivebox.mcp.server.MCPTool, arguments: dict[str, typing.Any]) -> dict[str, typing.Any]
:canonical: archivebox.mcp.server.execute_click_command

```{autodoc2-docstring} archivebox.mcp.server.execute_click_command
```
````

````{py:function} _tool_result(tool: archivebox.mcp.server.MCPTool, *, exit_code: int, stdout: str = '', stderr: str = '', is_error: bool) -> dict[str, typing.Any]
:canonical: archivebox.mcp.server._tool_result

```{autodoc2-docstring} archivebox.mcp.server._tool_result
```
````

`````{py:class} MCPServer()
:canonical: archivebox.mcp.server.MCPServer

```{autodoc2-docstring} archivebox.mcp.server.MCPServer
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.mcp.server.MCPServer.__init__
```

````{py:method} _discover_command(command: click.Command, command_path: tuple[str, ...], tools: dict[str, archivebox.mcp.server.MCPTool]) -> None
:canonical: archivebox.mcp.server.MCPServer._discover_command

```{autodoc2-docstring} archivebox.mcp.server.MCPServer._discover_command
```

````

````{py:method} get_tools() -> dict[str, archivebox.mcp.server.MCPTool]
:canonical: archivebox.mcp.server.MCPServer.get_tools

```{autodoc2-docstring} archivebox.mcp.server.MCPServer.get_tools
```

````

````{py:method} get_public_tool_definitions() -> list[dict[str, typing.Any]]
:canonical: archivebox.mcp.server.MCPServer.get_public_tool_definitions

```{autodoc2-docstring} archivebox.mcp.server.MCPServer.get_public_tool_definitions
```

````

````{py:method} handle_initialize(params: dict) -> dict
:canonical: archivebox.mcp.server.MCPServer.handle_initialize

```{autodoc2-docstring} archivebox.mcp.server.MCPServer.handle_initialize
```

````

````{py:method} handle_tools_list(params: dict) -> dict
:canonical: archivebox.mcp.server.MCPServer.handle_tools_list

```{autodoc2-docstring} archivebox.mcp.server.MCPServer.handle_tools_list
```

````

````{py:method} handle_tools_call(params: dict) -> dict
:canonical: archivebox.mcp.server.MCPServer.handle_tools_call

```{autodoc2-docstring} archivebox.mcp.server.MCPServer.handle_tools_call
```

````

````{py:method} handle_request(request: dict) -> dict | None
:canonical: archivebox.mcp.server.MCPServer.handle_request

```{autodoc2-docstring} archivebox.mcp.server.MCPServer.handle_request
```

````

````{py:method} run_stdio_server() -> None
:canonical: archivebox.mcp.server.MCPServer.run_stdio_server

```{autodoc2-docstring} archivebox.mcp.server.MCPServer.run_stdio_server
```

````

`````

````{py:function} run_mcp_server() -> None
:canonical: archivebox.mcp.server.run_mcp_server

```{autodoc2-docstring} archivebox.mcp.server.run_mcp_server
```
````
