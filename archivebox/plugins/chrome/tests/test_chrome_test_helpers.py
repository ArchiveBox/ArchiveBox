"""
Tests for chrome_test_helpers.py functions.

These tests verify the Python helper functions used across Chrome plugin tests.
"""

import os
import pytest
import tempfile
from pathlib import Path

from archivebox.plugins.chrome.tests.chrome_test_helpers import (
    get_test_env,
    get_machine_type,
    get_lib_dir,
    get_node_modules_dir,
    get_extensions_dir,
    find_chromium_binary,
    get_plugin_dir,
    get_hook_script,
    parse_jsonl_output,
)


def test_get_machine_type():
    """Test get_machine_type() returns valid format."""
    machine_type = get_machine_type()
    assert isinstance(machine_type, str)
    assert '-' in machine_type, "Machine type should be in format: arch-os"
    # Should be one of the expected formats
    assert any(x in machine_type for x in ['arm64', 'x86_64']), "Should contain valid architecture"
    assert any(x in machine_type for x in ['darwin', 'linux', 'win32']), "Should contain valid OS"


def test_get_lib_dir_with_env_var():
    """Test get_lib_dir() respects LIB_DIR env var."""
    with tempfile.TemporaryDirectory() as tmpdir:
        custom_lib = Path(tmpdir) / 'custom_lib'
        custom_lib.mkdir()

        old_lib_dir = os.environ.get('LIB_DIR')
        try:
            os.environ['LIB_DIR'] = str(custom_lib)
            lib_dir = get_lib_dir()
            assert lib_dir == custom_lib
        finally:
            if old_lib_dir:
                os.environ['LIB_DIR'] = old_lib_dir
            else:
                os.environ.pop('LIB_DIR', None)


def test_get_node_modules_dir_with_env_var():
    """Test get_node_modules_dir() respects NODE_MODULES_DIR env var."""
    with tempfile.TemporaryDirectory() as tmpdir:
        custom_nm = Path(tmpdir) / 'node_modules'
        custom_nm.mkdir()

        old_nm_dir = os.environ.get('NODE_MODULES_DIR')
        try:
            os.environ['NODE_MODULES_DIR'] = str(custom_nm)
            nm_dir = get_node_modules_dir()
            assert nm_dir == custom_nm
        finally:
            if old_nm_dir:
                os.environ['NODE_MODULES_DIR'] = old_nm_dir
            else:
                os.environ.pop('NODE_MODULES_DIR', None)


def test_get_extensions_dir_default():
    """Test get_extensions_dir() returns expected path format."""
    ext_dir = get_extensions_dir()
    assert isinstance(ext_dir, str)
    assert 'personas' in ext_dir
    assert 'chrome_extensions' in ext_dir


def test_get_extensions_dir_with_custom_persona():
    """Test get_extensions_dir() respects ACTIVE_PERSONA env var."""
    old_persona = os.environ.get('ACTIVE_PERSONA')
    old_data_dir = os.environ.get('DATA_DIR')
    try:
        os.environ['ACTIVE_PERSONA'] = 'TestPersona'
        os.environ['DATA_DIR'] = '/tmp/test'
        ext_dir = get_extensions_dir()
        assert 'TestPersona' in ext_dir
        assert '/tmp/test' in ext_dir
    finally:
        if old_persona:
            os.environ['ACTIVE_PERSONA'] = old_persona
        else:
            os.environ.pop('ACTIVE_PERSONA', None)
        if old_data_dir:
            os.environ['DATA_DIR'] = old_data_dir
        else:
            os.environ.pop('DATA_DIR', None)


def test_get_test_env_returns_dict():
    """Test get_test_env() returns properly formatted environment dict."""
    env = get_test_env()
    assert isinstance(env, dict)

    # Should include key paths
    assert 'MACHINE_TYPE' in env
    assert 'LIB_DIR' in env
    assert 'NODE_MODULES_DIR' in env
    assert 'NODE_PATH' in env  # Critical for module resolution
    assert 'NPM_BIN_DIR' in env
    assert 'CHROME_EXTENSIONS_DIR' in env

    # Verify NODE_PATH equals NODE_MODULES_DIR (for Node.js module resolution)
    assert env['NODE_PATH'] == env['NODE_MODULES_DIR']


def test_get_test_env_paths_are_absolute():
    """Test that get_test_env() returns absolute paths."""
    env = get_test_env()

    # All path-like values should be absolute
    assert Path(env['LIB_DIR']).is_absolute()
    assert Path(env['NODE_MODULES_DIR']).is_absolute()
    assert Path(env['NODE_PATH']).is_absolute()


