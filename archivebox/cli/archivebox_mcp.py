#!/usr/bin/env python3
"""
archivebox mcp

Start the Model Context Protocol (MCP) server in stdio mode.
Exposes all ArchiveBox CLI commands as MCP tools for AI agents.
"""

__package__ = 'archivebox.cli'
__command__ = 'archivebox mcp'

import rich_click as click

from archivebox.misc.util import docstring, enforce_types


@enforce_types
def mcp():
    """
    Start the MCP server in stdio mode for AI agent control.

    The MCP (Model Context Protocol) server exposes all ArchiveBox CLI commands
    as tools that AI agents can discover and execute. It communicates via JSON-RPC
    2.0 over stdin/stdout.

    Example usage with an MCP client:
        archivebox mcp < requests.jsonl > responses.jsonl

    Or interactively:
        archivebox mcp
        {"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}
        {"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}
    """

    from mcp.server import run_mcp_server

    # Run the stdio server (blocks until stdin closes)
    run_mcp_server()


@click.command()
@docstring(mcp.__doc__)
def main(**kwargs):
    """Start the MCP server in stdio mode"""
    mcp()


if __name__ == '__main__':
    main()
