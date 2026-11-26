"""Choose the verified Chrome ZIP only for tests using the ordinary browser runtime."""

import ast
import functools
import json
import sys
from pathlib import Path

from abx_plugins import get_plugins_dir

SHARED_CHROME_HELPERS = {"browser_runtime", "resolve_abxpkg_chrome_env", "ci_browser_dependency_cache"}


def literal_strings(node):
    if isinstance(node, (ast.List, ast.Tuple)):
        return [element.value for element in node.elts if isinstance(element, ast.Constant) and isinstance(element.value, str)]
    return []


def cli_plugins(call):
    name = getattr(call.func, "id", None) or getattr(call.func, "attr", None)
    if name == "run_install":
        return [plugin for kw in call.keywords if kw.arg == "plugin_names" for plugin in literal_strings(kw.value)]
    if name != "run_archivebox_cmd" or not call.args:
        return []
    args = literal_strings(call.args[0])
    if not args:
        return []
    if args[0] == "install":
        return args[1:]
    plugins = []
    for index, arg in enumerate(args):
        if arg.startswith("--plugins="):
            plugins.extend(arg.split("=", 1)[1].split(","))
        elif arg == "--plugins" and index + 1 < len(args):
            plugins.extend(args[index + 1].split(","))
    return plugins


@functools.cache
def plugin_config(plugin):
    if not plugin.isidentifier():
        return {}
    config = get_plugins_dir() / plugin / "config.json"
    return json.loads(config.read_text()) if config.is_file() else {}


def requires_chrome(plugin, seen=None):
    if plugin == "chrome":
        return True
    seen = set() if seen is None else seen
    if plugin in seen:
        return False
    seen.add(plugin)
    return any(requires_chrome(dependency, seen) for dependency in plugin_config(plugin).get("required_plugins", ()))


def needs_browser(path):
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if (
            (isinstance(node, ast.Name) and node.id in SHARED_CHROME_HELPERS)
            or (isinstance(node, ast.arg) and node.arg in SHARED_CHROME_HELPERS)
            or (isinstance(node, ast.Attribute) and node.attr in SHARED_CHROME_HELPERS)
            or (isinstance(node, ast.Call) and any(requires_chrome(plugin) for plugin in cli_plugins(node)))
        ):
            return True
    return False


def pinned_browser_matches(version):
    return any(
        binary.get("name") == "{CHROME_BINARY}"
        and binary.get("min_version") == binary.get("max_version") == version
        and binary.get("overrides", {}).get("puppeteer", {}).get("install_args") == [f"chrome@{version}", "--install-deps"]
        for binary in plugin_config("chrome").get("required_binaries", ())
    )


if __name__ == "__main__":
    version, *paths = sys.argv[1:]
    print(str(pinned_browser_matches(version) and any(needs_browser(Path(path)) for path in paths)).lower())
