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
* - {py:obj}`click_command_to_mcp_tool <archivebox.mcp.server.click_command_to_mcp_tool>`
  - ```{autodoc2-docstring} archivebox.mcp.server.click_command_to_mcp_tool
    :summary:
    ```
* - {py:obj}`execute_click_command <archivebox.mcp.server.execute_click_command>`
  - ```{autodoc2-docstring} archivebox.mcp.server.execute_click_command
    :summary:
    ```
* - {py:obj}`run_mcp_server <archivebox.mcp.server.run_mcp_server>`
  - ```{autodoc2-docstring} archivebox.mcp.server.run_mcp_server
    :summary:
    ```
````

### API

`````{py:class} MCPJSONEncoder(*, skipkeys=False, ensure_ascii=True, check_circular=True, allow_nan=True, sort_keys=False, indent=None, separators=None, default=None)
:canonical: archivebox.mcp.server.MCPJSONEncoder

Bases: {py:obj}`json.JSONEncoder`

```{autodoc2-docstring} archivebox.mcp.server.MCPJSONEncoder
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.mcp.server.MCPJSONEncoder.__init__
```

````{py:method} default(o)
:canonical: archivebox.mcp.server.MCPJSONEncoder.default

````

`````

````{py:function} click_type_to_json_schema_type(click_type: click.ParamType) -> dict[str, typing.Any]
:canonical: archivebox.mcp.server.click_type_to_json_schema_type

```{autodoc2-docstring} archivebox.mcp.server.click_type_to_json_schema_type
```
````

````{py:function} click_command_to_mcp_tool(cmd_name: str, click_command: click.Command) -> dict[str, typing.Any]
:canonical: archivebox.mcp.server.click_command_to_mcp_tool

```{autodoc2-docstring} archivebox.mcp.server.click_command_to_mcp_tool
```
````

````{py:function} execute_click_command(cmd_name: str, click_command: click.Command, arguments: dict) -> dict
:canonical: archivebox.mcp.server.execute_click_command

```{autodoc2-docstring} archivebox.mcp.server.execute_click_command
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

````{py:method} get_click_command(cmd_name: str) -> click.Command | None
:canonical: archivebox.mcp.server.MCPServer.get_click_command

```{autodoc2-docstring} archivebox.mcp.server.MCPServer.get_click_command
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

````{py:method} handle_request(request: dict) -> dict
:canonical: archivebox.mcp.server.MCPServer.handle_request

```{autodoc2-docstring} archivebox.mcp.server.MCPServer.handle_request
```

````

````{py:method} run_stdio_server()
:canonical: archivebox.mcp.server.MCPServer.run_stdio_server

```{autodoc2-docstring} archivebox.mcp.server.MCPServer.run_stdio_server
```

````

`````

````{py:function} run_mcp_server()
:canonical: archivebox.mcp.server.run_mcp_server

```{autodoc2-docstring} archivebox.mcp.server.run_mcp_server
```
````
