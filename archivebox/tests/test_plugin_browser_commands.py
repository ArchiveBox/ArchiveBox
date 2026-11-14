"""Browser operations use the same installed command catalog as importers."""

import json
import subprocess

from archivebox.plugins.discovery import get_plugin_catalog


def test_browser_commands_reject_missing_source_before_installing(tmp_path):
    catalog = get_plugin_catalog()
    for name in ("browser-open", "browser-export-state"):
        commands = [command for plugin in catalog for command in [catalog.command(plugin, name)] if command]
        assert len(commands) == 1
        command = commands[0]
        result = subprocess.run(
            [str(command.path), *command.args],
            input=json.dumps({"config": {"ABXPKG_LIB_DIR": str(tmp_path / "lib")}}),
            text=True,
            capture_output=True,
            timeout=15,
            cwd=tmp_path,
        )
        assert result.returncode == 1
        assert "required" in result.stderr.lower()
        assert "Traceback" not in result.stderr
        assert not (tmp_path / "lib").exists()
