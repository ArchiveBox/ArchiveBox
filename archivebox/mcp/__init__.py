__package__ = 'archivebox.mcp'

"""
Model Context Protocol (MCP) server for ArchiveBox.

Exposes all ArchiveBox CLI commands as MCP tools via dynamic Click introspection.
Provides a JSON-RPC 2.0 interface over stdio for AI agents to control ArchiveBox.
"""
