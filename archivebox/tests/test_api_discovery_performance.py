"""Server discovery must not repeat schema generation or probe installed tools."""

import sys
import threading
import os
from pathlib import Path

import pytest
from django.test.utils import override_script_prefix

from archivebox.config import VERSION
from archivebox.machine.models import Machine
from archivebox.tests.conftest import install_real_binary, resolve_abxpkg_binary_env


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("script_name", ["", "/mounted"])
def test_repeated_discovery_reuses_schema_without_binary_filesystem_probes(client, hermetic_lib_dir, script_name):
    install_real_binary("node", binproviders="env,apt,brew")
    resolve_abxpkg_binary_env(hermetic_lib_dir, "node")
    machine = Machine.current()
    machine.config = {**machine.config, "NODE_BINARY": str(hermetic_lib_dir / "env" / "bin" / "node")}
    machine.save(update_fields=["config"])
    request = {"HTTP_HOST": "api.archivebox.localhost:5797", "SCRIPT_NAME": script_name}
    with override_script_prefix(script_name):
        first = client.get("/api/v1/openapi.json", **request)
    assert first.status_code == 200, first.content
    schema_calls = []
    filesystem_calls = []

    def observe(frame, event, arg):
        if event == "call" and frame.f_code.co_name == "model_json_schema":
            schema_calls.append(frame.f_code.co_filename)
        if (event == "call" and frame.f_code.co_name in {"stat", "lstat", "open", "iterdir", "glob", "rglob"}) or (
            event == "c_call" and arg in (os.stat, os.lstat)
        ):
            path = frame.f_locals.get("self", frame.f_locals.get("path"))
            if isinstance(path, (str, Path)) and Path(path).is_relative_to(hermetic_lib_dir):
                filesystem_calls.append(str(path))

    previous = sys.getprofile()
    previous_thread = threading.getprofile()
    threading.setprofile_all_threads(observe)
    try:
        with override_script_prefix(script_name):
            second = client.get("/api/v1/openapi.json", **request)
    finally:
        threading.setprofile_all_threads(previous_thread)
        sys.setprofile(previous)
    assert second.status_code == 200, second.content
    assert second.json() == first.json()
    assert second.json()["info"]["version"] == VERSION
    assert f"{script_name}/api/v1/core/snapshots" in second.json()["paths"]
    assert (len(schema_calls), filesystem_calls) == (0, [])