def test_find_chromium_binary():
    """Test find_chromium_binary() returns a path or None."""
    binary = find_chromium_binary()
    if binary:
        assert isinstance(binary, str)
        # Should be an absolute path if found
        assert os.path.isabs(binary)


def test_get_plugin_dir():
    """Test get_plugin_dir() finds correct plugin directory."""
    # Use this test file's path
    test_file = __file__
    plugin_dir = get_plugin_dir(test_file)

    assert plugin_dir.exists()
    assert plugin_dir.is_dir()
    # Should be the chrome plugin directory
    assert plugin_dir.name == 'chrome'
    assert (plugin_dir.parent.name == 'plugins')


def test_get_hook_script_finds_existing_hook():
    """Test get_hook_script() can find an existing hook."""
    from archivebox.plugins.chrome.tests.chrome_test_helpers import CHROME_PLUGIN_DIR

    # Try to find the chrome launch hook
    hook = get_hook_script(CHROME_PLUGIN_DIR, 'on_Crawl__*_chrome_launch.*')

    if hook:  # May not exist in all test environments
        assert hook.exists()
        assert hook.is_file()
        assert 'chrome_launch' in hook.name


def test_get_hook_script_returns_none_for_missing():
    """Test get_hook_script() returns None for non-existent hooks."""
    from archivebox.plugins.chrome.tests.chrome_test_helpers import CHROME_PLUGIN_DIR

    hook = get_hook_script(CHROME_PLUGIN_DIR, 'nonexistent_hook_*_pattern.*')
    assert hook is None


def test_parse_jsonl_output_valid():
    """Test parse_jsonl_output() parses valid JSONL."""
    jsonl_output = '''{"type": "ArchiveResult", "status": "succeeded", "output": "test1"}
{"type": "ArchiveResult", "status": "failed", "error": "test2"}
'''

    # Returns first match only
    result = parse_jsonl_output(jsonl_output)
    assert result is not None
    assert result['type'] == 'ArchiveResult'
    assert result['status'] == 'succeeded'
    assert result['output'] == 'test1'


def test_parse_jsonl_output_with_non_json_lines():
    """Test parse_jsonl_output() skips non-JSON lines."""
    mixed_output = '''Some non-JSON output
{"type": "ArchiveResult", "status": "succeeded"}
More non-JSON
{"type": "ArchiveResult", "status": "failed"}
'''

    result = parse_jsonl_output(mixed_output)
    assert result is not None
    assert result['type'] == 'ArchiveResult'
    assert result['status'] == 'succeeded'


def test_parse_jsonl_output_empty():
    """Test parse_jsonl_output() handles empty input."""
    result = parse_jsonl_output('')
    assert result is None


def test_parse_jsonl_output_filters_by_type():
    """Test parse_jsonl_output() can filter by record type."""
    jsonl_output = '''{"type": "LogEntry", "data": "log1"}
{"type": "ArchiveResult", "data": "result1"}
{"type": "ArchiveResult", "data": "result2"}
'''

    # Should return first ArchiveResult, not LogEntry
    result = parse_jsonl_output(jsonl_output, record_type='ArchiveResult')
    assert result is not None
    assert result['type'] == 'ArchiveResult'
    assert result['data'] == 'result1'  # First ArchiveResult


def test_parse_jsonl_output_filters_custom_type():
    """Test parse_jsonl_output() can filter by custom record type."""
    jsonl_output = '''{"type": "ArchiveResult", "data": "result1"}
{"type": "LogEntry", "data": "log1"}
{"type": "ArchiveResult", "data": "result2"}
'''

    result = parse_jsonl_output(jsonl_output, record_type='LogEntry')
    assert result is not None
    assert result['type'] == 'LogEntry'
    assert result['data'] == 'log1'


def test_machine_type_consistency():
    """Test that machine type is consistent across calls."""
    mt1 = get_machine_type()
    mt2 = get_machine_type()
    assert mt1 == mt2, "Machine type should be stable across calls"


def test_lib_dir_is_directory():
    """Test that lib_dir points to an actual directory when DATA_DIR is set."""
    with tempfile.TemporaryDirectory() as tmpdir:
        old_data_dir = os.environ.get('DATA_DIR')
        try:
            os.environ['DATA_DIR'] = tmpdir
            # Create the expected directory structure
            machine_type = get_machine_type()
            lib_dir = Path(tmpdir) / 'lib' / machine_type
            lib_dir.mkdir(parents=True, exist_ok=True)

            result = get_lib_dir()
            # Should return a Path object
            assert isinstance(result, Path)
        finally:
            if old_data_dir:
                os.environ['DATA_DIR'] = old_data_dir
            else:
                os.environ.pop('DATA_DIR', None)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
