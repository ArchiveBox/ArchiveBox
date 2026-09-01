#!/usr/bin/env python3
"""Tests for the ArchiveBox MCP server and CLI entry point."""

import json
import os

import pytest

from archivebox.mcp.server import MCPServer
from archivebox.tests.conftest import run_archivebox_cmd


pytestmark = pytest.mark.django_db(transaction=True)


def test_mcp_help_runs_successfully(tmp_path):
    """The mcp command should be registered and expose help."""

    result = run_archivebox_cmd(["mcp", "--help"])

    assert result.returncode == 0
    assert "mcp" in result.stdout.lower()


def test_mcp_stdio_handles_handshake_notification_and_ping(initialized_archive):
    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "archivebox-test", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}},
    ]
    result = run_archivebox_cmd(
        ["mcp"],
        cwd=initialized_archive,
        input="".join(json.dumps(request) + "\n" for request in requests),
        default_cli_env=True,
    )
    responses = [json.loads(line) for line in result.stdout.splitlines()]

    assert result.returncode == 0
    assert [response["id"] for response in responses] == [1, 2]
    assert responses[0]["result"]["protocolVersion"] == "2025-11-25"
    assert responses[1]["result"] == {}


def test_mcp_exposes_six_focused_tools():
    tools = MCPServer().handle_tools_list({})["tools"]
    tools_by_name = {tool["name"]: tool for tool in tools}

    assert set(tools_by_name) == {"add", "search", "crawl", "snapshot", "archiveresult", "shell"}
    assert len(tools) == 6
    assert all("outputSchema" in tool for tool in tools)

    crawl_schema = tools_by_name["crawl"]["inputSchema"]
    assert crawl_schema["properties"]["action"]["enum"] == ["create", "delete", "list", "update"]
    assert crawl_schema["properties"]["urls"]["type"] == "array"
    assert crawl_schema["properties"]["records"]["type"] == "array"
    assert tools_by_name["search"]["annotations"]["readOnlyHint"] is True
    assert tools_by_name["shell"]["inputSchema"]["required"] == ["code"]
    assert tools_by_name["shell"]["annotations"]["destructiveHint"] is True


def test_mcp_crawl_create_returns_structured_json(initialized_archive):
    os.chdir(initialized_archive)
    result = MCPServer().handle_tools_call(
        {
            "name": "crawl",
            "arguments": {
                "action": "create",
                "urls": ["https://mcp-test.example.com/"],
                "depth": 1,
                "tag": "mcp-test",
            },
        },
    )

    assert result["isError"] is False, result
    assert result["structuredContent"]["success"] is True
    assert result["structuredContent"]["error"] is None
    assert result["structuredContent"]["command"] == "archivebox crawl create"
    assert result["structuredContent"]["exitCode"] == 0
    assert result["structuredContent"]["records"][0]["urls"] == "https://mcp-test.example.com/"
    assert result["structuredContent"]["records"][0]["max_depth"] == 1
    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]


def test_mcp_snapshot_update_accepts_records_without_a_jsonl_pipeline(initialized_archive):
    os.chdir(initialized_archive)
    server = MCPServer()
    created = server.handle_tools_call(
        {
            "name": "snapshot",
            "arguments": {
                "action": "create",
                "urls": ["https://mcp-update.example.com/"],
            },
        },
    )
    assert created["isError"] is False, created
    snapshot = created["structuredContent"]["records"][0]

    updated = server.handle_tools_call(
        {
            "name": "snapshot",
            "arguments": {
                "action": "update",
                "records": [{"id": snapshot["id"]}],
                "tag": "updated-through-mcp",
            },
        },
    )

    assert updated["isError"] is False
    assert updated["structuredContent"]["records"][0]["id"] == snapshot["id"]
    assert "updated-through-mcp" in updated["structuredContent"]["records"][0]["tags"]


def test_mcp_cli_errors_are_structured_for_agents(initialized_archive):
    os.chdir(initialized_archive)
    result = MCPServer().handle_tools_call(
        {
            "name": "crawl",
            "arguments": {"action": "create"},
        },
    )

    assert result["isError"] is True
    assert result["structuredContent"]["success"] is False
    assert result["structuredContent"]["exitCode"] == 1
    assert "No URLs provided" in result["structuredContent"]["error"]
    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]


def test_mcp_invalid_action_is_a_protocol_error():
    response = MCPServer().handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "crawl", "arguments": {"action": "bogus"}},
        },
    )

    assert response["error"]["code"] == -32602
    assert "Choose one of: create, delete, list, update" in response["error"]["message"]


def test_mcp_shell_runs_python_through_archivebox_shell(initialized_archive):
    os.chdir(initialized_archive)
    result = MCPServer().handle_tools_call(
        {
            "name": "shell",
            "arguments": {
                "code": "from archivebox.core.models import Snapshot; print(f'shell_ok={Snapshot.objects.count() >= 0}')",
            },
        },
    )

    assert result["isError"] is False, result
    assert result["structuredContent"]["command"] == "archivebox shell"
    assert result["structuredContent"]["stdout"] == "shell_ok=True\n"
